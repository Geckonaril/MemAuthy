"""Defense conditions D0-D4 behind a common interface."""

from __future__ import annotations

from typing import Any

from memauthy.defenses.base import MemoryDefense
from memauthy.defenses.baselines import D2_PATTERNS, KeywordFilter, WipeMemory
from memauthy.defenses.d0 import NoDefense
from memauthy.defenses.d3 import LLMSanitizer
from memauthy.defenses.d4 import ProvenanceAuthorityDefense
from memauthy.provenance import ProvenanceContext

AVAILABLE = ("D0", "D1", "D2", "D3", "D4")


def build_defense(
    name: str, context: ProvenanceContext | None = None, **options: Any
) -> MemoryDefense:
    """Construct a defense by condition code.

    ``context`` is only used by D4. D3 needs ``client=`` (a JSON LLM client, local only).
    """
    if name == "D0":
        return NoDefense()
    if name == "D1":
        return WipeMemory(**options)
    if name == "D2":
        return KeywordFilter(**options)
    if name == "D3":
        if "client" not in options:
            raise ValueError("D3 requires a local LLM client: build_defense('D3', client=...)")
        return LLMSanitizer(**options)
    if name == "D4":
        return ProvenanceAuthorityDefense(context=context or ProvenanceContext(), **options)
    raise ValueError(f"unknown defense {name!r}; available: {', '.join(AVAILABLE)}")


__all__ = [
    "AVAILABLE",
    "D2_PATTERNS",
    "KeywordFilter",
    "LLMSanitizer",
    "MemoryDefense",
    "NoDefense",
    "ProvenanceAuthorityDefense",
    "WipeMemory",
    "build_defense",
]
