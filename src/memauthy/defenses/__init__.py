"""Defense conditions D0-D4 behind a common interface."""

from __future__ import annotations

from typing import Any

from memauthy.defenses.base import MemoryDefense
from memauthy.defenses.baselines import D2_PATTERNS, KeywordFilter, WipeMemory
from memauthy.defenses.d0 import NoDefense
from memauthy.defenses.d4 import ProvenanceAuthorityDefense
from memauthy.provenance import ProvenanceContext

AVAILABLE = ("D0", "D1", "D2", "D4")


def build_defense(
    name: str, context: ProvenanceContext | None = None, **options: Any
) -> MemoryDefense:
    """Construct a defense by condition code. ``context`` is only used by D4."""
    if name == "D0":
        return NoDefense()
    if name == "D1":
        return WipeMemory(**options)
    if name == "D2":
        return KeywordFilter(**options)
    if name == "D4":
        return ProvenanceAuthorityDefense(context=context or ProvenanceContext(), **options)
    if name == "D3":
        raise NotImplementedError("D3 (local LLM sanitizer) is planned for phase 3")
    raise ValueError(f"unknown defense {name!r}; available: {', '.join(AVAILABLE)}")


__all__ = [
    "AVAILABLE",
    "D2_PATTERNS",
    "KeywordFilter",
    "MemoryDefense",
    "NoDefense",
    "ProvenanceAuthorityDefense",
    "WipeMemory",
    "build_defense",
]
