# ADR-0005: Safety and cost rules

- **Status:** Accepted
- **Date:** 2026-11-19

## Context
The project has no dedicated compute budget and handles prompt-injection payloads that target
real agent products.

## Decision
- **Cost tiers.** Every experiment is assigned a tier: 0 offline (no model calls), 1 local or
  free model (Ollama / vLLM / free notebooks), 2 paid API. Everything runs at tier 0 first.
- **Paid calls need explicit approval.** Before any code that calls a paid API is run, the
  estimated number of calls and tokens is shown and the maintainer approves it. Pilots run on
  1–5 cases first; real cost is measured before scaling.
- **Secrets** are read only from environment variables; configs store variable names.
  `.env` is git-ignored and `.env.example` documents the expected names.
- **Isolation.** Agent sessions run inside Docker containers. Attack content is never written to
  a real agent memory on the host or to a developer's own agent configuration.
- **Synthetic data only.** No real personal data anywhere.
- **Responsible disclosure.** A new, serious vulnerability in a real product is reported to the
  vendor's security channel before publication. Published adaptive variants stay limited to
  synthetic research contexts.

## Alternatives considered
- **Running agents on the host** — faster to set up, but risks contaminating real memory.

## Consequences
- Tier-2 work is gated on the maintainer and labelled `cost: paid-api`.
- Experiment issues use a template with a cost estimate and an approval checkbox.
