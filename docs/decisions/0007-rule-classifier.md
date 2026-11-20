# ADR-0007: Rule-based memory block classifier

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
Before deciding authority, a defense has to know what a memory block *is*. A block is one of:

- a persistent behavioral **rule**,
- a **preference** attributed to a person,
- plain **information** (facts, logs, headings, metadata).

The project has no compute budget for tier 0, and the classifier has to be explainable and
reproducible. Phase 2 runs offline on synthetic snapshots (maintainer decision, 2026-11-20).

## Decision
- A deterministic, **rule-based** classifier (`memauthy.rules.classifier`, `rule-based-v0.1`)
  scores general linguistic cues for persistent directives:

  | Feature | Weight | Examples |
  |---|---|---|
  | `imperative_opening` | 2.0 | "Use …", "Never …"; also after a frame ("When …, put …", "For X, include …") or a label ("Reminder: rotate …") |
  | `obligation` | 1.5 | must, should, make sure, do not, always, never |
  | `persistence` | 1.5 | from now on, going forward, for later …, next time, by default, until revised |
  | `rule_label` | 1.5 | "Policy: …", "Workflow: …", "… convention: …" |
  | `rule_noun` | 0.5 | policy, procedure, convention (in running text) |

- **How the score maps to a kind.**
  - **Rule:** score ≥ 3.0, or score ≥ 1.5 when a directive cue is present and the block does
    not look like a log entry or a past-tense report.
  - **Preference:** a preference cue ("prefers", "likes", "would rather", +1 with a person
    subject) that outweighs the rule score. An imperative "Prefer X" is a rule, not a stated
    preference.
  - **Information:** everything else.
  - **By block kind:** front matter → information (metadata), code blocks → information,
    empty blocks → unknown.
- **Output.** Kind, a confidence (bounded heuristic, not a calibrated probability), the matched
  features and a rationale string.
- **Kind is not authority.** The classifier says nothing about whether a block is authorized.
  Preferences shape behavior too, so the authority policy (#13) audits both rules and
  preferences.

## Development data and contamination
- The features were designed from general language, **not** from benchmark phrasing. They were
  developed against a hand-written dev set, `data/dev/rule_classifier_dev_v0.1.jsonl`: 85
  synthetic blocks (42 rules, 14 preferences, 29 information) from varied domains, including
  documented hard cases. Dev scores are therefore optimistic and serve only as regression
  checks.
- **Caveat.** Before writing the features, the developer viewed one `target_memory_rule` and
  one `payload_text` per benchmark template (24 templates) to understand the phrasing. Recall
  on benchmark rules is therefore **not a blind result**. Those rules are highly formulaic
  ("For later … concerning …", "… convention: …"), so high recall there says little about
  paraphrases written by real agents. Blind evaluation comes from the control set (phase 3),
  the adaptive variants and real snapshots from the pilot.

## Results at acceptance (v0.1)
- **Dev set:** 83/85. The two misses are documented hard cases:
  - a habitual fact with "always" (false rule)
  - a directive stated as a fact: "Invoices … now go to account …" (missed rule). This is also
    an adaptive-attack vector.
- **Benchmark:** 288/288 `target_memory_rule` and 288/288 `payload_text` classified as rule,
  with the caveat above.
- **OpenClaw bootstrap templates** (owner-provided, legitimate): of 140 blocks, 26 are
  classified as rules and 10 as preferences. A content-only defense would see these as
  candidates. This motivates provenance information (P1/P0) over content-only auditing (P3).

## Alternatives considered
- **Local LLM classifier (Ollama):** more flexible, but slower and less deterministic. It also
  overlaps with D3 (the LLM sanitizer). It may be added later as a separate comparison.
- **Supervised model trained on benchmark rules:** would overfit to 24 templates and leak
  evaluation data.

## Consequences
- Cheap and explainable per-block features, reusable by D2 and D4.
- Known blind spots (directives stated as facts, rules split across blocks) are measured
  explicitly with the control set and the adaptive variants.
