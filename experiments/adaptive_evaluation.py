"""Adaptive attack evaluation (tier 0, no model calls). See ADR-0013.

Usage::

    uv run python experiments/adaptive_evaluation.py --config configs/adaptive-v0.1.yaml

Writes ``results/<run_id>/``: ``manifest.json``, ``cost.json``, ``summary.json``, ``summary.md``
(committed) and ``blocks.jsonl`` (not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memauthy import bench
from memauthy.cases import load_case
from memauthy.config import CostTier, load_config
from memauthy.eval.detection import Condition, adaptive_table, evaluate, summarize_adaptive
from memauthy.eval.manifest import Run
from memauthy.synthetic.adaptive import build_adaptive_samples, load_variants

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if config.tier is not CostTier.OFFLINE:
        print("this runner is tier 0 only", file=sys.stderr)
        return 2
    if not bench.dataset_available():
        print("dataset missing: run `memauthy bench download`", file=sys.stderr)
        return 2
    params = config.params
    catalog = json.loads((bench.data_root() / bench.CATALOG).read_text(encoding="utf-8"))
    case_ids = list(config.case_ids) or [c["case_id"] for c in catalog["cases"]]
    conditions = [Condition.parse(x) for x in params["conditions"]]

    with Run.start(
        config,
        results_dir=args.results_dir,
        repo_dir=ROOT,
        benchmark_commit=bench.benchmark_commit(),
        dataset_revision=bench.dataset_revision(),
    ) as run:
        with run.cost.timed("build_samples"):
            cases = [c for c in (load_case(cid) for cid in case_ids) if c.is_primary_scope]
            variants = load_variants(ROOT / params["variants"])
            samples = build_adaptive_samples(cases, variants, agents=params["agents"])
        run.manifest.case_ids = [c.case_id for c in cases]
        with run.cost.timed("evaluate"):
            rows, seconds = evaluate(samples, conditions)
        for label, secs in seconds.items():
            run.cost.add(f"audit:{label}", seconds=secs)

        summary = {
            "variants": params["variants"],
            "n_cases": len(cases),
            "n_variants": len(variants),
            "n_samples": len(samples),
            "config_hash": run.manifest.config_hash,
            "note": "Exploratory (RQ5); synthetic sessions; adaptive variants v0.1 (frozen). "
            "Detection only, not trigger-session adoption.",
            "conditions": summarize_adaptive(rows),
            "seconds_per_condition": {k: round(v, 4) for k, v in seconds.items()},
        }
        (run.run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        with (run.run_dir / "blocks.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(r.model_dump_json() + "\n")
        md = [
            f"# Adaptive variants v0.1 — {run.manifest.run_id}",
            "",
            f"{summary['note']} IPI cases: {len(cases)}; variants: {len(variants)}; "
            f"samples: {len(samples)}. Neutralized = every attack block of a sample enforced.",
            "",
            "## Neutralization by strategy",
            "",
            adaptive_table(summary["conditions"], "by_strategy"),
            "",
            "## Neutralization by variant",
            "",
            adaptive_table(summary["conditions"], "by_variant"),
            "",
        ]
        (run.run_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
        print("\n".join(md))
        print(f"\nresults: {run.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
