"""MemHarmBench campaign with MemAuthy defense arms (issues #45, #46). See ADR-0016.

Usage (PowerShell, from the repo root)::

    $cfg = "configs/rehearsal-claude-v0.1.yaml"
    uv run python experiments/benchmark_arms.py --config $cfg check
    uv run python experiments/benchmark_arms.py --config $cfg start
    uv run python experiments/benchmark_arms.py --config $cfg status --watch
    uv run python experiments/benchmark_arms.py --config $cfg pause
    uv run python experiments/benchmark_arms.py --config $cfg profile

Same control semantics as the benchmark's ``scripts/experiment.py`` (background worker,
checkpoints, ``pause``/``resume``/``retry``), with three differences:

* only the configured cases and replicates are queued;
* each chain runs ``memauthy.benchrun`` (one exposure, one defended trigger per arm);
* rehearsals (tier 1) may use local ``http://`` Ollama endpoints. Paid runs are refused.

Outputs go to ``runs/<name>/`` (git-ignored). Nothing in ``third_party/`` is modified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "third_party" / "MemHarmBench"
ACTIONS = ("check", "start", "status", "pause", "resume", "retry", "profile", "_worker")

from memauthy import bench  # noqa: E402
from memauthy.benchrun import harness  # noqa: E402
from memauthy.benchrun.launch import (  # noqa: E402
    LaunchError,
    filter_jobs,
    freeze_json,
    relaxed_loader,
    run_plan,
)
from memauthy.benchrun.profile import campaign_profile  # noqa: E402
from memauthy.config import config_hash, load_config  # noqa: E402
from memauthy.eval.manifest import git_state  # noqa: E402


def prepare(config_path: Path) -> tuple[dict[str, Any], Path, Path]:
    config = load_config(config_path)
    if not bench.dataset_available():
        raise LaunchError("dataset missing: run `uv run python -m memauthy bench download`")
    catalog = json.loads((bench.data_root() / bench.CATALOG).read_text(encoding="utf-8"))
    run_dir = ROOT / "runs" / config.name
    plan = run_plan(config, catalog["cases"], run_dir)
    plan["config_hash"] = config_hash(config)
    bench_config = run_dir / "benchmark.local.json"
    freeze_json(bench_config, plan["benchmark_config"], "benchmark config")
    freeze_json(run_dir / "memauthy_run.json", plan, "MemAuthy campaign plan")
    return plan, run_dir, bench_config


def bootstrap(plan: dict[str, Any], bench_config: Path) -> Any:
    """Import the benchmark runtime with the MemAuthy patches applied (this process only)."""
    for path in (BENCH, BENCH / "src", BENCH / "workflow_quickrouter", BENCH / "runtime/bridge"):
        sys.path.insert(0, str(path))
    os.environ["MEMHARMBENCH_CONFIG"] = str(bench_config)
    from runtime import settings

    if plan["rehearsal"]:
        settings.load = relaxed_loader(settings.load, str(bench_config))
    from runtime import control, protocols

    full_jobs = protocols.jobs

    def subset(config: Any = None) -> list[dict[str, Any]]:
        return filter_jobs(full_jobs(), plan["case_ids"], plan["replicates"])

    original_check = control.check

    def check(offline: bool = False) -> dict[str, Any]:
        control.jobs = full_jobs  # the benchmark verifies its full 864-chain protocol
        try:
            result = original_check(offline)
        finally:
            control.jobs = subset
        result["planned_chains"] = len(subset())
        result["memauthy"] = {
            "arms": plan["arms"],
            "case_ids": plan["case_ids"],
            "replicates": plan["replicates"],
            "rehearsal": plan["rehearsal"],
        }
        return result

    protocols.jobs = subset
    control.jobs = subset
    control.check = check
    harness.install(plan["arms"], force_trigger=plan.get("force_trigger", False))
    return control


def ollama_models(plan: dict[str, Any]) -> dict[str, Any]:
    """Which local models stand behind the benchmark's model names (rehearsal record)."""
    cfg = plan["benchmark_config"]
    url = urlparse(cfg["judge_endpoint"])
    show = f"{url.scheme}://localhost:{url.port or 11434}/api/show"
    info = {}
    for name in sorted({cfg["model"], cfg["judge_model"]}):
        body = json.dumps({"model": name}).encode()
        try:
            req = Request(show, data=body, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except OSError as exc:
            raise LaunchError(
                f"local model {name!r} not available in Ollama ({exc}); create the alias "
                "first (see configs/rehearsal-ollama.Modelfile)"
            ) from None
        base = [ln for ln in data.get("modelfile", "").splitlines() if ln.startswith("FROM ")]
        info[name] = {
            "details": data.get("details", {}),
            "from": base[0] if base else None,
            "parameters": data.get("parameters", ""),
        }
    return info


def remove_stale_gateway(control: Any) -> str | None:
    """Remove this campaign's gateway container if its private token file no longer exists.

    The gateway name depends only on the benchmark config, so a container left behind by a
    deleted run directory is reused by a fresh campaign with the same config. It still holds
    the old master key and rejects the new client (``400 No connected db``).
    """
    if control.CONFIG["agent"] != "claude_code":
        return None
    from runtime.settings import owner

    name = owner(control.CONFIG) + "-gateway"
    if (Path(control.CONFIG["run_dir"]) / "gateway" / "tokens.json").exists():
        return None
    label = '{{index .Config.Labels "memharmbench.owner"}}'
    found = subprocess.run(
        ["docker", "inspect", "--type", "container", name, "--format", label],
        capture_output=True,
        text=True,
    )
    if found.returncode or found.stdout.strip() != name:
        return None  # no container, or not owned by this benchmark config
    if subprocess.run(["docker", "rm", "-f", name], capture_output=True).returncode:
        raise RuntimeError(f"could not remove stale gateway container {name}")
    return name


def start(control: Any, config_path: Path, plan: dict[str, Any], run_dir: Path, action: str):
    """``runtime.control.start`` with the worker command pointing at this script."""
    if os.name != "nt":
        raise RuntimeError("background execution follows the benchmark: Windows + Docker")
    launch = {
        "at": datetime.now(UTC).isoformat(),
        "action": action,
        "memauthy_git": git_state(ROOT).model_dump(mode="json"),
        "local_models": ollama_models(plan) if plan["rehearsal"] else None,
        "removed_stale_gateway": remove_stale_gateway(control),
    }
    with (run_dir / "launches.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(launch) + "\n")
    with control.exclusive("launcher"):
        if control.read(control.HERE / "campaign.json"):
            control.verify_lock()
        current = control.status()
        if current["worker_alive"]:
            if action == "retry":
                raise ValueError("Pause and wait for worker_alive=False before retry")
            return current
        control.freeze()
        if action == "retry":
            marker = {"at": control.now(), "id": uuid.uuid4().hex, "budgets_reset": False}
            control.write(control.STATE / "retry.request", marker)
            for path in (control.HERE / "outputs").glob("**/steps/*/try*/error.json"):
                error = control.read(path)
                ack = path.parent / "recharge_ack.json"
                if error.get("category") in ("quota", "authentication") and not ack.exists():
                    control.immutable(ack, marker)
        pause = control.STATE / "pause.request"
        if pause.exists():
            pause.unlink()
        logdir = control.HERE / "logs" / uuid.uuid4().hex
        logdir.mkdir(parents=True)
        env = dict(
            os.environ,
            MEMHARMBENCH_CONFIG=control.CONFIG["config_path"],
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
        )
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
        command = [sys.executable, "-B", str(Path(__file__).resolve())]
        command += ["--config", str(config_path.resolve()), "_worker"]
        with (logdir / "stdout.log").open("ab") as out, (logdir / "stderr.log").open("ab") as err:
            proc = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                creationflags=flags,
                close_fds=True,
            )
        control.write(
            control.STATE / "worker.json",
            {
                "pid": proc.pid,
                "birth": control.birth(proc.pid),
                "state": "STARTING",
                "stage": "initializing",
                "heartbeat_at": control.now(),
            },
        )
        return {"started": True, "pid": proc.pid, "logs": str(logdir), "run_dir": str(run_dir)}


def write_profile(plan: dict[str, Any], run_dir: Path) -> int:
    """Counts only (no transcript text) to ``results/<name>/summary.json`` (committed)."""
    launches = [
        json.loads(x)
        for x in (run_dir / "launches.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    profile = campaign_profile(run_dir / "campaign")
    summary = {
        "plan": {k: v for k, v in plan.items() if k != "benchmark_config"},
        "benchmark": {k: plan["benchmark_config"][k] for k in ("agent", "model", "judge_model")},
        "launches": launches,
        "profile": profile,
    }
    out = ROOT / "results" / plan["name"] / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(profile["totals"], indent=2))
    print(f"written: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan, run_dir, bench_config = prepare(args.config)
        if args.action == "profile":
            return write_profile(plan, run_dir)
        control = bootstrap(plan, bench_config)
        if args.action == "_worker":
            return control.worker()
        if args.action == "check":
            value = control.check(args.offline)
        elif args.action in ("start", "resume", "retry"):
            value = start(control, args.config, plan, run_dir, args.action)
        elif args.action == "pause":
            control.write(control.STATE / "pause.request", {"at": control.now()})
            value = {"pause_requested": True, "note": "wait until worker_alive is false"}
        else:
            while True:
                print(json.dumps(control.status(), ensure_ascii=False))
                if not args.watch:
                    return 0
                time.sleep(5)
    except (LaunchError, ValueError, RuntimeError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Display stopped. The background worker is unchanged.")
        return 0
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
