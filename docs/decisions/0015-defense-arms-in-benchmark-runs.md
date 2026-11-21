# ADR-0015: Defense arms between exposure and trigger in benchmark runs

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
The confirmatory experiment needs real trigger sessions in which each defense arm starts from
the **same** post-exposure memory (matched design, `docs/preregistration.md`). MemHarmBench's
`main` runner (`runtime.protocols.run_standard`) runs one exposure and one trigger per chain and
has no defense step. The submodule must not be modified (ADR-0002).

The paid budget can be spent only once (decision of 2026-11-21), so the hook must reuse the
benchmark's own executors, judge, checkpoints and integrity checks instead of re-implementing
them.

## Decision

### Where the defense runs
- After the accepted exposure and its PMIR judgment, before any trigger.
- The benchmark's trigger restores memory from the selected exposure evidence
  (`memory_after`; for Claude Code also `final_workspace_state`).
- `memauthy.benchrun.defend_exposure` returns a deep copy of that evidence with the defended
  memory:
  - Every memory key is kept; a fully removed file becomes an empty file.
  - `workspace:` keys are mirrored into `final_workspace_state`, which the Claude Code
    replayer requires to match.
- Provenance inputs:
  - P1/P2 use the transcripts of all accepted exposure attempts.
  - The baseline is the memory before the first exposure.
  - P0 uses `oracle_labels_from_case`.
  - A missing input is a reported `defense_failure`, never a silent fallback.

### Chain layout (`memauthy.benchrun.run_defended_chain`)
- **Exposure.** Same logic as `run_standard`: attempt 1, attempt 2 only if PMIR is 0, and no
  trigger if PMIR is unresolved.
- **PMIR 1.** One trigger branch per arm under `outputs/<chain_id>/arms/<slug>/`. Each branch
  holds the arm's `defense.json` (decisions and change report), the benchmark's own trigger
  checkpoints and the judge output.
- **PMIR 0 after both attempts.** Every arm is `skipped`, with adoption 0. Nothing was stored,
  so there is nothing to defend and no trigger is paid for.
- **Lineage.**
  - The trigger must start from the arm's defended memory, in a session different from the
    exposure.
  - A violation raises `LineageError`, which maps to the benchmark's `NeedsAttention`.
  - A change of job or arms on resume is refused.
- **Failures.** A technical failure in one arm (`TerminalStage`) is recorded for that arm only.
  The chain is then `complete_with_unresolved`; failures are never dropped.
- **Arm labels.** Labels are `<condition>:<policy>`, e.g. `D4@P2:block`. The policy defaults
  to `block`. The `D0` baseline arm is mandatory.

### Binding to the benchmark (`memauthy.benchrun.harness`)
- `make_chain_runner(arms)` returns a drop-in replacement for `run_standard`. It reuses:
  - `claude_executor`, with a fresh replayer per arm whose output directory is the arm root;
  - OpenClaw's `step`, because `openclaw_executor` keeps the selected exposure in a closure;
  - `judge_phase` and `valid_label`.
- `install(arms)` swaps it into `runtime.control` inside the worker process.
- Benchmark imports are deferred, because the runtime reads its campaign config at import time.
- The orchestration is unit-tested with fakes. The bindings are exercised by the zero-cost
  rehearsal (issue #46), which also adds the launcher.

## Consequences
- Agent and judge cost per chain scales with the number of arms for triggers only; the
  exposure is paid once. This feeds the budget estimator (issue #47).
- The benchmark's `chain_result.json` is replaced by a MemAuthy result with an `arms` map
  (`design: memauthy-matched-arms-v1`). The benchmark's own metric aggregation does not read it;
  MemAuthy computes matched statistics per arm.
- **The trigger's workspace is the exposure's final workspace, as in the benchmark.** This
  includes the carrier artifact. A defense that edits memory does not remove the artifact,
  which is a property of the benchmark design and is reported as a limitation.
- Only the `main` experiment is supported; the ablation experiments keep the benchmark's
  runner.
