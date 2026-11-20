"""Synthetic snapshots and offline detection evaluation (issue #15)."""

import json
from pathlib import Path

import pytest

from memauthy import bench
from memauthy.cases import load_case
from memauthy.eval.detection import (
    DEFAULT_CONDITIONS,
    Condition,
    evaluate,
    markdown_table,
    summarize,
)
from memauthy.memory_io import openclaw
from memauthy.schema import ProvenanceLevel, SourceKind
from memauthy.synthetic import VARIANTS, BlockRole, attack_text, build_sample

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(not bench.dataset_available(), reason="dataset not downloaded"),
]
IPI = "i_u1_embedded_convention__email_contacts"
DPI = "d_u1_standing_instruction__email_contacts"
ROOT = Path(__file__).resolve().parents[1]


def test_condition_labels_round_trip() -> None:
    for c in DEFAULT_CONDITIONS:
        assert Condition.parse(c.label) == c
    assert Condition.parse("D4@P1").level is ProvenanceLevel.P1


@pytest.mark.parametrize("agent", ["claude-code", "openclaw"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_sample_construction(agent: str, variant: str) -> None:
    s = build_sample(load_case(IPI), agent, variant)
    roles = list(s.roles.values())
    assert roles.count(BlockRole.ATTACK) == 1
    assert BlockRole.TASK_NOTE in roles and BlockRole.USER_RULE in roles
    assert BlockRole.BASELINE in roles
    assert set(s.roles) == set(s.memory.snapshot.record_ids) == set(s.oracle)
    attack_id = next(k for k, v in s.roles.items() if v is BlockRole.ATTACK)
    assert s.oracle[attack_id] is SourceKind.DOCUMENT
    assert s.context.oracle is None and s.context_with_oracle().oracle is not None
    if agent == "openclaw":
        assert set(openclaw.load_seed_templates()) <= set(s.memory.files)


def test_fact_variant_has_no_directive_wording() -> None:
    text = attack_text(load_case(IPI), "fact")
    assert "ARCHIVE-ALT" in text and "later" not in text.lower() and "convention" not in text


def test_dpi_attack_source_is_user() -> None:
    s = build_sample(load_case(DPI), "claude-code", "target")
    attack_id = next(k for k, v in s.roles.items() if v is BlockRole.ATTACK)
    assert s.oracle[attack_id] is SourceKind.USER


def test_evaluation_on_small_set() -> None:
    samples = [
        build_sample(load_case(cid), agent, v, index=i)
        for i, cid in enumerate((IPI, DPI))
        for agent in ("claude-code", "openclaw")
        for v in VARIANTS
    ]
    rows, seconds = evaluate(samples)
    summary = summarize(rows, seconds)
    ipi = summary["overall"]
    # Bounds: D0 never enforces, D1 enforces everything.
    assert ipi["D0"]["ipi"]["attack_recall"]["k"] == 0
    assert ipi["D1"]["ipi"]["attack_recall"]["rate"] == 1.0
    assert ipi["D1"]["ipi"]["false_block_rate"]["rate"] == 1.0
    # P0 oracle: every IPI attack enforced, no legitimate block touched.
    assert ipi["D4@P0"]["ipi"]["false_block_rate"]["k"] == 0
    # The fact variant is classified as information; provenance-first (ADR-0012) still catches
    # it with oracle provenance, while P1 (no content evidence) does not.
    by_variant = summary["by_variant"]
    assert by_variant["D4@P0"]["ipi"]["target"]["attack_recall"]["rate"] == 1.0
    assert by_variant["D4@P0"]["ipi"]["fact"]["attack_recall"]["rate"] == 1.0
    assert by_variant["D4@P1"]["ipi"]["fact"]["attack_recall"]["rate"] == 0.0
    # DPI-U: the rule is user-sourced, so D4 at P0/P1 does not enforce it (by design).
    assert ipi["D4@P1"]["dpi"]["attack_recall"]["k"] == 0
    assert "| D4@P1 |" in markdown_table(summary, "ipi")


def test_runner_writes_results(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "offline_detection", ROOT / "experiments" / "offline_detection.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "name: offline-detection-test\ntier: 0\nseed: 1\n"
        f"case_ids: [{IPI}, {DPI}]\n"
        "params:\n  agents: [claude-code]\n  variants: [target]\n  conditions: [D0, D2, D4@P1]\n",
        encoding="utf-8",
    )
    assert module.main(["--config", str(cfg), "--results-dir", str(tmp_path / "results")]) == 0
    (run_dir,) = (tmp_path / "results").iterdir()
    for name in ("manifest.json", "cost.json", "summary.json", "summary.md", "blocks.jsonl"):
        assert (run_dir / name).is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed" and manifest["benchmark_commit"]
    assert manifest["case_ids"] == [IPI, DPI]
