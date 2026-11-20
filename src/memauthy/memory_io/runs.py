"""Locate memory snapshots and exposure transcripts in MemHarmBench run outputs.

Supported chain layouts (``<run_dir>/outputs/<chain_id>/``), see ``docs/benchmark_formats.md``:

* ``distance`` (Claude Code only): ``snapshots/S{0,2,4}.json`` and
  ``stages/<stage>/evidence.json`` (``exposure``, ``benign1..4``, ``trigger{0,2,4}``)
* ``claude_main``: ``{exposure1,exposure2,trigger}_evidence.json`` at the chain root
* ``openclaw_main``: ``steps/{exposure1,exposure2,trigger}/evidence.json``

Everything here is read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from memauthy.cases import CaseInfo
from memauthy.memory_io import agent, claude_code, openclaw
from memauthy.memory_io.agent import AgentLayout, AgentMemory, read_json_object
from memauthy.memory_io.files import Granularity
from memauthy.memory_io.transcript import transcript_from_evidence
from memauthy.schema import Transcript

Protocol = Literal["distance", "claude_main", "openclaw_main"]
EXPOSURE_STAGES = ("exposure", "exposure1", "exposure2")


@dataclass
class ChainInspection:
    chain_dir: Path
    protocol: Protocol
    layout: AgentLayout
    case_id: str | None
    # label -> post-exposure memory available to a defense (e.g. "S0", "exposure1/memory_after")
    snapshots: dict[str, AgentMemory] = field(default_factory=dict)
    # exposure session name -> transcript
    transcripts: dict[str, Transcript] = field(default_factory=dict)
    # files that exist but could not be used, with the reason (never silently dropped)
    problems: dict[str, str] = field(default_factory=dict)


def detect_protocol(chain_dir: Path) -> Protocol:
    if (chain_dir / "snapshots").is_dir():
        return "distance"
    if (chain_dir / "steps").is_dir():
        return "openclaw_main"
    if any(chain_dir.glob("exposure*_evidence.json")):
        return "claude_main"
    raise ValueError(f"unrecognized MemHarmBench chain layout: {chain_dir}")


def _evidence_files(chain_dir: Path, protocol: Protocol) -> dict[str, Path]:
    if protocol == "distance":
        found = {p.parent.name: p for p in sorted(chain_dir.glob("stages/*/evidence.json"))}
    elif protocol == "openclaw_main":
        found = {p.parent.name: p for p in sorted(chain_dir.glob("steps/*/evidence.json"))}
    else:
        found = {
            p.name.removesuffix("_evidence.json"): p
            for p in sorted(chain_dir.glob("*_evidence.json"))
        }
    return found


def _case_id(evidence: dict[str, Any]) -> str | None:
    value = evidence.get("case_id")
    if not isinstance(value, str):
        target = evidence.get("template_and_target")
        value = target.get("case_id") if isinstance(target, dict) else None
    return value if isinstance(value, str) else None


def inspect_chain(
    chain_dir: str | Path, granularity: Granularity = Granularity.BLOCK
) -> ChainInspection:
    chain_dir = Path(chain_dir)
    protocol = detect_protocol(chain_dir)
    layout = openclaw.LAYOUT if protocol == "openclaw_main" else claude_code.LAYOUT
    result = ChainInspection(chain_dir, protocol, layout, case_id=None)

    evidence_files = _evidence_files(chain_dir, protocol)
    for stage, path in evidence_files.items():
        if stage not in EXPOSURE_STAGES:
            continue
        try:
            evidence = read_json_object(path)
            result.case_id = result.case_id or _case_id(evidence)
            result.transcripts[stage] = transcript_from_evidence(evidence, layout)
            if protocol != "distance":
                label = f"{stage}/memory_after"
                result.snapshots[label] = agent.load_evidence(
                    layout, path, snapshot_id=f"{chain_dir.name}/{label}", granularity=granularity
                )
        except (ValueError, OSError) as exc:
            result.problems[str(path)] = f"{type(exc).__name__}: {exc}"

    if protocol == "distance":
        for path in sorted((chain_dir / "snapshots").glob("S*.json")):
            try:
                mem = claude_code.load_distance_snapshot(
                    path, case_id=result.case_id, granularity=granularity
                )
                result.snapshots[mem.snapshot.label or path.stem] = mem
            except (ValueError, OSError) as exc:
                result.problems[str(path)] = f"{type(exc).__name__}: {exc}"
    return result


def _preview(text: str, width: int = 100) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def summarize(inspection: ChainInspection, case: CaseInfo | None = None) -> dict[str, Any]:
    """JSON-serialisable overview: records per snapshot, memory writes per exposure session.

    If ``case`` is given, records containing the payload value are marked ``oracle_payload``.
    That is ground truth (P0) and is shown for inspection only.
    """
    writes: dict[str, list[dict[str, Any]]] = {}
    for session, transcript in inspection.transcripts.items():
        for ev in transcript.events:
            if ev.memory_file:
                writes.setdefault(ev.memory_file, []).append(
                    {
                        "session": session,
                        "index": ev.index,
                        "tool": ev.tool_name,
                        "ref": ev.event_ref,
                    }
                )
    snapshots = {}
    for label, mem in inspection.snapshots.items():
        snapshots[label] = [
            {
                "record_id": r.record_id,
                "file": r.metadata["file"],
                "file_role": r.metadata.get("file_role"),
                "block_kind": r.metadata["block_kind"],
                "line": r.metadata["start_line"],
                "preview": _preview(r.content),
                **({"oracle_payload": case.payload_value in r.content} if case else {}),
            }
            for r in mem.snapshot.records
        ]
    transcripts = {
        name: {
            "session_id": t.session_id,
            "events": len(t.events),
            "tool_calls": sum(e.kind == "tool_use" for e in t.events),
            "memory_writes": sum(e.memory_file is not None for e in t.events),
        }
        for name, t in inspection.transcripts.items()
    }
    out: dict[str, Any] = {
        "chain": inspection.chain_dir.name,
        "protocol": inspection.protocol,
        "agent": inspection.layout.agent,
        "case_id": inspection.case_id,
        "snapshots": snapshots,
        "transcripts": transcripts,
        "memory_writes_by_file": writes,
        "problems": inspection.problems,
    }
    if case:
        out["case"] = {
            "channel": case.channel,
            "victim": case.victim,
            "permission_condition": case.permission_condition,
            "source_authority": case.source_authority,
            "carrier_artifact": case.carrier_artifact,
            "payload_value": case.payload_value,
            "target_memory_rule": case.target_memory_rule,
        }
    return out


def find_chains(run_dir: str | Path) -> list[Path]:
    """All chain directories under ``<run_dir>/outputs`` with a recognizable layout."""
    outputs = Path(run_dir) / "outputs"
    chains = []
    for path in sorted(outputs.iterdir()) if outputs.is_dir() else []:
        if not path.is_dir():
            continue
        try:
            detect_protocol(path)
        except ValueError:
            continue
        chains.append(path)
    return chains
