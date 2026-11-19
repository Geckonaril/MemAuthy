"""Map agent memory files to a :class:`MemorySnapshot` and back.

Agent-neutral: works on a ``{file_key: text}`` mapping (the representation MemHarmBench uses for
native memory, e.g. ``"claude_config:projects/-workspace/memory/MEMORY.md"``). Agent adapters only
decide which files are memory and where they come from.

Defenses never touch the original files: :func:`render_memory_files` returns a new mapping plus a
:class:`ChangeReport`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from memauthy.memory_io.markdown import (
    Document,
    Edit,
    parse_markdown,
    parse_whole_file,
    render_edited,
)
from memauthy.schema import MemoryRecord, MemorySnapshot


class Granularity(StrEnum):
    BLOCK = "block"  # one record per logical Markdown block (default)
    FILE = "file"  # one record per file (for comparison)


def parse_memory_files(
    files: Mapping[str, str], granularity: Granularity = Granularity.BLOCK
) -> dict[str, Document]:
    parse = parse_markdown if granularity is Granularity.BLOCK else parse_whole_file
    return {key: parse(key, files[key]) for key in sorted(files)}


def snapshot_from_files(
    files: Mapping[str, str],
    *,
    snapshot_id: str,
    agent: str,
    granularity: Granularity = Granularity.BLOCK,
    case_id: str | None = None,
    label: str | None = None,
) -> MemorySnapshot:
    """Build a snapshot with one record per block (or per file)."""
    records: list[MemoryRecord] = []
    for doc in parse_memory_files(files, granularity).values():
        for ordinal, block in enumerate(doc.blocks):
            assert block.block_id is not None and block.kind is not None
            records.append(
                MemoryRecord(
                    record_id=block.block_id,
                    content=block.body,
                    source_path=doc.key,
                    metadata={
                        "file": doc.key,
                        "block_kind": block.kind.value,
                        "ordinal": ordinal,
                        "start_line": block.start_line,
                        "section": list(block.section),
                        "granularity": granularity.value,
                    },
                )
            )
    return MemorySnapshot(
        snapshot_id=snapshot_id,
        agent=agent,
        case_id=case_id,
        label=label,
        records=tuple(records),
    )


class Change(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    file: str
    action: Literal["removed", "quarantined", "replaced"]
    before: str
    after: str | None = None


class ChangeReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    granularity: Granularity
    changes: tuple[Change, ...] = ()
    changed_files: tuple[str, ...] = ()
    unchanged_files: tuple[str, ...] = ()

    @property
    def is_noop(self) -> bool:
        return not self.changes


def render_memory_files(
    original_files: Mapping[str, str],
    audited: MemorySnapshot,
    granularity: Granularity = Granularity.BLOCK,
) -> tuple[dict[str, str], ChangeReport]:
    """Render the audited snapshot back onto the original files.

    A record missing from ``audited.records`` is removed from its file (``quarantined`` if it is
    in ``audited.quarantine``, else ``removed``); a record whose content differs is replaced in
    place. Every other byte of every file is preserved. Returns ``(new_files, report)``; the input
    mapping is not modified.
    """
    docs = parse_memory_files(original_files, granularity)
    original = {b.block_id: (doc, b) for doc in docs.values() for b in doc.blocks}

    active = {r.record_id: r for r in audited.records}
    quarantined = {r.record_id for r in audited.quarantine}
    unknown = (set(active) | quarantined) - set(original)
    if unknown:
        raise ValueError(f"audited snapshot has unknown records: {', '.join(sorted(unknown))}")

    removals: dict[str, set[str]] = {}
    replacements: dict[str, dict[str, str]] = {}
    changes: list[Change] = []
    for block_id, (doc, block) in original.items():
        assert block_id is not None
        record = active.get(block_id)
        if record is None:
            removals.setdefault(doc.key, set()).add(block_id)
            action: Literal["removed", "quarantined"] = (
                "quarantined" if block_id in quarantined else "removed"
            )
            changes.append(
                Change(record_id=block_id, file=doc.key, action=action, before=block.body)
            )
        elif record.content != block.body:
            replacements.setdefault(doc.key, {})[block_id] = record.content
            changes.append(
                Change(
                    record_id=block_id,
                    file=doc.key,
                    action="replaced",
                    before=block.body,
                    after=record.content,
                )
            )

    new_files: dict[str, str] = {}
    changed, unchanged = [], []
    for key, doc in docs.items():
        edit = Edit(remove=frozenset(removals.get(key, set())), replace=replacements.get(key, {}))
        if edit.remove or edit.replace:
            new_files[key] = render_edited(doc, edit)
            changed.append(key)
        else:
            new_files[key] = original_files[key]
            unchanged.append(key)

    report = ChangeReport(
        granularity=granularity,
        changes=tuple(changes),
        changed_files=tuple(changed),
        unchanged_files=tuple(unchanged),
    )
    return new_files, report
