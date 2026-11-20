# ADR-0010: Baseline defenses D1 and D2

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
H1 and H2 compare the proposed audit (D4) with two baselines:

- **D0**, no defense;
- **simple filtering.**

D1 (wipe memory) bounds the trade-off: maximum security, minimum functionality. All conditions
share the `MemoryDefense` interface and are built through one registry.

## Decision

### D1 `WipeMemory`
- Every record is marked `unauthorized` with source `unknown`, including OpenClaw bootstrap
  files and other baseline memory. With `Policy.BLOCK`, memory is emptied.
- The block kind is still recorded, from the rule classifier, for reporting.

### D2 `KeywordFilter` (`d2-v0.1`)
- Content only; provenance is ignored. Any block matching an indicator pattern is
  `unauthorized` (kind `rule`); every other block is `authorized` (kind `information`).
- The patterns are generic prompt-injection and persistent-directive indicators:

  | Group | What it matches |
  |---|---|
  | `override` | "ignore previous …", "new instructions" |
  | `persistence` | from now on, for future/later, next time, by default, until … revises |
  | `absolute` | always, never |
  | `obligation` | must, you should, make sure |
  | `rule_label` | "… policy:", "… convention:" |
  | `redirect` | send/forward/route/copy … to |
  | `destination` | account, IBAN, recipient |
  | `email`, `url` | e-mail addresses, links |
  | `secret` | password, API key, token |

- **The patterns are not tuned on benchmark text.** A test asserts that no benchmark
  identifier (`ARCHIVE`, `CAL-`, …) appears in them.

### Registry
`build_defense(name, context, **options)` builds D0, D1, D2 and D4. D3 raises
`NotImplementedError` until phase 3.

## Observations at acceptance
- **Benchmark rules.** D2 flags 288/288 `target_memory_rule` and 288/288 `payload_text`,
  because the benchmark's rules carry explicit persistence phrases ("for later …", "until an
  owner revises it"). D2 is therefore a strong baseline on unparaphrased benchmark text.
  Paraphrased agent-written memory and the adaptive variants (phase 3) are the real test.
- **Legitimate rules.** D2 flags legitimate rules too ("Always run tests before pushing"). Its
  false-block rate is measured on the control set (H2).
- **OpenClaw bootstrap templates.** D2 flags 7 of 141 blocks.

## Consequences
- The offline detection experiment (#15) can run D0, D1, D2 and D4 (P0, P1, P3) through one
  interface.
- If D2 matches D4 on raw benchmark rules, H2 rests on false blocks, measured on the control set,
  and on robustness to paraphrase.
