# ADR-0001: Repository layout and tooling

- **Status:** Accepted
- **Date:** 2026-11-19

## Context
The project is a research prototype that has to be reproducible by others, testable without
API keys, and compatible with MemHarmBench (Python 3.11+, CI on 3.11/3.12).

## Decision
- `src/` layout with a single package `memauthy` and sub-packages by responsibility:
  `memory_io` (agent memory adapters), `rules` (rule classification), `provenance` (P0–P3
  extractors), `policy` (authority decision, block/quarantine/downgrade), `defenses` (D0–D4),
  `eval` (metrics, statistics, manifests, reporting). CLI in `memauthy.cli` (typer).
- Top-level folders: `configs/` (YAML experiment configs), `experiments/` (run scripts),
  `data/control/`, `data/adaptive/` (our datasets), `results/` (manifests and summaries only),
  `docs/`, `tests/`, `third_party/` (pinned submodules).
- **uv** for environments and locking (`uv.lock` committed); `.python-version` pins 3.12,
  `requires-python >=3.11`; hatchling build backend.
- **ruff** for lint and format, **pytest** for tests. Type hints everywhere; a type checker
  may be added later.
- **MIT** license, compatible with MemHarmBench.
- English for code, docs, issues and PRs.

## Alternatives considered
- **pip + venv** (MemHarmBench's own setup) — no lockfile, slower; uv can still install the
  benchmark as a path dependency.
- **Flat layout** — risks tests importing the working tree instead of the installed package.

## Consequences
- One command (`uv sync`) reproduces the environment.
- On Windows with Smart App Control, the generated console-script shim may be blocked;
  `python -m memauthy` is provided as an equivalent entry point.
