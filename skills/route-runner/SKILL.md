---
name: route-runner
description: Runs and orchestrates predictable multi-step prompt routes (.route.md playbooks) with 100% attention allocation per step, interactive Stepping Deck HUD, deterministic safety gates, 4-tier branch swaps, and bounded auto-heal.
---

# Route Runner Skill

The **Route Runner** skill equips Antigravity agents to execute structured, multi-step prompt routes (`.route.md` playbooks) with surgical precision.

Instead of stuffing multiple objectives into a single massive prompt—which dilutes reasoning and invites regressions—Route Runner guides the agent through focused sequential steps where **100% of cognitive capacity** is dedicated to one clear goal at a time.

--------------------------------------------------------------------------------

## Core Principles

1. **100% Attention Allocation**: One step, one goal. Never juggle architecture, implementation, defensive edge cases, and visual polish in the same turn.
2. **Axiom of Non-Self-Attestation**: No agent grades its own homework. Progress between steps requires passing deterministic, objective gates—not probabilistic self-assessment.
3. **Bounded Auto-Healing**: If a step gate fails, the agent receives an immediate, targeted retry with the exact gate failure logs. If errors do not decrease between attempts, the circuit breaker immediately halts execution to prevent thrashing and save your tokens.
4. **Instant Branch Flexibility**: Every step includes ranked alternative strategies (Primary, QA Defensive, Alternative Architecture, Fallback) that can be swapped on the fly before or during execution.

--------------------------------------------------------------------------------

## Playbook Structure (`.route.md`)

Route playbooks are authored in plain, human-friendly Markdown with zero boilerplate:

```markdown
# Feature Shipping Route

1. Build the core data model and persistence interface.
   Implement the schema, data validations, and storage methods.
   Keep changes strictly scoped to data layer files.
   - *Quick Spike*: Implement in-memory dictionary storage first.
   - *QA Defensive*: Add strict invariant checks and schema validation.
   - *Fallback*: Build minimal flat-file JSON storage.
   - Assert: python3 -m pytest tests/test_models.py passes

2. Build the API endpoints and connect handlers.
   Expose CRUD operations with standard JSON request/response formats.
   - *Fast Prototype*: Stub out endpoints with mock responses.
   - *QA Defensive*: Add input sanitization and HTTP status code checks.
   - *Fallback*: Implement single dispatcher function.
   - Assert: python3 -m pytest tests/test_api.py passes
```

### Anatomy of a Step
- **Step Header**: Numbered item (`1.`, `2.`, etc.) with a concise title.
- **Primary Prompt**: The main instruction block executed by default.
- **Alternative Branches**: Indented bullet points with `*Rank Label*: prompt` (Ranks 1 to 4).
- **Assertions**: `Assert: <shell_command>` defining deterministic criteria for step completion.

--------------------------------------------------------------------------------

## How to Execute Routes

### Mode 1: Hands-Free Stop Hook (Recommended for Antigravity)

When configured in `.agents/hooks.json`, Antigravity intercepts the model stop event, runs the step gates, and automatically feeds the next step prompt directly into the agent's turn:

```bash
# 1. Enable the Stop hook in your project
cp hooks.json.example .agents/hooks.json

# 2. Launch your route
agy-route run playbooks/ship-feature.route.md --non-interactive
```

- When the model finishes a turn, `agy-route hook` evaluates syntax, tests, blast radius, and assertions.
- If gates pass: the hook returns `{"decision": "continue", "reason": "<next_step_prompt>"}`.
- If all steps are complete: the hook emits a clean milestone card and concludes the route.

### Mode 2: Interactive Stepping Deck HUD (CLI)

Run routes interactively in your terminal with real-time visual progress and keyboard controls:

```bash
agy-route run playbooks/ship-feature.route.md
```

#### Available CLI Flags
- `--dry-run`: Walk through the route without executing commands or modifying files.
- `--checkpoint <path>`: Specify a custom checkpoint file (default: `.agy-route-state.json`).
- `--non-interactive`: Run continuously without pausing for keyboard input between steps.
- `--swap <step_idx>:<rank>`: Pre-swap a step's branch before running (e.g., `--swap 0:2` selects QA Defensive for Step 1).

### Mode 3: Autonomous In-Session Agent Workflow

When acting as an autonomous pair programmer without a terminal daemon, the agent manages the route directly:

1. **Load and Validate Playbook**:
   ```bash
   agy-route validate playbooks/ship-feature.route.md
   ```
2. **Display the Stepping Deck HUD**:
   Present the HUD card to the user so they see the active step, completed milestones, and alternative options.
3. **Execute Active Step**:
   Focus 100% of tool actions on fulfilling the active step's primary prompt.
4. **Run Deterministic Step Gates**:
   Execute the assertions and verify AST integrity before advancing.
5. **Advance or Auto-Heal**:
   - If gates pass: advance to the next step and display the updated HUD.
   - If gates fail: trigger auto-heal retry with the error log.

--------------------------------------------------------------------------------

## The Stepping Deck HUD

The **Stepping Deck HUD** provides an optical, high-intent dashboard of route progress:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 🚀 AUTO-REPLY ROUTE: Ship Feature Route                                      │
│ State: RUNNING  │  Progress: [2/5] (40%)  │  Mode: LIVE                      │
│ Checkpoint: .agy-route-state.json                                            │
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
│                                                                              │
│   Alternative Branch Options (3):                                            │
│     [Rank 2: QA Defensive] Audit strictly for auth bypasses, injection, ...  │
│     [Rank 3: Alternative Arch] Audit resource bounds and memory leaks        │
│     [Rank 4: Fallback] Self-inspect full diff against quality checklist      │
├──────────────────────────────────────────────────────────────────────────────┤
│ CONTROLS: [Enter/c] Step  [s] Swap Branch  [p] Pause  [q] Quit               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### HUD Icons & Progression States
- `[✔ N]`: Step completed and verified through deterministic gates.
- `[▶ N]`: Step currently in flight.
- `[⏸ N]`: Step paused (by user request or circuit breaker).
- `[✖ N]`: Step failed or halted.
- `[⏳ N]`: Step queued and waiting.

--------------------------------------------------------------------------------

## 5-Layer Deterministic Safety Gating

Before any step is marked as complete, it must pass through the **Deterministic Gate Sieve**:

```
 ┌────────────────────────────────────────────────────────────┐
 │ Layer 0: AST Syntax Gate (Python, JSON, JS, TS)           │
 └────────────────────────────┬───────────────────────────────┘
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Layer 1: Compiler & Type Gate (tsc, pyright, mypy, cargo) │
 └────────────────────────────┬───────────────────────────────┘
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Layer 2: Test Delta & Anti-Cheat Gate (AST Scanner)        │
 └────────────────────────────┬───────────────────────────────┘
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Layer 3: Blast Radius Gate (≤15 files, no sensitive paths) │
 └────────────────────────────┬───────────────────────────────┘
                              ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Layer 4: Runtime Smoke & Assertions Gate (Shell tests)     │
 └────────────────────────────────────────────────────────────┘
```

### Layer Details
1. **Layer 0: AST Syntax Gate**:
   - Parses all modified `.py` files with Python's native `ast.parse()`.
   - Validates all modified `.json` files via `json.load()`.
   - Checks JavaScript/TypeScript files with `node --check` or heuristic bracket balancing.
   - Any syntax error immediately rejects the step.

2. **Layer 1: Type / Compiler Gate**:
   - If type checkers or compilers are present (`tsc`, `pyright`, `mypy`, `cargo check`), runs them on modified files.

3. **Layer 2: Test Delta & AST Anti-Cheat Gate**:
   - **Baseline Test Preservation**: Verifies the total number of passing tests has not decreased.
   - **AST Anti-Cheat Scanner**: Scans test files for forbidden modifications:
     - Trivialized assertions (e.g., replacing `assert res.status_code == 200` with `assert True`).
     - Commented-out test functions or assertion lines (`# def test_foo()`).
     - Injected `@pytest.mark.skip` or `@unittest.skip` decorators.
     - Tests hidden inside dead string literals or docstrings.

4. **Layer 3: Blast Radius Gate**:
   - Ensures the number of modified files stays within bounds (default: $\le 15$ files).
   - Enforces forbidden path protection: changes to `.git`, `.env`, lockfiles (`package-lock.json`, `poetry.lock`, `Cargo.lock`), or shell rc files (`.bashrc`, `.zshrc`) are hard blocked.

5. **Layer 4: Runtime Smoke Gate**:
   - Executes each assertion specified on the step (e.g., `Assert: pytest tests/ -v passes`).
   - Requires zero exit code from all assertions.

--------------------------------------------------------------------------------

## 4-Tier Branch Alternatives & Swapping

Every step can specify up to 4 ranked alternatives:

| Rank | Tier Name | Purpose | When to Use |
| :--- | :--- | :--- | :--- |
| **1** | **Primary** | The default, balanced implementation path. | Standard execution under normal conditions. |
| **2** | **QA Defensive** | Fortified invariants, defensive error handling, input validation. | Mission-critical flows, public APIs, or after edge-case bugs. |
| **3** | **Alternative Arch / Spike** | Minimal prototype, performance refactor, or decoupled design. | When dependencies are missing or rapid validation is needed. |
| **4** | **Fallback** | Zero-dependency or manual verification fallback. | When standard tools/browsers are unavailable in the environment. |

### How to Swap Branches
- **Interactive CLI**: Press `s`, enter step number and target rank (e.g., `1 2` to switch Step 1 to Rank 2).
- **CLI Startup**: Add `--swap <step_index>:<rank>` (e.g., `agy-route run playbook.route.md --swap 0:2`).
- **Python API**:
  ```python
  from auto_reply_route.state_machine import RouteStateMachine
  sm = RouteStateMachine.load_checkpoint(".agy-route-state.json")
  sm.swap_branch(step_index=0, target_rank=2)
  sm.save_checkpoint(".agy-route-state.json")
  ```

--------------------------------------------------------------------------------

## Bounded Quarantine Auto-Heal & Circuit Breakers

When a gate check fails, Route Runner does not crash or give up—it activates **Quarantine Auto-Healing**:

```
Gate Failure ──> Attempt 1: Injected Error Prompt ──> Agent Fixes Issue
                      │
                      ├─ Errors = 0 ──> ✅ Gate Passes ──> Advance Step
                      │
                      ├─ Errors < Previous ──> Attempt 2: Final Retry Allowed
                      │
                      └─ Errors ≥ Previous ──> 🛑 Divergence Circuit Breaker Trips!
                                               Route Pauses, Human Notified
```

### Auto-Heal Rules
1. **Shot 1**: The failure log is injected directly into the agent's turn:
   ```
   [AUTO-HEAL ATTEMPT 1] Gate check failed: Layer 0 (AST Gate) failed: 1 syntax error(s) detected in src/api.py at line 42. Fix this issue.
   ```
2. **Shot 2 (Divergence Check)**:
   - If the error count decreases (e.g., from 3 errors down to 1), Shot 2 is granted.
   - If the error count stays the same or increases, the **Divergence Breaker** trips immediately (`DIVERGENCE_HALT`).
3. **Retry Exhaustion**: After 2 unsuccessful retries, execution halts (`EXHAUSTED_HALT`).

### Living-Room Explanation
When a circuit breaker trips, Route Runner writes a warm, human-friendly explanation following the **Zero Plumbing Law**:

> **We paused on Step 2 because the tests need a quick look. Your changes are safely saved.**
>
> We noticed 2 test issues on the latest try, which is more than the 1 issue before. Rather than continuing in circles, we paused so you can take a look.
>
> **What you can do:**
> 1. Check the test output above or run `python3 -m pytest tests/`.
> 2. When you are ready, press `resume` or run `agy-route run playbooks/ship-feature.route.md` to keep going.

--------------------------------------------------------------------------------

## Offline Route Mining

Extract successful prompt sequences from past conversation transcripts to build fresh, reusable playbooks:

```bash
# Mine all routes from default Antigravity conversation brain
agy-route mine --output playbooks/my-mined-route.route.md

# Mine specific transcript files
agy-route mine -t ~/.gemini/antigravity/brain/*/transcript.jsonl -o playbooks/custom.route.md
```

The miner normalizes prompt texts, clusters intent sequences using Markov transition models, balances diversity, and exports valid `.route.md` files ready for execution.

--------------------------------------------------------------------------------

## Agent Operational Checklist

When executing a route playbook:
- [ ] Validate playbook syntax before starting: `agy-route validate <playbook>`.
- [ ] Confirm active step and read the primary instruction carefully.
- [ ] Keep file modifications strictly confined to the active step's scope.
- [ ] Never modify or bypass test assertions to fake a pass.
- [ ] Run assertions locally before yielding turn: `eval "$(cat assertions)"`.
- [ ] If a gate fails, inspect the exact error line and fix root cause immediately.
- [ ] If the circuit breaker halts, present a friendly living-room update to the user.
