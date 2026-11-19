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
  `@pytest.mark.benchmark` and skip when the dataset is absent, so the main test jobs need no
  download. A separate CI job downloads the public dataset, runs the offline validation and the
  benchmark tests, and checks that the submodule stays unmodified.

### Pinned versions (2026-11-19)

| Item | Value |
|---|---|
| MemHarmBench commit | `9affbe5af5c2624ac6d4c03730a39ec11d6cc802` (package `memharmbench` 8.4.3) |
| Dataset | `kirco567/MemHarmBench` @ `2b4c2b736fdbabf7e56182870d71095ac38afdb0` |
| Dataset input fingerprint | `fc129ed3bef9fc040fac73f5f257f5b86447ff2404303d457a4de636d660e462` |
| Release lock sha256 | `9381083bd5a68c10472b00e3ee217ce5c6c3c4ae78c415d19c20dc1fb282a92c` |

Offline validation at these versions: 288 cases (96 direct, 192 indirect), 24 templates,
12 contexts, 12 objectives, 0 model requests.

The package is installed through the uv dependency group `bench` (enabled by default) rather
than the runtime dependencies, so `memauthy` itself installs without the submodule.

## Alternatives considered
- **Vendoring a copy** — easy to drift and to modify accidentally.
- **Installing from PyPI/Git URL only** — hides the exact source being run and makes reading
  the benchmark harder; still requires the separate dataset download.
- **Forking** — only if upstream changes become necessary; then this ADR is superseded.

## Consequences
- Clones need `git submodule update --init`.
- Upgrading the benchmark is an explicit, reviewed change (new ADR or an amendment here).
