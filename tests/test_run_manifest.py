import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memauthy.config import CostTier, ExperimentConfig, ModelConfig, config_hash
from memauthy.eval import CostTracker, Run, RunManifest, git_state, new_run_id
from memauthy.schema import AuditCost
from memauthy.seeding import seed_everything


@pytest.fixture(autouse=True)
def _restore_hashseed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)


@pytest.fixture
def config() -> ExperimentConfig:
    return ExperimentConfig(
        name="dummy",
        tier=CostTier.LOCAL,
        seed=7,
        case_ids=("c1", "c2"),
        models={
            "defense": ModelConfig(
                name="llama3.1", version="8b", provider="ollama", temperature=0.0
            )
        },
    )


def test_dummy_run_writes_manifest_and_cost(config: ExperimentConfig, tmp_path: Path) -> None:
    with Run.start(config, results_dir=tmp_path, benchmark_commit="abc123") as run:
        run.cost.add("defense", calls=2, input_tokens=100, output_tokens=20, usd=0.0)
        run.cost.add_audit_cost("defense", AuditCost(input_tokens=5, seconds=0.5))

    manifest = RunManifest.model_validate_json((run.run_dir / "manifest.json").read_text())
    assert manifest.status == "completed"
    assert manifest.finished_at is not None
    assert manifest.config_hash == config_hash(config)
    assert manifest.case_ids == ["c1", "c2"]
    assert manifest.seed == 7
    assert manifest.benchmark_commit == "abc123"
    assert manifest.models["defense"]["temperature"] == 0.0

    cost = json.loads((run.run_dir / "cost.json").read_text())
    assert cost["run_id"] == manifest.run_id
    assert cost["total"]["calls"] == 2
    assert cost["total"]["input_tokens"] == 105
    assert cost["total"]["seconds"] == pytest.approx(0.5)


def test_failed_run_is_recorded(config: ExperimentConfig, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), Run.start(config, results_dir=tmp_path) as run:
        raise RuntimeError("boom")
    manifest = RunManifest.model_validate_json((run.run_dir / "manifest.json").read_text())
    assert manifest.status == "failed"
    assert manifest.error == "RuntimeError: boom"


def test_run_id_format(config: ExperimentConfig) -> None:
    now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
    assert new_run_id(config, now) == f"20261119T120000Z-dummy-{config_hash(config)[:8]}"


def test_existing_run_dir_not_overwritten(
    config: ExperimentConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime(2026, 11, 19, tzinfo=UTC)
    monkeypatch.setattr("memauthy.eval.manifest._utcnow", lambda: fixed)
    Run.start(config, results_dir=tmp_path)
    with pytest.raises(FileExistsError):
        Run.start(config, results_dir=tmp_path)


def test_git_state_outside_repo(tmp_path: Path) -> None:
    state = git_state(tmp_path)
    assert state.commit is None and state.dirty is None


def test_cost_tracker_timed_and_sorted() -> None:
    tracker = CostTracker("r")
    with tracker.timed("z-component"):
        pass
    tracker.add("a-component", calls=1)
    log = tracker.to_log()
    assert [c.component for c in log.components] == ["a-component", "z-component"]
    assert log.components[1].seconds >= 0.0


def test_seed_everything_is_deterministic() -> None:
    seed_everything(42)
    first = [random.random() for _ in range(3)]
    seed_everything(42)
    assert [random.random() for _ in range(3)] == first
