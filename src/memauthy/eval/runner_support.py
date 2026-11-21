"""Shared helpers for experiment runners: cost tiers, case sampling, local LLM wiring."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from memauthy.config import CostTier, ExperimentConfig
from memauthy.eval.detection import Condition
from memauthy.eval.manifest import Run
from memauthy.llm import CachedClient, OllamaClient


def check_tier(config: ExperimentConfig) -> str | None:
    """Return an error message if the config's tier is not allowed for local runners."""
    if config.tier is CostTier.PAID:
        return "tier 2 (paid API) runs need explicit maintainer approval and a dedicated runner"
    return None


def select_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    per_template: int | None = None,
    seed: int = 0,
    channel: str | None = None,
) -> list[str]:
    """Case IDs, optionally stratified: ``per_template`` cases from every template (seeded)."""
    pool = [c for c in cases if channel is None or c["channel"] == channel]
    if per_template is None:
        return [c["case_id"] for c in pool]
    by_template: dict[str, list[str]] = defaultdict(list)
    for c in pool:
        by_template[c["template_id"]].append(c["case_id"])
    rng = random.Random(seed)
    chosen: list[str] = []
    for template in sorted(by_template):
        ids = sorted(by_template[template])
        chosen += sorted(rng.sample(ids, min(per_template, len(ids))))
    return chosen


def llm_defense_options(
    config: ExperimentConfig, conditions: Iterable[Condition], cache_dir: Path
) -> tuple[dict[str, dict[str, Any]], CachedClient | None]:
    """Build the D3 client if any condition needs it (model from ``config.models['d3']``)."""
    if not any(c.defense == "D3" for c in conditions):
        return {}, None
    from memauthy.defenses.d3 import PROMPT_VERSION

    if config.tier is not CostTier.LOCAL:
        raise ValueError("D3 runs are tier 1 (local model); set tier: 1 in the config")
    model_cfg = config.models.get("d3")
    if model_cfg is None or model_cfg.provider != "ollama":
        raise ValueError("D3 needs models.d3 with provider 'ollama' in the config")
    inner = OllamaClient(
        model=model_cfg.name,
        temperature=model_cfg.temperature,
        seed=config.seed,
        num_predict=model_cfg.max_tokens or 160,
    )
    safe = model_cfg.name.replace(":", "_").replace("/", "_")
    client = CachedClient(inner, cache_dir / f"{safe}-{PROMPT_VERSION}.jsonl", PROMPT_VERSION)
    return {"D3": {"client": client}}, client


def record_llm_usage(run: Run, client: CachedClient | None) -> dict[str, Any] | None:
    if client is None:
        return None
    s = client.stats
    run.cost.add(
        f"llm:{client.model}",
        calls=s.calls,
        input_tokens=s.input_tokens,
        output_tokens=s.output_tokens,
        seconds=s.seconds,
        usd=0.0,
        within="audit:D3",  # model time is spent inside the D3 audit
    )
    return {
        "model": client.model,
        "calls": s.calls,
        "cache_hits": s.cache_hits,
        "errors": s.errors,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "seconds": round(s.seconds, 2),
    }
