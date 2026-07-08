#!/usr/bin/env bun
/**
 * SkillExecutionLog.hook.ts - Skill execution append-only log
 *
 * TRIGGER: PostToolUse (matcher: Skill)
 */

import { appendFileSync, existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { paiPath } from './lib/paths';
import { getISOTimestamp } from './lib/time';
import {
  buildExecutionLine,
  extractSkillArgs,
  extractSkillName,
  isoZTimestamp,
} from './lib/skill-notify-core';

interface HookInput {
  tool_input?: unknown;
}

const SKILLS_DIR = paiPath('MEMORY', 'SKILLS');
const EXECUTION_FILE = join(SKILLS_DIR, 'execution.jsonl');

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

    const args = extractSkillArgs(data.tool_input);
    const ts = isoZTimestamp(getISOTimestamp());
    appendJsonLine(EXECUTION_FILE, buildExecutionLine(skill, args, ts));
  } catch (error) {
    console.error('[SkillExecutionLog]', error instanceof Error ? error.message : String(error));
  } finally {
    process.exit(0);
  }
}

main();
