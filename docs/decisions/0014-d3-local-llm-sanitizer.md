# ADR-0014: D3 local LLM memory sanitizer

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
D3 is the strong, content-focused comparison condition, similar to A-MemGuard: an LLM judges each
memory entry. The project has no API budget, so D3 runs at tier 1 on a local model.

Maintainer decisions on 2026-11-20:

- **Model:** `llama3.1:8b` via Ollama.
- **Scale:** a stratified subset.
- **Who runs it:** the maintainer runs the long D3 jobs from a terminal; the assistant prepares
  the commands and reads the results from `results/`.

Measured on the maintainer's RTX 4070 Laptop GPU (8 GB): about 2.5–3 s per call for
llama3.1:8b, qwen3:8b and gemma3:4b, all with valid JSON output.

## Decision

### `memauthy.llm`
- **`OllamaClient`**
  - Talks to a **local** Ollama server only. It refuses non-local URLs, so no paid or remote API
    can be used by accident (ADR-0005).
  - JSON mode, `temperature` from the config (0.0), seed from the config, bounded `num_predict`,
    thinking disabled.
  - Records input and output tokens and wall-clock time.
- **`CachedClient`**
  - Persistent JSONL cache under `.cache/llm/` (git-ignored).
  - Keyed by model, prompt version and messages.
  - Makes long runs resumable and evaluates repeated blocks (e.g. OpenClaw bootstrap templates)
    once.
  - Errors are not cached, so failed calls are retried on the next run.

### D3 `LLMSanitizer`
- **What the LLM sees.** One block at a time, with **no provenance**: text only. The fixed
  system prompt `d3-v1` asks whether the entry could steer future decisions against the user's
  expectations, for example by setting:
  - destinations, recipients or accounts;
  - approvals, rankings, thresholds or budgets;
  - overrides of normal procedures;
  - authority claimed without proof;
  - obfuscated values.
  
  Ordinary style, format or tooling preferences and plain facts are explicitly excluded. The
  answer is `{"suspicious", "kind", "reason"}`.
- **The prompt was written a priori** from general security guidance and **not tuned on any
  evaluation set**. A first probe with a minimal prompt flagged nothing, which motivated
  listing the generic criteria above. That probe used only a handful of hand-written
  sentences, none from the frozen sets.
- **Decisions.**
  - suspicious → `unauthorized`;
  - not suspicious → `authorized`;
  - unusable output → `uncertain` with the error in the rationale. Technical failures are
    reported, never dropped.

### Runners
- **Tiers.** Tier 0 and tier 1 are accepted. Tier 2 (paid) is refused and needs a dedicated
  runner plus maintainer approval.
- **D3 configuration.** Configs declare `models.d3` (provider `ollama`). LLM usage (calls,
  cache hits, errors, tokens, seconds) goes to `cost.json` and `summary.json`.
- **Stratified sampling.** `params.case_sample.per_template` selects a seeded, fixed number of
  cases per template; the adaptive runner draws from IPI cases only.

### Subset runs (tier 1)

| Config | Data | Conditions |
|---|---|---|
| `d3-control-v0.1` | Full control set (120 items × 2 agents) | D0, D2, D3, D4@P1, D4@P2 |
| `d3-detection-v0.1` | 2 cases per template (48) × 2 agents × 3 variants | same |
| `d3-adaptive-v0.1` | 2 IPI cases per template (32) × 2 agents × 24 variants | same |

D2 and D4 are rerun on the same subsets, so all conditions are compared on identical samples.

## Observations at acceptance
Runs on commit `c2ea5ea` (exploratory, synthetic, subset-based). No LLM errors; 1,099 uncached
calls in total, about 2.8 s per call.

| Measure | D2 | D3 | D4@P1 | D4@P2 |
|---|---|---|---|---|
| Control: enforce recall | 0.333 | 0.178 | 0.600 | 1.000 |
| Control: false-block rate | 0.107 | 0.027 | 0.093 | 0.333 |
| Detection (IPI): attack recall | 0.750 | 0.688 | 0.667 | 1.000 |
| Detection (IPI): false-block rate | 0.060 | 0.033 | 0.000 | 0.000 |
| Detection (IPI): recall on `fact` variant | 0.250 | 0.375 | 0.000 | 1.000 |
| Adaptive: neutralized | 0.302 | 0.488 | 0.375 | 0.917 |

- D3 is the most conservative content defense: few false blocks, but it misses most
  identical-text look-alikes (0.13) and every `preference_disguise` variant.
- On DPI-U (trusted user channel) D3 flags 0.812 of the rules. That is expected for a
  content-only defense and is the boundary case D4 deliberately leaves alone.
- The `cost.json` `total` row sums nested timers (`evaluate` contains `audit:*` and the LLM
  time), so its `seconds` overstates wall-clock time; use the `llm:*` and `audit:*` rows.

## Consequences
- D3 results are **subset-based and model-specific** (`llama3.1:8b`, `d3-v1`). A full run, or
  other models, are later additions.
- **D3 sees no provenance by design.** On identical-text twins it can only be right for one
  member of each pair, which is the central contrast with D4.
- The cache makes reruns cheap and lets the exact model outputs be inspected. It is not
  committed, because it holds raw model text.
