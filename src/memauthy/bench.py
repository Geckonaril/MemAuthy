"""Thin integration layer over the pinned MemHarmBench submodule (see ADR-0002).

MemHarmBench code and data are never modified; this module only locates them and calls the
benchmark's own offline commands.
"""

from __future__ import annotations

import os
from pathlib import Path

from memauthy.eval.manifest import git_state

DATA_ROOT_ENV = "MEMHARMBENCH_DATA_ROOT"
CATALOG = Path("cases") / "catalog.json"


class BenchmarkUnavailableError(RuntimeError):
    """The MemHarmBench package is not installed (submodule missing or not synced)."""


def source_root() -> Path:
    """Root of the MemHarmBench source checkout (the submodule)."""
    try:
        import memharmbench_v84
    except ImportError as exc:
        raise BenchmarkUnavailableError(
            "MemHarmBench is not installed. Run `git submodule update --init` and `uv sync`."
        ) from exc
    return Path(memharmbench_v84.__file__).resolve().parents[2]


def data_root() -> Path:
    """Where the dataset lives: ``$MEMHARMBENCH_DATA_ROOT`` or the submodule itself."""
    env = os.environ.get(DATA_ROOT_ENV)
    return Path(env).expanduser().resolve() if env else source_root()


def dataset_available(root: Path | None = None) -> bool:
    try:
        return ((root or data_root()) / CATALOG).is_file()
    except BenchmarkUnavailableError:
        return False


def benchmark_commit() -> str | None:
    """Pinned submodule commit, recorded in every run manifest."""
    return git_state(source_root()).commit


def dataset_revision() -> str:
    from memharmbench_v84.dataset_download import HF_REVISION

    return HF_REVISION


def run_benchmark_cli(args: list[str], root: Path | None = None) -> int:
    """Run ``memharmbench <args>`` in-process against ``root`` (default: :func:`data_root`)."""
    from memharmbench_v84.cli import main

    return main(["--root", str(root or data_root()), *args])
