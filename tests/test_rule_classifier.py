"""Rule classifier (issue #11).

The dev set (data/dev/rule_classifier_dev_v0.1.jsonl) was used to develop the classifier, so its
scores are optimistic and serve as regression checks. Benchmark rules were not used for tuning
(see ADR-0007 for the caveat that example rules were viewed).
"""

import json
from pathlib import Path

import pytest

from memauthy import bench
from memauthy.eval.classification import classification_report, wilson_interval
from memauthy.rules import RuleClassifier, classify
from memauthy.schema import RecordKind

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "dev" / "rule_classifier_dev_v0.1.jsonl"


def _dev_rows() -> list[dict[str, str]]:
    return [json.loads(line) for line in DEV.read_text(encoding="utf-8").splitlines() if line]


def test_dev_set_is_well_formed() -> None:
    rows = _dev_rows()
    assert len({r["id"] for r in rows}) == len(rows) >= 80
    assert {r["label"] for r in rows} == {"rule", "preference", "information"}


def test_dev_set_regression() -> None:
    rows = _dev_rows()
    pred = [classify(r["text"], r["block_kind"]).kind.value for r in rows]
    report = classification_report([r["label"] for r in rows], pred)
    assert report.accuracy >= 0.95
    assert report.per_class["rule"].recall >= 0.95
    assert report.per_class["preference"].recall >= 0.9
    misses = {r["id"] for r, p in zip(rows, pred, strict=True) if p != r["label"]}
    hard = {r["id"] for r in rows if r["note"].startswith("hard:")}
    assert misses <= hard, f"non-hard misses: {sorted(misses - hard)}"


@pytest.mark.parametrize(
    ("text", "block_kind", "expected"),
    [
        ("", "paragraph", RecordKind.UNKNOWN),
        ("name: x\ndescription: y", "front_matter", RecordKind.INFORMATION),
        ("```\nalways run make\n```", "code", RecordKind.INFORMATION),
        ("Prefer the stable channel for releases.", "list_item", RecordKind.RULE),
        ("User prefers the stable channel.", "list_item", RecordKind.PREFERENCE),
        ("2026-11-20 should we rename the repo?", "list_item", RecordKind.INFORMATION),
        ("Procedure: archive closed tickets weekly.", "list_item", RecordKind.RULE),
    ],
)
def test_specific_behaviour(text: str, block_kind: str, expected: RecordKind) -> None:
    assert classify(text, block_kind).kind is expected


def test_deterministic_and_explained() -> None:
    a = classify("Always cc legal@example.test on contracts.", "list_item")
    b = classify("Always cc legal@example.test on contracts.", "list_item")
    assert a == b
    assert a.kind is RecordKind.RULE and 0.5 <= a.confidence <= 0.95
    assert "obligation" in a.features and "rule=" in a.rationale
    assert RuleClassifier().name == "rule-based-v0.1"


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(8, 10)
    assert 0.49 < lo < 0.5 and 0.94 < hi < 0.95
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_classification_report_counts() -> None:
    r = classification_report(["a", "a", "b"], ["a", "b", "b"])
    assert r.confusion == {"a": {"a": 1, "b": 1}, "b": {"a": 0, "b": 1}}
    assert r.per_class["a"].precision == 1.0 and r.per_class["a"].recall == 0.5
    assert r.accuracy == pytest.approx(2 / 3)


requires_dataset = pytest.mark.skipif(
    not bench.dataset_available(), reason="dataset not downloaded"
)


@pytest.mark.benchmark
@requires_dataset
@pytest.mark.parametrize("field", ["target_memory_rule", "payload_text"])
def test_benchmark_rules_are_rules(field: str) -> None:
    catalog = json.loads((bench.data_root() / bench.CATALOG).read_text(encoding="utf-8"))
    kinds = [classify(c[field], "list_item").kind for c in catalog["cases"]]
    recall = sum(k is RecordKind.RULE for k in kinds) / len(kinds)
    assert recall >= 0.95, f"{field}: rule recall {recall:.3f}"
