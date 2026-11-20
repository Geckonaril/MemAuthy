"""P2: transcript taint. Attributes a memory block to the input its *content* came from.

Lexical, deterministic and local (maintainer decision 2026-11-20; embeddings are a later
ablation). For every non-baseline block:

1. Candidate sources are the untrusted tool results and the user messages that precede the
   memory write containing the block (or the whole history if no write is found, e.g. a shell
   write).
2. Similarity of the block to each source is the maximum of
   * character 5-gram **containment** (share of the block's 5-grams found in the source), robust
     to excerpting and light editing, and
   * **distinctive-token overlap**: share of the block's distinctive tokens (identifiers with
     digits, e-mail addresses, URLs, account-like strings, numbers) found in the source.
3. Taint = best untrusted similarity, user = best user similarity.
   * taint >= ``threshold`` and taint >= user + ``margin`` -> the untrusted source kind,
     ``derived_from_untrusted=True``
   * user >= ``threshold`` and user >= taint + ``margin`` -> ``user``, ``derived=False``
   * otherwise inconclusive -> fall back to P1's structural estimate with reduced confidence and
     ``derived=None`` (no content evidence)
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from memauthy.provenance.base import ProvenanceContext, ProvenanceEstimate
from memauthy.provenance.extractors import (
    BASELINE_SOURCE,
    StructuralProvenance,
    _is_harness_text,
    _memory_writes,
    _norm,
    _untrusted_kind,
)
from memauthy.schema import MemorySnapshot, ProvenanceLevel, SourceKind, TranscriptEvent

_DISTINCTIVE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"  # e-mail
    r"|https?://\S+"  # URL
    r"|\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"  # IBAN-like
    r"|\b(?=[A-Za-z0-9_.-]*\d)(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]\b"
    r"|\b\d+(?:[.,]\d+)*\b"  # numbers
)


def _grams(text: str, n: int = 5) -> set[str]:
    t = _norm(text.casefold())
    return (
        {t[i : i + n] for i in range(max(len(t) - n + 1, 0))}
        if len(t) >= n
        else {t}
        if t
        else set()
    )


def distinctive_tokens(text: str) -> set[str]:
    return {m.group(0).casefold().rstrip(".,;:!?)]}'\"") for m in _DISTINCTIVE.finditer(text)}


def similarity(block: str, source: str) -> float:
    """max(char-5-gram containment of block in source, distinctive-token overlap)."""
    bg = _grams(block)
    containment = len(bg & _grams(source)) / len(bg) if bg else 0.0
    bt = distinctive_tokens(block)
    st = distinctive_tokens(source) if bt else set()
    overlap = len(bt & st) / len(bt) if bt else 0.0
    return max(containment, overlap)


@dataclass(frozen=True)
class _Source:
    position: tuple[int, int]  # (session index, event index)
    event: TranscriptEvent
    untrusted: bool
    tool: str | None


def _sources(context: ProvenanceContext) -> list[_Source]:
    out: list[_Source] = []
    for si, t in enumerate(context.transcripts):
        current_tool: str | None = None
        for ev in t.events:
            if ev.kind == "tool_use":
                current_tool = ev.tool_name
            elif ev.kind == "tool_result" or ev.role == "tool":
                out.append(_Source((si, ev.index), ev, True, ev.tool_name or current_tool))
            elif ev.role == "user" and not _is_harness_text(ev.content):
                out.append(_Source((si, ev.index), ev, False, None))
    return out


@dataclass(frozen=True)
class TranscriptTaintProvenance:
    level: ProvenanceLevel = ProvenanceLevel.P2
    threshold: float = 0.6
    margin: float = 0.1
    fallback_penalty: float = 0.1

    def estimate(
        self, snapshot: MemorySnapshot, context: ProvenanceContext
    ) -> dict[str, ProvenanceEstimate]:
        baseline = context.baseline_block_ids()
        structural = StructuralProvenance().estimate(snapshot, context)
        sources = _sources(context)
        writes = _memory_writes(context.transcripts)
        session_index = {t.session_id: i for i, t in enumerate(context.transcripts)}
        out: dict[str, ProvenanceEstimate] = {}

        for r in snapshot.records:
            rid = r.record_id
            if rid in baseline:
                out[rid] = structural[rid].model_copy(update={"derived_from_untrusted": False})
                continue
            needle = _norm(r.content)
            file = r.metadata.get("file")
            matching = [
                w for w in writes if needle and needle in w.text and w.event.memory_file == file
            ]
            if matching:
                w = matching[-1]
                limit = (session_index[w.session], w.event.index)
                candidates: Iterable[_Source] = [s for s in sources if s.position < limit]
            else:
                candidates = sources

            best_u: tuple[float, _Source | None] = (0.0, None)
            best_t: tuple[float, _Source | None] = (0.0, None)
            for s in candidates:
                sim = similarity(r.content, s.event.content)
                if s.untrusted and sim > best_u[0]:
                    best_u = (sim, s)
                elif not s.untrusted and sim > best_t[0]:
                    best_t = (sim, s)
            taint, user = best_u[0], best_t[0]

            if taint >= self.threshold and taint >= user + self.margin and best_u[1]:
                src = best_u[1]
                kind = _untrusted_kind((src.event.model_copy(update={"tool_name": src.tool}),))
                out[rid] = ProvenanceEstimate(
                    record_id=rid,
                    source=kind,
                    confidence=round(min(0.5 + 0.4 * taint, 0.9), 3),
                    evidence=tuple(e for e in (src.event.event_ref,) if e),
                    rationale=f"P2: content matches untrusted {kind.value} output "
                    f"(taint {taint:.2f} vs user {user:.2f})",
                    derived_from_untrusted=True,
                )
            elif user >= self.threshold and user >= taint + self.margin and best_t[1]:
                out[rid] = ProvenanceEstimate(
                    record_id=rid,
                    source=SourceKind.USER,
                    confidence=round(min(0.5 + 0.4 * user, 0.9), 3),
                    evidence=tuple(e for e in (best_t[1].event.event_ref,) if e),
                    rationale=f"P2: content matches a user message (user {user:.2f} vs taint "
                    f"{taint:.2f})",
                    derived_from_untrusted=False,
                )
            else:
                fb = structural[rid]
                out[rid] = fb.model_copy(
                    update={
                        "confidence": round(max(fb.confidence - self.fallback_penalty, 0.0), 3),
                        "rationale": f"P2: inconclusive content match (taint {taint:.2f}, user "
                        f"{user:.2f}); structural fallback - {fb.rationale}",
                        "derived_from_untrusted": None,
                    }
                )
        return out


__all__ = ["BASELINE_SOURCE", "TranscriptTaintProvenance", "distinctive_tokens", "similarity"]
