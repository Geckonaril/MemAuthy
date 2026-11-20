"""Provenance extractors for levels P0 (oracle) to P3 (no provenance)."""

from memauthy.provenance.base import ProvenanceContext, ProvenanceEstimate, ProvenanceExtractor
from memauthy.provenance.extractors import (
    NoProvenance,
    OracleProvenance,
    StructuralProvenance,
    oracle_labels_from_case,
)
from memauthy.schema import ProvenanceLevel

EXTRACTORS: dict[ProvenanceLevel, type] = {
    ProvenanceLevel.P0: OracleProvenance,
    ProvenanceLevel.P1: StructuralProvenance,
    ProvenanceLevel.P3: NoProvenance,
}

__all__ = [
    "EXTRACTORS",
    "NoProvenance",
    "OracleProvenance",
    "ProvenanceContext",
    "ProvenanceEstimate",
    "ProvenanceExtractor",
    "StructuralProvenance",
    "oracle_labels_from_case",
]
