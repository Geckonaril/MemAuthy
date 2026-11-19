"""OpenClaw native memory adapter (MemHarmBench layout).

OpenClaw keeps memory as Markdown in the workspace root (single namespace ``workspace``):

* bootstrap files ``AGENTS.md``, ``SOUL.md``, ``TOOLS.md``, ``IDENTITY.md``, ``USER.md``,
  ``HEARTBEAT.md``, ``BOOTSTRAP.md`` (top level only)
* long-term memory ``MEMORY.md`` (top level only)
* daily notes ``memory/**/*.md`` (usually ``memory/YYYY-MM-DD.md``)

Rules mirror MemHarmBench's ``runtime.openclaw.adapter.is_memory`` but are never looser (raw-segment
checks; no backslashes, colons, ``.`` or empty segments).

Unlike Claude Code, an OpenClaw exposure does **not** start from empty memory: MemHarmBench seeds
the workspace with owner-provided bootstrap templates full of instructions. They are legitimate
(owner-authorized) memory and are tagged with ``file_role = "bootstrap"``;
:func:`load_seed_templates` returns them so defenses and evaluation can treat them correctly.
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

AGENT = "openclaw"
NAMESPACES = ("workspace",)
BOOTSTRAP_FILES = frozenset(
    {"AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md"}
)
LONG_TERM_FILE = "MEMORY.md"
DAILY_DIR = "memory"
SEED_TEMPLATE_DIR = Path("runtime") / "openclaw" / "templates"

__all__ = [
    "AGENT",
    "BOOTSTRAP_FILES",
    "LAYOUT",
    "MAX_FILE_CHARS",
    "TRUNCATION_MARKER",
    "MemoryFormatError",
    "from_files",
    "is_memory_key",
    "load_agent_dir",
    "load_evidence",
    "load_seed_templates",
    "memory_digest",
    "validate_memory",
    "write_agent_dir",
]


def _accepts(namespace: str, parts: tuple[str, ...]) -> bool:
    if len(parts) == 1:
        return parts[0] in BOOTSTRAP_FILES or parts[0] == LONG_TERM_FILE
    return parts[0] == DAILY_DIR and is_md_name(parts[-1])


def _file_role(namespace: str, parts: tuple[str, ...]) -> str:
    if len(parts) == 1:
        return "long_term" if parts[0] == LONG_TERM_FILE else "bootstrap"
    return "daily"


LAYOUT = AgentLayout(agent=AGENT, namespaces=NAMESPACES, accepts=_accepts, file_role=_file_role)


def is_memory_key(key: object) -> bool:
    """True if ``key`` names an OpenClaw native memory file."""
    return LAYOUT.is_memory_key(key)


def validate_memory(files: Mapping[str, Any]) -> dict[str, str]:
    return _agent.validate_memory(LAYOUT, files)


def from_files(files: Mapping[str, Any], **kwargs: Any) -> AgentMemory:
    return _agent.from_files(LAYOUT, files, **kwargs)


def load_evidence(path: str | Path, **kwargs: Any) -> AgentMemory:
    """Load ``memory_before`` / ``memory_after`` from ``steps/<step>/evidence.json``."""
    return _agent.load_evidence(LAYOUT, path, **kwargs)


def load_agent_dir(root: str | Path, **kwargs: Any) -> AgentMemory:
    """Collect memory from an agent directory containing ``workspace/``."""
    return _agent.load_agent_dir(LAYOUT, root, **kwargs)


def write_agent_dir(files: Mapping[str, str], out_root: str | Path) -> list[Path]:
    return _agent.write_agent_dir(LAYOUT, files, out_root)


def load_seed_templates(source_root: str | Path | None = None) -> dict[str, str]:
    """The bootstrap files MemHarmBench seeds into every OpenClaw exposure workspace.

    Read from the pinned submodule (``runtime/openclaw/templates``); keys are memory keys.
    """
    if source_root is None:
        from memauthy.bench import source_root as _source_root

        source_root = _source_root()
    template_dir = Path(source_root) / SEED_TEMPLATE_DIR
    if not template_dir.is_dir():
        raise MemoryFormatError(f"OpenClaw seed templates not found: {template_dir}")
    files = {
        f"workspace:{p.name}": p.read_text(encoding="utf-8")
        for p in sorted(template_dir.glob("*.md"))
    }
    return validate_memory(files)
