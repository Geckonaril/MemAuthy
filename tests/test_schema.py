import pytest
from pydantic import ValidationError

from memauthy.schema import (
    AuditCost,
    AuditDecision,
    AuditResult,
    Authority,
    MemoryRecord,
    MemorySnapshot,
    ProvenanceLevel,
    RecordKind,
    SourceKind,
    Transcript,
    TranscriptEvent,
)


@pytest.mark.parametrize("model", ["snapshot", "transcript", "audit_result"])
def test_json_round_trip(model: str, request: pytest.FixtureRequest) -> None:
    obj = request.getfixturevalue(model)
    restored = type(obj).model_validate_json(obj.model_dump_json())
    assert restored == obj


def test_models_are_frozen(snapshot: MemorySnapshot) -> None:
    with pytest.raises(ValidationError):
        snapshot.records[0].content = "changed"  # type: ignore[misc]


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        MemoryRecord(record_id="x", content="y", unexpected=1)  # type: ignore[call-arg]


def test_duplicate_record_ids_rejected() -> None:
    rec = MemoryRecord(record_id="dup", content="a")
    with pytest.raises(ValidationError, match="duplicate record_id: dup"):
        MemorySnapshot(snapshot_id="s", agent="a", records=(rec,), quarantine=(rec,))


def test_duplicate_decisions_rejected() -> None:
    d = AuditDecision(
        record_id="r",
        kind=RecordKind.RULE,
        source=SourceKind.WEB,
        confidence=0.5,
        authority=Authority.UNAUTHORIZED,
    )
    with pytest.raises(ValidationError, match="duplicate decision record_id"):
        AuditResult(
            defense="t", provenance_level=ProvenanceLevel.P3, snapshot_id="s", decisions=(d, d)
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_bounds(confidence: float) -> None:
    with pytest.raises(ValidationError):
        AuditDecision(
            record_id="r",
            kind=RecordKind.RULE,
            source=SourceKind.WEB,
            confidence=confidence,
            authority=Authority.UNAUTHORIZED,
        )


def test_transcript_indices_strictly_increasing() -> None:
    e0 = TranscriptEvent(index=0, role="user", content="a")
    with pytest.raises(ValidationError, match="strictly increasing"):
        Transcript(session_id="s", events=(e0, e0))


def test_trusted_sources() -> None:
    assert SourceKind.USER.is_trusted
    assert SourceKind.WORKSPACE_CONFIG.is_trusted
    untrusted = set(SourceKind) - {SourceKind.USER, SourceKind.WORKSPACE_CONFIG}
    assert not any(s.is_trusted for s in untrusted)


def test_audit_result_helpers(audit_result: AuditResult) -> None:
    assert audit_result.ids_with(Authority.UNAUTHORIZED) == ("r2",)
    assert audit_result.ids_with(Authority.UNCERTAIN) == ("r4",)
    assert audit_result.decision_for("r3") is None


def test_total_cost_sums_decisions_and_overhead() -> None:
    d = AuditDecision(
        record_id="r",
        kind=RecordKind.RULE,
        source=SourceKind.WEB,
        confidence=1.0,
        authority=Authority.UNAUTHORIZED,
        cost=AuditCost(input_tokens=10, output_tokens=2, seconds=0.5, usd=0.01),
    )
    result = AuditResult(
        defense="t",
        provenance_level=ProvenanceLevel.P3,
        snapshot_id="s",
        decisions=(d,),
        cost=AuditCost(input_tokens=5, seconds=0.25),
    )
    total = result.total_cost
    assert (total.input_tokens, total.output_tokens) == (15, 2)
    assert total.seconds == pytest.approx(0.75)
    assert total.usd == pytest.approx(0.01)
