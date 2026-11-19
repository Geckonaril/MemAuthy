"""D0: no defense (lower reference)."""

from __future__ import annotations

from memauthy.policy import apply_policy
from memauthy.schema import AuditResult, MemorySnapshot, Policy, ProvenanceLevel, Transcript


class NoDefense:
    """Makes no judgments, so every policy leaves the snapshot unchanged."""

    name = "D0"

    def audit(
        self,
        snapshot: MemorySnapshot,
        transcript: Transcript | None,
        provenance_level: ProvenanceLevel,
    ) -> AuditResult:
        return AuditResult(
            defense=self.name,
            provenance_level=provenance_level,
            snapshot_id=snapshot.snapshot_id,
        )

    def apply(
        self, snapshot: MemorySnapshot, result: AuditResult, policy: Policy
    ) -> MemorySnapshot:
        return apply_policy(snapshot, result, policy)
