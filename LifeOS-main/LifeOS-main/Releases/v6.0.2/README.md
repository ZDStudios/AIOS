<div align="center">

# LifeOS 6.0.2

**.md-first AI-native install.**

</div>

---

LifeOS 6.0.2 is skill-only distribution with an AI-native, `.md`-first install.

## Install

Give it to your AI:

> Read https://ourlifeos.ai/install and install LifeOS for me.

Terminal shortcut (Claude Code, macOS/Linux):

```bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
```

## What's in it

- The whole system ships as one self-contained `LifeOS/` skill — orchestrator plus the full install payload.
- `ourlifeos.ai/install` serves the AI-paste install doc; the shipped `install.sh` pins v6.0.2 and points at `danielmiessler/LifeOS`.
- Security-clean by construction: 15/15 release gates plus emit-time contract, staleness, and payload gates, and a cross-vendor audit before publish.

---

See the [main README](../../README.md) for more.
