"""Claude Code native memory adapter (MemHarmBench layout).

Memory is a ``{key: text}`` mapping with keys ``"<namespace>:<relative posix path>"``:

* ``workspace:CLAUDE.md`` (and nested ``CLAUDE.md``), except under ``imports/`` or ``records/``
* ``claude_config:**/CLAUDE.md``
* ``claude_config:projects/<slug>/memory/**/*.md`` (auto memory: ``MEMORY.md`` and topic files)

The key rules mirror MemHarmBench's ``is_native_memory_path`` and ``distance_stage.memory_path``
(the stricter of the two), so any mapping produced here can be restored by the benchmark.
Nothing here writes into a benchmark run directory: audited memory goes to a separate output.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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

AGENT = "claude-code"
NAMESPACES = ("workspace", "claude_config")
EXCLUDED_WORKSPACE_DIRS = ("imports", "records")
MAX_FILE_CHARS = 200_000  # benchmark truncation limit
TRUNCATION_MARKER = "...[truncated"


class MemoryFormatError(ValueError):
    """Input does not match the Claude Code memory layout or is incomplete."""


def is_memory_key(key: str) -> bool:
    """True if ``key`` names a Claude Code native memory file."""
    if not isinstance(key, str) or ":" not in key:
        return False
    namespace, relative = key.split(":", 1)
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/"):
        return False
    # Check raw segments: PurePosixPath would silently drop "." and empty segments.
    parts = tuple(relative.split("/"))
    if any(p in ("", ".", "..") for p in parts):
        return False
    if namespace == "workspace":
        return parts[-1] == "CLAUDE.md" and parts[0] not in EXCLUDED_WORKSPACE_DIRS
    if namespace == "claude_config":
        if parts[-1] == "CLAUDE.md":
            return True
        return (
            len(parts) >= 4
            and parts[0] == "projects"
            and parts[2] == "memory"
            and relative.endswith(".md")
        )
    return False


def memory_digest(files: Mapping[str, str]) -> str:
    """Same digest MemHarmBench stores as ``memory_sha256``."""
    return hashlib.sha256(canonical_json(dict(files)).encode("utf-8")).hexdigest()


def validate_memory(files: Mapping[str, Any]) -> dict[str, str]:
    """Check keys and contents; return a plain dict. Raises :class:`MemoryFormatError`."""
    out: dict[str, str] = {}
    for key, text in files.items():
        if not is_memory_key(key):
            raise MemoryFormatError(f"not a Claude Code memory key: {key!r}")
        if not isinstance(text, str):
            raise MemoryFormatError(f"memory content must be text: {key!r}")
        if len(text) >= MAX_FILE_CHARS or TRUNCATION_MARKER in text:
            raise MemoryFormatError(f"memory file is truncated or too large: {key!r}")
        out[key] = text
    return out


@dataclass(frozen=True)
class ClaudeCodeMemory:
    """Loaded memory: the original files and the derived snapshot."""

    files: dict[str, str]
    snapshot: MemorySnapshot
    granularity: Granularity
    source: str | None = None  # where it was loaded from

    def render(self, audited: MemorySnapshot) -> tuple[dict[str, str], ChangeReport]:
        """New memory files for the audited snapshot (originals untouched)."""
        new_files, report = render_memory_files(self.files, audited, self.granularity)
        return validate_memory(new_files), report


def from_files(
    files: Mapping[str, Any],
    *,
    snapshot_id: str,
    case_id: str | None = None,
    label: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
    source: str | None = None,
) -> ClaudeCodeMemory:
    checked = validate_memory(files)
    snapshot = snapshot_from_files(
        checked,
        snapshot_id=snapshot_id,
        agent=AGENT,
        granularity=granularity,
        case_id=case_id,
        label=label,
    )
    return ClaudeCodeMemory(checked, snapshot, granularity, source)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MemoryFormatError(f"{path}: expected a JSON object")
    return data


def load_distance_snapshot(
    path: str | Path,
    *,
    case_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> ClaudeCodeMemory:
    """Load ``outputs/<chain>/snapshots/S{d}.json`` and verify its ``memory_sha256``."""
    path = Path(path)
    data = _read_json(path)
    memory = data.get("memory")
    if not isinstance(memory, dict) or "distance" not in data:
        raise MemoryFormatError(f"{path}: not a MemHarmBench distance snapshot")
    expected = data.get("memory_sha256")
    if expected is not None and memory_digest(memory) != expected:
        raise MemoryFormatError(f"{path}: memory_sha256 mismatch")
    label = f"S{data['distance']}"
    chain = path.parent.parent.name
    return from_files(
        memory,
        snapshot_id=f"{chain}/{label}",
        case_id=case_id,
        label=label,
        granularity=granularity,
        source=str(path),
    )


def load_evidence(
    path: str | Path,
    *,
    which: str = "memory_after",
    snapshot_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> ClaudeCodeMemory:
    """Load ``memory_before`` / ``memory_after`` from a stage ``evidence.json``."""
    if which not in ("memory_before", "memory_after"):
        raise ValueError("which must be 'memory_before' or 'memory_after'")
    path = Path(path)
    data = _read_json(path)
    memory = data.get(which)
    if not isinstance(memory, dict):
        raise MemoryFormatError(f"{path}: no {which!r} mapping")
    case = data.get("template_and_target", {}).get("case_id") or data.get("case_id")
    return from_files(
        memory,
        snapshot_id=snapshot_id or f"{path.parent.name}/{which}",
        case_id=case if isinstance(case, str) else None,
        label=which,
        granularity=granularity,
        source=str(path),
    )


def load_agent_dir(
    root: str | Path,
    *,
    snapshot_id: str,
    case_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> ClaudeCodeMemory:
    """Collect memory from an agent directory containing ``workspace/`` and ``claude_config/``.

    Files are read like the benchmark reads them (UTF-8, universal newlines).
    """
    root = Path(root)
    files: dict[str, str] = {}
    for namespace in NAMESPACES:
        base = root / namespace
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            key = f"{namespace}:{path.relative_to(base).as_posix()}"
            if path.is_file() and is_memory_key(key):
                files[key] = path.read_text(encoding="utf-8")
    return from_files(
        files,
        snapshot_id=snapshot_id,
        case_id=case_id,
        granularity=granularity,
        source=str(root),
    )


def write_agent_dir(files: Mapping[str, str], out_root: str | Path) -> list[Path]:
    """Write memory files under ``out_root/<namespace>/<relative>`` (LF line endings).

    ``out_root`` must not exist yet or be empty, so nothing is ever overwritten.
    """
    out_root = Path(out_root)
    if out_root.exists() and any(out_root.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out_root}")
    checked = validate_memory(files)
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
