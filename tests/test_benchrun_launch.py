"""Campaign planning and cost guard for benchmark runs with defense arms (issue #46)."""

import json
from pathlib import Path
from typing import Any

import pytest

from memauthy.benchrun.launch import (
    LaunchError,
    benchmark_config,
    check_cost_guard,
    choose_cases,
    filter_jobs,
    freeze_json,
    is_local_endpoint,
    relaxed_loader,
    run_plan,
)
from memauthy.config import CostTier, ExperimentConfig, load_config

ROOT = Path(__file__).resolve().parents[1]
CATALOG = [
    {"case_id": f"{t}__c{i}", "template_id": t, "channel": ch}
    for t, ch in (("d_a", "direct_instruction"), ("i_b", "indirect_content"))
    for i in range(3)
] + [
    {"case_id": f"i_c__c{i}", "template_id": "i_c", "channel": "indirect_content"} for i in range(3)
]
BENCH = {
    "agent": "claude_code",
    "model": "gemini-2.5-flash",
    "judge_model": "gpt-5",
    "agent_endpoint": "http://host.docker.internal:11434/v1",
    "judge_endpoint": "http://localhost:11434/v1",
    "agent_key_env": "MHB_AGENT_API_KEY",
    "judge_key_env": "MHB_JUDGE_API_KEY",
    "agent_image": "memharmbench/claude-code:2.1.228",
    "gateway_image": "memharmbench/gateway:1.101.0",
}


def _config(tier: CostTier = CostTier.LOCAL, **params: Any) -> ExperimentConfig:
    base = {"rehearsal": True, "arms": ["D0", "D2"], "benchmark": dict(BENCH)}
    base.update(params)
    return ExperimentConfig(name="r", tier=tier, seed=7, params=base)


def test_local_endpoints() -> None:
    assert is_local_endpoint("http://localhost:11434/v1")
    assert is_local_endpoint("http://host.docker.internal:11434/v1")
    assert not is_local_endpoint("https://api.provider.example/v1")


def test_cost_guard_refuses_paid_and_remote() -> None:
    check_cost_guard(_config())
    with pytest.raises(LaunchError, match="#47"):
        check_cost_guard(_config(CostTier.PAID))
    with pytest.raises(LaunchError, match="rehearsal"):
        check_cost_guard(_config(rehearsal=False))
    remote = {**BENCH, "judge_endpoint": "https://api.provider.example/v1"}
    with pytest.raises(LaunchError, match="judge_endpoint"):
        check_cost_guard(_config(benchmark=remote))


def test_benchmark_config(tmp_path: Path) -> None:
    cfg = benchmark_config(_config(), tmp_path)
    assert cfg["experiment"] == "main" and cfg["replicates"] == 3
    assert cfg["run_dir"] == str((tmp_path / "campaign").resolve())
    with pytest.raises(LaunchError, match="missing"):
        benchmark_config(_config(benchmark={"agent": "openclaw"}), tmp_path)
    with pytest.raises(LaunchError, match="unknown"):
        benchmark_config(_config(benchmark={**BENCH, "replicates": 1}), tmp_path)


def test_case_choice() -> None:
    picked = choose_cases(
        _config(case_sample={"channel": "indirect_content", "n_cases": 2}), CATALOG
    )
    assert len(picked) == 2 and {c.split("__")[0] for c in picked} == {"i_b", "i_c"}
    assert picked == choose_cases(
        _config(case_sample={"channel": "indirect_content", "n_cases": 2}), CATALOG
    )
    explicit = ExperimentConfig(name="r", tier=1, seed=1, case_ids=("i_b__c1",), params={})
    assert choose_cases(explicit, CATALOG) == ["i_b__c1"]
    with pytest.raises(LaunchError, match="unknown case"):
        choose_cases(ExperimentConfig(name="r", tier=1, seed=1, case_ids=("x",)), CATALOG)


def test_filter_jobs() -> None:
    jobs = [{"case_id": c["case_id"], "replicate": r} for c in CATALOG for r in (1, 2, 3)]
    assert len(filter_jobs(jobs, ["i_b__c0", "i_c__c1"], [1, 3])) == 4
    with pytest.raises(LaunchError):
        filter_jobs(jobs, ["missing"], [1])


def test_run_plan(tmp_path: Path) -> None:
    plan = run_plan(_config(case_sample={"n_cases": 1}), CATALOG, tmp_path)
    assert plan["arms"] == ["D0:block", "D2:block"] and plan["replicates"] == [1]
    assert plan["rehearsal"] and len(plan["case_ids"]) == 1
    with pytest.raises(ValueError, match="D0"):
        run_plan(_config(arms=["D2"]), CATALOG, tmp_path)
    with pytest.raises(LaunchError, match="replicates"):
        run_plan(_config(replicates=[4]), CATALOG, tmp_path)


def test_freeze_json(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    freeze_json(path, {"a": 1}, "plan")
    freeze_json(path, {"a": 1}, "plan")
    with pytest.raises(LaunchError, match="changed"):
        freeze_json(path, {"a": 2}, "plan")


def _strict_load(path: Path) -> dict[str, Any]:
    """Stand-in for the benchmark loader: HTTPS only."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("agent_endpoint", "judge_endpoint"):
        if not value[k].startswith("https://"):
            raise ValueError(k + " must use HTTPS")
    value["config_path"] = str(path)
    return value


def test_relaxed_loader_only_for_local_hosts(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.local.json"
    path.write_text(json.dumps(BENCH), encoding="utf-8")
    value = relaxed_loader(_strict_load, str(path))()
    assert value["agent_endpoint"] == BENCH["agent_endpoint"]
    assert value["config_path"] == str(path.resolve())
    remote = {**BENCH, "judge_endpoint": "http://api.provider.example/v1"}
    path.write_text(json.dumps(remote), encoding="utf-8")
    with pytest.raises(ValueError, match="judge_endpoint"):
        relaxed_loader(_strict_load, str(path))()


@pytest.mark.parametrize("name", ["rehearsal-claude-v0.1.yaml", "rehearsal-openclaw-v0.1.yaml"])
def test_shipped_rehearsal_configs_pass_the_guard(name: str, tmp_path: Path) -> None:
    config = load_config(ROOT / "configs" / name)
    plan = run_plan(config, CATALOG, tmp_path)
    assert plan["rehearsal"] and plan["tier"] == 1 and "D0:block" in plan["arms"]


def test_force_trigger_is_rehearsal_only(tmp_path: Path) -> None:
    assert run_plan(_config(force_trigger=True), CATALOG, tmp_path)["force_trigger"]
    cfg = _config(force_trigger=True)
    with pytest.raises(LaunchError):
        run_plan(
            cfg.model_copy(update={"params": {**cfg.params, "rehearsal": False}}), CATALOG, tmp_path
        )


def test_profile_counts_each_message_once(tmp_path: Path) -> None:
    from memauthy.benchrun.profile import campaign_profile

    chain = tmp_path / "outputs" / "c1"

    def line(mid: str, inp: int, out: int) -> str:
        return json.dumps(
            {"message": {"id": mid, "usage": {"input_tokens": inp, "output_tokens": out}}}
        )

    def write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    write(
        chain / "exposure1_evidence.json",
        {"trajectory": [{"lines": [line("m1", 100, 5), line("m1", 100, 5)]}]},
    )
    write(chain / "exposure1_upstream.json", {"rows": [{}, {}]})
    write(
        chain / "exposure2_evidence.json",
        {"trajectory": [{"lines": [line("m1", 100, 5), line("m2", 300, 7)]}]},
    )
    write(
        chain / "arms" / "D0-block" / "trigger_evidence.json",
        {"trajectory": [{"lines": [line("t1", 50, 1)]}]},
    )
    write(
        chain / "judging" / "exposure1" / "judge_cache" / "h" / "response_001.json",
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 20}},
    )
    totals = campaign_profile(tmp_path)["totals"]
    assert (
        totals["exposure"]["agent_prompt_tokens"] == 400
        and totals["exposure"]["agent_messages"] == 2
    )
    assert (
        totals["exposure"]["upstream_calls"] == 2
        and totals["exposure"]["judge_prompt_tokens"] == 1000
    )
    assert totals["trigger"]["agent_prompt_tokens"] == 50 and totals["trigger"]["sessions"] == 1


def test_profile_reads_openclaw_layout(tmp_path: Path) -> None:
    from memauthy.benchrun.profile import campaign_profile

    ev = {
        "upstream_audit": [{}, {}, {}],
        "native_model_metadata": {"contextBudgetStatus": {"estimatedPromptTokens": 7886}},
    }
    path = tmp_path / "outputs" / "c1" / "steps" / "exposure1" / "evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ev), encoding="utf-8")
    totals = campaign_profile(tmp_path)["totals"]["exposure"]
    assert totals["upstream_calls"] == 3 and totals["agent_estimated_prompt_tokens"] == 7886
