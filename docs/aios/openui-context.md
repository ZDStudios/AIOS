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

## How to use it (in the AIOS Hub)
1. Answer in text as usual.
2. When a visual helps, emit a fenced **```ui** block containing a **self-contained HTML document**
   (inline CSS/JS, no external URLs). The AIOS Hub renders it **live and interactive** inside the chat,
   in a sandboxed iframe, using the page theme via CSS vars (`var(--accent)`, `var(--bg)`, `var(--text)`).
3. To pin a widget to the shared **Canvas** (visible to everyone, editable by any agent), call
   `POST http://<hub>/api/ui` with `{"op":"add","title":"…","by":"<agent>","html":"…"}`.
   CrewAI has a `build_dashboard_ui` tool for exactly this.
4. The **openclaw-os** client also renders OpenUI Lang natively for its own workspace.

Example:
~~~ui
<h3>Revenue</h3>
<div style="background:var(--accent);height:40px;width:70%;border-radius:6px"></div>
<button onclick="this.textContent='refreshed'">Refresh</button>
~~~

## Reference
- OpenUI: https://www.openui.com
- OpenUI Lang is the token-efficient standard used by the openclaw-os workspace
  (`openclaw-os-main/`), which ships the renderer and system prompt.

> This file is mounted into each agent's skill directory by `aios setup`
> (`openui.mount_context: true` in `aios.config.yaml`).
