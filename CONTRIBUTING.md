# Contributing

## Workflow

Every change follows **issue → branch → pull request → squash merge**. Nothing is pushed
directly to `main`.

1. **Issue.** Open (or pick) an issue that describes the change and its "done when" criteria.
   Assign a `type:` label, any `area:` labels and the roadmap milestone.
2. **Branch.** Branch from an up-to-date `main`:
   `<type>/<issue-number>-<short-slug>`, e.g. `feat/4-core-data-model`, `docs/7-threat-model`.
   Types: `feat`, `fix`, `docs`, `chore`, `ci`, `test`, `refactor`, `exp` (experiment).
3. **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/):
   `<type>(<optional scope>): <summary>`, e.g. `feat(policy): add quarantine policy`.
   Reference the issue in the body (`Refs #4`).
4. **Pull request.** Fill in the PR template. The description must contain `Closes #<n>`.
   CI must be green.
5. **Merge.** Squash merge, then delete the branch. The squash commit title follows
   Conventional Commits.

## Local checks

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Tests must pass **without any API key**. Tests that need the MemHarmBench dataset are marked
`@pytest.mark.benchmark` and skip automatically when it is absent.

## Rules

- **MemHarmBench is never modified.** It is a pinned submodule under `third_party/`. Integration
  code lives in `src/memauthy/memory_io/` (see [ADR-0002](docs/decisions/0002-benchmark-integration.md)).
- **Original attack cases are never modified.** New data (control set, adaptive variants) lives
  under `data/` and is versioned separately.
- **No paid API calls without explicit approval.** Anything that calls a paid model provider
  must show an estimated call and token count first and be approved by the maintainer
  (label `cost: paid-api`). See [ADR-0005](docs/decisions/0005-safety-and-cost.md).
- **Secrets** come only from environment variables. `.env` is git-ignored; configs reference
  variable *names*, never values.
- **Synthetic data only.** No real personal data in fixtures, configs or datasets.
- **Isolation.** Agent experiments run in Docker. Attack content must never be written to a
  real agent memory or a developer's own agent configuration.
- **Reproducibility.** Every experiment run writes a manifest and a cost log
  (see [ADR-0004](docs/decisions/0004-config-and-reproducibility.md)).
- **Failures are data.** Technical failures, non-evaluable and missing observations are reported
  in separate categories and never silently dropped.

## Architecture decisions

Significant design decisions are recorded as ADRs in [`docs/decisions/`](docs/decisions/).
Copy [`0000-template.md`](docs/decisions/0000-template.md), take the next number, and add it to
the index in that folder's README. Superseded ADRs are kept and marked as such.
