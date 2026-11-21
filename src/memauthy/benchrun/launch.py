"""Plan and guard a MemHarmBench campaign with MemAuthy defense arms (issues #46, #47).

Pure helpers used by ``experiments/benchmark_arms.py``: they turn a MemAuthy YAML config into
the benchmark's JSON campaign config, choose the chain subset, and enforce the cost guard.

**Rehearsal** runs (tier 1) point agent and judge at a local Ollama server. The benchmark only
accepts its fixed model names and HTTPS endpoints, so a rehearsal uses local Ollama aliases
with those names, and the HTTPS check is relaxed for local hosts only. Rehearsal outcomes are
never analysed; they measure plumbing, failures and token use. Paid runs (tier 2) are refused
here until the budget cap of issue #47 exists.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from memauthy.benchrun.defend import parse_arms
from memauthy.config import CostTier, ExperimentConfig
from memauthy.eval.runner_support import select_cases

ENDPOINT_KEYS = ("agent_endpoint", "judge_endpoint")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "host.docker.internal"})
BENCHMARK_KEYS = (
    "agent",
    "model",
    "judge_model",
    "agent_endpoint",
    "judge_endpoint",
    "agent_key_env",
    "judge_key_env",
    "agent_image",
    "gateway_image",
)
SHADOW_SUFFIX = ".https-shadow.json"


class LaunchError(ValueError):
    """The campaign plan is not allowed or not consistent."""


def is_local_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and (parsed.hostname or "") in LOCAL_HOSTS


def check_cost_guard(config: ExperimentConfig) -> None:
    """Rehearsal: tier 1 and local endpoints only. Anything else is refused for now."""
    params = config.params
    bench = params.get("benchmark", {})
    if config.tier is CostTier.PAID:
        raise LaunchError(
            "tier 2 (paid) campaigns need the approved budget cap of issue #47; refused"
        )
    if config.tier is not CostTier.LOCAL or not params.get("rehearsal"):
        raise LaunchError("benchmark campaigns run as tier-1 rehearsals (rehearsal: true)")
    remote = [k for k in ENDPOINT_KEYS if not is_local_endpoint(str(bench.get(k, "")))]
    if remote:
        raise LaunchError(f"rehearsal endpoints must be local hosts: {', '.join(remote)}")


def benchmark_config(config: ExperimentConfig, run_dir: Path) -> dict[str, Any]:
    """The benchmark's JSON campaign config (``replicates`` and model names are fixed by it)."""
    bench = dict(config.params.get("benchmark", {}))
    missing = [k for k in BENCHMARK_KEYS if k not in bench]
    if missing:
        raise LaunchError(f"params.benchmark is missing: {', '.join(missing)}")
    extra = set(bench) - set(BENCHMARK_KEYS) - {"agent_http_host", "judge_http_host"}
    if extra:
        raise LaunchError(f"unknown params.benchmark keys: {', '.join(sorted(extra))}")
    return {
        "experiment": "main",
        **{k: bench[k] for k in BENCHMARK_KEYS},
        "agent_http_host": bench.get("agent_http_host"),
        "judge_http_host": bench.get("judge_http_host"),
        "replicates": 3,
        "run_dir": str((run_dir / "campaign").resolve()),
    }


def choose_cases(config: ExperimentConfig, catalog_cases: Sequence[Mapping[str, Any]]) -> list[str]:
    """Explicit ``case_ids``, or ``n_cases`` from distinct templates (seeded, stratified)."""
    if config.case_ids:
        known = {c["case_id"] for c in catalog_cases}
        unknown = [c for c in config.case_ids if c not in known]
        if unknown:
            raise LaunchError(f"unknown case IDs: {', '.join(unknown)}")
        return list(config.case_ids)
    sample = config.params.get("case_sample", {})
    pool = select_cases(
        catalog_cases, per_template=1, seed=config.seed, channel=sample.get("channel")
    )
    n = int(sample.get("n_cases", len(pool)))
    return sorted(random.Random(config.seed).sample(pool, min(n, len(pool))))


def filter_jobs(
    jobs: Iterable[Mapping[str, Any]], case_ids: Sequence[str], replicates: Sequence[int]
) -> list[dict[str, Any]]:
    wanted = set(case_ids)
    reps = set(replicates)
    out = [dict(j) for j in jobs if j["case_id"] in wanted and j["replicate"] in reps]
    if len(out) != len(wanted) * len(reps):
        raise LaunchError("selected cases/replicates do not match the benchmark job list")
    return out


def run_plan(
    config: ExperimentConfig, catalog_cases: Sequence[Mapping[str, Any]], run_dir: Path
) -> dict[str, Any]:
    """Everything that defines the campaign; frozen to ``memauthy_run.json`` on first start."""
    check_cost_guard(config)
    arms = parse_arms(config.params.get("arms", []))
    replicates = [int(r) for r in config.params.get("replicates", [1])]
    if not replicates or any(r not in (1, 2, 3) for r in replicates):
        raise LaunchError("replicates must be a non-empty subset of [1, 2, 3]")
    return {
        "schema": "memauthy-benchmark-arms-v1",
        "name": config.name,
        "tier": int(config.tier),
        "rehearsal": bool(config.params.get("rehearsal")),
        "arms": [a.label for a in arms],
        "case_ids": choose_cases(config, catalog_cases),
        "replicates": replicates,
        "benchmark_config": benchmark_config(config, run_dir),
    }


def freeze_json(path: Path, value: Mapping[str, Any], what: str) -> None:
    """Write once; a different value later means the campaign changed (use a new name)."""
    if path.is_file():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old != value:
            raise LaunchError(f"{what} changed since the campaign started: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relaxed_loader(original: Callable[..., dict[str, Any]], env_path: str) -> Callable[..., Any]:
    """Wrap ``runtime.settings.load`` so local ``http://`` endpoints pass its HTTPS check.

    The benchmark validates a shadow copy whose local endpoints read ``https://``; the returned
    config carries the real local URLs and the real config path. Non-local endpoints are never
    rewritten, so they still need HTTPS.
    """

    def load(path: str | Path | None = None) -> dict[str, Any]:
        real = Path(path or env_path).resolve()
        raw = json.loads(real.read_text(encoding="utf-8"))
        shadow = dict(raw)
        for key in ENDPOINT_KEYS:
            url = str(raw.get(key, ""))
            if url.startswith("http://") and is_local_endpoint(url):
                shadow[key] = "https://" + url.removeprefix("http://")
        if shadow == raw:
            return original(real)
        shadow_path = real.with_name(real.stem + SHADOW_SUFFIX)
        shadow_path.write_text(json.dumps(shadow, indent=2) + "\n", encoding="utf-8")
        value = original(shadow_path)
        for key in ENDPOINT_KEYS:
            value[key] = str(raw[key]).rstrip("/")
        value["config_path"] = str(real)
        return value

    return load
