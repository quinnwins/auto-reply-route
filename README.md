# Auto-Reply Route (`/q` & `/g`) ⚡

[![CI](https://github.com/quinnwins/auto-reply-route/actions/workflows/ci.yml/badge.svg)](https://github.com/quinnwins/auto-reply-route/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Dependencies: Zero](https://img.shields.io/badge/runtime%20dependencies-0-success.svg)](pyproject.toml)

> Adaptive follow-up prompts for **Codex desktop and Google Antigravity**. Use `/g` to choose the next step after each turn, or `/q` to queue several follow-ups before starting your task.

---

## The Problem: The "Babysitting Tax"

When building real software with AI pair programmers, developers face three compounding frustrations:

1. **The Compound Prompt Trap:** You pack 5 complex tasks into one prompt (*"Write the API, review edge cases, check security, write tests, and verify styling"*). The model gets overwhelmed, drops instructions, and hallucinates that everything is finished.
2. **The Turn-by-Turn Babysitting Tax:** You break tasks down manually. But now you must sit at your desk playing ping-pong with the chat box—waiting 60–90 seconds per turn, typing the next obvious follow-up (*"now write tests"*, *"now check edge cases"*, *"now run pytest"*).
3. **The Synthetic Tone Clone Trap:** Re-prompting with generic templates results in bloated, overly academic responses that ignore your engineering standards and waste context tokens.

**Auto-Reply Route** gives you back your time with three tightly integrated capabilities:
- **Prompt Queuing (`/q`)**: Chooses and stages several follow-ups upfront, then executes the initial task. Codex uses its native CLI queue; Antigravity uses its visible **Queued Messages** tray.
- **Adaptive Guidance Engine (`/g`)**: Executes your request first, evaluates live test logs and tool results at turn conclusion, and dispatches the single next best move in your voice.
- **Operator DNA Bootstrapper (`agy-route init-dna`)**: Auto-creates your personal `operator_dna.md` by parsing `AGENTS.md` and mining your genuine prompt history from Antigravity session transcripts.

---

## Quick Start: Codex desktop

Requires Python 3.9+, Git, and a Codex desktop runtime with a working
`codex queue` command. Check availability with `codex queue --help`.

```bash
git clone https://github.com/quinnwins/auto-reply-route.git
cd auto-reply-route
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/g" ~/.codex/skills/g
ln -s "$PWD/skills/q" ~/.codex/skills/q
```

Keep the checkout in place: the skills link to its helpers. If you already have
skills named `g` or `q`, inspect them before installing; do not overwrite them.
No package installation or transcript mining is needed for the Codex helpers.

Open a new Codex task and try:

```text
/g fix the failing tests and verify the fix, with 3 total steps
```

`/g` does the work first, then chooses one follow-up from actual results before
its final answer. It continues in the same task, stopping at verified completion
or the step limit. The default is five total turns, including the initial turn.

```text
/q build a small calculator and verify it, with 3 follow-ups
```

`/q` stages the follow-ups upfront, then starts the initial task. Three follow-ups
means four turns total. Its default is five follow-ups plus the initial turn.
Use `/g stop` or `/q stop` to pause the corresponding loop.

**Codex limitation:** automatic follow-up execution works through `codex queue`,
but this integration does **not** populate the desktop's native composer chips.
For `/q`, the agent prints the staged prompts in commentary. Prompt generation
still takes model time. Follow-up turns also consume your normal Codex usage.

See [the Codex guide](docs/CODEX.md) for delivery, pause behavior, budgets, and
verification details. The Antigravity-specific behavior below does not apply to
Codex.

## Quick Start: Antigravity

```bash
git clone https://github.com/quinnwins/auto-reply-route.git
cd auto-reply-route
pip install -e ".[dev]"

# Bootstrap preferences from local rules and Antigravity transcripts
agy-route init-dna --mine

# Run the test suite
make test
```

---

## Antigravity Mode 1: Fast Queue Stager (`/q`)

Pre-stage multi-step follow-ups directly into Antigravity's visible **Queued Messages** container in 1.5 seconds.

### How It Works

1. In Antigravity chat, type:
   ```text
   /q Refactor database connection pool 3 sub
   ```
2. In **<1.5 seconds**, the next logical steps are synthesized and staged directly into Antigravity's native queue tray via fast AppleScript clipboard injection.
3. The initial task starts executing immediately in the current turn.
4. When the turn concludes, Antigravity automatically pops Step 1 from the queue tray and continues uninterrupted.

### Natural Syntax & Modifiers

- **Basic prompt:**
  ```text
  /q Build Stripe webhook endpoint
  ```
- **With subagent teams:** Add `<N> sub` or `<N> subagents` to launch dedicated worker teams:
  ```text
  /q Audit authentication flow 3 sub
  ```
- **Custom step count:** Append `<N> steps` to customize trajectory length (default: 5):
  ```text
  /q Investigate memory leak 3 steps
  ```

### Domain-Aware Engineering Trajectories

Prompts are mapped to their true operational domain—never forcing venture-capital questionnaires onto routine feature work or bugfixes:

- **Software Engineering & Features (Default):** Architecture & Flow Invariants ➔ Core Working Implementation ➔ Slop Pruning & Clean Refactoring ➔ Boundary Probes & Automated Tests ➔ Operational Walkthrough.
- **Bugfixing & Defect Repair:** Empirical Root Cause ➔ Minimal Repro Test ➔ Surgical Blast-Radius Fix ➔ Concurrency & Invariant Probe ➔ Zero-Regression Verification.
- **UI / Craft Polish:** Ergonomics & 44px Tap Hitboxes ➔ Transitions & Responsive Layout ➔ Plain Everyday Microcopy ➔ Screenshot Verification ➔ Design Walkthrough.
- **Venture & 0-to-1 Inventions (Explicit Venture Prompts):** Physical / Constraint Refutation ➔ Minimal Feasibility Spike ➔ Investment & ROI Reality Check ➔ Adversarial Go/No-Go Audit ➔ Executive Synthesis Memo.

### CLI & Offline Preview (`queue-paster`)

Run standalone offline in your terminal without any active LLM session or API key:

```bash
# Preview generated prompts without touching clipboard or sending keystrokes
queue-paster "implement OAuth2 authentication flow" --dry-run

# Output structured JSON for automation or shell pipelines
queue-paster "reconcile daily worker logs" --json --steps 3

# Explicitly override domain if desired
queue-paster "audit responsive layout" --domain ux --steps 3 --dry-run

# Optional AI synthesis via Gemini Flash (fails open to deterministic templates)
queue-paster "refactor billing webhooks" --ai --steps 4 --dry-run
```

---

## Antigravity Mode 2: Adaptive Guidance Engine (`/g`)

Unlike `/q` (which stages upfront), `/g` provides **end-of-turn adaptive guidance**:

1. **Zero Upfront Staging:** The queue tray stays completely clean while the turn executes.
2. **Execute First:** The agent executes your task first (runs audits, executes subagents, runs tests).
3. **End-of-Turn Evaluation:** At the conclusion of the turn, the controller inspects actual test failures, logs, or findings.
4. **Autonomous Next Prompt Dispatch:**
   - Formulates the single highest-leverage prompt in your operator voice (10–25 words, living-room English).
   - Prepends `/g (Step k/N)` for turn-to-turn tracking.
   - Pushes it into Antigravity so the next turn starts automatically.
   - Halts cleanly with `DONE: All requirements satisfied.` when the step budget is exhausted or all tests pass.

```bash
# Example invocation in Antigravity:
/g run unit tests and fix all regressions
```

---

## Mode 3: Operator DNA Bootstrapper (`init-dna`)

Prevent prompt queues from degrading into generic AI assistant slop. The bootstrapper builds your personal coding DNA:

```bash
# Auto-discover AGENTS.md rules and mine recent session transcripts
agy-route init-dna --mine

# Inspect or customize your generated DNA
cat ~/.gemini/config/operator_dna.md
```

### What It Does
- **Ingests `AGENTS.md` Invariants:** Extracts simplicity laws, living-room test criteria, anti-tower-of-babel rules, and anti-patterns.
- **Mines Genuine Prompts:** Uses `PromptMiner` to extract authentic user phrasing from past `transcript.jsonl` files while quarantining AI responses.
- **Strict Token Budget:** Limits total footprint to `<3,000` characters and `≤10` rules per section with sub-50ms linear scan performance.

---

## Mode 4: Playbook Route Execution (`agy-route run`)

Author predictable engineering workflows in plain Markdown and execute them with real-time HUD telemetry.

Save your playbook as `playbooks/my-feature.route.md`:

```markdown
# User Profile Route

1. Build the profile data model and migrations.
   Create clean schemas for user preferences, avatar storage, and notification settings.
   - *Quick Spike*: Build minimal in-memory SQLite schema first.
   - *QA Defensive*: Add strict check constraints and email format invariants.
   - *Safe Fallback*: Export raw SQL migration script.
   - Assert: python3 -m pytest tests/test_models.py passes

2. Build API endpoints and input validation.
   Create standard GET and PUT routes for profile settings.
   - *Mock First*: Return stubbed data for rapid UI testing.
   - *QA Defensive*: Validate request bodies and sanitize text inputs.
   - *Safe Fallback*: Implement single dispatcher handler.
   - Assert: python3 -m pytest tests/test_api.py passes

3. Polish settings screen and verify responsive layout.
   Ensure input fields are accessible and buttons have 44px tap hitboxes.
   - *Micro Polish*: Add smooth loading states and field focus rings.
   - *Mobile First*: Verify touch layout on 375px screens.
   - *Safe Fallback*: Verify basic HTML layout without styling.
   - Assert: npm test passes
```

### Execute the Playbook

```bash
# Run interactively with Stepping Deck HUD
agy-route run playbooks/ship-feature.route.md

# Run autonomously without pausing between steps
agy-route run playbooks/ship-feature.route.md --non-interactive
```

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 🚀 AUTO-REPLY ROUTE: Ship Feature Route                                      │
│ State: RUNNING  │  Progress: [2/5] (40%)  │  Mode: LIVE                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ DECK PROGRESSION:                                                            │
│   [✔ 1] ──> [▶ 2] ──> [⏳ 3] ──> [⏳ 4] ──> [⏳ 5]                           │
├──────────────────────────────────────────────────────────────────────────────┤
│ ▶ ACTIVE STEP 2: Review implementation with 3-agent QA team and fix defects  │
│                                                                              │
│   Primary Instruction Prompt:                                                │
│     Conduct multi-perspective code inspection focusing on edge cases, race   │
│     conditions, and error recovery. Fix all discovered bugs immediately.     │
│                                                                              │
│   Assertions (1):                                                            │
│     ✔ git diff --check passes                                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Built-in 2-Shot Bounded Auto-Heal

When a step assertion fails:
1. **Targeted Retry (Shot 1):** Feeds compiler/test failure logs back for an immediate fix.
2. **Progress Check (Shot 2):** If errors decreased (e.g. 4 errors down to 1), permits an additional retry.
3. **Circuit Breaker:** If errors diverge or persist, execution halts cleanly. Zero infinite loops, zero runaway token spend.

---

## Offline Route Miner & Sanitizer

Turn successful Antigravity pairing sessions into reusable `.route.md` playbooks while redacting all sensitive data:

```bash
# Mine past chat transcripts into a fresh playbook
agy-route mine --output playbooks/mined-feature.route.md
```

The miner automatically scrubs:
- AWS, GitHub, Stripe, and OpenAI API tokens
- Bearer authentication headers and private keys
- Passwords and connection URIs
- Personal emails, phone numbers, and SSNs

---

## CLI Reference

| Subcommand | Description |
| :--- | :--- |
| `agy-route init-dna` | Bootstrap Operator DNA matrix from `AGENTS.md` and user transcripts |
| `agy-route queue` | Manage, inspect, add, pop, or clear active queued messages |
| `agy-route watch` | Live-tail active queued messages with Unicode progress cards |
| `agy-route run` | Execute a `.route.md` playbook with Stepping Deck HUD |
| `agy-route validate`| Validate syntax, assertions, and branches of a route file |
| `agy-route mine` | Mine transcripts for prompt trajectories and sanitize credentials |
| `agy-route build` | Generate prompt matrices across 1–12 phases with subagent teams |
| `agy-route hook` | Antigravity Stop hook entry point (stdin/stdout JSON protocol) |
| `agy-route init` | Initialize Antigravity hooks and skills in current workspace |

---

## Essential Make Commands

| Command | Description |
| :--- | :--- |
| `make test` | Runs the full pytest suite |
| `make validate` | Lints and validates canonical `playbooks/ship-feature.route.md` |
| `make init-dna` | Bootstraps Operator DNA matrix |
| `make queue` | Lists active queued messages in terminal |
| `make watch` | Renders a one-shot queue status card |
| `make install` | Installs the package in editable mode via pip |

---

## License

MIT © [quinnwins](LICENSE)
