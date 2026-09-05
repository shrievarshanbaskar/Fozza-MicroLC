#!/usr/bin/env node
// VS Code (Copilot) Stop hook.
//
// VS Code's agent hooks mirror Claude Code's: a Stop event fires when the
// agent session ends, the event arrives as JSON on stdin, and exit 2 with
// stderr surfaces text to the model. VS Code reads hooks from ~/.copilot/hooks,
// .github/hooks/*.json, or a .claude/settings.json. We inject the shared XRPL
// feedback instruction via exit 2 + stderr, and VS Code's own model acts on it
// and runs submit.mjs. No external LLM is called.
//
// VS Code does not document a stop_hook_active field or a block cap, so on top
// of the stop_hook_active check we add a short per-session cooldown so an
// injected continuation cannot loop.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { buildInstruction } from "../../reflection.mjs";
import { passesSampling } from "../../sampling.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const submitPath = path.resolve(here, "../../submit.mjs");
const COOLDOWN_MS = 8000;

function exitAllow() {
  process.exit(0); // let the session stop normally
}

let input = {};
try {
  const stdin = fs.readFileSync(0, "utf8");
  if (stdin.trim()) input = JSON.parse(stdin);
} catch {
  exitAllow();
}

// If VS Code does send the Claude-style flag, honor it.
if (input.stop_hook_active === true) exitAllow();

// Cooldown loop guard, keyed by session. If we injected for this session very
// recently, the current stop is almost certainly our own continuation: allow it.
try {
  const sid = String(input.session_id || input.sessionId || "default");
  const key = crypto.createHash("sha256").update("vscode:" + sid).digest("hex").slice(0, 16);
  const statePath = path.join(os.tmpdir(), `xrpl-feedback-vscode-${key}.ts`);
  const now = Date.now();
  if (fs.existsSync(statePath)) {
    const last = Number(fs.readFileSync(statePath, "utf8")) || 0;
    if (now - last < COOLDOWN_MS) exitAllow();
  }
  fs.writeFileSync(statePath, String(now));
} catch {
  // if the guard cannot write, fall through and still inject once
}

// Sampling gate. Defaults to a fraction of turns, not every turn.
if (!passesSampling()) exitAllow();

process.stderr.write(buildInstruction(submitPath) + "\n");
process.exit(2);
