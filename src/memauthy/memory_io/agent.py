"""Shared loading and writing for agent memory in MemHarmBench layouts.

An :class:`AgentLayout` says which ``"<namespace>:<relative path>"`` keys are native memory for
one agent. Everything else — validation, loading from evidence or agent directories, rendering an
audited snapshot, writing to a fresh output directory — is shared. Agent modules
(:mod:`.claude_code`, :mod:`.openclaw`) only define their layout.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memauthy.config import canonical_json
from memauthy.memory_io.files import (
    ChangeReport,
    Granularity,
    render_memory_files,
    snapshot_from_files,
)
from memauthy.schema import MemorySnapshot

MAX_FILE_CHARS = 200_000  # benchmark truncation limit
TRUNCATION_MARKER = "...[truncated"


class MemoryFormatError(ValueError):
    """Input does not match the agent's memory layout or is incomplete."""


def split_key(key: object) -> tuple[str, tuple[str, ...]] | None:
    """``"ns:a/b.md"`` -> ``("ns", ("a", "b.md"))``; ``None`` if the key is unsafe.

    Raw segments are checked: ``PurePosixPath`` would silently drop ``.`` and empty segments.
    Backslashes, colons and absolute paths are rejected.
    """
    if not isinstance(key, str) or ":" not in key:
        return None
    namespace, relative = key.split(":", 1)
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/"):
        return None
    parts = tuple(relative.split("/"))
    if any(p in ("", ".", "..") for p in parts):
        return None
    return namespace, parts


def is_md_name(name: str) -> bool:
    """``x.md`` but not a bare ``.md`` (matches ``PurePosixPath.suffix == ".md"``)."""
    return name.endswith(".md") and len(name) > len(".md")


@dataclass(frozen=True)
class AgentLayout:
    agent: str  # e.g. "claude-code"
    namespaces: tuple[str, ...]  # directory names under an agent root
    accepts: Callable[[str, tuple[str, ...]], bool]  # (namespace, parts) -> is memory
    # Structural role of a memory file, derived from its key only (e.g. "bootstrap", "daily").
    file_role: Callable[[str, tuple[str, ...]], str] = lambda namespace, parts: "memory"

    def is_memory_key(self, key: object) -> bool:
        split = split_key(key)
        return split is not None and split[0] in self.namespaces and self.accepts(*split)

    def role_of(self, key: str) -> str:
        split = split_key(key)
        if split is None:
            raise MemoryFormatError(f"unsafe memory key: {key!r}")
        return self.file_role(*split)


def memory_digest(files: Mapping[str, str]) -> str:
    """Same digest MemHarmBench stores as ``memory_sha256`` (sha256 of canonical JSON)."""
    return hashlib.sha256(canonical_json(dict(files)).encode("utf-8")).hexdigest()


def validate_memory(layout: AgentLayout, files: Mapping[str, Any]) -> dict[str, str]:
    """Check keys and contents; return a plain dict. Raises :class:`MemoryFormatError`."""
    out: dict[str, str] = {}
    for key, text in files.items():
        if not layout.is_memory_key(key):
            raise MemoryFormatError(f"not a {layout.agent} memory key: {key!r}")
        if not isinstance(text, str):
            raise MemoryFormatError(f"memory content must be text: {key!r}")
        if len(text) >= MAX_FILE_CHARS or TRUNCATION_MARKER in text:
            raise MemoryFormatError(f"memory file is truncated or too large: {key!r}")
        out[key] = text
    return out


@dataclass(frozen=True)
class AgentMemory:
    """Loaded memory: the original files and the derived snapshot."""

    layout: AgentLayout
    files: dict[str, str]
    snapshot: MemorySnapshot
    granularity: Granularity
    source: str | None = None  # where it was loaded from

    def render(self, audited: MemorySnapshot) -> tuple[dict[str, str], ChangeReport]:
        """New memory files for the audited snapshot (originals untouched)."""
        new_files, report = render_memory_files(self.files, audited, self.granularity)
        return validate_memory(self.layout, new_files), report


def from_files(
    layout: AgentLayout,
    files: Mapping[str, Any],
    *,
    snapshot_id: str,
    case_id: str | None = None,
    label: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
    source: str | None = None,
) -> AgentMemory:
    checked = validate_memory(layout, files)
    snapshot = snapshot_from_files(
        checked,
        snapshot_id=snapshot_id,
        agent=layout.agent,
        granularity=granularity,
        case_id=case_id,
        label=label,
    )
    records = tuple(
        r.model_copy(
            update={"metadata": {**r.metadata, "file_role": layout.role_of(r.metadata["file"])}}
        )
        for r in snapshot.records
    )
    snapshot = snapshot.model_copy(update={"records": records})
    return AgentMemory(layout, checked, snapshot, granularity, source)


def read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MemoryFormatError(f"{path}: expected a JSON object")
    return data


def load_evidence(
    layout: AgentLayout,
    path: str | Path,
    *,
    which: str = "memory_after",
    snapshot_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> AgentMemory:
    """Load ``memory_before`` / ``memory_after`` from an ``evidence.json``."""
    if which not in ("memory_before", "memory_after"):
        raise ValueError("which must be 'memory_before' or 'memory_after'")
    path = Path(path)
    data = read_json_object(path)
    memory = data.get(which)
    if not isinstance(memory, dict):
        raise MemoryFormatError(f"{path}: no {which!r} mapping")
    target = data.get("template_and_target")
    case = (target.get("case_id") if isinstance(target, dict) else None) or data.get("case_id")
    return from_files(
        layout,
        memory,
        snapshot_id=snapshot_id or f"{path.parent.name}/{which}",
        case_id=case if isinstance(case, str) else None,
        label=which,
        granularity=granularity,
        source=str(path),
    )


def load_agent_dir(
    layout: AgentLayout,
    root: str | Path,
    *,
    snapshot_id: str,
    case_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> AgentMemory:
    """Collect memory from ``root/<namespace>/...`` (UTF-8, universal newlines, like the
    benchmark). Files that are not memory for this agent are ignored."""
    root = Path(root)
    files: dict[str, str] = {}
    for namespace in layout.namespaces:
        base = root / namespace
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            key = f"{namespace}:{path.relative_to(base).as_posix()}"
            if path.is_file() and not path.is_symlink() and layout.is_memory_key(key):
                files[key] = path.read_text(encoding="utf-8")
    return from_files(
        layout,
        files,
        snapshot_id=snapshot_id,
        case_id=case_id,
        granularity=granularity,
        source=str(root),
    )


def write_agent_dir(
    layout: AgentLayout, files: Mapping[str, str], out_root: str | Path
) -> list[Path]:
    """Write memory under ``out_root/<namespace>/<relative>`` with LF line endings.

    ``out_root`` must not exist yet or be empty, so nothing is ever overwritten.
    """
    out_root = Path(out_root)
    if out_root.exists() and any(out_root.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out_root}")
    checked = validate_memory(layout, files)
    written: list[Path] = []
    base = out_root.resolve()
    for key, text in sorted(checked.items()):
        namespace, relative = key.split(":", 1)
        target = (out_root / namespace / relative).resolve()
        if base not in target.parents:
            raise MemoryFormatError(f"path escapes output directory: {key!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(target)
    return written
