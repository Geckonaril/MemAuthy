"""D4: the proposed provenance- and authority-aware memory audit."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from memauthy.policy import AuthorityPolicy, apply_policy
from memauthy.provenance import EXTRACTORS, ProvenanceContext
from memauthy.rules.classifier import DEFAULT_CLASSIFIER, RuleClassifier
from memauthy.schema import (
    AuditCost,
    AuditDecision,
    AuditResult,
    MemorySnapshot,
    Policy,
    ProvenanceLevel,
    Transcript,
)


@dataclass
class ProvenanceAuthorityDefense:
    """Classify every block, estimate its provenance at the requested level, decide authority.

    ``context`` carries what the defense may know besides the snapshot (transcripts, trusted
    baseline, and oracle labels used only at P0). A ``transcript`` passed to :meth:`audit` is added
    to the context's transcripts.

    ``act_on_uncertain`` decides whether uncertain records (unknown or low-confidence source) are
    enforced; by default they are kept and flagged. At P3 every source is unknown, so the two
    settings give the two extremes of a content-only audit: nothing enforced, or every rule and
    preference enforced.
    """

    context: ProvenanceContext = field(default_factory=ProvenanceContext)
    classifier: RuleClassifier = DEFAULT_CLASSIFIER
    authority: AuthorityPolicy = field(default_factory=AuthorityPolicy)
    act_on_uncertain: bool = False
    name: str = "D4"

    def audit(
        self,
        snapshot: MemorySnapshot,
        transcript: Transcript | None,
        provenance_level: ProvenanceLevel,
    ) -> AuditResult:
        start = time.perf_counter()
        extractor_cls = EXTRACTORS.get(provenance_level)
        if extractor_cls is None:
            raise NotImplementedError(f"provenance level {provenance_level} not available yet")
        context = self.context
        if transcript is not None:
            context = replace(context, transcripts=(*context.transcripts, transcript))
        provenance = extractor_cls().estimate(snapshot, context)

        decisions = []
        for record in snapshot.records:
            kind = self.classifier.classify(record.content, record.metadata.get("block_kind"))
            prov = provenance[record.record_id]
            decision = self.authority.decide(kind, prov)
            decisions.append(
                AuditDecision(
                    record_id=record.record_id,
                    kind=kind.kind,
                    source=prov.source,
                    confidence=decision.confidence,
                    authority=decision.authority,
                    rationale=f"{decision.rationale}; kind[{kind.rationale}]; "
                    f"provenance[{prov.rationale}]",
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
        return apply_policy(snapshot, result, policy, act_on_uncertain=self.act_on_uncertain)
