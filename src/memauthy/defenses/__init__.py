"""Defense conditions D0-D4 behind a common interface."""

from memauthy.defenses.base import MemoryDefense
from memauthy.defenses.d0 import NoDefense
from memauthy.defenses.d4 import ProvenanceAuthorityDefense

__all__ = ["MemoryDefense", "NoDefense", "ProvenanceAuthorityDefense"]
