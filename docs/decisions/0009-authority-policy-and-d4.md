# ADR-0009: Authority policy and the D4 defense

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
D4 is the proposed defense. It combines two earlier pieces:

- what a block **is**, from the rule classifier ([ADR-0007](0007-rule-classifier.md));
- where a block **came from**, from the provenance extractors at P0–P3
  ([ADR-0008](0008-provenance-extractors.md)).

From these it decides whether each block is authorized. Enforcement uses the existing pure
policies ([ADR-0003](0003-data-model.md)).

## Decision

### Authority policy (`AuthorityPolicy`, `min_confidence = 0.5`)

| Block kind | Source estimate | Decision |
|---|---|---|
| information / unknown | any | **authorized** (not behavioral; not audited) |
| rule or preference | trusted (`user`, `workspace_config`), confidence ≥ 0.5 | **authorized** |
| rule or preference | untrusted (`document`, `web`, `tool_output`, `agent_inferred`), confidence ≥ 0.5 | **unauthorized** |
| rule or preference | `unknown`, or confidence < 0.5 | **uncertain** |

- **Preferences are audited like rules.** They shape behavior too, and "the user prefers …" is
  an obvious way to spoof provenance.
- **Decision confidence** is `min(classifier confidence, provenance confidence)` for
  authorized and unauthorized decisions.
- **Authority scope is not checked.** The second condition of an authorized rule (threat model
  §5) is not implemented. A rule from the user is authorized whatever it does. This is why
  DPI-U is analyzed only as a boundary case.

### D4 (`ProvenanceAuthorityDefense`)
- **Audit.** `audit(snapshot, transcript, level)` classifies every block, estimates its
  provenance with the extractor for `level` and records one `AuditDecision` per block, with
  kind, source, authority, confidence and a rationale chaining the three steps. A `transcript`
  argument is added to the defense's `ProvenanceContext`. Wall-clock time is recorded as the
  audit cost; token and USD costs are zero.
- **Apply.** `apply` uses `apply_policy` with the defense's `act_on_uncertain` setting.
  Uncertain records are kept and flagged by default (maintainer decision on #4).
- **P3 has two operating points.** At P3 every source is unknown, so D4 gives the two extremes
  of a content-only audit:
  - `act_on_uncertain=False`: nothing is enforced.
  - `act_on_uncertain=True`: every rule and preference is enforced, legitimate ones included.

  Both are points on the security–functionality trade-off (H4). P1 and P0 should improve on
  the trade-off between them.
- P2 raises `NotImplementedError` until phase 3.

## Consequences
- The P1 over-attribution limitation is partly mitigated. Information blocks in a tainted write
  are not audited, so they are kept. Legitimate *rules* written in the same tainted write are
  still blocked.
- On OpenClaw, bootstrap rules are authorized at P1 (baseline) but uncertain at P3. This is
  the provenance contribution H4 is meant to measure.
- Every decision is explainable from its rationale, which supports human labelling and error
  analysis.
