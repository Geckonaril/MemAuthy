# MemAuthy

[![CI](https://github.com/Geckonaril/MemAuthy/actions/workflows/ci.yml/badge.svg)](https://github.com/Geckonaril/MemAuthy/actions/workflows/ci.yml)

Provenance- and authority-aware memory auditing against cross-session prompt injection
in persistent-memory AI agents.

Persistent-memory LLM agents (e.g. Claude Code, OpenClaw) can write instructions that came from
untrusted sources (web pages, documents, tool output) into long-term memory. Those "rules" can
steer the agent's decisions in later sessions, even after the malicious content is gone and even
when the poisoned session itself looked normal.

MemAuthy is an agent- and model-independent layer that audits memory records **between
sessions**. It splits memory into records, decides which ones act as behavioral rules, estimates
where each one came from and whether that source had the authority to set it, and blocks,
quarantines or downgrades unauthorized records before the next session starts.

Experiments build on [MemHarmBench](https://github.com/Kirito14IT/MemHarmBench) (MIT), which is
used unmodified as a pinned submodule.

> **Status (November 2026):** the defense, the baselines and the offline evaluation are
> complete. The benchmark integration has been rehearsed end to end with local models at zero
> API cost. Next: a hard budget guard, preregistration, then one confirmatory run against the
> benchmark's reference models. All results below are **exploratory** (synthetic inputs, not
> yet preregistered).

## Approach

### Defense conditions

| Code | Condition | Role |
|---|---|---|
| D0 | No defense | Lower reference |
| D1 | Wipe memory | Upper bound for security, lower bound for utility |
| D2 | Keyword / regex filter | Simple filtering baseline |
| D3 | Local LLM memory sanitizer (content only, A-MemGuard-like) | Strong content-based baseline |
| **D4** | **Provenance- and authority-aware audit** (this work) | Proposed method |

D4 policies: `block` (remove), `quarantine` (keep aside, flag) and `downgrade` (rewrite a rule
into a non-instructional note). Records whose source is uncertain are kept, flagged and reported
separately.

### Provenance levels

D4 is evaluated at four levels of source information, which measures how much provenance
contributes to security and avoids evaluating only against oracle labels.

| Code | Name | Source information |
|---|---|---|
| P0 | Oracle | True origin known to the benchmark (upper bound, comparison only) |
| P1 | Structural | Message roles and tool-call boundaries in the agent transcript |
| P2 | Transcript taint | Lexical match (n-grams, rare tokens) plus temporal proximity between a memory write and earlier untrusted tool output |
| P3 | None | Memory content only |

With P2, D4 is **provenance-first**: any block derived from untrusted input is audited regardless
of how it is phrased, which closes the "rule written as a fact" blind spot found in phase 2
([ADR-0012](docs/decisions/0012-p2-taint-and-provenance-first.md)).

The threat model is in [docs/threat_model.md](docs/threat_model.md). The primary analysis covers
the 192 indirect (IPI) cases; the 96 direct cases, where the rule arrives through the trusted
user channel, are a separate boundary analysis.

## Results so far (exploratory, offline)

All runs are local, deterministic and cost nothing in API calls. Rates come with Wilson 95% CIs
in each run's `summary.md` under [results/](results/).

**Detection on synthetic snapshots of the 192 IPI cases** (block level):

| Condition | Attack recall | False-block rate | User rules preserved |
|---|---|---|---|
| D2 | 0.750 | 0.060 | 0.500 |
| D3 (llama3.1:8b, subset) | 0.688 | 0.033 | 1.000 |
| D4@P1 | 0.667 | 0.000 | 1.000 |
| **D4@P2** | **1.000** | **0.000** | **1.000** |
| D4@P0 (oracle) | 1.000 | 0.000 | 1.000 |

**Legitimate control set v0.1** (120 items: authorized user and owner rules next to look-alike
injected rules):

- D4@P2 enforces every unauthorized item (recall 1.000). Its false-block rate is 0.333, and all
  of it comes from two categories: harmless facts learned from untrusted inputs, and rules the
  user delegated to a document ("follow this file's conventions"). This is the explicit cost of
  provenance-first. `downgrade` is the planned mitigation.
- D2 reaches recall 0.333 at a false-block rate of 0.107. D3 reaches recall 0.178 at 0.027.

**Adaptive attacker v0.1** (24 hand-written variants across six strategies, detection only):

- D4@P2 neutralizes 0.917 of samples. The remaining gap is the `split` strategy (one rule spread
  across harmless-looking notes).
- D3 neutralizes 0.488, D4@P1 0.375 and D2 0.302.
- The variant set is frozen. Fixes are evaluated on a new variant set, never tuned on v0.1.

**What these numbers do not show yet:** whether a defended memory actually stops the agent from
adopting the attacker's decision in the next session (C-ASR). That needs the trigger experiments
below.

## Benchmark integration

Each MemHarmBench chain runs as a **matched-arms** design
([ADR-0015](docs/decisions/0015-defense-arms-in-benchmark-runs.md)): one exposure session, then
the defense is applied to its memory and one fresh trigger session runs per defense arm. Every
arm starts from the same exposure, task and starting memory, so arms are compared pairwise
(exact McNemar). The benchmark code is not modified; the defense is injected through its runtime
hooks.

A full rehearsal with local Ollama models standing in for the reference models
([ADR-0016](docs/decisions/0016-local-rehearsal.md)) ran the whole Docker chain for both Claude
Code and OpenClaw at zero cost. It surfaced and fixed several plumbing issues (Windows bind-mount
path length, stale gateway containers, triggers when nothing was stored) and produced the token
profile used for the budget estimate. Rehearsal outcomes are never analysed.

## Roadmap

| Phase | Content | Status |
|---|---|---|
| 0 | Repository, CI, pinned benchmark, offline validation | Done |
| 1 | Threat model, memory adapters, snapshot inspection | Done |
| 2 | Rule classifier, P0/P1/P3, D0–D2, offline detection | Done |
| 3 | P2 transcript taint, D3, control set v0.1, adaptive variants v0.1 | Done |
| 4 | Defense hook in benchmark runs, local rehearsal | Done |
| 4 | Budget estimator and hard spending cap, preregistration and power analysis | Next |
| 5 | One confirmatory matched-trigger run with the reference models | Planned |
| 6 | Human labelling (Cohen's kappa), statistics, Pareto and cost analysis | Planned |
| 7 | Preprint, released code, dataset and raw results | Planned |

No paid API call is made without an explicit cost estimate and approval
([ADR-0005](docs/decisions/0005-safety-and-cost.md)).

## Repository layout

```
src/memauthy/
  memory_io/    memory and transcript adapters (Claude Code, OpenClaw), block-level records
  rules/        rule / information / preference classifier
  provenance/   P0–P3 source extractors
  policy/       authority decision and block / quarantine / downgrade
  defenses/     D0–D4 behind one MemoryDefense interface
  benchrun/     matched defense arms inside MemHarmBench runs
  eval/         metrics, manifests, cost logging
data/
  control/      legitimate control set (versioned)
  adaptive/     adaptive attack variants (versioned)
configs/        experiment configs (YAML)
experiments/    run scripts
results/        manifests and summaries (raw outputs are not committed)
docs/           threat model, preregistration draft, decision records
third_party/MemHarmBench   pinned submodule
```

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

### Reproducing the offline results

```bash
uv run python experiments/offline_detection.py --config configs/offline-detection-v0.2.yaml
uv run python experiments/control_evaluation.py --config configs/control-v0.2.yaml
uv run python experiments/adaptive_evaluation.py --config configs/adaptive-v0.1.yaml
```

The D3 configs (`configs/d3-*.yaml`) also need a local [Ollama](https://ollama.com/) with
`llama3.1:8b`. Each run writes `results/<run_id>/` with a manifest (git commit, benchmark commit,
config hash, seed, case IDs), a cost log and summaries.

## Contributing and design decisions

See [CONTRIBUTING.md](CONTRIBUTING.md) for the issue → branch → PR workflow and project rules,
and [docs/decisions/](docs/decisions/) for architecture decision records.

## License

[MIT](LICENSE)
