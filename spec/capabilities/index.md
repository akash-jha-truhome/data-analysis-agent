# Capabilities Index

> **Boilerplate status:** The spec-writer sub-agent creates one file per capability in this directory. Each file describes exactly one discrete thing the agent can do.

---

## What Is a Capability?

A capability is a single, discrete action or behavior the agent performs. Examples:
- "Search the web for companies matching criteria X"
- "Draft a personalized email given a lead profile"
- "Send a Slack notification when a threshold is crossed"

## Capabilities in This Project

### Phase 1 — core (real)

| Capability | File |
|-----------|------|
| Upload Dataset | [upload-dataset.md](upload-dataset.md) |
| Answer Question (code-execution loop) | [answer-question.md](answer-question.md) |
| Auto Chart + Table | [auto-chart.md](auto-chart.md) |
| Audit Trail | [audit-trail.md](audit-trail.md) |

### Deferred (labelled stubs in Phase 1 → wired later)

| Capability | Phase | Notes |
|-----------|-------|-------|
| Session memory (multi-turn) | 2 | Conversation history + persistent loaded dataset for follow-ups |
| Follow-up suggestions | 2 | 2–3 suggested questions after each answer |
| Data-quality flags | 2 | Missing values / duplicates / outliers noticed while answering |
| Run-history browser | 2 | Past queries + running session token total |
| Multi-file analysis | 3 | Join/compare multiple loaded files |
| Excel multi-sheet | 3 | Load + reference multiple sheets in one workbook |
| Clarification gate | 3 | Ask one clarifying question when genuinely ambiguous |

> Deferred capabilities get their own `<name>.md` files when their phase is built.

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer sub-agent will:
1. Create a new file in this directory (`<name>.md`, no number prefix)
2. Update this index
3. Flag any dependencies on existing capabilities
4. Self-review that it fits the architecture and data model before returning

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Error cases** (what can go wrong and how it's handled)
- **Success criteria** (how we test it)
