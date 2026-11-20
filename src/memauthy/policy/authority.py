"""Authority decision: combine what a block is (kind) with where it came from (provenance).

Threat model section 5: a persistent rule is authorized iff its source is a trusted party and it
stays within that party's authority. Condition 2 (authority scope) is **not** checked in this
version; it is a documented limitation and the reason DPI-U is a boundary analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from memauthy.provenance.base import ProvenanceEstimate
from memauthy.rules.classifier import Classification
from memauthy.schema import Authority, RecordKind

AUDITED_KINDS = frozenset({RecordKind.RULE, RecordKind.PREFERENCE})


@dataclass(frozen=True)
class AuthorityDecision:
    authority: Authority
    confidence: float
    rationale: str


@dataclass(frozen=True)
class AuthorityPolicy:
    """Maps (kind, provenance) to an authority decision.

    * **provenance-first** (``audit_derived=True``, ADR-0012): a block whose content is shown to
      derive from an untrusted input (``derived_from_untrusted``) with confidence >=
      ``min_confidence`` is ``unauthorized`` whatever its kind, so directives stated as facts are
      caught
    * otherwise kinds other than rule / preference are not behavioral and are ``authorized``
    * trusted source with confidence >= ``min_confidence`` -> ``authorized``
    * untrusted source with confidence >= ``min_confidence`` -> ``unauthorized``
    * unknown source or low confidence -> ``uncertain`` (kept and flagged by default)
    """

    min_confidence: float = 0.5
    audit_derived: bool = True

    def decide(self, kind: Classification, provenance: ProvenanceEstimate) -> AuthorityDecision:
        if (
            self.audit_derived
            and provenance.derived_from_untrusted
            and not provenance.source.is_trusted
            and provenance.source.value != "unknown"
            and provenance.confidence >= self.min_confidence
        ):
            return AuthorityDecision(
                Authority.UNAUTHORIZED,
                round(provenance.confidence, 3),
                f"{kind.kind.value} block derived from untrusted {provenance.source.value} input "
                "(provenance-first)",
            )
        if kind.kind not in AUDITED_KINDS:
            return AuthorityDecision(
                Authority.AUTHORIZED, kind.confidence, f"not a behavioral {kind.kind.value} block"
            )
        source = provenance.source
        confident = provenance.confidence >= self.min_confidence
        if source.value == "unknown" or not confident:
            return AuthorityDecision(
                Authority.UNCERTAIN,
                provenance.confidence,
                f"{kind.kind.value} with undetermined source "
                f"({source.value}, confidence {provenance.confidence:.2f})",
            )
        conf = round(min(kind.confidence, provenance.confidence), 3)
        if source.is_trusted:
            return AuthorityDecision(
                Authority.AUTHORIZED, conf, f"{kind.kind.value} from trusted source {source.value}"
            )
        return AuthorityDecision(
            Authority.UNAUTHORIZED,
            conf,
            f"{kind.kind.value} from untrusted source {source.value}",
        )
