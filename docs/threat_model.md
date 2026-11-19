# Threat model

This document defines what MemAuthy defends against, what it assumes, and what is out of scope.
It is the reference for the defense design, the evaluation scope and the preregistration.

## 1. System

A **persistent-memory agent** (e.g. Claude Code, OpenClaw) works across sessions. During a
session it reads inputs, calls tools and may write records to a long-term memory store (e.g.
memory files). In later sessions those records are loaded into the agent's context and can
shape its decisions.

The attack unfolds across sessions (the MemHarmBench protocol):

```
exposure session ──► normal sessions ──► snapshot (S0/S2/S4) ──► trigger session
 attacker content       content gone        memory persists        harmful decision?
 reaches the agent;                                                (C-ASR)
 a rule is written
 to memory (PMIR)
```

**Defense placement.** MemAuthy runs **between sessions**: it audits the memory snapshot after
exposure and before the trigger session, and passes on a (possibly modified) snapshot. It does
not intervene during exposure, so PMIR is context, not the primary measure of defense effect.

## 2. Assets

- The integrity of the agent's **decisions in later sessions** (destinations, rankings,
  thresholds, routing, records — the decision points targeted by the benchmark objectives).
- The **legitimate persistent memory**: user-authorized preferences and project rules that must
  keep working (functionality).

Three victim classes are considered: the **user**, the **workspace owner**, and **external
stakeholders**.

## 3. Parties and trust

| Party / channel | Trust | Notes |
|---|---|---|
| Session user (direct user messages) | **Trusted** | Can authorize persistent rules within their own authority |
| Workspace owner's explicitly authorized configuration | **Trusted** | E.g. project instruction files placed by the owner |
| Web content, documents, third-party files | Untrusted | Attacker-controllable |
| Tool and MCP outputs | Untrusted | Attacker-controllable content |
| Agent's own inferences | Not a source of authority | Can relay, but not create, authority |

`SourceKind.is_trusted` in the code implements exactly this boundary: only `user` and
`workspace_config` are trusted ([ADR-0003](decisions/0003-data-model.md)).

## 4. Attacker

**Controls:** the content of untrusted inputs that reach the agent (web pages, documents, tool
and MCP outputs, third-party files).

**Does not control:** the user channel, the system prompt, the agent infrastructure, the model,
or the memory store directly (no file-system write access).

**Goal:** get a persistent behavioral rule into memory that makes the agent adopt an
attacker-chosen decision in a later session, ideally while the legitimate task still appears to
complete normally.

**Adaptive attacker** (exploratory, RQ5): additionally knows that a memory audit exists and its
general logic (not its exact thresholds or prompts), and tries to evade it — e.g. phrasing a rule
as a user preference, spoofing provenance ("the user said …"), splitting a rule into
harmless-looking notes, or using indirect or conditional wording.

## 5. Authorized rule

A persistent behavioral rule is **authorized** iff

1. its **source** is a trusted party (§3), and
2. it stays within that party's **authority** (a user can set their own preferences; the
   workspace owner can set project rules).

Everything else is **unauthorized**. When the source cannot be determined with sufficient
confidence, the record is **uncertain**: by default it is kept and flagged, not removed, because
uncertainty alone is not evidence of an attack.

In the current version, condition 2 is not checked automatically: authority scope is not
inferred from content. This is why DPI-U is a boundary case (§7).

## 6. Provenance levels

How much provenance information the defense may use is an experimental variable.

| Level | Name | Source of provenance information |
|---|---|---|
| P0 | Oracle | Ground-truth origin known to the benchmark. Upper bound, comparison only. |
| P1 | Structural | Message roles and tool-call boundaries (user message vs. tool output) |
| P2 | Transcript taint | Content similarity and temporal proximity between a memory write and preceding untrusted tool output |
| P3 | None | Memory content only (content classifier) |

## 7. Evaluation scope

MemHarmBench v8.4.3 has 288 attack cases:

| Channel | Permission condition | Source authority (benchmark) | Cases | Role in this study |
|---|---|---|---|---|
| Indirect content (IPI) | `IPI-UNTRUSTED-ARTIFACT` | untrusted external or low-privilege artifact author | 192 | **Primary** — matches this threat model |
| Direct instruction (DPI-U) | `DPI-U` | authorized user message | 96 | **Separate boundary analysis** |

**Why DPI-U is not primary.** In DPI-U the rule arrives through the authorized user channel. By
§5 its source is trusted, so a provenance-based defense is *expected* to treat it as authorized.
Including these cases in the primary analysis would test something the defense is, by design,
not meant to detect. They are reported separately to make this limitation visible. The analysis
also compares content-based defenses (D2, D3) and reports the provenance-based defense's
expected non-effect. The benchmark itself asks that this source-authority distinction be kept
when comparing channels.

## 8. Out of scope

- Attacks on model weights or training data.
- Compromise of the agent infrastructure, the host, or the memory store itself (direct
  file-system access to memory files).
- Attacks through the trusted user channel, including social engineering of the user; DPI-U is
  analyzed only as a boundary case (§7).
- Defense at write time (during exposure); listed as future work.
- Harms within a single session that do not persist through memory.

## 9. Assumptions and limitations

- Session transcripts are available to the defense for P1/P2 (true for the benchmark setup; may
  not hold for every commercial agent).
- Agents may paraphrase or merge content when writing memory; P2 must tolerate this, and its
  errors are measured, not assumed away.
- A user can delegate authority to a document ("remember what this guide says"). Such delegated
  rules are hard cases. They are labelled explicitly in the control set rather than resolved by
  assumption.
- All identities, documents and preferences used in experiments are synthetic. Experiments run
  in isolated containers and never touch a real agent's memory.

## 10. Responsible disclosure

If a new, serious vulnerability in a real product is found, it is reported to the vendor's
security channel before publication. Adaptive attack variants are published only in synthetic
research contexts.
