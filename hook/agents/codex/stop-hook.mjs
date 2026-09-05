#!/usr/bin/env node
// Codex Stop hook.
//
// Codex fires a Stop hook when a turn completes, sends the event as JSON on
// stdin (with stop_hook_active and last_assistant_message), and lets the hook
// inject an instruction back into its own model via exit 2 + stderr (or a
// {"decision":"block","reason":...} stdout payload). We use exit 2 + stderr.
// Codex's built-in model then judges the turn and, if warranted, runs
// submit.mjs. No external LLM is called.
//
// Register in ~/.codex/hooks.json (see hooks.snippet.json).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildInstruction } from "../../reflection.mjs";
import { passesSampling } from "../../sampling.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const submitPath = path.resolve(here, "../../submit.mjs");

function exitAllow() {
  process.exit(0); // let the turn stop normally
}

let input = {};
try {
  const stdin = fs.readFileSync(0, "utf8");
  if (stdin.trim()) input = JSON.parse(stdin);
} catch {
  exitAllow();
}

// Already inside a hook-triggered continuation: allow the stop, never loop.
if (input.stop_hook_active === true) exitAllow();

// Sampling gate. Defaults to a fraction of turns, not every turn.
if (!passesSampling()) exitAllow();

// Inject the instruction and ask Codex to continue.
process.stderr.write(buildInstruction(submitPath) + "\n");
process.exit(2);
