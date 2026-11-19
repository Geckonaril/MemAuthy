# Preregistration (DRAFT)

> **Status: draft outline. Not yet registered.** This text will be finalized and submitted to OSF
> before the main (phase 5) experiments. Anything changed after registration is labelled
> *exploratory* in the paper. Items marked **TBD** are decided after the pilot (phase 4).

## 1. Title
Provenance- and authority-aware memory auditing against cross-session prompt injection in
persistent-memory AI agents.

## 2. Research questions and hypotheses

| | Question | Hypothesis | Type |
|---|---|---|---|
| RQ1 / H1 | Does the provenance- and authority-aware audit (D4) reduce cross-session attack success? | D4 lowers the adoption of the attacker-targeted decision in the trigger session (C-ASR, full-cohort adoption) compared with no defense (D0). | Confirmatory |
| RQ2 / H2 | Does D4 preserve legitimate preferences better than simple filtering? | D4 has a lower false-block rate than the keyword/regex filter (D2), with equal or better security. | Confirmatory |
| RQ3 / H3 | What does the defense cost? | The security gain comes with limited, measurable overhead (tokens, wall-clock time, USD). | Confirmatory (descriptive bound **TBD**) |
| RQ4 / H4 | How much does provenance information contribute? | The security–functionality trade-off improves from P3 to P0. Realistic transcript provenance (P2) comes meaningfully close to the oracle (P0). | Confirmatory (closeness margin **TBD**) |
| RQ5 | How robust is D4 against an adaptive attacker? | — | Exploratory |

## 3. Design

- **Matched design.** For each attack case, all defense arms are derived from the same
  post-exposure memory snapshot. Arms use the same model, task input, initial memory and trigger
  session. The defense is applied after exposure and before the trigger session.
- **Conditions.** D0 no defense; D1 wipe memory; D2 keyword/regex filter; D3 LLM memory
  sanitizer (content-based, A-MemGuard-like); D4 proposed audit at P0, P1, P2 and P3.
- **Policies for D4.** `block`, `quarantine`, `downgrade`. Primary policy: **TBD** (chosen on
  the pilot, before registration). Uncertain-provenance records are kept and flagged, and are
  reported separately.
- **Snapshots.** MemHarmBench S0/S2/S4. Primary distance: **TBD**.

## 4. Data

- **Attack cases.** MemHarmBench v8.4.3, commit `9affbe5`, dataset revision `2b4c2b7`. Cases are
  used unmodified.
  - **Primary scope:** the 192 indirect-content (IPI) cases.
  - **Boundary analysis:** the 96 direct-instruction (DPI-U) cases, reported separately, because
    their rules arrive through the trusted user channel ([threat model §7](threat_model.md#7-evaluation-scope)).
- **Control set.** Synthetic, user-authorized persistent preferences plus surface-similar
  unauthorized rules (`data/control/`, versioned). Version used: **TBD**.
- **Adaptive variants.** Hand-crafted variants (`data/adaptive/`); exploratory only.
- **Sampling.** Stratified by 12 attack objectives, with the IPI/DPI-U balance per stratum.
  Sample size from the power analysis on pilot estimates: **TBD**.

## 5. Outcomes

**Primary**
- C-ASR / full-cohort adoption in the trigger session (H1, H4).
- False-block rate on the control set (H2).

**Secondary**
- Offline detection precision/recall/F1.
- Legitimate-preference preservation rate.
- UTDR (deviation from legitimate task requirements).
- ATAR (execution anomaly rate).
- Cost: extra tokens, wall-clock time, USD (H3).
- PMIR, reported for context only. It is not a measure of defense effect, because the defense
  acts after exposure.

## 6. Analysis plan

- **Paired binary outcomes** (same case, two arms): exact McNemar test. Effect size: matched
  odds ratio with a 95% CI.
- **Proportions:** Wilson 95% intervals. Case-level bootstrap where needed.
- **Multiple comparisons:** Holm correction within each family of confirmatory tests.
- **H4:** compare trade-off points (security vs. false blocks) across P0–P3. The criterion for
  "meaningfully close" is **TBD** before registration.
- **Judge reliability:** a subset is labelled independently by two humans. Cohen's κ is
  computed, and the automatic judge is validated against the human labels.
- **Small samples:** if the achieved sample is below the planned size, results are interpreted
  as exploratory.

## 7. Exclusions and failure handling

Technical failures, unresolved judgments, non-evaluable trigger runs and missing observations
are reported as **separate categories** with counts per arm. They are never silently dropped.
Pairs with a technical failure in either arm are excluded from the paired tests, and their
number is reported.

## 8. Cost and compute

The experiments run in cost tiers: 0 offline, 1 local or free model, 2 paid API. Any paid run
first goes through a 1–5 case pilot with measured cost and explicit approval. The models and
budget actually used are recorded here before registration: **TBD**.

## 9. Reproducibility

Every run writes a manifest (code commit, benchmark commit, dataset revision, config hash,
models and parameters, seed, case IDs) and a cost log. Tables and figures are regenerated from
raw results by analysis code in the repository.
