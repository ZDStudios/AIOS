/**
 * LifeOS Installer v6.0 — CLI Wizard
 * Interactive command-line installation experience.
 */

import type { EngineEvent, InstallState, StepId } from "../engine/types";
import { STEPS, getProgress } from "../engine/steps";
import {
  createFreshState,
  hasSavedState,
  loadState,
  saveState,
  clearState,
  completeStep,
} from "../engine/state";
import {
  runSystemDetect,
  runPrerequisites,
  runApiKeys,
  runIdentity,
  runRepository,
  runConfiguration,
  runVoiceSetup,
  runTelegramSetup,
  runTemplateSubstitution,
  getCopyMissingFailures,
} from "../engine/actions";
import { runValidation, generateSummary } from "../engine/validate";
import {
  printBanner,
  printStep,
  printSectionHeader,
  printDetection,
  printValidation,
  printSummary,
  print,
  printSuccess,
  printError,
  printWarning,
  printInfo,
  progressBar,
  c,
} from "./display";
import { promptText, promptSecret, promptChoice, promptChoiceWithPreview, promptConfirm } from "./prompts";

type CLIChoice = {
  label: string;
  value: string;
  description?: string;
  voiceId?: string;
};

async function previewVoiceViaPulse(
  choice: { label: string; value: string; voiceId?: string },
  previewText: string
): Promise<void> {
  if (!choice.voiceId) {
    throw new Error("no preview available");
  }

  try {
    const response = await fetch("http://localhost:31337/notify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: previewText,
        voice_id: choice.voiceId,
        voice_settings: { stability: 0.35, similarity_boost: 0.80, style: 0.90, speed: 1.1 },
      }),
      signal: AbortSignal.timeout(8000),
    });

    if (!response.ok) {
      throw new Error(response.statusText ? `${response.status} ${response.statusText}` : `HTTP ${response.status}`);
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(reason);
  }
}

/**
 * Handle engine events in CLI mode.
 */
function createEventHandler(): (event: EngineEvent) => void {
  return (event: EngineEvent) => {
    switch (event.event) {
      case "step_start":
        // Handled by the main loop with printStep
        break;
      case "section_header":
        printSectionHeader(event.title, event.subtitle, event.stepNumber);
        break;
      case "step_complete":
        printSuccess("Step complete");
        break;
      case "step_skip":
        printInfo(`Skipped: ${event.reason}`);
        break;
      case "step_error":
        printError(`Error: ${event.error}`);
        break;
      case "progress":
        print(`  ${progressBar(event.percent)} ${c.gray}${event.detail}${c.reset}`);
        break;
      case "message":
        print(`\n  ${event.content}\n`);
        break;
      case "error":
        printError(event.message);
        break;
    }
  };
}

/**
 * CLI input adapter — bridges engine's input requests to readline prompts.
 */
async function getInput(
  id: string,
  prompt: string,
  type: "text" | "password" | "key",
  placeholder?: string,
  daName?: string
): Promise<string> {
  if (type === "key" || type === "password") {
    return promptSecret(prompt, placeholder, daName);
  }
  return promptText(prompt, placeholder, daName);
}

/**
 * CLI choice adapter.
 */
async function getChoice(
  id: string,
  prompt: string,
  choices: CLIChoice[],
  daName?: string
): Promise<string> {
  return promptChoice(prompt, choices, daName);
}

async function getChoiceWithPreview(
  id: string,
  prompt: string,
  choices: CLIChoice[],
  previewText: string,
  daName?: string
): Promise<string> {
  return promptChoiceWithPreview(
    prompt,
    choices,
    async (choice) => previewVoiceViaPulse(choice, previewText),
    daName
  );
}

/**
 * Run the full CLI installation wizard.
 */
export async function runCLI(): Promise<void> {
  printBanner();

  const emit = createEventHandler();

  // Check for resume
  let state: InstallState;

  if (hasSavedState()) {
    const saved = loadState();
    if (saved) {
      print(`  ${c.yellow}Found previous installation in progress.${c.reset}`);
      print(`  ${c.gray}Started: ${saved.startedAt}${c.reset}`);
      print(`  ${c.gray}Progress: ${getProgress(saved)}% (${saved.completedSteps.length} steps completed)${c.reset}`);
      print("");

      const resume = await promptConfirm("Resume previous installation?");
      if (resume) {
        state = saved;
        state.mode = "cli";
        print(`\n  ${c.green}Resuming from step: ${state.currentStep}${c.reset}\n`);
      } else {
        state = createFreshState("cli");
      }
    } else {
      state = createFreshState("cli");
    }
  } else {
    state = createFreshState("cli");
  }

  try {
    // ── Step 1: System Detection ──
    if (!state.completedSteps.includes("system-detect")) {
      const step = STEPS[0];
      printStep(step.number, 9, step.name);
      const detection = await runSystemDetect(state, emit, getChoice);
      printDetection(detection);
      completeStep(state, "system-detect");
      state.currentStep = "prerequisites";
    }

    // ── Step 2: Prerequisites ──
    if (!state.completedSteps.includes("prerequisites")) {
      const step = STEPS[1];
      printStep(step.number, 9, step.name);
      await runPrerequisites(state, emit);
      completeStep(state, "prerequisites");
      state.currentStep = "api-keys";
    }

    // ── Step 3: API Keys ──
    if (!state.completedSteps.includes("api-keys")) {
      const step = STEPS[2];
      printStep(step.number, 9, step.name);
      await runApiKeys(state, emit, getInput, getChoice);
      completeStep(state, "api-keys");
      state.currentStep = "identity";
    }

    // ── Step 4: Identity ──
    if (!state.completedSteps.includes("identity")) {
      const step = STEPS[3];
      printStep(step.number, 9, step.name);
      await runIdentity(state, emit, getInput);
      completeStep(state, "identity");
      state.currentStep = "repository";
    }

    // ── Step 5: Repository ──
    if (!state.completedSteps.includes("repository")) {
      const step = STEPS[4];
      printStep(step.number, 9, step.name);
      await runRepository(state, emit);
      completeStep(state, "repository");
      state.currentStep = "configuration";
    }

    // ── Step 6: Configuration ──
    if (!state.completedSteps.includes("configuration")) {
      const step = STEPS[5];
      printStep(step.number, 9, step.name);
      await runConfiguration(state, emit);
      completeStep(state, "configuration");
      state.currentStep = "voice";
    }

    // ── Step 7: Voice ──
    if (!state.completedSteps.includes("voice") && !state.skippedSteps.includes("voice")) {
      const step = STEPS[6];
      printStep(step.number, 9, step.name);
      await runVoiceSetup(state, emit, getChoice, getInput, getChoiceWithPreview);
      completeStep(state, "voice");
      state.currentStep = "telegram";
    }

    // ── Step 8: Telegram (optional) ──
    if (!state.completedSteps.includes("telegram") && !state.skippedSteps.includes("telegram")) {
      const step = STEPS[7];
      printStep(step.number, 9, step.name);
      await runTelegramSetup(state, emit, getChoice, getInput);
      // runTelegramSetup either completes or marks the step skipped internally;
      // ensure something is recorded so the loop advances.
      if (!state.completedSteps.includes("telegram") && !state.skippedSteps.includes("telegram")) {
        completeStep(state, "telegram");
      }
      state.currentStep = "validation";
    }

    // ── Step 9: Validation ──
    if (!state.completedSteps.includes("validation")) {
      const step = STEPS[8];
      printStep(step.number, 9, step.name);

      // Unconditional template substitution — used to live at the end of the
      // voice step; that coupling broke every skip-voice install. Now runs
      // here so all collected identity values (principal name, DA name, voice
      // IDs, etc.) land in CLAUDE.md / agents / hooks / skills / USER tree
      // regardless of which optional steps the user skipped.
      const paiDirForSubst = state.detection?.paiDir || `${process.env.HOME}/.claude`;
      await runTemplateSubstitution(state, paiDirForSubst, emit);

      const checks = await runValidation(state, emit);
      printValidation(checks);

      // Surface any copyMissing failures captured during the install. F6 fix
      // wired here so the failure list captured at actions.ts:676 actually
      // reaches the operator. Non-empty list = soft warning (not a critical
      // gate; the install still completed) but the operator should know which
      // files didn't copy so they can fix manually.
      const copyFailures = getCopyMissingFailures();
      if (copyFailures.length > 0) {
        printWarning(`\n${copyFailures.length} file(s) failed to copy during install:`);
        for (const f of copyFailures) print(`  - ${f}`);
        print("");
      }

      const allCritical = checks.filter((c) => c.critical).every((c) => c.passed);
      if (allCritical) {
        completeStep(state, "validation");
      } else {
        printError("\nSome critical checks failed. Please review and fix the issues above.");
      }
    }

    // ── Summary ──
    const summary = generateSummary(state);
    printSummary(summary);

    // Clean up state file on success
    clearState();

    print(`  ${c.green}${c.bold}Installation complete!${c.reset}`);
    print("");
    print(`  ${c.lightBlue}${c.bold}You have a working LifeOS, but it's a generic shell.${c.reset}`);
    print(`  ${c.gray}To make it ${c.bold}yours${c.reset}${c.gray}, you tell it who you are, what you're working on,${c.reset}`);
    print(`  ${c.gray}and how you think. Two paths to do that:${c.reset}`);
    print("");
    print(`  ${c.lightBlue}${c.bold}Fast path — let the DA interview you:${c.reset}`);
    print(`  ${c.gray}1.${c.reset} Run ${c.bold}source ~/.zshrc && pai${c.reset}${c.gray} to launch PAI.${c.reset}`);
    print(`  ${c.gray}2.${c.reset} Type ${c.bold}/interview${c.reset}${c.gray} — the DA walks through TELOS, identity, projects, preferences. Pause and resume anytime.${c.reset}`);
    print(`     ${c.gray}(Already have goals/journals/notes in Obsidian, Notion, etc.? Run the ${c.bold}Migrate${c.reset}${c.gray} skill first so the interview fills gaps instead of asking you to re-type.)${c.reset}`);
    print("");
    print(`  ${c.lightBlue}${c.bold}Manual path — edit the files yourself:${c.reset}`);
    print(`  ${c.gray}Each subdirectory under ~/.config/LIFEOS/USER/ has a README.md explaining what goes inside and how to customize it.${c.reset}`);
    print(`  ${c.gray}Start with:${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/README.md${c.reset}                       ${c.gray}— full layout map${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/TELOS/README.md${c.reset}                 ${c.gray}— missions, goals, problems, strategies${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/DIGITAL_ASSISTANT/README.md${c.reset}     ${c.gray}— your DA's identity, voice, personality${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/PRINCIPAL/README.md${c.reset}             ${c.gray}— your identity, resume, writing style${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/PROJECTS.md${c.reset}                     ${c.gray}— project registry + routing aliases${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/SECURITY/README.md${c.reset}              ${c.gray}— bash/path rules (already has working defaults)${c.reset}`);
    print(`     ${c.bold}~/.config/LIFEOS/USER/CONFIG/README.md${c.reset}                ${c.gray}— credentials and LifeOS config${c.reset}`);
    print("");
    print(`  ${c.lightBlue}${c.bold}Where your data actually lives:${c.reset}`);
    print(`  ${c.gray}System code lives at ${c.bold}~/.claude/${c.reset}${c.gray}. Your private user data lives at ${c.bold}~/.config/LIFEOS/USER/${c.reset}${c.gray}.${c.reset}`);
    print(`  ${c.gray}${c.bold}~/.claude/LIFEOS/USER${c.reset}${c.gray} is a symlink to ${c.bold}~/.config/LIFEOS/USER${c.reset}${c.gray} — this separation is required for LifeOS to work.${c.reset}`);
    print(`  ${c.gray}When you edit ${c.bold}~/.claude/LIFEOS/USER/...${c.reset}${c.gray} you're really editing ${c.bold}~/.config/LIFEOS/USER/...${c.reset}${c.gray} (same file).${c.reset}`);
    print(`  ${c.gray}${c.bold}Optional but recommended:${c.reset}${c.gray} turn ${c.bold}~/.config/LIFEOS/${c.reset}${c.gray} into a private git repo so you have versioned history of everything you write:${c.reset}`);
    print(`     ${c.bold}cd ~/.config/LIFEOS && git init && git add -A && git commit -m "initial"${c.reset}`);
    print(`     ${c.gray}Private remote (optional): ${c.bold}gh repo create pai-user-data --private --source=. --push${c.reset}`);
    print("");
    print(`  ${c.lightBlue}${c.bold}While you're here:${c.reset}`);
    print(`  ${c.gray}•${c.reset} Visit the Life Dashboard at ${c.bold}http://localhost:31337${c.reset}${c.gray} (Pulse).${c.reset}`);
    print(`  ${c.gray}•${c.reset} Anything you write under ${c.bold}LIFEOS/USER/${c.reset}${c.gray} stays on your machine — it never ships in any LifeOS release.${c.reset}`);
    print("");

    process.exit(0);
  } catch (error: any) {
    printError(`\nInstallation failed: ${error.message}`);
    printInfo("Your progress has been saved. Run the installer again to resume.");
    saveState(state);
    process.exit(1);
  }
}
