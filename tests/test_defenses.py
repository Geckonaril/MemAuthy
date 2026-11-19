import pytest

from memauthy.defenses import MemoryDefense, NoDefense
from memauthy.schema import MemorySnapshot, Policy, ProvenanceLevel, Transcript


def test_no_defense_satisfies_protocol() -> None:
    assert isinstance(NoDefense(), MemoryDefense)


@pytest.mark.parametrize("level", list(ProvenanceLevel))
@pytest.mark.parametrize("policy", list(Policy))
def test_no_defense_leaves_snapshot_unchanged(
    snapshot: MemorySnapshot,
    transcript: Transcript,
    level: ProvenanceLevel,
    policy: Policy,
) -> None:
    d0 = NoDefense()
    result = d0.audit(snapshot, transcript, level)
    assert result.defense == "D0"
    assert result.provenance_level is level
    assert result.decisions == ()
    assert d0.apply(snapshot, result, policy) == snapshot
