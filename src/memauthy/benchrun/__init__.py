"""Defense arms inside real MemHarmBench runs: exposure → defense → trigger (issue #45)."""

from memauthy.benchrun.chain import LineageError, run_defended_chain
from memauthy.benchrun.defend import (
    Arm,
    DefendedExposure,
    DefenseInputError,
    defend_exposure,
    parse_arms,
)

__all__ = [
    "Arm",
    "DefendedExposure",
    "DefenseInputError",
    "LineageError",
    "defend_exposure",
    "parse_arms",
    "run_defended_chain",
]
