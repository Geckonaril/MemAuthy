# MemAuthy

[![CI](https://github.com/Geckonaril/MemAuthy/actions/workflows/ci.yml/badge.svg)](https://github.com/Geckonaril/MemAuthy/actions/workflows/ci.yml)

Provenance- and authority-aware memory auditing against cross-session prompt injection
in persistent-memory AI agents.

Persistent-memory LLM agents (e.g. Claude Code, OpenClaw) can write instructions that came from
untrusted sources (web pages, documents, tool output) into long-term memory. Those "rules" can
steer the agent's decisions in later sessions, even after the malicious content is gone.
MemAuthy is an agent- and model-independent layer that audits memory records between sessions,
identifies behavioral rules, assesses their provenance and authority, and blocks, quarantines or
downgrades unauthorized ones before they reach the next session.

Experiments build on [MemHarmBench](https://github.com/Kirito14IT/MemHarmBench) (MIT).

> **Status:** early development. Architecture and experiment setup are in progress.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in `.python-version` (3.11+ supported).

```bash
git clone --recurse-submodules https://github.com/Geckonaril/MemAuthy.git
cd MemAuthy                  # existing clone: git submodule update --init
uv sync                      # create .venv and install dependencies (incl. MemHarmBench)
uv run pytest -q             # tests (no API key needed)
uv run ruff check .          # lint
uv run ruff format --check . # format check
uv run memauthy --version    # or: uv run python -m memauthy --version
```

### Benchmark

[MemHarmBench](https://github.com/Kirito14IT/MemHarmBench) is a pinned git submodule at
`third_party/MemHarmBench` (commit `9affbe5`, dataset revision `2b4c2b7`; see
[ADR-0002](docs/decisions/0002-benchmark-integration.md)). Its inputs come from a public
Hugging Face dataset and are verified offline; no API key or model call is involved.

```bash
uv run memauthy bench info         # pinned commit, dataset revision, data location
uv run memauthy bench download     # fetch and verify the pinned dataset
uv run memauthy bench validate     # offline validation (288 cases)
uv run memauthy bench catalog      # list cases
uv run pytest -q -m benchmark      # tests that need the dataset
```

Set `MEMHARMBENCH_DATA_ROOT` to keep the dataset outside the submodule.

## Contributing and design decisions

See [CONTRIBUTING.md](CONTRIBUTING.md) for the issue → branch → PR workflow and project rules,
and [docs/decisions/](docs/decisions/) for architecture decision records.

## License

[MIT](LICENSE)
