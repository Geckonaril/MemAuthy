"""Phase 2 offline detection experiment (tier 0, no model calls). See ADR-0011.

Usage::

    uv run python experiments/offline_detection.py --config configs/offline-detection-v0.1.yaml

Writes ``results/<run_id>/``: ``manifest.json``, ``cost.json``, ``summary.json``, ``summary.md``
(committed) and ``blocks.jsonl`` (raw block-level rows, not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memauthy import bench
from memauthy.cases import load_case
from memauthy.config import CostTier, load_config
from memauthy.eval.detection import Condition, evaluate, markdown_table, summarize, variant_table
from memauthy.eval.manifest import Run
from memauthy.synthetic import build_samples

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
    case_ids = list(config.case_ids) or [
        c["case_id"]
        for c in json.loads((bench.data_root() / bench.CATALOG).read_text(encoding="utf-8"))[
            "cases"
        ]
    ]
    conditions = [Condition.parse(x) for x in params["conditions"]]

    with Run.start(
        config,
        results_dir=args.results_dir,
        repo_dir=ROOT,
        benchmark_commit=bench.benchmark_commit(),
        dataset_revision=bench.dataset_revision(),
    ) as run:
        run.manifest.case_ids = case_ids
        with run.cost.timed("build_samples"):
            cases = [load_case(cid) for cid in case_ids]
            samples = build_samples(cases, agents=params["agents"], variants=params["variants"])
        with run.cost.timed("evaluate"):
            rows, seconds = evaluate(samples, conditions)
        for label, secs in seconds.items():
            run.cost.add(f"audit:{label}", seconds=secs)

        summary = summarize(rows, seconds)
        summary["config_hash"] = run.manifest.config_hash
        summary["note"] = (
            "Exploratory, synthetic snapshots (ADR-0011). Block-level detection only; "
            "not trigger-session adoption."
        )
        (run.run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        with (run.run_dir / "blocks.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(r.model_dump_json() + "\n")
        md = [
            f"# Offline detection — {run.manifest.run_id}",
            "",
            f"{summary['note']} Samples: {summary['n_samples']}; block rows: "
            f"{summary['n_block_rows']}. Rates with Wilson 95% CI.",
            "",
            "## Primary scope (IPI)",
            "",
            markdown_table(summary, "ipi"),
            "",
            "### Attack recall by rule surface variant (IPI)",
            "",
            variant_table(summary, "ipi"),
            "",
            "## Boundary analysis (DPI-U; rule arrives through the trusted user channel)",
            "",
            markdown_table(summary, "dpi"),
            "",
        ]
        (run.run_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
        print("\n".join(md))
        print(f"\nresults: {run.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
