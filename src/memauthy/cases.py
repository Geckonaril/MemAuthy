"""MemHarmBench case metadata, including ground-truth provenance (the basis of P0).

Ground truth is for the oracle level P0 and for evaluation only; realistic levels (P1-P3) must
not read it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CaseInfo(BaseModel):
    """Subset of a MemHarmBench case file (``cases/<case_id>.json``)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str
    template_id: str
    objective_id: str
    victim: Literal["user", "workspace_owner", "external_stakeholder"]
    channel: Literal["direct_instruction", "indirect_content"]
    context_id: str
    permission_condition: str  # "IPI-UNTRUSTED-ARTIFACT" | "DPI-U"
    source_authority: str
    exposure_input: str
    carrier_artifact: str = ""  # empty for DPI-U
    payload_text: str
    payload_value: str
    prohibited_value: str = ""
    target_memory_rule: str
    trigger_input: str
    harm_outcome: str = ""

    @property
    def is_primary_scope(self) -> bool:
        """IPI cases are the primary analysis scope (threat model section 7)."""
        return self.channel == "indirect_content"


def load_case(case_id: str, data_root: str | Path | None = None) -> CaseInfo:
    if data_root is None:
        from memauthy.bench import data_root as _data_root

        data_root = _data_root()
    path = Path(data_root) / "cases" / f"{case_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"case not found: {path}")
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    return CaseInfo.model_validate(data)
