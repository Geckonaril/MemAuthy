"""Call and token profile of a benchmark campaign, per stage (issue #46, input to #47).

Reads ``<campaign>/outputs/<chain>/``, written by the benchmark and by ``memauthy.benchrun``:

* **Agent (Claude Code).** Native transcript usage in each ``*_evidence.json``. One API
  response can span several transcript lines; they are counted once by message ID, and a
  message already seen in an earlier stage of the same chain is not counted again (exposure
  attempt 2 continues the attempt-1 session). Upstream call counts come from
  ``*_upstream.json``.
* **Judge.** ``usage`` of every ``judge_cache/*/response_*.json``.

Only counts are read; no transcript text is copied into the profile.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

Counter = dict[str, int]


def _new() -> Counter:
    return defaultdict(int)


def _messages(evidence: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for entry in evidence.get("trajectory") or []:
        for line in entry.get("lines") or []:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            msg = event.get("message") if isinstance(event, dict) else None
            if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                yield str(msg.get("id") or event.get("uuid")), msg["usage"]


def agent_usage(evidence: Mapping[str, Any], seen: set[str]) -> Counter:
    out = _new()
    for mid, u in _messages(evidence):
        if mid in seen:
            continue
        seen.add(mid)
        out["messages"] += 1
        out["input_tokens"] += int(u.get("input_tokens") or 0)
        out["cache_read_input_tokens"] += int(u.get("cache_read_input_tokens") or 0)
        out["cache_creation_input_tokens"] += int(u.get("cache_creation_input_tokens") or 0)
        out["output_tokens"] += int(u.get("output_tokens") or 0)
    out["prompt_tokens"] = (
        out["input_tokens"] + out["cache_read_input_tokens"] + out["cache_creation_input_tokens"]
    )
    out["max_prompt_tokens"] = max(
        (
            int(u.get("input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0)
            + int(u.get("cache_creation_input_tokens") or 0)
            for _, u in _messages(evidence)
        ),
        default=0,
    )
    return out


def judge_usage(judging_dir: Path) -> Counter:
    out = _new()
    for path in sorted(judging_dir.glob("judge_cache/*/response_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        usage = data.get("usage") or (data.get("body") or {}).get("usage") or {}
        out["calls"] += 1
        out["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        out["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        details = usage.get("completion_tokens_details") or {}
        out["reasoning_tokens"] += int(details.get("reasoning_tokens") or 0)
    return out


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def chain_profile(chain_dir: Path) -> dict[str, Any]:
    """Per-stage counts for one Claude Code chain (``exposure1``, ``exposure2``, ``arm:<slug>``)."""
    stages: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    def stage(name: str, base: Path, prefix: str, judging: Path) -> None:
        evidence = _read(base / f"{prefix}_evidence.json")
        if evidence is None:
            return
        upstream = _read(base / f"{prefix}_upstream.json") or {}
        stages[name] = {
            "agent": dict(agent_usage(evidence, seen)),
            "upstream_calls": len(upstream.get("rows", [])),
            "judge": dict(judge_usage(judging)),
        }

    for attempt in (1, 2):
        stage(
            f"exposure{attempt}",
            chain_dir,
            f"exposure{attempt}",
            chain_dir / "judging" / f"exposure{attempt}",
        )
    for arm_dir in sorted((chain_dir / "arms").glob("*")):
        # each arm's trigger is a fresh session: transcript IDs never overlap the exposure
        stage(f"arm:{arm_dir.name}", arm_dir, "trigger", arm_dir / "judging" / "trigger")
    result = _read(chain_dir / "chain_result.json") or {}
    return {
        "chain_id": chain_dir.name,
        "state": result.get("state"),
        "trigger_status": (result.get("exposure") or {}).get("trigger_status"),
        "stages": stages,
    }


def campaign_profile(campaign_dir: Path) -> dict[str, Any]:
    chains = [chain_profile(p) for p in sorted((campaign_dir / "outputs").glob("*")) if p.is_dir()]
    totals: dict[str, Counter] = defaultdict(_new)
    for chain in chains:
        for name, st in chain["stages"].items():
            kind = "trigger" if name.startswith("arm:") else "exposure"
            t = totals[kind]
            t["sessions"] += 1
            t["upstream_calls"] += st["upstream_calls"]
            for k, v in st["agent"].items():
                if k == "max_prompt_tokens":
                    t[k] = max(t[k], v)
                else:
                    t["agent_" + k] += v
            for k, v in st["judge"].items():
                t["judge_" + k] += v
    return {
        "schema": "memauthy-campaign-profile-v1",
        "n_chains": len(chains),
        "totals": {k: dict(v) for k, v in totals.items()},
        "chains": chains,
    }
