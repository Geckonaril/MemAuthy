"""Experiment configuration: YAML files validated by pydantic (see ADR-0004)."""

from __future__ import annotations

import hashlib
import json
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from memauthy.schema import Policy, ProvenanceLevel

ENV_VAR_PATTERN = r"^[A-Z_][A-Z0-9_]*$"


class CostTier(IntEnum):
    """Cost tier of an experiment (see ADR-0005)."""

    OFFLINE = 0  # no model calls
    LOCAL = 1  # local / free model
    PAID = 2  # paid API; requires explicit approval


class ModelConfig(BaseModel):
    """A model used by an agent, judge or LLM-based defense. Every parameter is explicit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str | None = None
    provider: str  # e.g. "ollama", "openai-compatible", "anthropic"
    temperature: float = Field(ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, gt=0)
    # Names of environment variables, never the values themselves.
    endpoint_env: str | None = Field(default=None, pattern=ENV_VAR_PATTERN)
    key_env: str | None = Field(default=None, pattern=ENV_VAR_PATTERN)


class ExperimentConfig(BaseModel):
    """Top-level experiment configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = ""
    tier: CostTier
    seed: int
    defenses: tuple[str, ...] = ()
    provenance_levels: tuple[ProvenanceLevel, ...] = ()
    policies: tuple[Policy, ...] = ()
    case_ids: tuple[str, ...] = ()
    models: dict[str, ModelConfig] = Field(default_factory=dict)  # role -> model
    params: dict[str, Any] = Field(default_factory=dict)  # experiment-specific settings


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace, UTF-8."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_hash(config: ExperimentConfig) -> str:
    """sha256 of the canonical JSON form; independent of key order in the YAML file."""
    payload = canonical_json(config.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> ExperimentConfig:
    """Load and validate an experiment config from a YAML file."""
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return ExperimentConfig.model_validate(data)
