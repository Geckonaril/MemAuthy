# MemAuthy

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

## License

[MIT](LICENSE)
