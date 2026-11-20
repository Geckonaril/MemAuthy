"""Common interface for provenance extractors P0-P3 (threat model section 6)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from memauthy.memory_io.files import Granularity, parse_memory_files
from memauthy.schema import MemorySnapshot, ProvenanceLevel, SourceKind, Transcript


class ProvenanceEstimate(BaseModel):
    """Estimated origin of one memory record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    source: SourceKind
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...] = ()  # e.g. transcript event refs
    rationale: str = ""
    # Positive evidence that the block's *content* derives from an untrusted input
    # (True), from a trusted one (False), or no content evidence (None). Drives the
    # provenance-first rule (ADR-0012): untrusted-derived blocks are audited whatever their kind.
    derived_from_untrusted: bool | None = None


@dataclass(frozen=True)
class ProvenanceContext:
    """What a defense may know besides the snapshot.

    * ``transcripts``: sessions between the baseline and the snapshot (P1, P2)
    * ``baseline_files``: memory before any untrusted exposure, e.g. the OpenClaw bootstrap
      templates or an earlier audited state (P1, P2)
    * ``oracle``: ground-truth source per record ID, for P0 only; realistic levels never read it
    """

    transcripts: tuple[Transcript, ...] = ()
    baseline_files: Mapping[str, str] | None = None
    granularity: Granularity = Granularity.BLOCK
    oracle: Mapping[str, SourceKind] | None = field(default=None, repr=False)

    def baseline_block_ids(self) -> frozenset[str]:
        if not self.baseline_files:
            return frozenset()
        docs = parse_memory_files(self.baseline_files, self.granularity)
        return frozenset(b.block_id for d in docs.values() for b in d.blocks if b.block_id)


@runtime_checkable
class ProvenanceExtractor(Protocol):
    level: ProvenanceLevel

    def estimate(
        self, snapshot: MemorySnapshot, context: ProvenanceContext
    ) -> dict[str, ProvenanceEstimate]:
        """One estimate per record in ``snapshot.records``."""
        ...
