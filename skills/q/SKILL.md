---
name: q
description: "Stage bespoke follow-up prompts upfront in the native Codex or Antigravity queue, then execute the initial request. Usage: /q [task]."
---

# /q Fast Queue Stager & Unified Executor (Operator DNA Engine)

## Coding rule (both hosts)

For coding work, understand the affected flow first. Reuse existing code or
platform capabilities before adding anything. Make the smallest clear change
that satisfies the request. Preserve essential safeguards and meaningful
verification. Before advancing, check for unnecessary complexity introduced by
this step.

Apply this before implementing the user's task and briefly before finishing each
coding step, within the current turn. It adds no queued turns or separate review
phase. `/q` still stages its prompts first; review-only work stays review-only.

## Codex: stage first

For an initial `/q`, `\q`, or `$q` request, stage immediately after reading this
skill. Use the request and conversation already in context to choose concise,
bespoke follow-ups. The **first tool call after loading this skill must stage the
batch**: don't read another reference, inspect the repo, load DNA, plan, or spawn
subagents first. Those can happen after queue acceptance. Exception: resolve a
missing objective, conflicting authorization, or an existing unfinished batch.

Helper: `~/.codex/skills/q/scripts/codex_q.py` (or `scripts/codex_q.py` relative to
the installed skill). In one tool call write the original objective to a UTF-8
text file and ordered prompts to a JSON array, then execute:

```
python3 <helper> stage --objective-file <file> --prompts-file <json-file>
```

Default: five follow-ups. An explicit follow-up count overrides it; an explicit
**total-turn** count includes the initial answer. Keep the user's requested
subagents in the prompts but launch them only after staging. Never broaden scope.
Check for `status: initial` and the native receipt IDs. Immediately show the actual
queued prompt texts in a concise commentary list, then do the original work and
call `finish --step 0` before its final answer. This list gives immediate visibility
but is not a native queue chip. Do not claim that chips were displayed.

For `/q (Follow-up k/N)`, `/q stop`, or any delivery error, read
[Codex lifecycle details](references/codex.md). Existing follow-ups enter their step;
they never stage a new batch. Do not retry an uncertain delivery automatically.

## Antigravity

The instructions below retain the existing Antigravity delivery path.

When the user types `/q [prompt]`, `/q <prompt> <M> sub`, or `/q <N> (<M> subagents) <prompt>`:

The agent MUST perform two actions in the SAME turn:

---

## Action 1: Stage Follow-Up Prompts into Native Queue (First 1.5s)
1. **Parse Arguments:**
   - Seed prompt: the user's core task/idea.
   - Step count: `<N>` (default: 5).
   - Subagents: `<M>` if specified (e.g. `(3 subagents)` or `5 sub`); default is 0 for the queued follow-up prompts unless explicitly requested.
2. **Synthesize Follow-Up Trajectory (Grounded in History & Anti-Tower-of-Babel):**
   - **Session-History Grounding:** Inspect the last 2–5 turns in this chat: what did the user originally ask for, what code/tests actually ran, and what failed?
   - **Anti-Tower-of-Babel:** Forbid speculative abstractions, bloated class hierarchies, or generic plugin frameworks. Every prompt must demand the most direct, least-complicated solution first.
   - **Rabbit Hole Breaker:** If a previous turn got distracted by a tangential issue (e.g. obscure linter warnings on untouched files or hypothetical edge cases), pull execution directly back to the primary North Star.
   - **Trajectory Mapping:** Using the Operator DNA Matrix (`~/.gemini/config/operator_dna.md` or `~/.gemini/config/personal_dna.md`), dynamically generate `<N>` bespoke follow-up prompts:
     - For 2–3 steps: Build ➔ Harden & Edge Cases ➔ Real Test Verification.
     - For 5 steps: Phase 1 Refutation ➔ Phase 2 Minimal Spike ➔ Phase 3 Feasibility ➔ Phase 4 Go/No-Go Attack ➔ Phase 5 Synthesis.
3. **Stage into Visible Queue:**
   Execute immediately via `run_command` without reading files, inspecting git, or planning first:
   ```bash
   queue_paster "<idea>" -n <N> -s <M> --delivery-mode gui
   ```
   Or with bespoke prompts:
   ```bash
   python3 -c '
   from auto_reply_route.queue_paster import queue_prompts_into_antigravity
   prompts = [...] # your bespoke prompts
   queue_prompts_into_antigravity(prompt="<idea>", steps=<N>, subagents=<M>, countdown_seconds=0.2, delivery_mode="gui", custom_prompts=prompts)
   '
   ```
   All follow-ups now sit in the visible **`Queued Messages`** tray above the chat bar.

---

## Action 2: Fully Execute the User's Original Prompt (Same Turn)
**NEVER stop or conclude the turn after just staging the prompts! The user's original request must be answered and executed.**
1. **Execute the Requested Task:**
   - Immediately proceed to work on the user's initial prompt in this turn.
   - If the user requested subagents (e.g. `5 sub`, `with 3 subagents`), invoke those subagents NOW to perform the requested analysis, research, or audit.
2. **Deliver Results:**
   - Provide the complete findings, synthesis, or solution for the initial prompt.
3. **Seamless Transition:**
   - When this turn concludes, Antigravity automatically pops Step 1 from the queue tray and proceeds to the next phase. Nothing is lost!

---

## Relationship with /g
- **/q** is strictly for **upfront multi-step queue staging** (pre-loading the tray).
- For **end-of-turn adaptive guidance** (executing first, then evaluating results to pick the next step), use the **/g** command.
