---
name: t3-followup
description: For interactive T3 user requests, answer simple questions directly. For large changes with consequential open scope, consult council before implementation. Before returning a bounded source-based handoff, report, or fix, have one fresh read-only reviewer on the same provider check the original request, source evidence and actual draft for omissions and invented duties. Give only the authorized context. Fix material gaps in scope and verify. If no reviewer is available, say so and check the evidence yourself. For dependent stages, continue the original task through verified completion or a real blocker. Honor explicit opt-outs and skip delegated reviews and background text helpers.
---

# Follow-up selection for T3 Antigravity

The user has opted into choosing one workflow for each interactive T3 request. Explicit instructions, a stop request, a named or existing verification workflow and any limits on tools or delegation take precedence. Use this policy only in an interactive T3 chat.

- **Direct answer.** Finish simple questions, status checks and mechanical edits directly. For requested titles, summaries and other constrained text generation, return the requested text.
- **Council for scoping.** For a large change with an open decision that would materially alter the scope or approach, use council before choosing a plan or implementing it. For example, two credible redesigns would change different user flows. Only the top-level interactive T3 agent with `delegate_task` takes this path. Read the council skill at `~/.claude/skills/council/SKILL.md` and follow its planning rounds with the configured seats. Use the result for the authorized work. This choice needs no completion review or adaptive follow-through. A settled rollout, a large mechanical edit, or a discussion about council routing does not trigger it.
- **Completion review.** For a bounded deliverable that needs source reconciliation or a real behavior check, do the work first. Before handing it back, ask one fresh reviewer on the current provider to check the original request against the actual artifact and relevant evidence. Give the reviewer a read-only brief, with only the context it needs. Follow the native or T3 delegation contract for the current chat. If a reviewer already verified this result, respect that verdict. Correct any material gap that falls within the request and verify the correction. If independent review is unavailable, say which evidence you checked yourself.
- **Adaptive follow-through.** When later steps depend on what you find, finish the next authorized step, inspect the result, and repeat until you have verified the requested outcome or reached a genuine blocker. Use the current ACP task. Respect a user-specified step limit, and stop when the user pauses or changes direction.

Generated next steps inherit the original permissions. Keep decisions, account changes, and external actions within what the user authorized.
