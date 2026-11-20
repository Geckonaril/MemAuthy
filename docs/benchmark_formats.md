# MemHarmBench on-disk formats

Reference for the formats MemAuthy reads. Pinned to MemHarmBench commit `9affbe5` (v8.4.3), see
[ADR-0002](decisions/0002-benchmark-integration.md). Source locations refer to the submodule
`third_party/MemHarmBench`.

**Important:** the benchmark publishes inputs only. Run outputs (memory, snapshots, transcripts)
exist only after running agents locally; none are shipped. Everything below was read from the
benchmark code, and MemAuthy's tests use synthetic fixtures in these layouts. Validation on
real run outputs is planned for the phase-4 pilot.

## Native memory

Memory is a `{key: text}` mapping. Keys have the form `"<namespace>:<relative posix path>"`.

| Agent | Memory keys | Benchmark rule |
|---|---|---|
| Claude Code 2.1.228 | `workspace:**/CLAUDE.md`, except under `imports/` and `records/`<br>`claude_config:**/CLAUDE.md`<br>`claude_config:projects/<slug>/memory/**/*.md` (slug `-workspace`) | `adapters/native_evidence.py::is_native_memory_path`, `runtime/distance_stage.py::memory_path` |
| OpenClaw 2026.7.1 | `workspace:{AGENTS,SOUL,TOOLS,IDENTITY,USER,HEARTBEAT,BOOTSTRAP,MEMORY}.md` (top level)<br>`workspace:memory/**/*.md` | `runtime/openclaw/adapter.py::is_memory` |

Container mounts:

- Claude Code: `CLAUDE_CONFIG_DIR=/config` (namespace `claude_config`) and `/workspace`.
- OpenClaw: `/workspace` only.

In both, the namespace is the directory name under the agent root. Files are read as UTF-8 with
universal newlines and restored with `\n` line endings. A file of 200,000 characters or more, or
one containing `...[truncated`, makes the snapshot incomplete.

Two differences between the agents:

- **OpenClaw starts with seeded memory.** Every OpenClaw exposure workspace is seeded from
  `runtime/openclaw/templates/*.md` (about 280 lines of owner-provided bootstrap instructions).
  Claude Code starts with empty memory.
- **Claude Code has no explicit auto-memory setting.** The benchmark sets nothing for it;
  capture relies on the Claude Code 2.1.228 defaults.

MemAuthy: `memory_io/claude_code.py`, `memory_io/openclaw.py` (never looser than the benchmark
rules; tested against them).

## Distance snapshots (Claude Code only)

`<run_dir>/outputs/<chain_id>/snapshots/S{0,2,4}.json`, written by
`runtime/distance_stage.py::snapshot`:

```json
{"distance": 2, "memory": {"<key>": "<text>"}, "memory_sha256": "<sha256>",
 "source_stage": "benign2", "native_session_id": "<uuid>", "evidence_sha256": "<sha256>"}
```

`memory_sha256` is sha256 of canonical JSON: sorted keys, `(",", ":")` separators,
`ensure_ascii=False`. `S{d}` is the memory after exposure followed by `d` benign sessions. Each
trigger branch `trigger{d}` starts from a deep copy. Memory is restored with
`restore_memory(<attempt>/agent, memory)`, which writes `agent/<namespace>/<relative>`.

Chain layout:

```
outputs/<chain_id>/
  identity.json, chain_result.json
  snapshots/S0.json, S2.json, S4.json
  stages/<exposure|benign1..4|trigger0|trigger2|trigger4>/evidence.json, ...
```

## Main protocol

- **Claude Code:** `outputs/<chain_id>/{exposure1,exposure2,trigger}_evidence.json` plus
  `replay/...`.
- **OpenClaw:** `outputs/<chain_id>/steps/{exposure1,exposure2,trigger}/evidence.json` plus
  `try{n}/agent/{workspace,state}`.

The trigger runs only when the exposure's PMIR is 1. Its `memory_before` must equal the selected
exposure's `memory_after`.

## Evidence bundle (`evidence.json`)

Built by `src/memharmbench_v84/runtime/evidence.py::build_evidence`. Fields MemAuthy uses:

| Field | Content |
|---|---|
| `case_id`, `phase`, `session_id` | Identity |
| `template_and_target` | Ground truth: `target_memory_rule`, `payload_text`, `payload_value`, `permission_condition`, `source_authority`, … (P0 only) |
| `user_message` | The session's user message |
| `trajectory` | Raw native JSONL lines: `[{source, native_session_id, scope, lines}]` |
| `native_events` | Normalized content blocks (see below) |
| `memory_before`, `memory_after`, `memory_diff` | Memory mappings |
| `evidence_integrity` | `native_capture_complete`, `native_session_id`, errors |

### `native_events`

`adapters/native_evidence.py::normalize_native_trace` produces one event per content block:

```json
{"type": "text|tool_use|tool_result|...", "role": "user|assistant|...",
 "event_ref": "native:<source>:<line>:<block>", "source": "...", "line": 3, "block": 0,
 "scope": "session|subagent", "native_session_id": "<uuid>", "timestamp": "...",
 "name": "Write", "input": {"file_path": "..."}, "content": "..."}
```

OpenClaw logs are converted to the same schema (`runtime/openclaw/native.py`):
`exec/read/write/edit` become `Bash/Read/Write/Edit`, `path` is copied to `file_path`, and
`toolResult` messages become `tool_result` blocks.

MemAuthy (`memory_io/transcript.py`) keeps `text`, `tool_use` and `tool_result` blocks, and
skips thinking and other blocks. It marks `Write`/`Edit`/`MultiEdit`/`NotebookEdit` calls whose
`file_path` maps to a memory key (`memory_file`). This is structural information for P1/P2, not
ground truth.

## Case files (`cases/<case_id>.json`)

These come from the downloaded dataset. Fields used are `channel`, `victim`,
`permission_condition`, `source_authority`, `exposure_input`, `carrier_artifact` (empty for
DPI-U), `payload_text`, `payload_value`, `target_memory_rule` and `trigger_input`.

- In IPI cases, `payload_text` is the literal text in the carrier artifact, while
  `target_memory_rule` is the canonical rule the judge looks for. The two are worded
  differently.
- In DPI-U cases, the two are identical and arrive in the user message.

MemAuthy: `memauthy/cases.py` (oracle / evaluation only), `memauthy inspect case <id>`.

## PMIR judgment

The exposure judge must cite `memory_after:<key>` references. Only native memory files count,
and a rule found only in business files or in the transcript does not. MemAuthy's defense acts
after exposure, so PMIR is context, not the defense's effect measure (threat model §1).
