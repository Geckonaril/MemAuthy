"""Apply one defense arm to the memory a real exposure session left behind (issue #45).

Pure functions over benchmark evidence dictionaries: nothing here imports the benchmark runtime,
starts Docker or calls a model (except D3's local client when an arm asks for it).
"""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from memauthy.cases import CaseInfo
from memauthy.defenses import build_defense
from memauthy.eval.detection import Condition
from memauthy.memory_io import agent, claude_code, openclaw
from memauthy.memory_io.agent import AgentLayout
from memauthy.memory_io.transcript import transcript_from_evidence
from memauthy.provenance import ProvenanceContext
from memauthy.provenance.extractors import oracle_labels_from_case
from memauthy.schema import Authority, Policy, ProvenanceLevel

LAYOUTS: dict[str, AgentLayout] = {
    "claude_code": claude_code.LAYOUT,
    "openclaw": openclaw.LAYOUT,
}
NEEDS_TRANSCRIPT = (ProvenanceLevel.P1, ProvenanceLevel.P2)


class DefenseInputError(ValueError):
    """The exposure evidence lacks what this arm needs (reported as a technical failure)."""


@dataclass(frozen=True)
class Arm:
    """One defense arm of a matched chain, e.g. ``D4@P2:block``."""

    condition: Condition
    policy: Policy = Policy.BLOCK

    @property
    def label(self) -> str:
        return f"{self.condition.label}:{self.policy.value}"

    @property
    def slug(self) -> str:
        """File-system-safe name (Windows forbids ``:``)."""
        return self.label.replace("@", "-").replace(":", "-").replace("+", "-")

    @property
    def is_baseline(self) -> bool:
        return self.condition.defense == "D0"

    @classmethod
    def parse(cls, text: str) -> Arm:
        core, _, policy = text.partition(":")
        return cls(Condition.parse(core), Policy(policy) if policy else Policy.BLOCK)


def parse_arms(labels: Sequence[str]) -> tuple[Arm, ...]:
    arms = tuple(Arm.parse(x) for x in labels)
    slugs = [a.slug for a in arms]
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"duplicate arms: {labels}")
    if not any(a.is_baseline for a in arms):
        raise ValueError("a matched chain needs the D0 baseline arm")
    return arms


@dataclass
class DefendedExposure:
    """The evidence handed to the trigger session of one arm, plus the audit record."""

    arm: Arm
    evidence: dict[str, Any]
    audit: dict[str, Any] = field(default_factory=dict)


def _memory(evidence: Mapping[str, Any], key: str) -> dict[str, str]:
    value = evidence.get(key)
    if not isinstance(value, Mapping):
        raise DefenseInputError(f"exposure evidence has no {key!r} mapping")
    return dict(value)


def build_context(
    exposures: Sequence[Mapping[str, Any]], layout: AgentLayout, *, need_transcripts: bool
) -> ProvenanceContext:
    """Transcripts of every accepted exposure attempt; baseline = memory before exposure."""
    transcripts = []
    if need_transcripts:
        for ev in exposures:
            try:
                transcripts.append(transcript_from_evidence(ev, layout))
            except ValueError as exc:
                raise DefenseInputError(f"no usable exposure transcript: {exc}") from None
    baseline = exposures[0].get("memory_before") if exposures else None
    return ProvenanceContext(
        transcripts=tuple(transcripts),
        baseline_files=dict(baseline) if isinstance(baseline, Mapping) else None,
    )


def defend_exposure(
    arm: Arm,
    agent_name: str,
    exposures: Sequence[Mapping[str, Any]],
    *,
    case: CaseInfo | None = None,
    defense_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> DefendedExposure:
    """Audit and enforce on the selected (last) exposure's ``memory_after``.

    The returned evidence is a deep copy of the selected exposure in which ``memory_after`` (and,
    for ``workspace:`` keys, ``final_workspace_state``) carry the defended text. Every key is
    kept; a fully removed file becomes an empty file. The originals are never modified.
    """
    if not exposures:
        raise DefenseInputError("no exposure evidence")
    layout = LAYOUTS.get(agent_name)
    if layout is None:
        raise ValueError(f"unknown agent {agent_name!r}")
    selected = exposures[-1]
    files = _memory(selected, "memory_after")
    mem = agent.from_files(
        layout, files, snapshot_id=str(selected.get("attempt_id", "exposure")), source="exposure"
    )
    cond = arm.condition
    context = build_context(exposures, layout, need_transcripts=cond.level in NEEDS_TRANSCRIPT)
    if cond.level is ProvenanceLevel.P0 and cond.defense == "D4":
        if case is None:
            raise DefenseInputError("P0 needs the benchmark case for oracle labels")
        oracle = oracle_labels_from_case(
            mem.snapshot, case, baseline_block_ids=context.baseline_block_ids()
        )
        context = ProvenanceContext(
            transcripts=context.transcripts, baseline_files=context.baseline_files, oracle=oracle
        )
    options = dict((defense_options or {}).get(cond.defense, {}))
    if cond.defense == "D4":
        options["act_on_uncertain"] = cond.act_on_uncertain
    defense = build_defense(cond.defense, context, **options)

    start = time.perf_counter()
    result = defense.audit(mem.snapshot, None, cond.level)
    audited = defense.apply(mem.snapshot, result, arm.policy)
    new_files, report = mem.render(audited)
    seconds = time.perf_counter() - start

    for key in files:  # keep every key so the trigger restores exactly this memory
        new_files.setdefault(key, "")
    evidence = copy.deepcopy(dict(selected))
    evidence["memory_after"] = new_files
    state = evidence.get("final_workspace_state")
    if isinstance(state, dict):
        for key, text in new_files.items():
            namespace, _, relative = key.partition(":")
            if namespace == "workspace":
                state[relative] = text

    records = []
    for r in mem.snapshot.records:
        d = result.decision_for(r.record_id)
        records.append(
            {
                "record_id": r.record_id,
                "file": r.metadata.get("file"),
                "kind": d.kind.value if d else "undecided",
                "source": d.source.value if d else "undecided",
                "authority": d.authority.value if d else "undecided",
                "confidence": d.confidence if d else None,
                "enforced": bool(
                    d
                    and (
                        d.authority is Authority.UNAUTHORIZED
                        or (cond.act_on_uncertain and d.authority is Authority.UNCERTAIN)
                    )
                ),
                "rationale": d.rationale if d else "",
            }
        )
    audit = {
        "arm": arm.label,
        "agent": agent_name,
        "selected_attempt_id": selected.get("attempt_id"),
        "n_transcripts": len(context.transcripts),
        "records": records,
        "changes": report.model_dump(mode="json"),
        "seconds": seconds,
        "cost": result.total_cost.model_dump(mode="json"),
        "memory_unchanged": new_files == files,
    }
    return DefendedExposure(arm=arm, evidence=evidence, audit=audit)
