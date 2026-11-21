"""Control set evaluation (tier 0, no model calls).

Usage::

    uv run python experiments/control_evaluation.py --config configs/control-v0.1.yaml

Writes ``results/<run_id>/``: ``manifest.json``, ``cost.json``, ``summary.json``, ``summary.md``
(committed) and ``blocks.jsonl`` (not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memauthy import bench
from memauthy.config import load_config
from memauthy.eval.detection import Condition, control_table, evaluate, summarize_control
from memauthy.eval.manifest import Run
from memauthy.eval.runner_support import check_tier, llm_defense_options, record_llm_usage
from memauthy.synthetic.control import build_control_samples, load_control_set

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if (err := check_tier(config)) is not None:
        print(err, file=sys.stderr)
        return 2
    params = config.params
    control_path = ROOT / params["control_set"]
    conditions = [Condition.parse(x) for x in params["conditions"]]
    defense_options, llm = llm_defense_options(config, conditions, ROOT / ".cache" / "llm")

    with Run.start(
        config,
        results_dir=args.results_dir,
        repo_dir=ROOT,
        benchmark_commit=bench.benchmark_commit(),
    ) as run:
        with run.cost.timed("build_samples"):
            items = load_control_set(control_path)
            samples = build_control_samples(items, agents=params["agents"])
        run.manifest.case_ids = [it.id for it in items]
        with run.cost.timed("evaluate"):
            rows, seconds = evaluate(samples, conditions, defense_options)
        for label, secs in seconds.items():
            run.cost.add(f"audit:{label}", seconds=secs, within="evaluate")

        summary = {
            "llm_usage": record_llm_usage(run, llm),
            "control_set": params["control_set"],
            "n_items": len(items),
            "n_samples": len(samples),
            "config_hash": run.manifest.config_hash,
            "note": "Exploratory; synthetic sessions; control set v0.1 (frozen).",
            "conditions": summarize_control(rows),
            "seconds_per_condition": {k: round(v, 4) for k, v in seconds.items()},
        }
        (run.run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        with (run.run_dir / "blocks.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(r.model_dump_json() + "\n")
        md = [
            f"# Control set v0.1 — {run.manifest.run_id}",
            "",
            f"{summary['note']} Items: {len(items)}; samples: {len(samples)} "
            "(both agents). Item blocks only. Category cells = share of items enforced "
            "(want 0 for keep categories, 1 for injected_lookalike / directive_as_fact).",
            "",
            control_table(summary["conditions"]),
            "",
        ]
        (run.run_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
        print("\n".join(md))
        print(f"\nresults: {run.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
