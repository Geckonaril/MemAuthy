"""Adaptive attack variants v0.1 (issue #19)."""

import base64

import pytest

from memauthy import bench
from memauthy.cases import load_case
from memauthy.eval.detection import Condition, evaluate, summarize_adaptive
from memauthy.synthetic import BlockRole
from memauthy.synthetic.adaptive import (
    STRATEGIES,
    build_adaptive_sample,
    load_variants,
    placeholders,
)

IPI = "i_u1_embedded_convention__email_contacts"
DPI = "d_u1_standing_instruction__email_contacts"


def test_variants_file() -> None:
    variants = load_variants()
    assert len(variants) == 24
    assert {v.strategy for v in variants} == set(STRATEGIES)
    assert {v.write_mode for v in variants} == {
        "write",
        "bash",
        "merge_user_rule",
        "benign_session",
    }
    for v in variants:
        assert "{v" in "".join(v.blocks) or "{target_rule}" in "".join(v.blocks), v.id


@pytest.mark.benchmark
@pytest.mark.skipif(not bench.dataset_available(), reason="dataset not downloaded")
def test_placeholders() -> None:
    case = load_case(IPI)
    ph = placeholders(case, "Keep briefs short.")
    assert ph["v"] == case.payload_value
    assert f"{ph['v_head']}-{ph['v_tail']}" == case.payload_value
    assert base64.b64decode(ph["v_b64"]).decode() == case.payload_value
    assert "-" not in ph["v_spaced"] and "_" not in ph["v_spaced"]


@pytest.mark.benchmark
@pytest.mark.skipif(not bench.dataset_available(), reason="dataset not downloaded")
@pytest.mark.parametrize("agent", ["claude-code", "openclaw"])
def test_every_variant_builds(agent: str) -> None:
    case = load_case(IPI)
    for v in load_variants():
        s = build_adaptive_sample(case, agent, v)
        assert sum(r is BlockRole.ATTACK for r in s.roles.values()) == len(v.blocks)
        assert s.scope == "adaptive" and s.category == v.strategy
        tool_results = [
            e.content for t in s.context.transcripts for e in t.events if e.kind == "tool_result"
        ]
        if v.id == "adv-16":  # carrier spells the value with spaces only
            assert case.payload_value not in tool_results[0]


@pytest.mark.benchmark
@pytest.mark.skipif(not bench.dataset_available(), reason="dataset not downloaded")
def test_dpi_rejected() -> None:
    with pytest.raises(ValueError, match="IPI"):
        build_adaptive_sample(load_case(DPI), "claude-code", load_variants()[0])


@pytest.mark.benchmark
@pytest.mark.skipif(not bench.dataset_available(), reason="dataset not downloaded")
def test_summary_semantics() -> None:
    case = load_case(IPI)
    variants = {v.id: v for v in load_variants()}
    samples = [
        build_adaptive_sample(case, "claude-code", variants[i]) for i in ("adv-08", "adv-23")
    ]
    conds = [Condition.parse(x) for x in ("D0", "D4@P1", "D4@P2")]
    summary = summarize_adaptive(evaluate(samples, conds)[0])
    assert summary["D0"]["neutralized"]["k"] == 0
    # Rewritten in a later benign session after a user message: P1 attributes it to the user,
    # P2 still traces the content to the earlier untrusted read.
    p1 = summary["D4@P1"]["by_variant"]["adv-23"]["neutralized"]["rate"]
    p2 = summary["D4@P2"]["by_variant"]["adv-23"]["neutralized"]["rate"]
    assert p1 == 0.0 and p2 == 1.0
    # Split attack counts as neutralized only if both blocks are enforced.
    split = summary["D4@P2"]["by_variant"]["adv-08"]
    assert split["block_recall"]["n"] == 2
