"""Defense conditions D0-D4 behind a common interface."""

from memauthy.defenses.base import MemoryDefense
from memauthy.defenses.d0 import NoDefense

__all__ = ["MemoryDefense", "NoDefense"]
