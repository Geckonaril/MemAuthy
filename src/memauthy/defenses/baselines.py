"""Baseline defenses: D1 (wipe memory) and D2 (keyword / regex filter)."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from memauthy.policy import apply_policy
from memauthy.rules.classifier import DEFAULT_CLASSIFIER, RuleClassifier
from memauthy.schema import (
    AuditCost,
    AuditDecision,
    AuditResult,
    Authority,
    MemorySnapshot,
    Policy,
    ProvenanceLevel,
    RecordKind,
    SourceKind,
    Transcript,
)


@dataclass
class WipeMemory:
    """D1: treat every record as unauthorized (bootstrap/baseline files included).

    Security upper bound and functionality lower bound. With ``Policy.BLOCK`` the memory is
    emptied; other policies apply to every record likewise.
    """

    classifier: RuleClassifier = DEFAULT_CLASSIFIER
    name: str = "D1"

    def audit(
        self,
        snapshot: MemorySnapshot,
        transcript: Transcript | None,
        provenance_level: ProvenanceLevel,
    ) -> AuditResult:
        start = time.perf_counter()
        decisions = tuple(
            AuditDecision(
                record_id=r.record_id,
                kind=self.classifier.classify(r.content, r.metadata.get("block_kind")).kind,
                source=SourceKind.UNKNOWN,
                confidence=1.0,
                authority=Authority.UNAUTHORIZED,
                rationale="D1: all memory is discarded",
            )
            for r in snapshot.records
        )
        return AuditResult(
            defense=self.name,
            provenance_level=provenance_level,
            snapshot_id=snapshot.snapshot_id,
            decisions=decisions,
            cost=AuditCost(seconds=time.perf_counter() - start),
        )

    def apply(
        self, snapshot: MemorySnapshot, result: AuditResult, policy: Policy
    ) -> MemorySnapshot:
        return apply_policy(snapshot, result, policy)


# Generic prompt-injection and persistent-directive indicators (D2 v0.1). Deliberately generic:
# no benchmark-specific identifiers. Matching is case-insensitive.
D2_PATTERNS: tuple[tuple[str, str], ...] = (
    ("override", r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b"),
    ("override", r"\b(new|updated|revised) (instructions?|rules?|polic(y|ies))\b"),
    ("persistence", r"\b(from now on|going forward|henceforth|until further notice)\b"),
    ("persistence", r"\b(for|in) (all )?(future|later|subsequent|upcoming)\b"),
    ("persistence", r"\b(next time|every time|each time|whenever|by default)\b"),
    ("persistence", r"\buntil (an? |the )?\w+ (revises|changes|updates|says)\b"),
    ("absolute", r"\b(always|never)\b"),
    ("obligation", r"\b(must|you should|make sure|be sure to|do not tell|don't tell)\b"),
    ("rule_label", r"^\W*\w[\w /-]{0,30}(convention|policy|rule|instruction|procedure)s?\s*:"),
    (
        "redirect",
        r"\b(send|forward|route|redirect|transfer|copy|cc|bcc|export|upload)\b.{0,40}\bto\b",
    ),
    ("destination", r"\b(account|iban|wallet|recipient|destination|endpoint)\b"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("url", r"\bhttps?://\S+"),
    ("secret", r"\b(password|api[_ -]?key|token|credential)s?\b"),
)


@dataclass
class KeywordFilter:
    """D2: block every record matching any indicator pattern; provenance is ignored."""

    patterns: Sequence[tuple[str, str]] = D2_PATTERNS
    name: str = "D2"
    version: str = "d2-v0.1"
    _compiled: list[tuple[str, re.Pattern[str]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._compiled = [
            (label, re.compile(p, re.IGNORECASE | re.MULTILINE)) for label, p in self.patterns
        ]

    def matches(self, text: str) -> list[str]:
        return sorted({label for label, rx in self._compiled if rx.search(text)})

    def audit(
        self,
        snapshot: MemorySnapshot,
        transcript: Transcript | None,
        provenance_level: ProvenanceLevel,
    ) -> AuditResult:
        start = time.perf_counter()
        decisions = []
        for r in snapshot.records:
            hits = self.matches(r.content)
            decisions.append(
                AuditDecision(
                    record_id=r.record_id,
                    kind=RecordKind.RULE if hits else RecordKind.INFORMATION,
                    source=SourceKind.UNKNOWN,
                    confidence=1.0,
                    authority=Authority.UNAUTHORIZED if hits else Authority.AUTHORIZED,
                    rationale=f"D2 ({self.version}): matched {','.join(hits)}"
                    if hits
                    else f"D2 ({self.version}): no indicator matched",
                )
            )
        return AuditResult(
            defense=self.name,
            provenance_level=provenance_level,
            snapshot_id=snapshot.snapshot_id,
            decisions=tuple(decisions),
            cost=AuditCost(seconds=time.perf_counter() - start),
        )

    def apply(
        self, snapshot: MemorySnapshot, result: AuditResult, policy: Policy
    ) -> MemorySnapshot:
        return apply_policy(snapshot, result, policy)
