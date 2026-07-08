#!/usr/bin/env bun
/**
 * SkillVoiceNotify.hook.ts - Skill voice notification mirror
 *
 * TRIGGER: PostToolUse (matcher: Skill)
 *
 * During observation this hook is log-only. The mirror file proves that the
 * hook fired without speaking through Pulse.
 */

import { appendFileSync, existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { paiPath } from './lib/paths';
import { getISOTimestamp } from './lib/time';
import {
  buildVoiceMirrorLine,
  extractSkillName,
  isoZTimestamp,
} from './lib/skill-notify-core';

// Flip to true only after per-skill voice prose has been stripped.
const VOICE_LIVE = false;

interface HookInput {
  tool_input?: unknown;
}

const VOICE_DIR = paiPath('MEMORY', 'VOICE');
const MIRROR_FILE = join(VOICE_DIR, 'skill-voice-notify.jsonl');
const NOTIFY_URL = 'http://localhost:31337/notify';
const FETCH_TIMEOUT_MS = 2000;

async function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let data = '';
    const timer = setTimeout(() => resolve(data), 2000);
    process.stdin.on('data', (chunk) => { data += chunk.toString(); });
    process.stdin.on('end', () => { clearTimeout(timer); resolve(data); });
    process.stdin.on('error', () => { clearTimeout(timer); resolve(data); });
  });
}

function appendJsonLine(filePath: string, line: unknown): void {
  const dir = dirname(filePath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  appendFileSync(filePath, JSON.stringify(line) + '\n', 'utf-8');
}

async function postVoiceNotification(title: string, message: string): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    await fetch(NOTIFY_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title, message, voice_enabled: true }),
      signal: controller.signal,
    });
  } catch {
    // Best-effort only; the mirror line is the durable record.
  } finally {
    clearTimeout(timer);
  }
}

async function main(): Promise<void> {
  try {
    const raw = await readStdin();
    if (!raw.trim()) return;

    let data: HookInput;
    try {
      data = JSON.parse(raw) as HookInput;
    } catch {
      return;
    }

    const skill = extractSkillName(data.tool_input);
    if (!skill) return;

    const ts = isoZTimestamp(getISOTimestamp());
    const mirrorLine = {
      ...buildVoiceMirrorLine(skill, ts),
      voice_live: VOICE_LIVE,
    };

    appendJsonLine(MIRROR_FILE, mirrorLine);

    if (VOICE_LIVE) {
      await postVoiceNotification('Skill', mirrorLine.message);
    }
  } catch (error) {
    console.error('[SkillVoiceNotify]', error instanceof Error ? error.message : String(error));
  } finally {
    process.exit(0);
  }
}

main();
