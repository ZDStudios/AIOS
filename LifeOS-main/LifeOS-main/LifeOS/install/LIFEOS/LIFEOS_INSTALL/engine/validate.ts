/**
 * LifeOS Installer v6.0 — Validation
 * Verifies installation completeness after all steps run.
 */

import { existsSync, lstatSync, readFileSync, readdirSync, readlinkSync } from "fs";
import { join, extname } from "path";
import { spawnSync } from "child_process";
import type { InstallState, ValidationCheck, InstallSummary, EngineEventHandler } from "./types";
import { LIFEOS_VERSION } from "./types";
import { homedir } from "os";

/**
 * Check if Pulse is running. LifeOS 5.0 absorbed the standalone voice server
 * into Pulse on port 31337 — Pulse serves /notify for voice + the Life
 * Dashboard + observability. Probe /notify with an empty silent payload.
 * Any 2xx-4xx response means Pulse is up and the route is registered.
 */
async function checkPulseHealth(): Promise<boolean> {
  try {
    const res = await fetch("http://localhost:31337/notify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "", voice_enabled: false }),
      signal: AbortSignal.timeout(2000),
    });
    return res.status >= 200 && res.status < 500;
  } catch {
    return false;
  }
}

/**
 * Run Safety.hook.ts as Claude Code would, with a synthetic WebFetch tool
 * result (PostToolUse path). The hook MUST exit 0 and emit a JSON object
 * with hookSpecificOutput.additionalContext containing the EXTERNAL
 * CONTENT warning. A failure here means web content reaches the model
 * without the "treat as data" header, weakening the L3 layer of the
 * security model.
 *
 * Safety.hook.ts is the consolidated permissions/content-tagging hook —
 * it dispatches by hook_event_name, replacing the prior split between
 * SmartApprover.hook.ts (PermissionRequest) and PromptInjection.hook.ts
 * (PostToolUse). This smoke test exercises only the PostToolUse path.
 *
 * Returns { passed, detail }. `passed=false` is CRITICAL.
 */
function checkSecurityHookSmoke(paiDir: string): { passed: boolean; detail: string } {
  const hookPath = join(paiDir, "hooks", "Safety.hook.ts");
  if (!existsSync(hookPath)) {
    return { passed: false, detail: "Hook not found at hooks/Safety.hook.ts" };
  }
  const payload = JSON.stringify({
    session_id: "smoke-test",
    hook_event_name: "PostToolUse",
    tool_name: "WebFetch",
    tool_response: "smoke-test-content",
  });
  try {
    const res = spawnSync(process.execPath, [hookPath], {
      input: payload,
      encoding: "utf-8",
      timeout: 8000,
      env: { HOME: homedir(), PATH: process.env.PATH || "" },
    });
    if (res.status !== 0) {
      const stderr = (res.stderr || "").toString();
      return { passed: false, detail: `Hook exited ${res.status}: ${stderr.trim().slice(0, 160) || "no stderr"}` };
    }
    const stdout = (res.stdout || "").toString();
    if (!/EXTERNAL CONTENT/.test(stdout)) {
      return { passed: false, detail: `Hook output did not contain EXTERNAL CONTENT warning: ${stdout.slice(0, 160)}` };
    }
    return { passed: true, detail: "Safety.hook.ts emits the EXTERNAL CONTENT warning on synthetic input" };
  } catch (err: any) {
    return { passed: false, detail: `Hook execution threw: ${err?.message || String(err)}` };
  }
}

function collectValidationFiles(paiDir: string): string[] {
  const files: string[] = [];
  const extensions = new Set([".md", ".json", ".yaml", ".sh", ".ts"]);
  const shouldSkip = (path: string): boolean =>
    path.includes("/node_modules/") ||
    path.includes("/.git/") ||
    path.includes("/LIFEOS/MEMORY/") ||
    path.includes("/PAI/LIFEOS_INSTALL/");

  const addFile = (path: string): void => {
    if (existsSync(path) && extensions.has(extname(path)) && !shouldSkip(path)) {
      files.push(path);
    }
  };

  // Root files that may carry installer placeholders but fall outside the
  // template-extension set (no extension or non-template extension). Without
  // this explicit add, LICENSE and bunfig.toml leak placeholders past validate.
  const addRootFileExplicit = (path: string): void => {
    if (existsSync(path) && !shouldSkip(path)) {
      files.push(path);
    }
  };

  const walk = (dir: string): void => {
    if (!existsSync(dir) || shouldSkip(`${dir}/`)) return;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = join(dir, entry.name);
      if (shouldSkip(`${child}${entry.isDirectory() ? "/" : ""}`)) continue;
      if (entry.isDirectory()) walk(child);
      else if (entry.isFile()) addFile(child);
    }
  };

  addFile(join(paiDir, "CLAUDE.md"));
  addFile(join(paiDir, "settings.json"));
  addFile(join(paiDir, "LifeOS", "LIFEOS_SYSTEM_PROMPT.md"));
  addRootFileExplicit(join(paiDir, "LICENSE"));
  addRootFileExplicit(join(paiDir, "bunfig.toml"));
  walk(join(paiDir, "LifeOS", "USER"));
  walk(join(paiDir, "LifeOS", "DOCUMENTATION"));
  walk(join(paiDir, "LifeOS", "ALGORITHM"));
  walk(join(paiDir, "agents"));
  walk(join(paiDir, "hooks"));
  walk(join(paiDir, "skills"));
  return files;
}

const KNOWN_PLACEHOLDER_KEYS = [
  "DA_FULL_NAME", "DA_NAME", "PRINCIPAL_NAME", "PRINCIPAL_FULL_NAME",
  "PRIMARY_VOICE_ID", "SECONDARY_VOICE_ID",
  "LIFEOS_VERSION", "ALGORITHM_VERSION",
  "REPO_OWNER",
];

export function runSurvivingPlaceholdersCheck(paiDir: string): ValidationCheck {
  const knownKeysAlt = KNOWN_PLACEHOLDER_KEYS.join("|");
  const placeholderPattern = new RegExp(`\\{\\{(?:${knownKeysAlt})\\}\\}|\\{(?:DA_IDENTITY|PRINCIPAL)\\.NAME\\}`);
  const failedFiles = collectValidationFiles(paiDir).filter((file) =>
    placeholderPattern.test(readFileSync(file, "utf-8"))
  );

  return {
    name: "surviving-placeholders",
    passed: failedFiles.length === 0,
    detail: failedFiles.length === 0
      ? "0 files contain installer placeholders"
      : `${failedFiles.length} files contain installer placeholders`,
    critical: true,
  };
}

export function runInterviewBannersCheck(paiDir: string): ValidationCheck {
  const bannerPattern = /<INTERVIEW REQUIRED — [^>]+>/;
  const filesNeedingInterview = collectValidationFiles(paiDir).filter((file) =>
    bannerPattern.test(readFileSync(file, "utf-8"))
  );

  return {
    name: "interview-banners",
    passed: filesNeedingInterview.length === 0,
    detail: filesNeedingInterview.length === 0
      ? "0 files need /interview"
      : `Run /interview to populate ${filesNeedingInterview.length} files.`,
    critical: false,
  };
}

/**
 * Run all validation checks against the current state.
 */
export async function runValidation(state: InstallState, emit?: EngineEventHandler): Promise<ValidationCheck[]> {
  if (emit) {
    await emit({ event: "step_start", step: "validation" });
    await emit({
      event: "section_header",
      sectionId: "FINAL-VALIDATION",
      title: "FINAL VALIDATION",
      subtitle: "Verifying the install before handing control back to you",
      stepNumber: 9,
    });
  }

  const paiDir = state.detection?.paiDir || join(homedir(), ".claude");
  const configDir = state.detection?.configDir || join(homedir(), ".config", "LifeOS");
  const checks: ValidationCheck[] = [];

  // 1. settings.json exists and is valid JSON
  const settingsPath = join(paiDir, "settings.json");
  const settingsExists = existsSync(settingsPath);
  let settingsValid = false;
  let settings: any = null;

  if (settingsExists) {
    try {
      settings = JSON.parse(readFileSync(settingsPath, "utf-8"));
      settingsValid = true;
    } catch {
      settingsValid = false;
    }
  }

  checks.push({
    name: "settings.json",
    passed: settingsExists && settingsValid,
    detail: settingsValid
      ? "Valid configuration file"
      : settingsExists
        ? "File exists but invalid JSON"
        : "File not found",
    critical: true,
  });

  // 2. Required settings fields
  if (settings) {
    checks.push({
      name: "Principal name",
      passed: !!settings.principal?.name,
      detail: settings.principal?.name ? `Set to: ${settings.principal.name}` : "Not configured",
      critical: true,
    });

    checks.push({
      name: "AI identity",
      passed: !!settings.daidentity?.name,
      detail: settings.daidentity?.name ? `Set to: ${settings.daidentity.name}` : "Not configured",
      critical: true,
    });

    checks.push({
      name: "LifeOS version",
      passed: !!settings.pai?.version,
      detail: settings.pai?.version ? `v${settings.pai.version}` : "Not set",
      critical: false,
    });

    checks.push({
      name: "Timezone",
      passed: !!settings.principal?.timezone,
      detail: settings.principal?.timezone || "Not configured",
      critical: false,
    });
  }

  // 3. Directory structure
  const requiredDirs = [
    { path: "skills", name: "Skills directory" },
    { path: "MEMORY", name: "Memory directory" },
    { path: "MEMORY/STATE", name: "State directory" },
    { path: "MEMORY/WORK", name: "Work directory" },
    { path: "hooks", name: "Hooks directory" },
    { path: "Plans", name: "Plans directory" },
  ];

  for (const dir of requiredDirs) {
    const fullPath = join(paiDir, dir.path);
    checks.push({
      name: dir.name,
      passed: existsSync(fullPath),
      detail: existsSync(fullPath) ? "Present" : "Missing",
      critical: dir.path === "skills" || dir.path === "MEMORY",
    });
  }


  // 5. ElevenLabs key stored — check all three possible locations
  const envPaths = [
    join(configDir, ".env"),
    join(paiDir, ".env"),
    join(homedir(), ".env"),
  ];
  let elevenLabsKeyStored = false;
  let elevenLabsKeyLocation = "";
  for (const ep of envPaths) {
    if (existsSync(ep)) {
      try {
        const envContent = readFileSync(ep, "utf-8");
        if (envContent.includes("ELEVENLABS_API_KEY=") &&
            !envContent.includes("ELEVENLABS_API_KEY=\n")) {
          elevenLabsKeyStored = true;
          elevenLabsKeyLocation = ep;
          break;
        }
      } catch {}
    }
  }

  checks.push({
    name: "ElevenLabs API key",
    passed: elevenLabsKeyStored,
    detail: elevenLabsKeyStored ? `Stored in ${elevenLabsKeyLocation}` : state.collected.elevenLabsKey ? "Collected but not saved" : "Not configured",
    critical: false,
  });

  // 6. DA voice configured in settings (nested under voices.main.voiceId)
  const voiceId = settings?.daidentity?.voices?.main?.voiceId;
  const voiceIdConfigured = !!voiceId;

  checks.push({
    name: "DA voice ID",
    passed: voiceIdConfigured,
    detail: voiceIdConfigured ? `Voice ID: ${voiceId.substring(0, 8)}...` : "Not configured",
    critical: false,
  });

  // 7. Pulse running — embeds voice + dashboard + observability (LifeOS 5.0)
  const pulseHealthy = await checkPulseHealth();

  checks.push({
    name: "Pulse (voice + dashboard)",
    passed: pulseHealthy,
    detail: pulseHealthy
      ? "Running on localhost:31337"
      : "Not reachable — install via: bash ~/.claude/LIFEOS/PULSE/manage.sh install",
    critical: false,
  });

  // 7b. Pulse auto-start service present (launchd on macOS, systemd on Linux)
  let pulseServiceInstalled = false;
  let pulseServiceDetail = "";
  if (process.platform === "darwin") {
    const pulsePlist = join(homedir(), "Library", "LaunchAgents", "com.lifeos.pulse.plist");
    pulseServiceInstalled = existsSync(pulsePlist);
    pulseServiceDetail = pulseServiceInstalled
      ? "Installed at ~/Library/LaunchAgents/com.lifeos.pulse.plist"
      : "Not installed — Pulse will not auto-start on login";
  } else {
    const pulseUnit = join(homedir(), ".config", "systemd", "user", "com.lifeos.pulse.service");
    pulseServiceInstalled = existsSync(pulseUnit);
    pulseServiceDetail = pulseServiceInstalled
      ? "Installed at ~/.config/systemd/user/com.lifeos.pulse.service"
      : "Not installed — Pulse will not auto-start on login";
  }
  checks.push({
    name: "Pulse auto-start service",
    passed: pulseServiceInstalled,
    detail: pulseServiceDetail,
    critical: false,
  });

  // 8. Shell alias configured (.zshrc, .bashrc, or .profile)
  const shellRcFiles = [".zshrc", ".bashrc", ".profile"];
  let aliasConfigured = false;
  let aliasFoundIn = "";
  for (const rc of shellRcFiles) {
    const rcPath = join(homedir(), rc);
    if (existsSync(rcPath)) {
      try {
        const rcContent = readFileSync(rcPath, "utf-8");
        if (rcContent.includes("# LifeOS alias") && rcContent.includes("alias pai=")) {
          aliasConfigured = true;
          aliasFoundIn = rc;
          break;
        }
      } catch {}
    }
  }

  checks.push({
    name: "Shell alias (pai)",
    passed: aliasConfigured,
    detail: aliasConfigured ? `Configured in ~/${aliasFoundIn}` : "Not found — run: source ~/.<shell>rc",
    critical: true,
  });

  // 9. Safety hook smoke test — runs the actual hook with a synthetic
  // WebFetch payload. Confirms the L3 "treat as data" header gets emitted to
  // the model. If this fails, external content reaches the model unlabeled.
  const securitySmoke = checkSecurityHookSmoke(paiDir);
  checks.push({
    name: "Safety hook (smoke test)",
    passed: securitySmoke.passed,
    detail: securitySmoke.detail,
    critical: true,
  });

  checks.push(runSurvivingPlaceholdersCheck(paiDir));
  checks.push(runInterviewBannersCheck(paiDir));
  checks.push(runSymlinkContractCheck(paiDir));

  return checks;
}

// Verify the post-Phase-G system/user separation contract: ~/.claude/LIFEOS/USER
// must be a symlink whose target is ~/.config/LIFEOS/USER. A silent symlink
// failure during install would leave @-imports unable to reach identity files
// and the system non-functional, with no other validation gate detecting it.
export function runSymlinkContractCheck(paiDir: string): ValidationCheck {
  const liveUserDir = join(paiDir, "LifeOS", "USER");
  const expectedTarget = join(homedir(), ".config", "LifeOS", "USER");

  if (!existsSync(liveUserDir)) {
    return {
      name: "USER symlink contract",
      passed: false,
      detail: `Expected symlink at ${liveUserDir} → ${expectedTarget} but the path does not exist.`,
      critical: true,
    };
  }

  let stat: ReturnType<typeof lstatSync>;
  try {
    stat = lstatSync(liveUserDir);
  } catch (err) {
    return {
      name: "USER symlink contract",
      passed: false,
      detail: `Could not lstat ${liveUserDir}: ${err instanceof Error ? err.message : String(err)}`,
      critical: true,
    };
  }

  if (!stat.isSymbolicLink()) {
    return {
      name: "USER symlink contract",
      passed: false,
      detail: `${liveUserDir} exists but is NOT a symlink — system/user separation broken. Expected target: ${expectedTarget}.`,
      critical: true,
    };
  }

  let target: string;
  try {
    target = readlinkSync(liveUserDir);
  } catch (err) {
    return {
      name: "USER symlink contract",
      passed: false,
      detail: `Could not readlink ${liveUserDir}: ${err instanceof Error ? err.message : String(err)}`,
      critical: true,
    };
  }

  if (target !== expectedTarget) {
    return {
      name: "USER symlink contract",
      passed: false,
      detail: `${liveUserDir} symlinks to ${target} but expected ${expectedTarget}.`,
      critical: true,
    };
  }

  return {
    name: "USER symlink contract",
    passed: true,
    detail: `~/.claude/LIFEOS/USER → ${target}`,
    critical: true,
  };
}

/**
 * Generate install summary from state.
 */
export function generateSummary(state: InstallState): InstallSummary {
  return {
    paiVersion: LIFEOS_VERSION,
    principalName: state.collected.principalName || "User",
    aiName: state.collected.aiName || "LifeOS",
    timezone: state.collected.timezone || "UTC",
    voiceEnabled: state.completedSteps.includes("voice"),
    voiceMode: state.collected.elevenLabsKey ? "elevenlabs" : state.completedSteps.includes("voice") ? "macos-say" : "none",
    catchphrase: state.collected.catchphrase || "",
    installType: state.installType || "fresh",
    completedSteps: state.completedSteps.length,
    totalSteps: 9,
  };
}
