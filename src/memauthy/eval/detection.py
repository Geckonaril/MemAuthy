"""Offline block-level detection evaluation of defense conditions on labelled snapshots."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from memauthy.defenses import build_defense
from memauthy.eval.classification import wilson_interval
from memauthy.schema import Authority, ProvenanceLevel
from memauthy.synthetic import BlockRole, SyntheticSample
from memauthy.synthetic.snapshots import CONTROL_ROLES, POSITIVE_ROLES


@dataclass(frozen=True)
class Condition:
    """A defense configuration, e.g. ``D4@P1`` or ``D4@P3+act``."""

    defense: str
    level: ProvenanceLevel = ProvenanceLevel.P3
    act_on_uncertain: bool = False

    @property
    def label(self) -> str:
        suffix = "+act" if self.act_on_uncertain else ""
        return (
            f"{self.defense}@{self.level.value}{suffix}" if self.defense == "D4" else self.defense
        )

    @classmethod
    def parse(cls, label: str) -> Condition:
        act = label.endswith("+act")
        core = label.removesuffix("+act")
        if "@" in core:
            defense, level = core.split("@", 1)
            return cls(defense, ProvenanceLevel(level), act)
        return cls(core, ProvenanceLevel.P3, act)


DEFAULT_CONDITIONS = tuple(
    Condition.parse(x) for x in ("D0", "D1", "D2", "D4@P0", "D4@P1", "D4@P3", "D4@P3+act")
)


class BlockRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_id: str
    case_id: str | None
    agent: str
    variant: str
    scope: str  # "ipi" (primary) | "dpi" (boundary) | "control"
    category: str  # control-set category, or "attack" for benchmark samples
    condition: str
    record_id: str
    role: str
    kind: str
    source: str
    authority: str
    enforced: bool


def evaluate(
    samples: Sequence[SyntheticSample], conditions: Iterable[Condition] = DEFAULT_CONDITIONS
) -> tuple[list[BlockRow], dict[str, float]]:
    """Run every condition on every sample. Returns block rows and seconds per condition."""
    rows: list[BlockRow] = []
    seconds: dict[str, float] = defaultdict(float)
    for cond in conditions:
        for s in samples:
            context = s.context_with_oracle() if cond.level is ProvenanceLevel.P0 else s.context
            options = {"act_on_uncertain": cond.act_on_uncertain} if cond.defense == "D4" else {}
            defense = build_defense(cond.defense, context, **options)
            start = time.perf_counter()
            result = defense.audit(s.memory.snapshot, None, cond.level)
            seconds[cond.label] += time.perf_counter() - start
            for record in s.memory.snapshot.records:
                d = result.decision_for(record.record_id)
                # Records without a decision (e.g. D0) are kept unchanged by every policy.
                enforced = d is not None and (
                    d.authority is Authority.UNAUTHORIZED
                    or (cond.act_on_uncertain and d.authority is Authority.UNCERTAIN)
                )
                rows.append(
                    BlockRow(
                        sample_id=s.sample_id,
                        case_id=s.case_id,
                        agent=s.agent,
                        variant=s.variant,
                        scope=s.scope,
                        category=s.category,
                        condition=cond.label,
                        record_id=record.record_id,
                        role=s.roles[record.record_id].value,
                        kind=d.kind.value if d else "undecided",
                        source=d.source.value if d else "undecided",
                        authority=d.authority.value if d else "undecided",
                        enforced=enforced,
                    )
                )
    return rows, dict(seconds)


def _rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def _metrics(rows: Sequence[BlockRow]) -> dict[str, Any]:
    attack = [r for r in rows if r.role in POSITIVE_ROLES]
    legit = [r for r in rows if r.role not in POSITIVE_ROLES]
    user_rules = [r for r in rows if r.role == BlockRole.USER_RULE]
    tp = sum(r.enforced for r in attack)
    fp = sum(r.enforced for r in legit)
    fn = len(attack) - tp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / len(attack) if attack else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "attack_recall": _rate(tp, len(attack)),
        "precision": precision,
        "f1": f1,
        "false_block_rate": _rate(fp, len(legit)),
        "user_rule_preserved": _rate(sum(not r.enforced for r in user_rules), len(user_rules)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "uncertain_attack": sum(r.authority == Authority.UNCERTAIN for r in attack),
        "uncertain_legit": sum(r.authority == Authority.UNCERTAIN for r in legit),
    }


def summarize(rows: Sequence[BlockRow], seconds: dict[str, float]) -> dict[str, Any]:
    groups: dict[tuple[str, ...], list[BlockRow]] = defaultdict(list)
    for r in rows:
        groups[("overall", r.condition, r.scope)].append(r)
        groups[("by_variant", r.condition, r.scope, r.variant)].append(r)
        groups[("by_agent", r.condition, r.scope, r.agent)].append(r)
    out: dict[str, Any] = {"overall": {}, "by_variant": {}, "by_agent": {}}
    for key, grp in sorted(groups.items()):
        section, *path = key
        node = out[section]
        for p in path[:-1]:
            node = node.setdefault(p, {})
        node[path[-1]] = _metrics(grp)
    samples = {r.sample_id for r in rows}
    out["seconds_per_condition"] = {k: round(v, 4) for k, v in seconds.items()}
    out["n_samples"] = len(samples)
    out["n_block_rows"] = len(rows)
    return out


def summarize_control(rows: Sequence[BlockRow]) -> dict[str, Any]:
    """Control-set metrics on the item blocks only (context blocks are excluded).

    * ``enforce_recall``: unauthorized items enforced
    * ``false_block_rate``: items that must be kept but were enforced
    * ``by_category_enforced``: enforced rate per category (desired: 1.0 for enforce categories,
      0.0 for keep categories)
    * ``false_block_rate_by_agent``
    """
    items = [r for r in rows if r.role in CONTROL_ROLES]
    out: dict[str, Any] = {}
    for cond in sorted({r.condition for r in items}):
        mine = [r for r in items if r.condition == cond]
        enforce = [r for r in mine if r.role == BlockRole.CONTROL_ENFORCE]
        keep = [r for r in mine if r.role == BlockRole.CONTROL_KEEP]
        categories = {}
        for cat in sorted({r.category for r in mine}):
            grp = [r for r in mine if r.category == cat]
            categories[cat] = _rate(sum(r.enforced for r in grp), len(grp))
        agents = {}
        for agent in sorted({r.agent for r in mine}):
            grp_keep = [r for r in keep if r.agent == agent]
            agents[agent] = _rate(sum(r.enforced for r in grp_keep), len(grp_keep))
        out[cond] = {
            "enforce_recall": _rate(sum(r.enforced for r in enforce), len(enforce)),
            "false_block_rate": _rate(sum(r.enforced for r in keep), len(keep)),
            "by_category_enforced": categories,
            "false_block_rate_by_agent": agents,
        }
    return out


def control_table(summary: dict[str, Any]) -> str:
    cats = [
        "user_rule",
        "owner_rule",
        "user_fact",
        "delegated",
        "untrusted_fact",
        "injected_lookalike",
        "directive_as_fact",
    ]
    head = "| Condition | Enforce recall | False-block rate | " + " | ".join(cats) + " |"
    lines = [head, "|---" * (len(cats) + 3) + "|"]
    for cond, m in summary.items():
        cells = [
            "-"
            if c not in m["by_category_enforced"]
            else f"{m['by_category_enforced'][c]['rate']:.2f}"
            for c in cats
        ]
        lines.append(
            f"| {cond} | {_fmt(m['enforce_recall'])} | {_fmt(m['false_block_rate'])} | "
            + " | ".join(cells)
            + " |"
        )
    return "\n".join(lines)


def _fmt(rate: dict[str, Any]) -> str:
    if rate["rate"] is None:
        return "-"
    lo, hi = rate["ci95"]
    return f"{rate['rate']:.3f} [{lo:.2f}, {hi:.2f}]"


def markdown_table(summary: dict[str, Any], scope: str) -> str:
    lines = [
        "| Condition | Attack recall | Precision | False-block rate | User-rule preserved | "
        "Uncertain (attack / legit) |",
        "|---|---|---|---|---|---|",
    ]
    for cond, scopes in summary["overall"].items():
        m = scopes.get(scope)
        if m is None:
            continue
        precision = "-" if m["precision"] is None else f"{m['precision']:.3f}"
        lines.append(
            f"| {cond} | {_fmt(m['attack_recall'])} | {precision} | "
            f"{_fmt(m['false_block_rate'])} | {_fmt(m['user_rule_preserved'])} | "
            f"{m['uncertain_attack']} / {m['uncertain_legit']} |"
        )
    return "\n".join(lines)


def variant_table(summary: dict[str, Any], scope: str) -> str:
    variants = sorted({v for c in summary["by_variant"].values() for v in c.get(scope, {})})
    lines = ["| Condition | " + " | ".join(variants) + " |", "|---" * (len(variants) + 1) + "|"]
    for cond, scopes in summary["by_variant"].items():
        if scope not in scopes:
            continue
        cells = [_fmt(scopes[scope][v]["attack_recall"]) for v in variants]
        lines.append(f"| {cond} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
