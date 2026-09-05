# Install the XRPL feedback hook

This wires your coding agent to send XRPL developer feedback to the hackathon server after each response. The agent's own built in model does the thinking. Nothing calls any external LLM. The only network call is a small POST to our feedback server.

This guide is written so an AI agent can install it, and a human can too.

## How it works

After a turn finishes, the agent reviews its own last response and decides whether it revealed genuine XRPL developer feedback (docs gaps, SDK friction, faucet or devnet issues, and so on). If it did, the agent runs `submit.mjs`, which POSTs the feedback to the server. If not, nothing happens.

There is no shared hook standard across agents, but all four have a stop hook that can feed an instruction back into their own model. The registration differs by agent:

| Agent | Mechanism |
|---|---|
| Claude Code | `Stop` hook, injects via exit 2 + stderr |
| Cursor | `stop` hook, returns `followup_message` |
| Codex | `Stop` hook, injects via exit 2 + stderr |
| VS Code Copilot | `Stop` hook, injects via exit 2 + stderr |

All four use the agent's own model and all four only call our server.

## Prerequisites

* Node 18 or newer (`node --version`). The scripts are zero dependency.
* No feedback token needed, it is baked into `submit.mjs`.
* No LLM API key of any kind.

## Files

Everything is in this `hook/` directory. Copy the whole directory somewhere stable, for example `~/.xrpl-feedback/hook/`, and note the absolute path. The steps below use `~/.xrpl-feedback/hook` as `HOOK_DIR`.

## Step 1: capture identity and write the config

Team name and real name are attached to every submission, so they must be entered first.

### Human

```bash
node ~/.xrpl-feedback/hook/setup.mjs
```

Answer the prompts. Team name and your name cannot be blank.

### AI agent

Do not launch the interactive prompt in a non interactive shell. Ask the developer for their team name and real name in chat, then:

```bash
TEAM_NAME="<their team>" \
HACKER_NAME="<their name>" \
node ~/.xrpl-feedback/hook/setup.mjs --non-interactive
```

Both write `~/.xrpl-feedback-hook.json` (owner only). Confirm it:

```bash
cat ~/.xrpl-feedback-hook.json
```

## Step 2: register with your agent (project scoped, not global)

Install the hook only for THIS project. Always use the project-local config file (inside the repo), never the global one in your home directory. This keeps the hook from firing in your other projects. `HOOK_DIR` is the absolute path to this repo's `hook` directory.

### Claude Code

Create or merge into `.claude/settings.json` at the PROJECT root (not `~/.claude/settings.json`), see `agents/claude-code/settings.snippet.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "node \"$CLAUDE_PROJECT_DIR/hook/agents/claude-code/stop-hook.mjs\"" }
        ]
      }
    ]
  }
}
```

`$CLAUDE_PROJECT_DIR` resolves to this project, so the path stays portable. Run `/hooks` to confirm it loaded.

### Cursor

Create or merge into `.cursor/hooks.json` at the PROJECT root (not `~/.cursor/hooks.json`), see `agents/cursor/hooks.snippet.json`:

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      { "command": "node HOOK_DIR/agents/cursor/stop-hook.mjs", "loop_limit": 2 }
    ]
  }
}
```

### Codex

Create or merge into `.codex/hooks.json` at the PROJECT root (not `~/.codex/hooks.json`), see `agents/codex/hooks.snippet.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "node HOOK_DIR/agents/codex/stop-hook.mjs", "timeout": 60 }
        ]
      }
    ]
  }
}
```

If you prefer inline config, use the `[[hooks.Stop]]` form in the project's `.codex/config.toml` from `agents/codex/config.toml.snippet` instead.

### VS Code Copilot

VS Code exposes a `Stop` hook, but unlike Claude, Cursor, and Codex it is not confirmed that its Stop hook re-invokes the model to run a command. So for VS Code use the instructions file as the primary, reliable mechanism, and optionally add the hook as a backup.

Primary (reliable): paste the block from `agents/vscode-copilot/copilot-instructions.snippet.md` into `.github/copilot-instructions.md` at the PROJECT root, replacing the path with `HOOK_DIR/submit.mjs`. Get the text with the path already filled in via `node HOOK_DIR/print-instruction.mjs`. Make sure Copilot can run terminal commands.

Optional backup: also register the Stop hook in `.github/hooks/xrpl-feedback.json` at the PROJECT root (see `agents/vscode-copilot/hooks.snippet.json`):

```json
{
  "hooks": {
    "Stop": [
      { "type": "command", "command": "node HOOK_DIR/agents/vscode-copilot/stop-hook.mjs", "timeout": 60 }
    ]
  }
}
```

VS Code also reads a project-level `.claude/settings.json`, so if you already set up the Claude Code hook there, it will pick that up too.

### Any other agent (fallback, for an AI installer)

If the agent is not one of the four above, do not give up. Work through this in order and set up the best mechanism the agent supports. The goal is unchanged: after each response the agent's own model reviews the turn and runs `HOOK_DIR/submit.mjs` when there is real XRPL feedback.

1. Identify the agent and find its hook or lifecycle docs. Search the web for its exact hook system, for example `"<agent name> hooks"`, `"<agent name> stop hook"`, `"<agent name> after response hook"`, `"<agent name> notify"`, `"<agent name> lifecycle"`, and `"<agent name> config file"`. Read the official docs, not blog summaries. You are looking for an event that fires when a turn or response finishes, and how to register a shell command for it.

2. If it has a stop / after-turn hook that runs a shell command:
   * If the hook can surface stderr or a block decision back to the model (most can, they mirror the Claude vocabulary), register the generic injecting hook:
     ```
     node HOOK_DIR/agents/generic/stop-hook.mjs
     ```
     Use whatever registration format that agent documents (JSON like `{"hooks":{"Stop":[{"type":"command","command":"..."}]}}`, a TOML `[[hooks.Stop]]` block, an argv notify program, and so on). Register it in the agent's PROJECT-scoped config (inside this repo), not its global config, so it only fires here. The generic hook injects via exit 2 + stderr and guards against loops with both `stop_hook_active` and a per-session cooldown.
   * If the hook instead expects a JSON stdout field to feed the model (like Cursor's `followup_message`), copy `agents/cursor/stop-hook.mjs` and rename the output field to match that agent's schema.

3. If the agent has no hook that can inject into the model, use its instructions or rules file (the file it always loads, for example `AGENTS.md`, `.rules`, a system prompt file, or a project instructions file). Get the exact instruction text and paste it in:
   ```
   node HOOK_DIR/print-instruction.mjs
   ```
   That prints the same reflection instruction, including the `submit.mjs` command and a direct curl fallback.

4. Always verify with the Step 3 tests below, then do one real end to end run and confirm a row lands (ask the organizer to check, or use the server's own read command).

The auth token is baked into `submit.mjs` and into the printed instruction's curl fallback, so no token setup is needed for any agent.

## Step 3: test

Test the submit path directly. A short string is rejected, a real one is sent:

```bash
node HOOK_DIR/submit.mjs --text "short"   # rejected, under 50 chars
node HOOK_DIR/submit.mjs --text "The XRPL testnet faucet returned a 500 twice with no retry guidance, so a first time developer cannot fund a wallet to start building."
```

Test that the hook injects (Claude example, no submission happens here, it only prints the instruction it would give Claude):

```bash
printf '%s' '{"hook_event_name":"Stop","stop_hook_active":false}' | node HOOK_DIR/agents/claude-code/stop-hook.mjs
echo "exit $?"   # exit 2 means it injected the instruction
```

## Controlling how often it fires

By default the check runs on about 20 percent of turns (`sample` defaults to 0.2). Each fired turn costs one extra reflection turn, so running on every turn is chatty and burns model quota. Tune it in `~/.xrpl-feedback-hook.json` (or `XRPL_FEEDBACK_SAMPLE`): set `"sample": 1` to run every turn, `"sample": 0.5` for half, or `"sample": 0` to pause it.

## Config reference

Read from env first, then `~/.xrpl-feedback-hook.json` (override path with `XRPL_FEEDBACK_CONFIG`).

| Key | Env var | Required | Purpose |
|---|---|---|---|
| `teamName` | `TEAM_NAME` | yes | Attached to every submission |
| `hackerName` | `HACKER_NAME` | yes | Attached to every submission |
| `feedbackUrl` | `FEEDBACK_URL` | no | Overrides the baked-in server URL |
| `feedbackToken` | `FEEDBACK_TOKEN` | no | Overrides the baked-in token |
| `sample` | `XRPL_FEEDBACK_SAMPLE` | no | 0 to 1, fraction of turns the check fires (default 0.2) |

The server URL and token are hardcoded in `submit.mjs`, so only team name and real name are required.

Scope: the hook registration is project scoped (it lives in this repo's `.claude`, `.cursor`, `.codex`, or `.github/hooks` config, so it only fires in this project). The `~/.xrpl-feedback-hook.json` config that holds your team name and real name is per user and shared across your projects, which is fine since the hook only runs here. To keep the config with the project instead, set `XRPL_FEEDBACK_CONFIG` to a path inside the repo.

## Safety notes

* The stop hooks never break a turn: on any parse problem or the loop guard they exit cleanly and let the agent stop.
* Loop protection: Claude and Codex use `stop_hook_active`, Cursor uses `loop_count` plus `loop_limit`, and VS Code adds a short per-session cooldown, so the reflection turn cannot recurse.
* `submit.mjs` validates 50 to 2000 characters and dedupes identical feedback within a session before sending.
* What leaves the machine: your team name, your name, and the feedback paragraph, sent only to the feedback server.

## Troubleshooting

* `missing config`: rerun setup, or check that `teamName` and `hackerName` are set in `~/.xrpl-feedback-hook.json`.
* `server returned 401`: the token is baked in, so this only happens if you overrode it with a wrong `feedbackToken`. Remove the override.
* Claude never continues after a turn: confirm the Stop hook is in the project's `.claude/settings.json` (not the global one) and the command points at `stop-hook.mjs`.
* Cursor loops: make sure `loop_limit` is set in the project's `.cursor/hooks.json`.
