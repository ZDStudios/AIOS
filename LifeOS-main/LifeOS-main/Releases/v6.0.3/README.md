<div align="center">

# LifeOS 6.0.3

**Comprehensive AI-native install — and the constitution wires itself.**

</div>

---

LifeOS 6.0.3 makes the install doc comprehensive and gets the constitutional layer loading on its own.

## Install

Give it to your AI:

> Read https://ourlifeos.ai/install and install LifeOS for me.

Terminal shortcut (Claude Code, macOS/Linux):

```bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
```

## What's new

- **Comprehensive component menu** — `INSTALL.md` now lays out the full two-tier model: Core (skill + ~50-skill library + runtime + system prompt) plus à-la-carte enhancements (hooks, statusline, tooltips, spinner verbs, agents, Pulse, background jobs). Install all or pick a subset.
- **The launch command** — a new install step wires a `lifeos` shell alias that launches Claude with `--append-system-prompt-file LIFEOS_SYSTEM_PROMPT.md`, so the constitutional layer actually loads. Plain `claude` stays vanilla.
- **One source for the install doc** — `ourlifeos.ai/install` renders the same canonical `INSTALL.md` as a clean page for humans and raw markdown for AIs, updated in one place.
- Security-clean: 15/15 release gates plus emit-time contract, staleness, and payload gates, and an independent leak scan.

---

See the [main README](../../README.md) for more.
