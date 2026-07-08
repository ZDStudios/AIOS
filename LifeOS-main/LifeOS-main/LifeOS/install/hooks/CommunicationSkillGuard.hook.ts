#!/usr/bin/env bun
/**
 * CommunicationSkillGuard.hook.ts — PreToolUse Bash gate
 *
 * Catches raw outbound-email sends — `gmail.ts send` and `aws ses send-email`
 * — that are NOT routed through the _COMMUNICATION skill, and blocks them
 * BEFORE the tool runs.
 *
 * Sending email is the _COMMUNICATION skill's SendEmail workflow. That
 * workflow carries load-bearing rules the bare tool skips: mandatory auto-BCC
 * to the principal, send-as-DA identity/signature consistency, and DKIM/DMARC-
 * safe transport selection (gmail.ts for the principal's personal domain, SES
 * for the org domain). Free-handing the tool bypasses all of it (the
 * 2026-06-13 ISA-email miss is the canonical failure).
 *
 * The skill's SendEmail workflow tags every send command with the marker
 * `LIFEOS_SKILL=_COMMUNICATION` (an inert env assignment the tools ignore). This
 * hook allows commands carrying that marker and blocks the rest — same
 * model as ArtWorkflowGuard's `--workflow=` requirement for Generate.ts.
 *
 * TRIGGER: PreToolUse (matcher: Bash)
 * EXIT CODES: 0 = allow, 2 = deny (blocks the call, message goes to model)
 */

import { readFileSync } from "node:fs";

interface HookInput {
  tool_input?: { command?: string };
}

function readHookInput(): HookInput {
  try {
    return JSON.parse(readFileSync(0, "utf-8")) as HookInput;
  } catch {
    return {};
  }
}

// Outbound-send signatures. Read-only gmail ops (count/ids/fetch/archive) and
// non-send aws ses ops (verify-email-identity, etc.) are deliberately NOT gated.
function isEmailSend(command: string): boolean {
  const gmailSend = /gmail\.ts['"]?\s+send\b/.test(command);
  const sesSend = /\baws\s+sesv?2?\s+send(-raw)?-email\b/.test(command);
  return gmailSend || sesSend;
}

function isSkillRouted(command: string): boolean {
  return /LIFEOS_SKILL=_COMMUNICATION\b/.test(command);
}

function main(): never {
  const command = readHookInput()?.tool_input?.command ?? "";

  if (!isEmailSend(command)) process.exit(0);
  if (isSkillRouted(command)) process.exit(0);

  const lines = [
    "",
    "═══════════════════════════════════════════════════════════════════════════",
    "  CommunicationSkillGuard — raw email send BLOCKED before execution.",
    "═══════════════════════════════════════════════════════════════════════════",
    "",
    "  Sending email is the _COMMUNICATION skill, not a standalone tool call.",
    "  The SendEmail workflow carries rules a bare `gmail.ts send` / `aws ses",
    "  send-email` skips: mandatory auto-BCC to the principal, send-as-DA",
    "  identity + signature consistency, and DKIM/DMARC-safe transport.",
    "",
    "  Do this instead:",
    "    1. Invoke  Skill(\"_COMMUNICATION\")",
    "    2. Follow its SendEmail workflow (skills/_COMMUNICATION/Workflows/SendEmail.md)",
    "    3. The send command it builds carries  LIFEOS_SKILL=_COMMUNICATION  and passes.",
    "",
    "  Explicit one-off override (logged): prefix the command with",
    "    LIFEOS_SKILL=_COMMUNICATION  <your send command>",
    "  Only do this when you have genuinely already applied the workflow's rules",
    "  (BCC, identity/signature, transport).",
    "",
    "═══════════════════════════════════════════════════════════════════════════",
    "",
  ];
  process.stderr.write(lines.join("\n"));
  process.exit(2);
}

main();
