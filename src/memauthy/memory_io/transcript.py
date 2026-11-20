"""Session transcripts from MemHarmBench evidence bundles.

``evidence.json`` already contains ``native_events``: the benchmark's lossless normalization of
the agent's native JSONL into a common block schema (Claude Code natively; OpenClaw via its
converter, with ``exec/read/write/edit`` mapped to ``Bash/Read/Write/Edit``). Each event is one
content block with ``role``, ``type`` (``text``, ``tool_use``, ``tool_result``, ...), ``line``,
``block`` and a stable ``event_ref``.

This module turns those events into a :class:`~memauthy.schema.Transcript` and marks tool calls
that write a memory file. That is structural information (P1/P2), not ground truth.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from memauthy.memory_io.agent import AgentLayout
from memauthy.schema import Transcript, TranscriptEvent

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
# Container mount points used by MemHarmBench (Claude: /config + /workspace; OpenClaw: /workspace).
MOUNTS = {"/config/": "claude_config", "/workspace/": "workspace"}


def memory_key_for_path(path: object, layout: AgentLayout) -> str | None:
    """Map a tool's file path to a memory key of ``layout``, or ``None``.

    Absolute container paths are mapped through the benchmark mount points; relative paths are
    taken relative to the workspace.
    """
    if not isinstance(path, str) or not path:
        return None
    posix = path.replace("\\", "/")
    key = None
    for mount, namespace in MOUNTS.items():
        if posix.startswith(mount):
            key = f"{namespace}:{posix[len(mount) :]}"
            break
    if key is None:
        if posix.startswith("/"):
            return None
        key = f"workspace:{PurePosixPath(posix).as_posix()}"
    return key if layout.is_memory_key(key) else None


def _text(value: Any) -> str:
    """Flatten tool-result content (string or list of blocks) to text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def events_to_transcript(
    events: Iterable[Mapping[str, Any]],
    *,
    session_id: str,
    layout: AgentLayout,
    include_subagents: bool = False,
) -> Transcript:
    """Convert benchmark ``native_events`` to a transcript.

    Kept: ``text`` blocks (user/assistant), ``tool_use`` (assistant), ``tool_result`` (tool).
    Skipped: thinking and other non-content blocks. Order follows the native log.
    """
    out: list[TranscriptEvent] = []
    for ev in events:
        if ev.get("scope") == "subagent" and not include_subagents:
            continue
        kind = ev.get("type")
        role = ev.get("role")
        if kind == "text" and role in ("user", "assistant", "system"):
            content, tool_name, memory_file = _text(ev.get("text")), None, None
            out_role = role
        elif kind == "tool_use":
            tool_input = ev.get("input") if isinstance(ev.get("input"), Mapping) else {}
            tool_name = ev.get("name") if isinstance(ev.get("name"), str) else None
            content = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
            memory_file = (
                memory_key_for_path(tool_input.get("file_path"), layout)
                if tool_name in WRITE_TOOLS
                else None
            )
            out_role = "assistant"
        elif kind == "tool_result":
            content, tool_name, memory_file = _text(ev.get("content")), None, None
            native = ev.get("native_tool_name")
            tool_name = native if isinstance(native, str) else None
            out_role = "tool"
        else:
            continue
        out.append(
            TranscriptEvent(
                index=len(out),
                role=out_role,
                content=content,
                tool_name=tool_name,
                kind=kind,
                memory_file=memory_file,
                event_ref=ev.get("event_ref") if isinstance(ev.get("event_ref"), str) else None,
            )
        )
    return Transcript(session_id=session_id, events=tuple(out))


def transcript_from_evidence(evidence: Mapping[str, Any], layout: AgentLayout) -> Transcript:
    """Build the transcript of one evidence bundle (one session)."""
    events = evidence.get("native_events")
    if not isinstance(events, list):
        raise ValueError("evidence has no normalized 'native_events'")
    integrity = evidence.get("evidence_integrity")
    session = (
        integrity.get("native_session_id") if isinstance(integrity, Mapping) else None
    ) or evidence.get("session_id")
    return events_to_transcript(events, session_id=str(session or "unknown-session"), layout=layout)
