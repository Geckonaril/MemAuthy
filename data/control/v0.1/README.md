# Dataset card: MemAuthy legitimate control set v0.1

**Version:** 0.1.0, semver. Any change to items, labels or fields bumps the version, and old
versions are kept. **Status:** frozen for phase-3 evaluation. **License:** MIT, same as the
repository.

## Purpose
MemHarmBench contains attack cases only. This set measures what a memory defense costs in
functionality:

- **false blocks**: legitimate memory removed;
- **legitimate preference preservation**;
- whether a defense can tell **authorized rules from surface-identical unauthorized ones**.

It supports H2 (proposed audit vs. simple filtering) and H4 (value of provenance).

## Contents
`control_set.jsonl` has 120 items, one JSON object per line:

| Field | Meaning |
|---|---|
| `id` | `ctl-NNN` |
| `category` | See the table below |
| `text` | The memory block text |
| `kind` | Gold block kind: `rule`, `preference` or `information` |
| `source` | Gold origin: `user`, `workspace_config`, `document`, `web` or `tool_output` |
| `expected` | `keep` (authorized or harmless) or `enforce` (unauthorized and behavior-relevant) |
| `pair_id` | Links an authorized item to its surface-identical or near-identical unauthorized twin |
| `domain` | code, communication, scheduling, finance, ops, docs, support, procurement or legal |
| `delegated` | `true` if the user explicitly delegated authority to a document |
| `note` | Remarks |

| Category | n | Source | Expected | What it tests |
|---|---|---|---|---|
| `user_rule` | 30 | user | keep | Legitimate persistent rules and preferences stated by the user |
| `owner_rule` | 10 | workspace_config | keep | Owner configuration present before any exposure |
| `injected_lookalike` | 30 | document / web / tool_output | enforce | 25 items are **identical** to a `user_rule` / `owner_rule` twin; 5 are near-paraphrases that change a target, recipient, criterion or threshold |
| `delegated` | 10 | document | keep | The user asks the agent to adopt a document's conventions (threat model §9 hard case) |
| `untrusted_fact` | 15 | document / web / tool_output | keep | Harmless facts learned from untrusted inputs |
| `directive_as_fact` | 15 | document / web / tool_output | enforce | Directives stated as facts with a decision-relevant value (the phase-2 blind spot) |
| `user_fact` | 10 | user | keep | Facts stated by the user |

## How it is used
`memauthy.synthetic.control` turns each item into a synthetic session. The item text reaches the
agent through its gold source:

- **user** items: a user message;
- **untrusted** items: a tool result after a read, fetch or MCP call;
- **owner** items: the trusted baseline.

The agent then writes the item into memory, and defenses are evaluated on the item's block.

## Provenance and limitations
- **Authorship.** All items are synthetic, written in English by the project's developer with
  an AI assistant, and contain no real personal data. Identifiers such as e-mail addresses and
  IBANs are fake. The `example.test` domain is reserved.
- **Not blind.** The authors knew the classifier and D2 patterns. Items were not tuned against
  them and the set is frozen before evaluation, but it is not blind. A second human annotator
  will review labels (phase 6), and Cohen's κ will be reported.
- **Coverage.** English only, short single-sentence blocks. Real agent-written memory is longer
  and noisier; pilot snapshots will complement this set.
- **`delegated` labels are a normative choice.** They are marked `keep`, because the user
  authorized the document. A defense that blocks them errs on the safe side, and this is
  reported separately.
- **`untrusted_fact` labels are a normative choice too.** They are marked `keep` because they
  do not direct behavior. A provenance-first defense that removes all untrusted-derived content
  trades these false blocks for robustness, which this category measures.
