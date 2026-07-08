#!/usr/bin/env bun
/**
 * GenerateReleasesPage.ts — single source of truth for the public releases index.
 *
 * Renders `Releases/README.md` from `Releases/releases.json` and ASSERTS that the
 * manifest lists exactly the version directories present under `Releases/`. If a
 * release directory exists with no manifest entry (or a manifest entry has no
 * directory), it fails — so the rendered text can NEVER drift from the folders
 * GitHub shows above it. That drift is the exact bug this tool exists to kill.
 *
 * Usage:
 *   bun Tools/GenerateReleasesPage.ts            # regenerate Releases/README.md
 *   bun Tools/GenerateReleasesPage.ts --check    # verify only; exit 1 on drift (release gate)
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
const RELEASES_DIR = join(REPO, "Releases");
const MANIFEST = join(RELEASES_DIR, "releases.json");
const PAGE = join(RELEASES_DIR, "README.md");

type Release = {
  dir: string;
  version: string;
  date?: string;
  title: string;
  summary: string;
  bullets?: string[];
  era: "current" | "legacy";
};

const versionKey = (v: string): number[] =>
  v.replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);

function cmpDesc(a: string, b: string): number {
  const ka = versionKey(a);
  const kb = versionKey(b);
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const d = (kb[i] || 0) - (ka[i] || 0);
    if (d) return d;
  }
  return 0;
}

const manifest: { releases: Release[] } = JSON.parse(readFileSync(MANIFEST, "utf8"));
const entries = manifest.releases;

// --- parity assertion: manifest dirs must equal the actual Releases/v* dirs ---
const actualDirs = readdirSync(RELEASES_DIR, { withFileTypes: true })
  .filter((d) => d.isDirectory() && /^v\d/.test(d.name))
  .map((d) => d.name);
const manifestDirs = entries.map((e) => e.dir);

const missingFromManifest = actualDirs.filter((d) => !manifestDirs.includes(d));
const missingOnDisk = manifestDirs.filter((d) => !actualDirs.includes(d));
const dupes = manifestDirs.filter((d, i) => manifestDirs.indexOf(d) !== i);
const noNotes = entries
  .filter((e) => !existsSync(join(RELEASES_DIR, e.dir, "README.md")))
  .map((e) => e.dir);

const problems: string[] = [];
if (missingFromManifest.length)
  problems.push(`Release dirs with NO manifest entry (the drift bug): ${missingFromManifest.join(", ")}`);
if (missingOnDisk.length)
  problems.push(`Manifest entries with NO release dir: ${missingOnDisk.join(", ")}`);
if (dupes.length) problems.push(`Duplicate manifest dirs: ${[...new Set(dupes)].join(", ")}`);
if (noNotes.length) problems.push(`Release dirs missing README.md: ${noNotes.join(", ")}`);

if (problems.length) {
  console.error("✗ Releases page parity check FAILED:\n  - " + problems.join("\n  - "));
  process.exit(1);
}

// --- render ---
const sorted = [...entries].sort((a, b) => cmpDesc(a.dir, b.dir));
const newest = sorted[0]?.dir;

function renderEntry(e: Release): string {
  const currentTag = e.dir === newest ? " (Current)" : "";
  const lines = [`### v${e.version} — ${e.title}${currentTag}`, "", e.summary, ""];
  for (const b of e.bullets ?? []) lines.push(`- ${b}`);
  if (e.bullets?.length) lines.push("");
  lines.push(`**[Get ${e.dir} →](${e.dir}/)**`, "", "---", "");
  return lines.join("\n");
}

const current = sorted.filter((e) => e.era === "current");
const legacy = sorted.filter((e) => e.era === "legacy");

const HEADER = `<!--
  GENERATED FILE — do not hand-edit the release list below.
  Source of truth: Releases/releases.json
  Regenerate:      bun Tools/GenerateReleasesPage.ts
  A release dir with no manifest entry FAILS the build, so this text always
  matches the version directories GitHub shows above it.
-->
<div align="center">

<img src="releases-icon.png" alt="LifeOS Releases" width="220">

# LifeOS Releases

</div>

---

## What Are Releases?

LifeOS ships as a **single self-contained skill** — your AI installs it for you. Each release is a versioned snapshot of that skill. There's no \`~/.claude/\` directory to copy; installing the skill *is* the install.

**About the older releases.** LifeOS began as **PAI (Personal AI Infrastructure)**, and back then it shipped as a \`~/.claude/\` directory you installed into your home folder. Releases **v2.3–v5.0.0** are that era — kept here for history, not for new installs. **v6.0.0** is the first skill-based release and the current model. Same system, same lineage — just no longer a \`.claude/\` directory.

---

`;

const LEGACY_INTRO = `## Legacy Releases (\`.claude/\`-era)

These predate the skill model — they shipped as \`~/.claude/\` directories. Kept for history; **not** the current install path.

`;

const FOOTER = `## Installation

LifeOS installs as a skill — give it to your AI. Paste this into any capable harness (Claude Code, Cursor, Codex, …):

> **Read https://ourlifeos.ai/install and install LifeOS for me.**

Or the one-line shortcut for Claude Code on macOS/Linux:

\`\`\`bash
curl -fsSL https://ourlifeos.ai/install.sh | bash
\`\`\`

The install asks for your name, AI name, timezone, temperature unit, and optional voice preferences.

**Legacy releases (v2–v5)** installed the old way — as a \`~/.claude/\` directory with their own \`install.sh\`. That's no longer how LifeOS works; if you specifically need an old version, follow that release's own README. New installs use the skill above.

See the [main README](../README.md) for more.

---

## Troubleshooting

**Install didn't take?** Re-run it — just ask your AI to install LifeOS again from [ourlifeos.ai/install](https://ourlifeos.ai/install).

**Hooks not firing?** Restart your harness after installation.

---

**Questions?** See the main [LifeOS README](../README.md).
`;

const rendered =
  HEADER +
  "## Available Releases\n\n" +
  current.map(renderEntry).join("\n") +
  "\n" +
  LEGACY_INTRO +
  legacy.map(renderEntry).join("\n") +
  "\n" +
  FOOTER;

const normalized = rendered.replace(/\n{3,}/g, "\n\n").replace(/\s+$/, "") + "\n";

if (process.argv.includes("--check")) {
  const existing = existsSync(PAGE) ? readFileSync(PAGE, "utf8") : "";
  if (existing !== normalized) {
    console.error(
      "✗ Releases/README.md is STALE — run `bun Tools/GenerateReleasesPage.ts` to regenerate.",
    );
    process.exit(1);
  }
  console.log(`✓ Releases/README.md in sync (${entries.length} releases, ${actualDirs.length} dirs).`);
} else {
  writeFileSync(PAGE, normalized);
  console.log(
    `✓ Regenerated Releases/README.md — ${current.length} current + ${legacy.length} legacy = ${entries.length} releases; dir-parity OK (${actualDirs.length} dirs).`,
  );
}
