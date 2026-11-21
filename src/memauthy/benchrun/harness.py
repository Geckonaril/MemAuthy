"""Bindings from the matched-arm chain to MemHarmBench's own runtime (issue #45).

Nothing in ``third_party/`` is modified. ``make_chain_runner`` returns a drop-in replacement for
``runtime.protocols.run_standard`` (same ``(job, case, lock, live)`` signature) that reuses the
benchmark's own executors, judge, checkpoints and integrity checks, and only adds the defense
step and one trigger branch per arm. ``install`` swaps it into ``runtime.control`` inside the
benchmark worker process.

The benchmark runtime reads its campaign configuration at import time, so every import here is
deferred to call time. This module is exercised end to end by the rehearsal (issue #46); the
orchestration it delegates to is unit-tested in ``tests/test_benchrun.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from memauthy.benchrun.chain import LineageError, run_defended_chain
from memauthy.benchrun.defend import Arm, defend_exposure, parse_arms
from memauthy.cases import load_case


def make_chain_runner(
    arm_labels: Sequence[str],
    defense_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> Any:
    arms = parse_arms(arm_labels)

    def run_chain(job: Mapping[str, Any], case: Any, lock: Mapping[str, Any], live: Any) -> Any:
        from runtime import protocols
        from runtime.common import CONFIG, DATA, HERE
        from runtime.distance_stage import NeedsAttention, TerminalStage
        from runtime.judging import judge_phase

        if CONFIG["experiment"] != "main":
            raise NeedsAttention("MemAuthy arms support the 'main' experiment only")
        agent_name = CONFIG["agent"]
        root = Path(HERE) / "outputs" / job["chain_id"]
        info = load_case(case.case_id, DATA)

        if agent_name == "claude_code":
            execute = protocols.claude_executor(case, root, lock, live)
        else:
            execute = protocols.openclaw_executor(case, root, lock, live)

        def exposure(attempt: int, previous: dict[str, Any] | None) -> dict[str, Any]:
            return execute("exposure", previous, attempt)

        def trigger(arm: Arm, arm_root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
            if agent_name == "claude_code":
                # A fresh replayer per arm: its output dir (and step cache) is the arm root.
                return protocols.claude_executor(case, arm_root, lock, live)("trigger", evidence)
            return _openclaw_trigger(case, arm_root, evidence, lock, live, CONFIG["model"])

        def judge(path: Path, phase: str, evidence: dict[str, Any]) -> Mapping[str, Any]:
            return judge_phase(case, path, phase, evidence, live)

        def defend(arm: Arm, exposures: Sequence[dict[str, Any]]) -> Any:
            return defend_exposure(
                arm, agent_name, exposures, case=info, defense_options=defense_options
            )

        try:
            from memharmbench_v84.metrics import valid_label

            return run_defended_chain(
                job=job,
                root=root,
                arms=arms,
                exposure=exposure,
                trigger=trigger,
                judge=judge,
                defend=defend,
                valid_label=valid_label,
                terminal_errors=(TerminalStage,),
            )
        except LineageError as exc:
            raise NeedsAttention(str(exc)) from None

    return run_chain


def _openclaw_trigger(
    case: Any,
    arm_root: Path,
    evidence: dict[str, Any],
    lock: Mapping[str, Any],
    live: Any,
    model: str,
) -> dict[str, Any]:
    """OpenClaw's own executor keeps the selected exposure in a closure, so call ``step``."""
    from runtime.distance_stage import NeedsAttention, TerminalStage
    from runtime.openclaw.oc_step import Pause, TerminalTechnical, step

    lock_values = {**lock, "image_id": lock["images"]["agent"], "model": model}
    previous = {"evidence": evidence, "folder": None}  # folder is only read for exposure retries
    try:
        value = step(case, arm_root, "trigger", None, previous, lock_values, live)
    except Pause as exc:
        raise NeedsAttention(str(exc)) from None
    except TerminalTechnical as exc:
        raise TerminalStage(str(exc)) from None
    return value["evidence"]


def install(
    arm_labels: Sequence[str],
    defense_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Replace ``run_standard`` in the benchmark worker (call before ``runtime.control.worker``)."""
    from runtime import control

    control.run_standard = make_chain_runner(arm_labels, defense_options)
