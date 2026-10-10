---
name: queue-prompts
description: Stages multi-step follow-up prompts directly into Antigravity's native visible 'Queued Messages' tray without requiring the terminal. Use whenever the user asks to queue follow-up prompts, stage turns, or break an idea into sequential subagent phases in the Antigravity UI.
---

# Antigravity Queue Prompts Skill

This skill allows Antigravity agents to populate the native **`Queued Messages (N) — Sends after agent finishes working`** container in the Antigravity desktop app.

## When to Activate
Activate this skill whenever the user says:
- "Queue N follow-ups for [idea]"
- "Stage follow-up prompts for [idea]"
- "Break this project into queued prompts with N subagents"

## How It Works (100% Inside Antigravity)
1. The user asks to queue follow-ups right here in the Antigravity chat.
2. The agent runs the queue stager tool:
   ```bash
   python3 -m auto_reply_route.queue_paster "<idea>" --steps <N> --subagents <M> --countdown 0
   ```
3. Because the agent's turn is currently active, Antigravity automatically captures each submitted prompt and stacks it into the visible **`Queued Messages`** card above the chat bar.
4. The user sees all upcoming prompts with edit (pencil) and delete (trash) icons.
5. Once the agent concludes the turn, Antigravity automatically pops Step 1 from the queue and runs it as an isolated turn with dedicated subagents.
