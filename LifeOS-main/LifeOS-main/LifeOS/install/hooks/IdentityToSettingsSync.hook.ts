#!/usr/bin/env bun
/**
 * IdentityToSettingsSync.hook.ts — Mirror PRINCIPAL_IDENTITY frontmatter
 * `preferences` into settings.json `.preferences` whenever the identity file
 * is edited.
 *
 * TRIGGER: PostToolUse (Write, Edit)
 *
 * PRINCIPAL_IDENTITY.md is canonical. settings.json `.preferences` is the
 * machine-readable mirror that consumers (statusline, hooks) read directly.
 * The mirror exists because shell consumers can't parse YAML frontmatter
 * cheaply. This hook keeps the two structurally aligned.
 *
 * Idempotent: SyncIdentityToSettings.ts no-ops when nothing changed.
 */
import { readFileSync } from 'fs';
import { execSync } from 'child_process';
import { paiPath } from './lib/paths';

const SYNC_TOOL = paiPath('TOOLS', 'SyncIdentityToSettings.ts');

let input: any;
try {
  input = JSON.parse(readFileSync(0, 'utf-8'));
} catch {
  process.exit(0);
}

const filePath: string = input.tool_input?.file_path || '';
if (!filePath.endsWith('/PRINCIPAL/PRINCIPAL_IDENTITY.md')) process.exit(0);

try {
  execSync(`bun run ${SYNC_TOOL}`, { timeout: 3000, stdio: 'pipe' });
} catch (err) {
  console.error(`⚠️ Identity → settings sync failed: ${err}`);
}

process.exit(0);
