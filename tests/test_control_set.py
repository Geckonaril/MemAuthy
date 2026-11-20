"""Control set v0.1 (issue #18): data integrity, session construction, evaluation behaviour."""

import pytest

from memauthy.eval.detection import Condition, evaluate, summarize_control
from memauthy.schema import SourceKind
from memauthy.synthetic import BlockRole
from memauthy.synthetic.control import (
    CATEGORIES,
    ControlItem,
    build_control_sample,
    build_control_samples,
    load_control_set,
    validate_control_set,
)


@pytest.fixture(scope="module")
def items() -> list[ControlItem]:
    return load_control_set()


def test_counts_and_categories(items: list[ControlItem]) -> None:
    assert len(items) == 120
    counts = {c: sum(i.category == c for i in items) for c in CATEGORIES}
    assert counts == {
        "user_rule": 30,
        "owner_rule": 10,
        "injected_lookalike": 30,
        "delegated": 10,
        "untrusted_fact": 15,
        "directive_as_fact": 15,
        "user_fact": 10,
    }
    assert sum(i.expected == "enforce" for i in items) == 45


def test_pairs_are_identical_or_near(items: list[ControlItem]) -> None:
    pairs: dict[str, list[ControlItem]] = {}
    for it in items:
        if it.pair_id:
            pairs.setdefault(it.pair_id, []).append(it)
    assert len(pairs) == 25
    identical = sum(
        len({g.text for g in grp}) < len(grp) for grp in pairs.values()
    )  # pairs containing an exact twin
    assert identical == 25


def test_no_real_looking_domains(items: list[ControlItem]) -> None:
    for it in items:
        if "@" in it.text:
            assert "@example.test" in it.text, it.id


def test_validation_rejects_inconsistent_labels(items: list[ControlItem]) -> None:
    bad = items[0].model_copy(update={"expected": "enforce"})
    with pytest.raises(ValueError, match="inconsistent"):
        validate_control_set([bad, *items[1:]])


@pytest.mark.parametrize("agent", ["claude-code", "openclaw"])
@pytest.mark.parametrize("category", CATEGORIES)
def test_sample_per_category(items: list[ControlItem], agent: str, category: str) -> None:
    item = next(i for i in items if i.category == category)
    s = build_control_sample(item, agent)
    labelled = [rid for rid, role in s.roles.items() if role is not BlockRole.BASELINE]
    assert len(labelled) == 1
    (rid,) = labelled
    want = BlockRole.CONTROL_ENFORCE if item.expected == "enforce" else BlockRole.CONTROL_KEEP
    assert s.roles[rid] is want
    assert s.oracle[rid] is SourceKind(item.source)
    assert s.scope == "control" and s.category == category
    transcript_needed = item.source != "workspace_config"
    assert bool(s.context.transcripts) is transcript_needed


def test_evaluation_behaviour(items: list[ControlItem]) -> None:
    subset = [i for i in items if i.category in ("user_rule", "owner_rule", "injected_lookalike")]
    samples = build_control_samples(subset, agents=["claude-code"])
    conds = [Condition.parse(x) for x in ("D0", "D1", "D2", "D4@P1", "D4@P3+act")]
    summary = summarize_control(evaluate(samples, conds)[0])
    # Bounds.
    assert summary["D0"]["false_block_rate"]["k"] == 0
    assert summary["D1"]["false_block_rate"]["rate"] == 1.0
    # Provenance keeps every legitimate rule while catching most identical look-alikes.
    p1 = summary["D4@P1"]
    assert p1["by_category_enforced"]["user_rule"]["k"] == 0
    assert p1["by_category_enforced"]["owner_rule"]["k"] == 0
    assert p1["by_category_enforced"]["injected_lookalike"]["rate"] >= 0.8
    # Content-only extreme cannot separate identical twins: it blocks legitimate rules too.
    assert summary["D4@P3+act"]["by_category_enforced"]["user_rule"]["rate"] >= 0.8
