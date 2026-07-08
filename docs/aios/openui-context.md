# OpenUI — generative UI for The AI OS

**OpenUI** (https://www.openui.com) is the open standard for LLM-generated interfaces.
Instead of replying only in plain text, an agent can emit **OpenUI Lang** — a compact,
token-efficient description of a live interface (charts, tables, forms, dashboards, cards)
that the **openclaw-os** dashboard renders as a real, interactive app.

Every agent in The AI OS (opencode, hermes, openclaw, CrewAI, the AIOS Brain) is
OpenUI-aware via this context. The openclaw-os workspace renders OpenUI Lang natively;
other surfaces fall back to text.

## When to use it
- The answer is naturally visual: metrics, comparisons, tables, timelines, forms, status.
- The user asks for a "dashboard", "chart", "table", "form", or "app".
- A result should persist and update from a prompt rather than being re-typed.

## How to use it
1. Answer in text as usual.
2. When a visual would help, additionally provide an OpenUI Lang block describing the UI
   (components + data). Keep it declarative and minimal.
3. The openclaw-os client renders it; it can refresh with new data and update from a prompt.

## Reference
- OpenUI: https://www.openui.com
- OpenUI Lang is the token-efficient standard used by the openclaw-os workspace
  (`openclaw-os-main/`), which ships the renderer and system prompt.

> This file is mounted into each agent's skill directory by `aios setup`
> (`openui.mount_context: true` in `aios.config.yaml`).
