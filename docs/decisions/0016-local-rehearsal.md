# ADR-0016: Zero-cost local rehearsal of benchmark campaigns

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
The paid budget can be spent once (decision of 2026-11-21). Before that run we need two things:

- evidence that the whole chain works with the arms of ADR-0015: Docker images, gateway, native
  memory capture, defense, per-arm triggers and the judge;
- real call and token counts per stage, for the budget estimate (issue #47).

The benchmark accepts only `gemini-2.5-flash`/`gpt-5` as model names and HTTPS endpoints, and
checks that the upstream answers with exactly that model name.

## Decision

### Launcher: `experiments/benchmark_arms.py`
- Control semantics are the same as the benchmark's `scripts/experiment.py`: `check`, `start`,
  `status`, `pause`, `resume`, `retry`, a background worker and checkpoints.
- The launcher imports the benchmark runtime and applies three in-process patches:
  1. the job list is limited to the configured cases and replicates (the benchmark's own
     864-chain check still runs on the full list);
  2. `run_standard` is replaced by the arm runner of ADR-0015;
  3. for rehearsals only, local `http://` endpoints pass the HTTPS check. The benchmark
     validates a shadow copy of the config, and the real local URLs are used.
- The worker is the same script with the hidden `_worker` action, so the patches also apply
  there.
- Outputs go to `runs/<name>/` (git-ignored):
  - `benchmark.local.json` and `memauthy_run.json`: the plan, frozen on first use; a change
    is refused, so a changed campaign needs a new name;
  - `launches.jsonl`: one line per launch, with the MemAuthy git state and the local models
    behind the model names.

### Cost guard (`memauthy.benchrun.launch`)
- Only tier-1 configs with `rehearsal: true` and local endpoints (`localhost`, `127.0.0.1`,
  `host.docker.internal`) are accepted.
- Tier 2 is refused until the budget cap (issue #47) exists. A rehearsal therefore cannot
  reach a paid API by mistake.

### Local stand-in models
- `configs/rehearsal-ollama.Modelfile` creates the Ollama aliases `gemini-2.5-flash` and
  `gpt-5` from `llama3.1:8b`, with `num_ctx` 32768 for the agents' large system prompts.
- The names exist only to pass the benchmark's fixed model check. `launches.jsonl` records the
  real base model.

### Rehearsal configs
- `configs/rehearsal-{claude,openclaw}-v0.1.yaml`: 3 IPI cases from distinct templates
  (seeded), replicate 1, arms `D0`, `D2`, `D4@P2`.

## Consequences
- **Rehearsal outcomes are never analysed.** A small local model is a different agent; only
  plumbing, failures and token use are read from it.
- **Token counts are approximate.**
  - Prompt sizes (system prompt, tools, memory, files) do not depend on the model, but the
    tokenizer does.
  - Turn counts and output lengths depend on the model.
  - The budget estimate therefore uses a safety margin (issue #47).
- D3 arms are not wired into campaigns yet (no LLM client option in the launcher).
- The launcher runs on Windows only, like the benchmark's background control.

## Findings from the rehearsal
- **v0.1 (Claude Code).**
  - Exposure, memory capture and judging ran without technical failure.
  - The local 8B "judge" produced invalid evidence references, so PMIR stayed unresolved and
    no trigger ran.
  - The rehearsal-only option `force_trigger` (refused outside rehearsals) runs the arms when
    the exposure changed memory. The chain is then marked `trigger_status: forced`.
- **v0.2 (Claude Code), first attempt.**
  - The trigger's native transcript could not be written: Docker Desktop's Windows bind mount
    returned `Input/output error` for the arm directories nested inside the benchmark's
    already long chain path. This was reproduced with a probe container, and a shorter
    directory worked.
  - Arms now live in `<run_dir>/arms/<10 hex of chain_id>/<arm>/`. `chain_result.json` records
    each arm's `root`.
- **v0.2, second attempt.**
  - After the run directory was deleted, the benchmark reused the gateway container of the
    same config. That container held the old master key and rejected the new client with
    `400 No connected db`, so exposure 1 stopped as an integrity failure.
  - The launcher now removes this campaign's own gateway container (checked by its owner
    label) when the campaign's private token file is missing. The removal is recorded in
    `launches.jsonl`.
- **v0.2, third attempt (commit `670552b`).**
  - All three chains completed without technical failure.
  - Two chains ran forced triggers: six arm sessions, each restored from its defended memory,
    with lineage checks passing, and each judged.
  - The 8B stand-in agent stored only placeholder text, with no attack payload. D4@P2
    therefore correctly left memory unchanged, and D2 removed one block.
  - Labels from the 8B judge are unreliable (`need_human_review`) and are not analysed.
  - **Observation for the real run.** Exposure attempt 2 starts with the benchmark's follow-up
    *user* message. A block written right after it, with no tool output in between, gets P1
    source `user`, even if its content came from the carrier read in attempt 1. P2 still
    checks content against all earlier tool outputs, so the payload is caught by content
    match. P1 alone would miss it, as expected for a structural method.
- **Token profile (approximate; the stand-in model makes few tool calls).**
  - Claude Code requests are about 2.9k to 20k prompt tokens each.
  - Judge requests are about 11k to 17.5k prompt tokens each, with about 150 completion
    tokens.
  - Call counts per session are not representative of the target model. The budget
    estimate (issue #47) must assume them.
- **OpenClaw v0.2 (commit `acd8f3c`).**
  - The three exposures completed without technical failure.
  - The 8B stand-in answered without writing memory, so `force_trigger` (which then
    required changed memory) did not fire, and the OpenClaw trigger binding stayed untested.
  - `force_trigger` now fires whenever there is memory to restore; OpenClaw always has its
    bootstrap files.
  - OpenClaw's relay records zero token usage. The profile therefore uses OpenClaw's
    pre-prompt estimate (about 7.9k tokens at session start) and the upstream call count:
    about 5 per exposure.
- **OpenClaw v0.3, first attempt (commit `67d8e81`).**
  - In exposure 1 the stand-in agent looped: 48 upstream calls of about 26 s each, until
    OpenClaw's own 900 s embedded-run timeout aborted the last request.
  - The benchmark's audit check then rejected the capture (`ValueError`, an aborted upstream
    row) and stopped the campaign with `NEEDS_ATTENTION`. That is benchmark behaviour, not a
    MemAuthy failure.
  - **Implications for the paid run (issue #47).**
    1. Neither agent has a turn limit; the session timeout is the only bound. A looping
       session can make dozens of full-prompt calls, so the budget must assume a worst case
       per session, not a typical one.
    2. A timeout-aborted capture halts the whole campaign until it is handled by hand.
