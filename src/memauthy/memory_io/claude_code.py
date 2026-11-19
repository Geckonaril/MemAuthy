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

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from memauthy.memory_io import agent as _agent
from memauthy.memory_io.agent import (
    MAX_FILE_CHARS,
    TRUNCATION_MARKER,
    AgentLayout,
    AgentMemory,
    MemoryFormatError,
    is_md_name,
    memory_digest,
)
from memauthy.memory_io.files import Granularity

AGENT = "claude-code"
NAMESPACES = ("workspace", "claude_config")
EXCLUDED_WORKSPACE_DIRS = ("imports", "records")

__all__ = [
    "AGENT",
    "LAYOUT",
    "MAX_FILE_CHARS",
    "TRUNCATION_MARKER",
    "ClaudeCodeMemory",
    "MemoryFormatError",
    "from_files",
    "is_memory_key",
    "load_agent_dir",
    "load_distance_snapshot",
    "load_evidence",
    "memory_digest",
    "validate_memory",
    "write_agent_dir",
]


def _accepts(namespace: str, parts: tuple[str, ...]) -> bool:
    if namespace == "workspace":
        return parts[-1] == "CLAUDE.md" and parts[0] not in EXCLUDED_WORKSPACE_DIRS
    if parts[-1] == "CLAUDE.md":
        return True
    return (
        len(parts) >= 4
        and parts[0] == "projects"
        and parts[2] == "memory"
        and is_md_name(parts[-1])
    )


def _file_role(namespace: str, parts: tuple[str, ...]) -> str:
    if parts[-1] == "CLAUDE.md":
        return "project_instructions" if namespace == "workspace" else "user_instructions"
    return "auto_memory_index" if len(parts) == 4 and parts[-1] == "MEMORY.md" else "auto_memory"


LAYOUT = AgentLayout(agent=AGENT, namespaces=NAMESPACES, accepts=_accepts, file_role=_file_role)
ClaudeCodeMemory = AgentMemory


def is_memory_key(key: object) -> bool:
    """True if ``key`` names a Claude Code native memory file."""
    return LAYOUT.is_memory_key(key)


def validate_memory(files: Mapping[str, Any]) -> dict[str, str]:
    return _agent.validate_memory(LAYOUT, files)


def from_files(files: Mapping[str, Any], **kwargs: Any) -> AgentMemory:
    return _agent.from_files(LAYOUT, files, **kwargs)


def load_evidence(path: str | Path, **kwargs: Any) -> AgentMemory:
    """Load ``memory_before`` / ``memory_after`` from a stage ``evidence.json``."""
    return _agent.load_evidence(LAYOUT, path, **kwargs)


def load_agent_dir(root: str | Path, **kwargs: Any) -> AgentMemory:
    """Collect memory from an agent directory containing ``workspace/`` and ``claude_config/``."""
    return _agent.load_agent_dir(LAYOUT, root, **kwargs)


def write_agent_dir(files: Mapping[str, str], out_root: str | Path) -> list[Path]:
    return _agent.write_agent_dir(LAYOUT, files, out_root)


def load_distance_snapshot(
    path: str | Path,
    *,
    case_id: str | None = None,
    granularity: Granularity = Granularity.BLOCK,
) -> AgentMemory:
    """Load ``outputs/<chain>/snapshots/S{d}.json`` and verify its ``memory_sha256``.

    Distance snapshots exist only for Claude Code in MemHarmBench.
    """
    path = Path(path)
    data = _agent.read_json_object(path)
    memory = data.get("memory")
    if not isinstance(memory, dict) or "distance" not in data:
        raise MemoryFormatError(f"{path}: not a MemHarmBench distance snapshot")
    expected = data.get("memory_sha256")
    if expected is not None and memory_digest(memory) != expected:
        raise MemoryFormatError(f"{path}: memory_sha256 mismatch")
    label = f"S{data['distance']}"
    return from_files(
        memory,
        snapshot_id=f"{path.parent.parent.name}/{label}",
        case_id=case_id,
        label=label,
        granularity=granularity,
        source=str(path),
    )
