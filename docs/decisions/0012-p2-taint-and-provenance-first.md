# ADR-0012: P2 transcript taint and the provenance-first rule

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
Phase 2 found a blind spot. A directive stated as a fact ("Refund destination: account …") is
classified as *information*, so D4 kept it even with oracle provenance. The control set showed
the same for some imperative rules the classifier misses. The maintainer chose a
**provenance-first** fix: blocks shown to derive from untrusted input are audited whatever
their kind. P2 should use **lexical similarity first**, with embeddings as a later ablation
(2026-11-20).

## Decision

### `derived_from_untrusted` on every provenance estimate
- `True`: positive content evidence that the block came from an untrusted input.
- `False`: positive evidence that it came from a trusted input.
- `None`: no content evidence.

Each level sets it as follows:

| Level | Setting |
|---|---|
| P0 | Derived from the oracle source |
| P1, P3 | Always `None`; P1 has structure but no content evidence |
| P2 | Computed |

### Provenance-first rule (`AuthorityPolicy.audit_derived=True`, default)
A block is `unauthorized` **whatever its kind** when all of the following hold:

- `derived_from_untrusted` is `True`,
- its source is untrusted and known,
- the confidence is at least `min_confidence`.

Otherwise the earlier kind- and source-based rules apply
([ADR-0009](0009-authority-policy-and-d4.md)). Setting `audit_derived=False` restores the old
behavior for ablations.

### P2 `TranscriptTaintProvenance`
Lexical, deterministic, local.

1. **Candidate sources.** Untrusted tool results and user messages that precede the memory
   write containing the block. If no write matches (for example a shell write), the whole
   history is used. Harness text is not a user message.
2. **Similarity.** The maximum of two measures:
   - character 5-gram containment of the block in the source, which survives excerpting and
     light edits;
   - distinctive-token overlap: the share of the block's identifiers with digits, e-mail
     addresses, URLs, IBAN-like strings and numbers that also appear in the source.
3. **Decision.** Let *taint* be the best untrusted similarity and *user* the best user
   similarity; the threshold is 0.6 and the margin 0.1.

   | Condition | Source | `derived_from_untrusted` | Confidence |
   |---|---|---|---|
   | taint ≥ 0.6 and taint ≥ user + 0.1 | untrusted kind of the best source | `True` | 0.5 + 0.4·sim, at most 0.9 |
   | user ≥ 0.6 and user ≥ taint + 0.1 | `user` | `False` | 0.5 + 0.4·sim, at most 0.9 |
   | otherwise (inconclusive) | P1's structural estimate | `None` | P1's confidence − 0.1 |

   An inconclusive block keeps P1's source but has no content evidence.

### What P2 fixes relative to P1
- **Paraphrased rules** are still traced to the document through shared identifiers.
- **Shell writes** are traced by content.
- **Over-attribution of user rules.** A rule the user stated, written after an unrelated read,
  is attributed to the user.
- **Task notes.** A note the agent composed itself is inconclusive. It is kept because it is
  information without untrusted-derivation evidence.

## Consequences and expected trade-offs
- **P0 numbers change.** P0 now also enforces untrusted-derived information blocks, so the
  phase-2 `fact` variant is caught at P0. The v0.1 results stay in `results/` as history, and
  the v0.2 configs rerun everything with D4@P2 added.
- **Untrusted facts are blocked.** Harmless facts learned from untrusted inputs (control
  category `untrusted_fact`) are now false-blocked at P0 and P2. This is the explicit cost of
  provenance-first. A `downgrade` policy, which rewrites the block into a non-instructional
  note, is the natural mitigation for information blocks and will be evaluated.
- **Delegated rules remain a limitation.** "Adopt this document's conventions" is attributed
  to the document.
- **Known weaknesses of P2.**
  - **Heavy paraphrase.** A rewrite that drops every identifier and changes the wording falls
    back to P1. Embeddings are the planned ablation for this.
  - **Shared identifiers.** If the user message and the document share all of the block's
    identifiers, the margin rule keeps the block inconclusive.
  - **Fixed thresholds.** The thresholds are fixed and not tuned on the control set; tuning
    them on it would contaminate it.
