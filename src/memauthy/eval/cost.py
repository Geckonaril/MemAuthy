"""Cost accounting per run: tokens, wall-clock time and USD (see ADR-0004/0005)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from memauthy.schema import SCHEMA_VERSION, AuditCost


class CostRecord(BaseModel):
    """Accumulated cost of one component (e.g. "agent", "judge", "defense:D3")."""

    model_config = ConfigDict(extra="forbid")

    component: str
    calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    seconds: float = Field(default=0.0, ge=0)
    usd: float = Field(default=0.0, ge=0)


class CostLog(BaseModel):
    """Contents of ``results/<run_id>/cost.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    components: list[CostRecord]
    total: CostRecord


class CostTracker:
    """Mutable accumulator used while a run is in progress."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._records: dict[str, CostRecord] = {}

    def _get(self, component: str) -> CostRecord:
        return self._records.setdefault(component, CostRecord(component=component))

    def add(
        self,
        component: str,
        *,
        calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        seconds: float = 0.0,
        usd: float = 0.0,
    ) -> None:
        rec = self._get(component)
        rec.calls += calls
        rec.input_tokens += input_tokens
        rec.output_tokens += output_tokens
        rec.seconds += seconds
        rec.usd += usd

    def add_audit_cost(self, component: str, cost: AuditCost, *, calls: int = 0) -> None:
        self.add(
            component,
            calls=calls,
            input_tokens=cost.input_tokens,
            output_tokens=cost.output_tokens,
            seconds=cost.seconds,
            usd=cost.usd,
        )

    @contextmanager
    def timed(self, component: str) -> Iterator[None]:
        """Add the wall-clock time of the ``with`` block to ``component``."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(component, seconds=time.perf_counter() - start)

    def to_log(self) -> CostLog:
        components = [r.model_copy() for r in sorted(self._records.values(), key=_by_name)]
        total = CostRecord(component="total")
        for r in components:
            total.calls += r.calls
            total.input_tokens += r.input_tokens
            total.output_tokens += r.output_tokens
            total.seconds += r.seconds
            total.usd += r.usd
        return CostLog(run_id=self.run_id, components=components, total=total)

    def write(self, run_dir: str | Path) -> Path:
        path = Path(run_dir) / "cost.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_log().model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path


def _by_name(record: CostRecord) -> str:
    return record.component
