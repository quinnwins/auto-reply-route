# Follow-up selection in T3 Code

Apply this in T3 Code, including to a worker producing a deliverable when its assignment permits an independent reviewer. Reviewers finish their assigned review without starting another reviewer. Follow the caller's latest instructions, including stop, scope, work-alone requests and limits on child agents. Leave a named workflow in control.

Choose the path that fits the user's request:

- Answer a simple question or perform a purely mechanical change directly.
- For a substantive deliverable that requires checking records or using a feature, select one independent review, even for short output. As the first available tool action run `python3 ~/.grok/hooks/grok_followup.py review`, then complete the task. If the command confirms the selection, Grok's Stop hook will ask for the review. If it reports hooks unavailable in this workspace, complete the deliverable and start the permitted read-only reviewer in this turn, before delivering the final answer. Use one fresh native Grok subagent, give it the original request and the minimum relevant evidence, and wait. Fix and verify any concrete in-scope omission. If the user asked to work alone or another workflow already reviews this result, finish normally.
- For sustained work whose next action depends on findings, choose an adaptive workflow. Do and verify what you can now. If one specific authorized core step still needs a continuation, run `python3 ~/.grok/hooks/grok_followup.py next` immediately before stopping. Grok can continue in this same thread up to four times. Stop when verified, genuinely blocked, interrupted, or at the limit. If native continuation is unavailable, do remaining authorized work now and report any real blocker.

These instructions give no extra permissions for tools or external actions. If an independent reviewer is unavailable, report that limitation.
