"""MemHarmBench integration. Tests marked ``benchmark`` need the downloaded dataset."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memauthy import bench
from memauthy.cli import app

ROOT = Path(__file__).resolve().parents[1]
SUBMODULE = ROOT / "third_party" / "MemHarmBench"
PINNED_DATASET_REVISION = "2b4c2b736fdbabf7e56182870d71095ac38afdb0"


def test_source_root_is_the_submodule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(bench.DATA_ROOT_ENV, raising=False)
    assert bench.source_root() == SUBMODULE.resolve()
    assert bench.data_root() == SUBMODULE.resolve()


def test_data_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(bench.DATA_ROOT_ENV, str(tmp_path))
    assert bench.data_root() == tmp_path.resolve()
    assert not bench.dataset_available()


def test_dataset_revision_is_pinned() -> None:
    assert bench.dataset_revision() == PINNED_DATASET_REVISION


def test_benchmark_commit_matches_submodule() -> None:
    commit = bench.benchmark_commit()
    assert commit is not None and len(commit) == 40


def test_cli_reports_missing_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(bench.DATA_ROOT_ENV, str(tmp_path))
    result = CliRunner().invoke(app, ["bench", "validate"])
    assert result.exit_code == 2
    assert "bench download" in result.output


requires_dataset = pytest.mark.skipif(
    not bench.dataset_available(), reason="MemHarmBench dataset not downloaded"
)


@pytest.mark.benchmark
@requires_dataset
def test_catalog_has_288_cases() -> None:
    catalog = json.loads((bench.data_root() / bench.CATALOG).read_text(encoding="utf-8"))
    cases = catalog["cases"]
    assert len(cases) == 288
    assert len({c["case_id"] for c in cases}) == 288


@pytest.mark.benchmark
@requires_dataset
def test_offline_validation_passes() -> None:
    assert bench.run_benchmark_cli(["validate"]) == 0
