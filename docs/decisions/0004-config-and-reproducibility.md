# ADR-0004: Configuration and reproducibility

- **Status:** Accepted
- **Date:** 2026-11-19

## Context
Results will be preregistered and published with code and raw outputs. Any table or figure
must be traceable to the exact code, benchmark, configuration, model and cases that produced it.

## Decision
- Experiments are described by **YAML configs** in `configs/`, validated by pydantic models.
  Model name, version, temperature and all sampling parameters are explicit; no hidden defaults.
- A **config hash** (sha256 of the canonical, key-sorted JSON form) identifies a configuration.
- Every run writes `results/<run_id>/manifest.json` containing: memauthy git commit (and dirty
  flag), MemHarmBench commit, dataset revision, config hash, model and version, seed, start/end
  timestamps, and case IDs.
- Every run writes `results/<run_id>/cost.json`: input/output tokens, wall-clock time, and USD
  cost, per component and in total.
- All randomness is seeded from the config.
- Raw outputs stay out of Git; manifests and summaries are committed. Analysis code regenerates
  every table and figure from raw results with a single command.

## Alternatives considered
- **Hydra / OmegaConf** — more power than needed and harder to hash canonically.
- **CLI flags only** — not reviewable or citable.

## Consequences
- Small upfront cost on every runner; in exchange, results are auditable and re-runnable.
