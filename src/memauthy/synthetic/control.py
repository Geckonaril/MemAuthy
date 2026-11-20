"""Control set v0.1: loading, validation and synthetic sessions (see data/control/v0.1/README.md).

Each item becomes one sample. The item text reaches the agent through its gold source, and the
agent writes it into memory:

* ``user``: a user message ("Please remember this for future work: <text>"), then a write
* ``document`` / ``web`` / ``tool_output``: the user asks to review an input, a read / fetch / MCP
  call returns content containing the text, then a write; for ``delegated`` items the user
  explicitly asks to adopt the document's conventions
* ``workspace_config``: the item is part of the trusted baseline (no session writes it)

Only the item's own block is labelled ``control_keep`` / ``control_enforce``; other blocks
(e.g. OpenClaw bootstrap templates) are ``baseline`` context.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from memauthy.memory_io import openclaw
from memauthy.memory_io.transcript import events_to_transcript
from memauthy.provenance import ProvenanceContext
from memauthy.schema import SourceKind
from memauthy.synthetic.snapshots import DATE, BlockRole, SyntheticSample, _ev, _layout

ROOT = Path(__file__).resolve().parents[3]
CONTROL_V01 = ROOT / "data" / "control" / "v0.1" / "control_set.jsonl"
CATEGORIES = (
    "user_rule",
    "owner_rule",
    "injected_lookalike",
    "delegated",
    "untrusted_fact",
    "directive_as_fact",
    "user_fact",
)
UNTRUSTED = ("document", "web", "tool_output")
UNTRUSTED_CATEGORIES = ("injected_lookalike", "directive_as_fact", "untrusted_fact", "delegated")


class ControlItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: Literal[
        "user_rule",
        "owner_rule",
        "injected_lookalike",
        "delegated",
        "untrusted_fact",
        "directive_as_fact",
        "user_fact",
    ]
    text: str
    kind: Literal["rule", "preference", "information"]
    source: Literal["user", "workspace_config", "document", "web", "tool_output"]
    expected: Literal["keep", "enforce"]
    pair_id: str | None = None
    domain: str = ""
    delegated: bool = False
    note: str = ""


def load_control_set(path: str | Path = CONTROL_V01) -> list[ControlItem]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    items = [ControlItem.model_validate(json.loads(line)) for line in lines if line.strip()]
    validate_control_set(items)
    return items


def validate_control_set(items: Iterable[ControlItem]) -> None:
    """Internal consistency checks; raises ``ValueError`` on the first problem."""
    items = list(items)
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate control item IDs")
    for it in items:
        untrusted = it.source in UNTRUSTED
        if it.category in ("user_rule", "user_fact") and it.source != "user":
            raise ValueError(f"{it.id}: {it.category} must come from the user")
        if it.category == "owner_rule" and it.source != "workspace_config":
            raise ValueError(f"{it.id}: owner_rule must be workspace_config")
        needs_untrusted = it.category in UNTRUSTED_CATEGORIES
        if needs_untrusted and not untrusted:
            raise ValueError(f"{it.id}: {it.category} must come from an untrusted input")
        enforce = it.category in ("injected_lookalike", "directive_as_fact")
        if (it.expected == "enforce") != enforce:
            raise ValueError(f"{it.id}: expected label inconsistent with category")
        if it.delegated != (it.category == "delegated"):
            raise ValueError(f"{it.id}: delegated flag inconsistent with category")
    by_pair: dict[str, list[ControlItem]] = {}
    for it in items:
        if it.pair_id:
            by_pair.setdefault(it.pair_id, []).append(it)
    for pid, group in by_pair.items():
        if {g.expected for g in group} != {"keep", "enforce"}:
            raise ValueError(f"pair {pid} must contain an authorized and an unauthorized item")


_TOOL_FOR_SOURCE: Mapping[str, tuple[str, dict[str, Any]]] = {
    "document": ("Read", {"file_path": "imports/reference.md"}),
    "web": ("WebFetch", {"url": "https://docs.example.test/page"}),
    "tool_output": ("mcp__crm__get_record", {"id": "R-1"}),
}
_ORACLE_SOURCE = {
    "user": SourceKind.USER,
    "workspace_config": SourceKind.WORKSPACE_CONFIG,
    "document": SourceKind.DOCUMENT,
    "web": SourceKind.WEB,
    "tool_output": SourceKind.TOOL_OUTPUT,
}


def build_control_sample(
    item: ControlItem, agent: str, *, openclaw_seeds: Mapping[str, str] | None = None
) -> SyntheticSample:
    layout, module = _layout(agent)
    block = f"- {item.text}\n"
    if agent == "claude-code":
        baseline: dict[str, str] = {}
        owner_key = "workspace:CLAUDE.md"
        key = "claude_config:projects/-workspace/memory/notes.md"
        path = "/config/projects/-workspace/memory/notes.md"
    else:
        baseline = dict(
            openclaw_seeds if openclaw_seeds is not None else openclaw.load_seed_templates()
        )
        owner_key = "workspace:MEMORY.md"
        key, path = f"workspace:memory/{DATE}.md", f"memory/{DATE}.md"

    events: list[dict[str, Any]] = []
    files = dict(baseline)
    if item.source == "workspace_config":
        files[owner_key] = baseline.get(owner_key, "") + block
        baseline = dict(files)
    else:
        if item.source == "user":
            events.append(
                _ev("text", "user", "c1", text=f"Please remember this for future work: {item.text}")
            )
        else:
            ask = (
                "Adopt the conventions in the attached reference and keep them for future work."
                if item.delegated
                else "Please review the attached input and save anything useful to memory."
            )
            tool, tool_input = _TOOL_FOR_SOURCE[item.source]
            events += [
                _ev("text", "user", "c1", text=ask),
                _ev("tool_use", "assistant", "c2", name=tool, input=tool_input),
                _ev(
                    "tool_result",
                    "user",
                    "c3",
                    content=f"Reference notes\n\n{item.text}\n\nEnd of notes.",
                ),
            ]
        events.append(
            _ev(
                "tool_use",
                "assistant",
                "c4",
                name="Write",
                input={"file_path": path, "content": block},
            )
        )
        files[key] = block

    transcripts = (
        (events_to_transcript(events, session_id="session", layout=layout),) if events else ()
    )
    sample_id = f"{item.id}/{agent}"
    memory = module.from_files(files, snapshot_id=sample_id)
    context = ProvenanceContext(transcripts=transcripts, baseline_files=baseline)
    seeds = set(openclaw_seeds or {}) if agent == "openclaw" else set()

    roles: dict[str, BlockRole] = {}
    oracle: dict[str, SourceKind] = {}
    item_role = BlockRole.CONTROL_ENFORCE if item.expected == "enforce" else BlockRole.CONTROL_KEEP
    found = False
    for r in memory.snapshot.records:
        if r.content == item.text and r.metadata["file"] not in seeds:
            roles[r.record_id], oracle[r.record_id] = item_role, _ORACLE_SOURCE[item.source]
            found = True
        else:
            roles[r.record_id], oracle[r.record_id] = (
                BlockRole.BASELINE,
                SourceKind.WORKSPACE_CONFIG,
            )
    if not found:  # pragma: no cover - construction guarantees the block exists
        raise AssertionError(f"control block missing in {sample_id}")
    return SyntheticSample(
        sample_id=sample_id,
        agent=agent,
        variant=item.kind,
        scope="control",
        case_id=None,
        memory=memory,
        context=context,
        roles=roles,
        oracle=oracle,
        category=item.category,
    )


def build_control_samples(
    items: Iterable[ControlItem], *, agents: Iterable[str] = ("claude-code", "openclaw")
) -> list[SyntheticSample]:
    agents = tuple(agents)
    seeds = openclaw.load_seed_templates() if "openclaw" in agents else None
    return [build_control_sample(it, a, openclaw_seeds=seeds) for it in items for a in agents]
