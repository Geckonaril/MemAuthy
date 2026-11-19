# ADR-0006: Block-level memory records

- **Status:** Accepted
- **Date:** 2026-11-20

## Context
Both target agents keep persistent memory as Markdown files. In MemHarmBench, memory is a
`{file_key: text}` mapping:

- Claude Code: `workspace:CLAUDE.md` and
  `claude_config:projects/-workspace/memory/*.md` (`MEMORY.md` and topic files).
- OpenClaw: `workspace:MEMORY.md`, `workspace:memory/YYYY-MM-DD.md` and the bootstrap files.

A single file often mixes a user preference, a project note and, after exposure, an injected
rule. If one file were one record, blocking the rule would also block the legitimate
preferences next to it.

## Decision
- **One `MemoryRecord` = one logical Markdown block**: front matter, heading, paragraph, list
  item (with its continuation lines and nested items), or fenced code block. Blank lines and a
  byte-order mark are layout-only gap segments, not records.
- **Lossless.** Each segment stores `prefix + body + suffix`, which together are the exact
  source text. Parsing and rendering without edits is byte-identical, including CRLF/CR line
  endings, BOM, a missing trailing newline and blank lines. Lines are split only on `\n`,
  `\r\n` and `\r`.
- **Structure is kept out of the content.** List markers and heading hashes are the `prefix`,
  so the record content is the text itself, and a replaced block keeps its marker and line
  ending.
- **Stable IDs.** `"<file_key>#<sha256(kind, normalized body)[:12]>"`, with `-2`, `-3`, … added
  for identical blocks in the same file. An ID does not change when other blocks are added or
  removed, or when only the line endings change.
- **Originals are never modified.** `render_memory_files(original_files, audited_snapshot)`
  returns a new mapping and a `ChangeReport`. The report lists every removed, quarantined or
  replaced block with its before and after text.
- **Minimal intervention.** Only the affected block is removed or rewritten. When a removal
  would leave two adjacent blank-line gaps, one of them is dropped. Every other byte is
  preserved.
- **Configurable granularity.** `Granularity.BLOCK` is the default. `Granularity.FILE` treats
  each file as a single record, so block-level and file-level defenses can be compared on the
  same data.
- The segmenter is a small line-based parser, not a full CommonMark implementation.
  Losslessness does not depend on it parsing Markdown correctly. Block boundaries only need to
  be sensible for agent-written memory.

## Alternatives considered
- **File-level records only:** simpler, but they cause false blocks of legitimate preferences.
  Kept as an option for comparison.
- **Full Markdown AST (e.g. markdown-it):** more faithful parsing, but rendering from an AST is
  not byte-lossless and adds a dependency.
- **Ordinal IDs (`file#3`):** shift when blocks are inserted or removed, so they cannot be
  compared across snapshots or after edits.

## Limitations
- **Distributed injection.** A rule split across several blocks, each harmless on its own, may
  not be detected by a per-block audit. This is one of the adaptive attack variants and is
  measured, not assumed away.
- **Duplicate blocks.** If an identical block is inserted *before* an existing duplicate, the
  `-n` suffixes of the duplicates shift.
- **Edited blocks get new IDs.** An edited block hashes to a new ID, so tracking a block across
  agent edits needs content similarity (planned for P2), not ID equality.
- **Approximate boundaries.** Unusual constructs (HTML blocks, tables, setext headings) are
  grouped as paragraphs. That is lossless, but coarser.

## Consequences
- Agent adapters (#8, #9) only decide which files count as memory and where they come from.
  Mapping files to and from records is shared code.
- Detection metrics are computed per block. The ground-truth target rule must be matched to
  the block that contains it.
