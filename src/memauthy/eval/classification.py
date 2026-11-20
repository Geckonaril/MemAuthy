"""Classification metrics with Wilson intervals (shared by classifier and detection evaluation)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


class ClassMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    support: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    recall_ci: tuple[float, float]


class ClassificationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int
    accuracy: float
    accuracy_ci: tuple[float, float]
    per_class: dict[str, ClassMetrics]
    confusion: dict[str, dict[str, int]]  # gold -> predicted -> count


def classification_report(
    gold: Sequence[str], predicted: Sequence[str], labels: Iterable[str] | None = None
) -> ClassificationReport:
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have the same length")
    labels = sorted(set(labels or ()) | set(gold) | set(predicted))
    pairs = Counter(zip(gold, predicted, strict=True))
    confusion = {g: {p: pairs.get((g, p), 0) for p in labels} for g in labels}
    per_class = {}
    for lab in labels:
        tp = pairs.get((lab, lab), 0)
        fp = sum(pairs.get((g, lab), 0) for g in labels if g != lab)
        fn = sum(pairs.get((lab, p), 0) for p in labels if p != lab)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[lab] = ClassMetrics(
            label=lab,
            support=tp + fn,
            tp=tp,
            fp=fp,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=f1,
            recall_ci=wilson_interval(tp, tp + fn),
        )
    correct = sum(pairs.get((lab, lab), 0) for lab in labels)
    n = len(gold)
    return ClassificationReport(
        n=n,
        accuracy=correct / n if n else 0.0,
        accuracy_ci=wilson_interval(correct, n),
        per_class=per_class,
        confusion=confusion,
    )
