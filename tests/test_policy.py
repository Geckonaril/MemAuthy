import pytest

from memauthy.policy import apply_policy
from memauthy.policy.apply import AUDIT_KEY, ORIGINAL_CONTENT_KEY, UNCERTAIN_FLAG
from memauthy.schema import (
    AuditDecision,
    AuditResult,
    Authority,
    MemorySnapshot,
    Policy,
    ProvenanceLevel,
    RecordKind,
    RecordStatus,
    SourceKind,
)


@pytest.mark.parametrize("policy", list(Policy))
def test_input_never_mutated(
    snapshot: MemorySnapshot, audit_result: AuditResult, policy: Policy
) -> None:
    before_snapshot = snapshot.model_dump_json()
    before_result = audit_result.model_dump_json()
    apply_policy(snapshot, audit_result, policy, act_on_uncertain=True)
    assert snapshot.model_dump_json() == before_snapshot
    assert audit_result.model_dump_json() == before_result


def test_block_removes_unauthorized(snapshot: MemorySnapshot, audit_result: AuditResult) -> None:
    out = apply_policy(snapshot, audit_result, Policy.BLOCK)
    assert out.record_ids == ("r1", "r3", "r4")
    assert out.quarantine == ()


def test_quarantine_moves_and_flags(snapshot: MemorySnapshot, audit_result: AuditResult) -> None:
    out = apply_policy(snapshot, audit_result, Policy.QUARANTINE)
    assert out.record_ids == ("r1", "r3", "r4")
    assert [r.record_id for r in out.quarantine] == ["r2"]
    q = out.quarantine[0]
    assert q.status is RecordStatus.QUARANTINED
    assert q.content == snapshot.get("r2").content  # type: ignore[union-attr]
    assert q.metadata["file"] == "MEMORY.md"
    assert q.metadata[AUDIT_KEY]["policy"] == "quarantine"
    assert q.metadata[AUDIT_KEY]["source"] == "document"


def test_downgrade_rewrites_in_place(snapshot: MemorySnapshot, audit_result: AuditResult) -> None:
    original = snapshot.get("r2")
    out = apply_policy(snapshot, audit_result, Policy.DOWNGRADE)
    assert out.record_ids == snapshot.record_ids
    r2 = out.get("r2")
    assert r2 is not None and original is not None
    assert r2.status is RecordStatus.DOWNGRADED
    assert r2.content != original.content
    assert original.content in r2.content
    assert "not an instruction" in r2.content
    assert r2.metadata[ORIGINAL_CONTENT_KEY] == original.content


def test_uncertain_left_alone_by_default(
    snapshot: MemorySnapshot, audit_result: AuditResult
) -> None:
    out = apply_policy(snapshot, audit_result, Policy.BLOCK)
    assert "r4" in out.record_ids


@pytest.mark.parametrize("policy", list(Policy))
def test_uncertain_kept_but_flagged(
    snapshot: MemorySnapshot, audit_result: AuditResult, policy: Policy
) -> None:
    original = snapshot.get("r4")
    r4 = apply_policy(snapshot, audit_result, policy).get("r4")
    assert r4 is not None and original is not None
    assert r4.content == original.content
    assert r4.status is RecordStatus.ACTIVE
    assert r4.metadata[AUDIT_KEY]["flag"] == UNCERTAIN_FLAG
    assert r4.metadata[AUDIT_KEY]["policy"] is None
    assert r4.metadata[AUDIT_KEY]["authority"] == "uncertain"


def test_authorized_and_undecided_not_flagged(
    snapshot: MemorySnapshot, audit_result: AuditResult
) -> None:
    out = apply_policy(snapshot, audit_result, Policy.QUARANTINE)
    assert out.get("r1") == snapshot.get("r1")  # authorized
    assert out.get("r3") == snapshot.get("r3")  # no decision


def test_uncertain_acted_on_when_requested(
    snapshot: MemorySnapshot, audit_result: AuditResult
) -> None:
    out = apply_policy(snapshot, audit_result, Policy.BLOCK, act_on_uncertain=True)
    assert out.record_ids == ("r1", "r3")


def test_existing_quarantine_preserved(snapshot: MemorySnapshot, audit_result: AuditResult) -> None:
    first = apply_policy(snapshot, audit_result, Policy.QUARANTINE)
    second_result = audit_result.model_copy(update={"decisions": ()})
    second = apply_policy(first, second_result, Policy.QUARANTINE)
    assert [r.record_id for r in second.quarantine] == ["r2"]


def test_snapshot_mismatch_rejected(snapshot: MemorySnapshot, audit_result: AuditResult) -> None:
    other = audit_result.model_copy(update={"snapshot_id": "other"})
    with pytest.raises(ValueError, match="not 'case-001/S2'"):
        apply_policy(snapshot, other, Policy.BLOCK)


def test_unknown_record_rejected(snapshot: MemorySnapshot) -> None:
    result = AuditResult(
        defense="t",
        provenance_level=ProvenanceLevel.P0,
        snapshot_id=snapshot.snapshot_id,
        decisions=(
            AuditDecision(
                record_id="missing",
                kind=RecordKind.RULE,
                source=SourceKind.WEB,
                confidence=1.0,
                authority=Authority.UNAUTHORIZED,
            ),
        ),
    )
    with pytest.raises(ValueError, match="unknown records: missing"):
        apply_policy(snapshot, result, Policy.BLOCK)
