"""Matched defended chain: one exposure, one trigger branch per defense arm (issue #45).

Mirrors the exposure logic of MemHarmBench's ``runtime.protocols.run_standard`` (two exposure
attempts, PMIR-gated trigger), then branches the selected exposure into one trigger session per
arm. All benchmark-specific steps are injected as callables, so the orchestration is tested
without Docker, network or the benchmark runtime (see ``harness.py`` for the real bindings).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memauthy.benchrun.defend import Arm, DefendedExposure, DefenseInputError

Evidence = dict[str, Any]
ExposureFn = Callable[[int, Evidence | None], Evidence]  # (attempt, previous) -> evidence
TriggerFn = Callable[[Arm, Path, Evidence], Evidence]  # (arm, arm_root, defended) -> evidence
JudgeFn = Callable[[Path, str, Evidence], Mapping[str, Any]]  # (dir, phase, evidence) -> metrics
DefendFn = Callable[[Arm, Sequence[Evidence]], DefendedExposure]
LabelFn = Callable[[Any], int | None]

RESULT_FILE = "chain_result.json"
TRIGGER_METRICS = ("C_ASR", "UTDR", "ATAR")


class LineageError(Exception):
    """Trigger did not start from the defended memory, or reused the exposure session."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def default_label(value: Any) -> int | None:
    """0/1 label, anything else unresolved (same contract as the benchmark's ``valid_label``)."""
    return value if value in (0, 1) and not isinstance(value, bool) else None


def run_defended_chain(
    *,
    job: Mapping[str, Any],
    root: Path,
    arms: Sequence[Arm],
    exposure: ExposureFn,
    trigger: TriggerFn,
    judge: JudgeFn,
    defend: DefendFn,
    valid_label: LabelFn = default_label,
    terminal_errors: tuple[type[BaseException], ...] = (),
) -> dict[str, Any]:
    """Run or resume one matched chain and write ``<root>/chain_result.json``.

    * Exposure: attempt 1, and attempt 2 only if PMIR is 0 (as in the benchmark).
    * PMIR unresolved → no trigger; PMIR 0 after both attempts → every arm ``skipped``
      (nothing was stored, so every arm counts as non-adoption in full-cohort analysis).
    * PMIR 1 → for each arm: defend, run a fresh trigger in ``<root>/arms/<slug>``, judge it.
    * A technical failure in one arm is recorded for that arm only; failures are never dropped.
    """
    root = Path(root)
    saved = _read_json(root / RESULT_FILE)
    if saved is not None:
        return saved
    identity = {"job": dict(job), "arms": [a.label for a in arms]}
    old = _read_json(root / "memauthy_identity.json")
    if old is not None and old != identity:
        raise LineageError("chain identity changed (job or arms differ from the saved run)")
    _write_json(root / "memauthy_identity.json", identity)

    result: dict[str, Any] = {
        **job,
        "condition": "attack",
        "design": "memauthy-matched-arms-v1",
        "state": "running",
        "technical_failure": False,
        "exposure": {"attempts": [], "final_pmir": None, "trigger_status": "pending"},
        "arms": {},
    }
    exposures: list[Evidence] = []
    try:
        selected: Evidence | None = None
        pmir: int | None = None
        for attempt in (1, 2):
            selected = exposure(attempt, selected)
            exposures.append(selected)
            metric = judge(root / "judging" / f"exposure{attempt}", "exposure", selected)
            pmir = valid_label(metric.get("PMIR"))
            result["exposure"]["attempts"].append(
                {
                    "attempt_no": attempt,
                    "pmir": metric.get("PMIR"),
                    "session_id": selected.get("session_id"),
                }
            )
            result["exposure"]["final_pmir"] = pmir
            result["selected_attempt"] = attempt
            result["technical_failure"] |= bool(metric.get("technical_failure"))
            if pmir is None or pmir == 1:
                break
        if pmir == 1:
            assert selected is not None
            if not selected.get("memory_after"):
                raise LineageError("positive PMIR contradicts empty memory")
            result["exposure"]["trigger_status"] = "run"
            for arm in arms:
                result["arms"][arm.label] = _run_arm(
                    arm, root, exposures, selected, trigger, judge, defend, valid_label,
                    terminal_errors,
                )  # fmt: skip
        elif pmir == 0:
            result["exposure"]["trigger_status"] = "skipped"
            for arm in arms:
                result["arms"][arm.label] = {"status": "skipped", "adoption": 0}
    except terminal_errors as exc:
        result.update(technical_failure=True, failure_stage="exposure", failure_category=str(exc))

    arm_results = result["arms"].values()
    result["technical_failure"] |= any(a.get("technical_failure") for a in arm_results)
    valid = result["exposure"]["final_pmir"] is not None and len(result["arms"]) == len(arms)
    valid = valid and all(a.get("adoption") is not None for a in arm_results)
    complete = valid and not result["technical_failure"]
    result.update(state="complete" if complete else "complete_with_unresolved", finished_at=_now())
    _write_json(root / RESULT_FILE, result)
    return result


def _run_arm(
    arm: Arm,
    root: Path,
    exposures: Sequence[Evidence],
    selected: Evidence,
    trigger: TriggerFn,
    judge: JudgeFn,
    defend: DefendFn,
    valid_label: LabelFn,
    terminal_errors: tuple[type[BaseException], ...],
) -> dict[str, Any]:
    arm_root = root / "arms" / arm.slug
    out: dict[str, Any] = {"status": "pending", "technical_failure": False, "adoption": None}
    try:
        defended = defend(arm, exposures)
    except DefenseInputError as exc:
        return {**out, "status": "defense_failure", "technical_failure": True, "error": str(exc)}
    _write_json(arm_root / "defense.json", defended.audit)
    out["memory_unchanged"] = defended.audit.get("memory_unchanged")
    out["n_enforced"] = sum(r["enforced"] for r in defended.audit.get("records", []))
    try:
        trig = trigger(arm, arm_root, defended.evidence)
        if trig.get("session_id") == selected.get("session_id"):
            raise LineageError(f"{arm.label}: trigger reused the exposure session")
        if trig.get("memory_before") != defended.evidence["memory_after"]:
            raise LineageError(f"{arm.label}: trigger did not start from the defended memory")
        metrics = judge(arm_root / "judging" / "trigger", "trigger", trig)
    except terminal_errors as exc:
        return {**out, "status": "trigger_failure", "technical_failure": True, "error": str(exc)}
    out.update({k.lower(): metrics.get(k) for k in TRIGGER_METRICS})
    out.update(
        status="run",
        session_id=trig.get("session_id"),
        termination=trig.get("termination"),
        adoption=valid_label(metrics.get("C_ASR")),
        technical_failure=bool(metrics.get("technical_failure")),
    )
    if any(valid_label(metrics.get(k)) is None for k in TRIGGER_METRICS):
        out["status"] = "unresolved_label"
    return out
