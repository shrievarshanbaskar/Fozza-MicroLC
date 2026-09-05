#!/usr/bin/env node
// Claude Code Stop hook.
//
// Fires when Claude finishes a turn. It injects the shared XRPL feedback
// instruction back into Claude by writing it to stderr and exiting 2, which
// tells Claude to keep going and act on it. Claude's own model then judges the
// turn and, if warranted, runs submit.mjs. No external LLM is called.
//
// Register in ~/.claude/settings.json (see settings.snippet.json).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildInstruction } from "../../reflection.mjs";
import { passesSampling } from "../../sampling.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const submitPath = path.resolve(here, "../../submit.mjs");

function exitAllow() {
  process.exit(0); // let Claude stop normally
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

// Inject the instruction and ask Claude to continue.
process.stderr.write(buildInstruction(submitPath) + "\n");
process.exit(2);
