# ADR-0008: Provenance extractors P0, P1, P3

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
The provenance level is an experimental variable (threat model §6). Each extractor estimates,
for every memory record, where the record came from. The authority policy (#13) turns that
estimate into a decision. P2 (transcript taint) comes in phase 3.

## Decision

### Interface
`ProvenanceExtractor.estimate(snapshot, context) -> {record_id: ProvenanceEstimate}`, where an
estimate carries a source, a confidence, evidence (event refs) and a rationale. Every record
gets an estimate.

`ProvenanceContext` defines what a defense may know besides the snapshot:

| Field | Used by | Meaning |
|---|---|---|
| `transcripts` | P1, P2 | Sessions between the baseline and the snapshot |
| `baseline_files` | P1, P2 | Memory before any untrusted exposure: OpenClaw bootstrap templates, empty for Claude Code, or an earlier audited state |
| `oracle` | **P0 only** | Ground-truth source per record; realistic levels never read it |

### P3: none
Every record gets `unknown` with confidence 0. A P3 defense relies on content alone.

### P0: oracle
P0 reads `context.oracle`, with confidence 1.0, and serves as the upper bound for comparison.
For synthetic snapshots the labels are known by construction. For real benchmark runs,
`oracle_labels_from_case()` derives them:

- A block containing the case's `payload_value` came from the attack source: `document` for
  IPI, `user` for DPI-U (`authorized_user_message`).
- A baseline block is `workspace_config`.
- Every other block is `user`. By benchmark design the carrier artifact is the only untrusted
  input, so the remaining blocks derive from the user's task.

The payload value is a distinctive identifier, so it is more robust than matching the rule text.
The agent paraphrases rules, and `payload_text` and `target_memory_rule` are worded differently
from each other.

### P1: structural
P1 uses message roles and tool-call boundaries only:

1. A block present in the baseline → `workspace_config` (0.8).
2. Otherwise, find memory-write tool calls (`Write`, `Edit`, `MultiEdit`, `NotebookEdit`) to the
   same file whose string arguments contain the block text, after whitespace normalization.
   The **latest** matching write decides:
   - If there were untrusted tool results since the last user message: `web` (WebFetch or
     WebSearch), `document` (Read, Grep, Glob) or `tool_output` (other tools), confidence 0.7.
   - If only a user message came before the write: `user`, confidence 0.7.
   - Harness text injected into user turns (`<system-reminder>`, …) does not count as a user
     message.
3. No matching write → `unknown` (0.0). The policy reports such records as uncertain.

## Limitations (measured, not assumed away)
- **Over-attribution.** Every block in a write that follows an untrusted read inherits the
  taint, so a legitimate note written together with an injected rule is also marked untrusted.
  P2 (similarity to the specific tool output) is meant to refine this.
- **Writes P1 cannot see.** Memory written through a shell (`echo >> MEMORY.md`), rewritten,
  merged or paraphrased between sessions is not matched, so it becomes `unknown`.
- **Delegated authority.** "Remember what this document says" followed by a read and a write
  is attributed to `document`. That is arguably the user's authority, and the control set
  labels such cases explicitly (threat model §9).
- **Fixed confidences.** 0.7 and 0.8 are fixed values, not calibrated probabilities.
- **Baseline assumption.** The baseline is assumed to be trusted, which is true by benchmark
  construction. In deployment, the baseline would be the last audited state.

## Consequences
- D4 can be run at P0, P1 and P3 on identical inputs, so the contribution of provenance is
  measured directly (H4).
- The P0 labelling rule used for real runs is explicit and reproducible.
