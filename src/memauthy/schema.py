"""Core data model shared by all components (see ADR-0003).

All models are immutable (``frozen``) and use tuples for collections, so a defense or policy can
only produce *new* snapshots and never mutate its input.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1"


class ProvenanceLevel(StrEnum):
    """How much provenance information a defense may use."""

    P0 = "P0"  # oracle: benchmark ground truth (upper bound, comparison only)
    P1 = "P1"  # structural: message roles and tool-call boundaries
    P2 = "P2"  # transcript taint: similarity + temporal proximity to untrusted tool output
    P3 = "P3"  # none: memory content only


class Policy(StrEnum):
    """Enforcement applied to records judged unauthorized."""

    BLOCK = "block"  # delete from the snapshot
    QUARANTINE = "quarantine"  # keep out of the active snapshot, store and flag
    DOWNGRADE = "downgrade"  # rewrite the rule into an informational note


class SourceKind(StrEnum):
    """Estimated origin of a memory record."""

    USER = "user"  # direct user message in the session
    WORKSPACE_CONFIG = "workspace_config"  # configuration explicitly authorized by the owner
    TOOL_OUTPUT = "tool_output"  # tool / MCP output
    WEB = "web"  # fetched web content
    DOCUMENT = "document"  # documents and third-party files
    AGENT_INFERRED = "agent_inferred"  # agent's own inference without a clear source
    UNKNOWN = "unknown"

    @property
    def is_trusted(self) -> bool:
        return self in TRUSTED_SOURCES


TRUSTED_SOURCES = frozenset({SourceKind.USER, SourceKind.WORKSPACE_CONFIG})


class RecordKind(StrEnum):
    """What a memory record is."""

    RULE = "rule"  # persistent behavioral rule / instruction
    PREFERENCE = "preference"  # user preference
    INFORMATION = "information"  # factual note
    UNKNOWN = "unknown"


class Authority(StrEnum):
    """Authority decision for a memory record."""

    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    UNCERTAIN = "uncertain"  # provenance could not be determined; reported separately


class RecordStatus(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    DOWNGRADED = "downgraded"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MemoryRecord(_Frozen):
    """One entry of an agent's persistent memory."""

    record_id: str = Field(min_length=1)
    content: str
    source_path: str | None = None  # file inside the agent's memory, if any
    created_at: datetime | None = None
    status: RecordStatus = RecordStatus.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)


def _check_unique(ids: list[str], what: str) -> None:
    dupes = sorted(i for i, n in Counter(ids).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate {what}: {', '.join(dupes)}")


class MemorySnapshot(_Frozen):
    """Agent memory at one point in time (e.g. MemHarmBench S0/S2/S4)."""

    schema_version: str = SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1)
    agent: str  # e.g. "claude-code", "openclaw"
    case_id: str | None = None
    label: str | None = None  # e.g. "S0", "S2", "S4"
    records: tuple[MemoryRecord, ...] = ()
    quarantine: tuple[MemoryRecord, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> MemorySnapshot:
        _check_unique([r.record_id for r in (*self.records, *self.quarantine)], "record_id")
        return self

    def get(self, record_id: str) -> MemoryRecord | None:
        return next((r for r in self.records if r.record_id == record_id), None)

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(r.record_id for r in self.records)


class TranscriptEvent(_Frozen):
    """One event in a session transcript."""

    index: int = Field(ge=0)
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_name: str | None = None
    timestamp: datetime | None = None
    memory_record_id: str | None = None  # set when this event writes a memory record
    # Additive fields (schema 0.1 compatible): structural information from native logs.
    kind: Literal["text", "tool_use", "tool_result"] | None = None
    memory_file: str | None = None  # memory key written by this tool call, if any
    event_ref: str | None = None  # benchmark reference, e.g. "native:<source>:<line>:<block>"


class Transcript(_Frozen):
    """Ordered events of one agent session."""

    session_id: str = Field(min_length=1)
    events: tuple[TranscriptEvent, ...] = ()

    @model_validator(mode="after")
    def _ordered(self) -> Transcript:
        indices = [e.index for e in self.events]
        if indices != sorted(set(indices)):
            raise ValueError("transcript event indices must be strictly increasing")
        return self


class AuditCost(_Frozen):
    """Cost incurred by auditing (zero for purely local, rule-based defenses)."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    seconds: float = Field(default=0.0, ge=0)
    usd: float = Field(default=0.0, ge=0)

    def __add__(self, other: AuditCost) -> AuditCost:
        return AuditCost(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            seconds=self.seconds + other.seconds,
            usd=self.usd + other.usd,
        )


class AuditDecision(_Frozen):
    """A defense's judgment about one memory record."""

    record_id: str = Field(min_length=1)
    kind: RecordKind
    source: SourceKind
    confidence: float = Field(ge=0.0, le=1.0)
    authority: Authority
    rationale: str = ""
    cost: AuditCost = AuditCost()


class AuditResult(_Frozen):
    """Output of ``MemoryDefense.audit`` for one snapshot.

    Records without a decision are left untouched by every policy.
    """

    schema_version: str = SCHEMA_VERSION
    defense: str
    provenance_level: ProvenanceLevel
    snapshot_id: str
    decisions: tuple[AuditDecision, ...] = ()
    cost: AuditCost = AuditCost()  # snapshot-level overhead not attributable to one record

    @model_validator(mode="after")
    def _unique_decisions(self) -> AuditResult:
        _check_unique([d.record_id for d in self.decisions], "decision record_id")
        return self

    def decision_for(self, record_id: str) -> AuditDecision | None:
        return next((d for d in self.decisions if d.record_id == record_id), None)

    def ids_with(self, authority: Authority) -> tuple[str, ...]:
        return tuple(d.record_id for d in self.decisions if d.authority is authority)

    @property
    def total_cost(self) -> AuditCost:
        total = self.cost
        for d in self.decisions:
            total = total + d.cost
        return total
