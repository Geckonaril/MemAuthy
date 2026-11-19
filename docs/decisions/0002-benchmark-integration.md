# ADR-0002: MemHarmBench integration

- **Status:** Accepted
- **Date:** 2026-11-19

## Context
Experiments build on MemHarmBench (Wang et al., 2026; MIT): 288 runnable cases, native agent
execution for Claude Code and OpenClaw, and a snapshot mechanism (exposure → normal sessions →
snapshots S0/S2/S4 → isolated trigger branches). Its inputs are not stored in Git but restored
from a pinned Hugging Face dataset revision. Results are only comparable if the benchmark code
and data are exactly the ones reported.

## Decision
- Add MemHarmBench as a **git submodule** at `third_party/MemHarmBench`, pinned to a specific
  commit. The commit hash is recorded in the README, in this ADR once pinned, and in every run
  manifest.
- Install it into the uv environment as an **editable path dependency** (package
  `memharmbench_v84`) so its loader, contracts and metrics can be reused directly.
- Restore the dataset with the benchmark's own downloader from its pinned revision
  (`kirco567/MemHarmBench`, revision `2b4c2b736fdbabf7e56182870d71095ac38afdb0` at the time of
  writing). Dataset and benchmark files are **never modified**.
- All adaptation code (reading native memory files, applying an audited snapshot to a trigger
  branch) lives in `src/memauthy/memory_io/`.
- Unit tests use synthetic fixtures. Tests that need real benchmark data are marked
  `@pytest.mark.benchmark` and skip when the dataset is absent, so CI needs no download.

## Alternatives considered
- **Vendoring a copy** — easy to drift and to modify accidentally.
- **Installing from PyPI/Git URL only** — hides the exact source being run and makes reading
  the benchmark harder; still requires the separate dataset download.
- **Forking** — only if upstream changes become necessary; then this ADR is superseded.

## Consequences
- Clones need `git submodule update --init`.
- Upgrading the benchmark is an explicit, reviewed change (new ADR or an amendment here).
