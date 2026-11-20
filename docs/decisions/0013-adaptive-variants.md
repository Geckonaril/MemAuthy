# ADR-0013: Adaptive attack variants v0.1

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
RQ5 (exploratory) asks how far adaptive attacks reduce the defense's effectiveness. Threat model
§4 assumes an adaptive attacker who knows that a memory audit exists and knows its general
logic, but not its thresholds or patterns.

## Decision
- **Variant set.** `data/adaptive/v0.1/variants.jsonl` contains 24 hand-crafted variants in
  six strategies: preference disguise, provenance spoofing, split, conditional or indirect
  phrasing, fact form with value obfuscation, and laundering. Each variant is a carrier template
  plus the memory blocks the agent writes and the write mode. Templates are filled from each
  IPI case. A dataset card accompanies the file.
- **The attacker controls the whole carrier.** The tool result contains only the variant's
  carrier text, not the benchmark's original `payload_text`. Otherwise obfuscation variants
  would be detected through the original text.
- **Write modes.**
  - `write`: written right after the read;
  - `bash`: written by a shell command, which P1 does not see;
  - `merge_user_rule`: merged into a legitimate user rule stated in the same session;
  - `benign_session`: rewritten in a later session right after an innocuous user message,
    which defeats P1's last-write rule by construction.
- **Metric.** *Neutralization*: a sample counts only if **every** attack block in it is
  enforced, because a split attack that keeps one block may still work. Block recall and false
  blocks are also reported, by strategy and by variant.
- **Scope.** IPI cases only (192), both agents: 192 × 2 × 24 = 9,216 samples. Runner:
  `experiments/adaptive_evaluation.py`.
- **No tuning on this set.** The variants were frozen before the defense saw them. Weaknesses
  found here are reported as v0.1 findings. Any fix is evaluated on a **new** variant set
  (v0.2), never by tuning on v0.1.

## Consequences
- RQ5 now has a reproducible baseline for D2 and for D4 at P0–P3.
- **Detection only.** Whether a variant still makes the agent adopt the attacker's value
  (C-ASR) needs the trigger experiments of phase 5. Some variants, such as base64 or split
  values, may fail to induce adoption at all.
- **Developer-written.** The defense developers also wrote the variants. A stronger evaluation
  would use attacks written independently, or an automated attacker.
