"""Lossless segmentation of Markdown memory files into logical blocks.

A file is split into an ordered list of :class:`Segment` objects whose raw texts concatenate
back to the exact input (``render(parse(text)) == text``). Content segments (front matter,
headings, paragraphs, list items, fenced code) become memory records; gap segments (blank
lines, a byte-order mark) only carry layout.

This is a deliberately small, line-based segmenter, not a full CommonMark parser. Its contract
is losslessness and stable block boundaries, which is what auditing needs.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class BlockKind(StrEnum):
    FRONT_MATTER = "front_matter"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE = "code"
    FILE = "file"  # whole file as one block (file-level granularity)


_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")
_LIST_ITEM = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])(?:[ \t]+|$)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FRONT_MATTER_OPEN = "---"
_FRONT_MATTER_CLOSE = ("---", "...")
BOM = "﻿"


@dataclass(frozen=True)
class Segment:
    """A slice of a file. ``prefix + body + suffix`` is the exact source text.

    ``prefix`` holds structure that must survive edits (a list marker, heading hashes),
    ``body`` is the editable content, ``suffix`` is the final line ending (may be empty).
    ``kind is None`` marks a layout-only gap.
    """

    kind: BlockKind | None
    prefix: str
    body: str
    suffix: str
    start_line: int  # 1-based
    section: tuple[str, ...] = ()
    block_id: str | None = None

    @property
    def raw(self) -> str:
        return self.prefix + self.body + self.suffix

    @property
    def is_block(self) -> bool:
        return self.kind is not None


@dataclass(frozen=True)
class Document:
    """A parsed memory file."""

    key: str  # file key, e.g. "workspace:MEMORY.md"
    segments: tuple[Segment, ...]

    @property
    def blocks(self) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.is_block)

    def render(self) -> str:
        return "".join(s.raw for s in self.segments)


@dataclass
class _Line:
    text: str  # without line ending
    eol: str  # "\n", "\r\n", "\r" or ""

    @property
    def blank(self) -> bool:
        return not self.text.strip()


_LINE = re.compile(r"([^\r\n]*)(\r\n|\r|\n)|([^\r\n]+)$")


def _split_lines(text: str) -> list[_Line]:
    """Split on ``\\n``, ``\\r\\n`` and ``\\r`` only (unlike ``str.splitlines``, which also
    splits on form feeds, U+2028 etc. and would move block boundaries)."""
    lines: list[_Line] = []
    for m in _LINE.finditer(text):
        if m.group(3) is not None:
            lines.append(_Line(m.group(3), ""))
        else:
            lines.append(_Line(m.group(1), m.group(2)))
    return lines


def _join(lines: list[_Line]) -> tuple[str, str]:
    """Join lines into (body, suffix): the last line ending becomes the suffix."""
    body = "".join(ln.text + ln.eol for ln in lines[:-1]) + lines[-1].text
    return body, lines[-1].eol


def _indent_width(prefix: str) -> int:
    return len(prefix.expandtabs(4))


def _starts_block(line: _Line) -> bool:
    return bool(_HEADING.match(line.text) or _FENCE.match(line.text) or _LIST_ITEM.match(line.text))


def _block_id(key: str, kind: BlockKind, body: str, seen: dict[str, int]) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    digest = hashlib.sha256(f"{kind.value}\0{normalized}".encode()).hexdigest()[:12]
    seen[digest] = seen.get(digest, 0) + 1
    n = seen[digest]
    return f"{key}#{digest}" if n == 1 else f"{key}#{digest}-{n}"


def parse_markdown(key: str, text: str) -> Document:
    """Split ``text`` into segments; ``render`` of the result reproduces ``text`` exactly."""
    segments: list[Segment] = []
    seen: dict[str, int] = {}
    section: list[tuple[int, str]] = []  # (level, title)

    def emit(kind: BlockKind | None, prefix: str, lines: list[_Line], start: int) -> None:
        body, suffix = _join(lines)
        body = body[len(prefix) :]
        block_id = _block_id(key, kind, body, seen) if kind is not None else None
        segments.append(
            Segment(
                kind=kind,
                prefix=prefix,
                body=body,
                suffix=suffix,
                start_line=start,
                section=tuple(title for _, title in section),
                block_id=block_id,
            )
        )

    if text.startswith(BOM):
        segments.append(Segment(None, "", BOM, "", 1))
        text = text[len(BOM) :]

    lines = _split_lines(text)
    i = 0

    # Front matter: only at the very start, only if it is closed.
    if lines and lines[0].text == _FRONT_MATTER_OPEN:
        for j in range(1, len(lines)):
            if lines[j].text in _FRONT_MATTER_CLOSE:
                emit(BlockKind.FRONT_MATTER, "", lines[: j + 1], 1)
                i = j + 1
                break

    while i < len(lines):
        line = lines[i]
        start = i + 1

        if line.blank:
            j = i
            while j < len(lines) and lines[j].blank:
                j += 1
            emit(None, "", lines[i:j], start)
            i = j
            continue

        if m := _FENCE.match(line.text):
            fence = m.group(1)
            close = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
            j = i + 1
            while j < len(lines) and not close.match(lines[j].text):
                j += 1
            j = min(j + 1, len(lines))  # include the closing fence (or run to EOF)
            emit(BlockKind.CODE, "", lines[i:j], start)
            i = j
            continue

        if m := _HEADING.match(line.text):
            level = len(m.group(1))
            title = line.text[m.end() :].strip().rstrip("#").strip()
            section[:] = [(lv, t) for lv, t in section if lv < level]
            emit(BlockKind.HEADING, m.group(0), [line], start)
            section.append((level, title))
            i += 1
            continue

        if m := _LIST_ITEM.match(line.text):
            base = _indent_width(m.group(1))
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.blank:
                    # A blank line continues the item only if indented content follows.
                    k = j
                    while k < len(lines) and lines[k].blank:
                        k += 1
                    if k < len(lines) and _indent_width(_leading_ws(lines[k].text)) > base:
                        j = k
                        continue
                    break
                indent = _indent_width(_leading_ws(nxt.text))
                if indent > base:
                    j += 1  # nested content or nested list item
                    continue
                if _starts_block(nxt):
                    break
                j += 1  # lazy continuation line
            emit(BlockKind.LIST_ITEM, m.group(0), lines[i:j], start)
            i = j
            continue

        j = i + 1
        while j < len(lines) and not lines[j].blank and not _starts_block(lines[j]):
            j += 1
        emit(BlockKind.PARAGRAPH, "", lines[i:j], start)
        i = j

    return Document(key=key, segments=tuple(segments))


def _leading_ws(text: str) -> str:
    return text[: len(text) - len(text.lstrip(" \t"))]


def parse_whole_file(key: str, text: str) -> Document:
    """File-level granularity: the entire file is a single block."""
    if not text:
        return Document(key=key, segments=())
    seg = Segment(
        kind=BlockKind.FILE,
        prefix="",
        body=text,
        suffix="",
        start_line=1,
        block_id=_block_id(key, BlockKind.FILE, text, {}),
    )
    return Document(key=key, segments=(seg,))


@dataclass(frozen=True)
class Edit:
    """Edits to apply to a document, by block ID."""

    remove: frozenset[str] = frozenset()
    replace: Mapping[str, str] = field(default_factory=dict)  # block_id -> new body


def render_edited(doc: Document, edit: Edit) -> str:
    """Render ``doc`` with blocks removed or their bodies replaced.

    Prefixes (list markers, heading hashes) and line endings of replaced blocks are kept.
    When a removal leaves two layout gaps next to each other, the second one is dropped so no
    extra blank lines accumulate. With an empty edit this equals ``doc.render()``.
    """
    known = {s.block_id for s in doc.blocks}
    unknown = (set(edit.remove) | set(edit.replace)) - known
    if unknown:
        raise KeyError(f"unknown block IDs for {doc.key}: {', '.join(sorted(unknown))}")

    out: list[Segment] = []
    removed_last = False
    for seg in doc.segments:
        if seg.block_id in edit.remove:
            removed_last = True
            continue
        if seg.kind is None and removed_last and out and out[-1].kind is None:
            removed_last = False
            continue
        removed_last = False
        if seg.block_id in edit.replace:
            seg = Segment(
                seg.kind,
                seg.prefix,
                edit.replace[seg.block_id],
                seg.suffix,
                seg.start_line,
                seg.section,
                seg.block_id,
            )
        out.append(seg)
    return "".join(s.raw for s in out)


def iter_blocks(docs: Iterable[Document]) -> Iterable[tuple[Document, int, Segment]]:
    """Yield ``(document, ordinal, block)`` for every content block, ordinal 0-based per file."""
    for doc in docs:
        for n, block in enumerate(doc.blocks):
            yield doc, n, block
