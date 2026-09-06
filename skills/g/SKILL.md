---
name: g
description: "End-of-turn adaptive guidance engine. Executes the user's task first, inspects actual findings or test results, and delivers the single best next prompt in operator's voice. Usage: /g [task] or /g"
---

# /g Adaptive Guidance Engine (End-of-Turn Steerer)

## Coding rule (both hosts)

For coding work, understand the affected flow first. Reuse existing code or
platform capabilities before adding anything. Make the smallest clear change
that satisfies the request. Preserve essential safeguards and meaningful
verification. Before advancing, check for unnecessary complexity introduced by
this step.

Apply this before implementing the user's task and briefly before finishing each
coding step, within the current turn. It adds no queued turns or separate review
phase. `/q` still stages its prompts first; review-only work stays review-only.

In **Codex**, read [Codex delivery](references/codex.md) and follow that path.
It retains end-of-turn adaptive prompt selection and uses Codex's native queue.
The instructions below are the existing **Antigravity** delivery path.

When the user types `/g [task]` or simply `/g`:

## Invariant 1: Zero Upfront Staging (Keep Tray Clean)
- **NEVER** call queue_paster or stage follow-up prompts into the tray at the start of the turn.
- The queue tray MUST remain clean while the turn executes.

## Invariant 2: Execute First
- Immediately execute the requested task in the current turn:
  - If the user requested an audit, human testing, or document generation, perform it thoroughly.
  - If subagents were requested (e.g. 3 sub), launch those subagents now.
  - Deliver complete, high-signal results.

## Invariant 3: End-of-Turn Adaptive Evaluation & Automatic Dispatch
- At the very end of your response, inspect reality:
  - What were the actual findings, test failures, or blockers?
  - Do NOT just assume success—look at the empirical facts.
- Consult Operator DNA (`~/.gemini/config/operator_dna.md` or `~/.gemini/config/personal_dna.md`).
- Synthesize the single high-leverage next prompt in the operator's voice (terse, 10–25 words, living-room English).
- **Check Step Budget & Termination:**
  - If current turn reached the step budget ($k \ge N$) OR all tasks are verified complete:
    Output `DONE: All requirements satisfied.` and do NOT call `queue_paster`. Stop cleanly.
- **Prefix with `/g` for Turn-to-Turn Continuity:**
  - Prepend `/g (Step k+1/N)` to the synthesized prompt so that the next turn also knows to evaluate and steer!
  - Example: `/g (Step 2/6) wire the for-agencies preview form to db and email alerts so partner leads stop evaporating`
- **CRITICAL: ACTUALLY SEND THE PROMPT:**
  Do NOT just print the prompt in markdown! You MUST dispatch the prompt via `run_command` so it is delivered directly into the originating conversation mailbox without stealing window focus or switching active chats:
  ```bash
  python3 -c '
  import sys
  sys.path.insert(0, str(__import__("pathlib").Path.home() / ".gemini/config/scripts"))
  from queue_paster import dispatch_prompt_to_conversation
  receipt = dispatch_prompt_to_conversation("<prefixed_prompt>")
  print("✔ Dispatched to", receipt["recipient"], ":", receipt["id"])
  '
  ```
  *(Note: `queue_prompts_into_antigravity(prompt="...", custom_prompts=["<prefixed_prompt>"])` also automatically detects the originating conversation ID and routes via targeted delivery).*
  This triggers Turn 2 automatically without switching windows or polluting other chats!
