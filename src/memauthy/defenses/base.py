"""Common interface implemented by every defense condition D0-D4 (see ADR-0003)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from memauthy.schema import AuditResult, MemorySnapshot, Policy, ProvenanceLevel, Transcript


@runtime_checkable
class MemoryDefense(Protocol):
    """A memory defense separates detection (``audit``) from enforcement (``apply``)."""

    name: str

    def audit(
        self,
        snapshot: MemorySnapshot,
        transcript: Transcript | None,
        provenance_level: ProvenanceLevel,
    ) -> AuditResult:
        """Judge every record in ``snapshot``; must not modify it."""
        ...

    def apply(
        self, snapshot: MemorySnapshot, result: AuditResult, policy: Policy
    ) -> MemorySnapshot:
        """Return a new snapshot with ``policy`` enforced according to ``result``."""
        ...
