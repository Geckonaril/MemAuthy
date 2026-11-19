# ADR-0003: Core data model and defense interface

- **Status:** Accepted
- **Date:** 2026-11-19

## Context
All defense conditions (D0–D4) and provenance levels (P0–P3) must be compared on identical
inputs (matched design). Audit decisions must be serialisable for later analysis, human
labelling and reproducibility.

## Decision
- Use **pydantic v2** models for all data exchanged between components and written to disk:
  `MemoryRecord`, `MemorySnapshot`, `TranscriptEvent`, `Transcript`, `AuditDecision`,
  `AuditResult`, and later `RunManifest`, `CostRecord`.
- Every defense implements one protocol:

  ```python
  class MemoryDefense(Protocol):
      name: str

      def audit(
          self,
          snapshot: MemorySnapshot,
          transcript: Transcript | None,
          provenance_level: ProvenanceLevel,
      ) -> AuditResult: ...
      def apply(
          self, snapshot: MemorySnapshot, result: AuditResult, policy: Policy
      ) -> MemorySnapshot: ...
  ```

- `AuditResult` holds one `AuditDecision` per record: is-rule, source estimate, confidence,
  authority decision (authorized / unauthorized / uncertain), rationale, and cost.
- Policies (`block`, `quarantine`, `downgrade`) are **pure functions**: they return a new
  snapshot and never mutate the input. Quarantined records are kept out of the active snapshot
  but stored and flagged. Uncertain-provenance records are reported separately.
- `audit` (detection) and `apply` (enforcement) are separate so detection can be evaluated
  offline (P/R/F1) independently of the policy.

## Alternatives considered
- **dataclasses** — no validation or JSON schema; more hand-written serialisation.
- **One `defend()` call** — couples detection and enforcement and prevents offline detection
  metrics.

## Consequences
- Agent-specific formats are converted at the edges (`memory_io`); the core stays agent-agnostic.
- Model changes are schema changes; persisted results carry a schema version.
