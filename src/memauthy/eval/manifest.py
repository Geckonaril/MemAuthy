"""Run manifests: everything needed to trace a result back to its inputs (see ADR-0004)."""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from memauthy import __version__
from memauthy.config import ExperimentConfig, config_hash
from memauthy.eval.cost import CostTracker
from memauthy.schema import SCHEMA_VERSION
from memauthy.seeding import seed_everything

RunStatus = Literal["running", "completed", "failed"]


class GitState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str | None
    dirty: bool | None


class RunManifest(BaseModel):
    """Contents of ``results/<run_id>/manifest.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    status: RunStatus = "running"
    memauthy_version: str
    memauthy_git: GitState
    benchmark_commit: str | None = None
    dataset_revision: str | None = None
    config_hash: str
    config: dict[str, Any]
    models: dict[str, dict[str, Any]]  # role -> {name, version, ...}
    seed: int
    case_ids: list[str]
    started_at: datetime
    finished_at: datetime | None = None
    python: str
    platform: str
    error: str | None = None


def git_state(repo_dir: str | Path = ".") -> GitState:
    """Commit hash and dirty flag of a git checkout; ``None`` fields if unavailable."""

    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return GitState(commit=None, dirty=None)
    status = _git("status", "--porcelain", "--untracked-files=no")
    return GitState(commit=commit, dirty=None if status is None else bool(status))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_run_id(config: ExperimentConfig, now: datetime | None = None) -> str:
    """``<UTC timestamp>-<config name>-<first 8 chars of config hash>``."""
    stamp = (now or _utcnow()).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{config.name}-{config_hash(config)[:8]}"


class Run:
    """Ties a manifest and a cost tracker to one run directory.

    Usage::

        with Run.start(config, results_dir="results") as run:
            with run.cost.timed("defense:D2"):
                ...
    """

    def __init__(self, manifest: RunManifest, run_dir: Path) -> None:
        self.manifest = manifest
        self.run_dir = run_dir
        self.cost = CostTracker(manifest.run_id)

    @classmethod
    def start(
        cls,
        config: ExperimentConfig,
        *,
        results_dir: str | Path = "results",
        repo_dir: str | Path = ".",
        benchmark_commit: str | None = None,
        dataset_revision: str | None = None,
    ) -> Run:
        seed_everything(config.seed)
        now = _utcnow()
        run_id = new_run_id(config, now)
        manifest = RunManifest(
            run_id=run_id,
            memauthy_version=__version__,
            memauthy_git=git_state(repo_dir),
            benchmark_commit=benchmark_commit,
            dataset_revision=dataset_revision,
            config_hash=config_hash(config),
            config=config.model_dump(mode="json"),
            models={role: m.model_dump(mode="json") for role, m in config.models.items()},
            seed=config.seed,
            case_ids=list(config.case_ids),
            started_at=now,
            python=sys.version.split()[0],
            platform=platform.platform(),
        )
        run_dir = Path(results_dir) / run_id
        if run_dir.exists():
            raise FileExistsError(f"run directory already exists: {run_dir}")
        run = cls(manifest, run_dir)
        run.write()
        return run

    def write(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "manifest.json").write_text(
            self.manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        self.cost.write(self.run_dir)

    def finish(self, status: RunStatus = "completed", error: str | None = None) -> None:
        self.manifest.status = status
        self.manifest.error = error
        self.manifest.finished_at = _utcnow()
        self.write()

    def __enter__(self) -> Run:
        return self

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        if exc is None:
            self.finish("completed")
        else:
            self.finish("failed", error=f"{type(exc).__name__}: {exc}")
