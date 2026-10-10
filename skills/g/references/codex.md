# /g in Codex desktop

Use the native `codex queue` command through the helper below. It queues for after
the final answer. `send_message_to_thread` steers the active turn and is unsuitable.
No Stop hook, clipboard access, background worker, or extra model call is needed.

The helper is `../scripts/codex_g.py`, relative to this reference. Resolve its full
path from the skill you loaded. In a linked user installation it is
`~/.codex/skills/g/scripts/codex_g.py`. Invoke it with Python 3.9 or newer.

## Start and do the work

Only start when the user invokes `/g`, `$g`, or explicitly asks for this adaptive
loop. Merely discussing the skill does not start a run. A plain `/g` uses the
current unfinished objective; if nothing remains, answer without starting.

For `/g stop`, read `status`, call `finish --step <current step> --reason paused`,
and stop. Do not interpret `stop` as a new objective. If no run exists, say so.

Write the user's objective to a temporary text file and call:

```
python3 <helper> start --objective-file <file> --steps 5
```

Use the user's requested total step budget; otherwise use five steps, including
this first turn. Limits from 1 to 12 are supported. Do not extend a budget yourself.
Starting records state only; it queues nothing.

For a received `/g (Step k/N)` follow-up, call `enter --step k` first. If it fails,
stop without executing the queued work. Read the returned original objective and
keep the work inside it. Do not start a new run for a continuation.

Do the requested work completely. Respect later user corrections. If the user
stops the loop, call `finish --step k --reason paused` and do not stage more work.
Pausing prevents the helper from executing a pending continuation; it does not
delete a native queued item. Use the desktop's native queue controls to remove
one if desired. Do not claim that you removed it without proof.

## At the end, choose one next step

After the work and verification, inspect actual results and the last few user
messages. Consult operator DNA if available. Generate a terse 10–25 word prompt
that addresses the most useful remaining work. The agent supplies the judgment;
the helper never generates canned next steps.

Before queueing, confirm the next action stays within the user's authorization.
An audit does not become permission to implement, and generated prompts do not
authorize commits, production changes, purchases, or messages to other people.
If a decision requires the user, pause and explain it. No automatic follow-up.

### Decide whether the objective is actually complete

Before finishing, compare the original objective with the results and any gaps
you are about to report. A known unfinished **core** check is remaining work,
even if the implementation compiled. Do not mark `complete` while saying the
primary interaction is "untested", "not verified", or "still needs checking".

For an interactive webpage, a successful build, typecheck, or HTTP 200 proves
neither rendering nor its primary interaction. Use an available browser to inspect
the page and exercise that interaction before declaring the working page complete.
This is a focused check, not a request for a full UX audit or unrelated hardening.

- If a core check remains and can be done now, do it in this turn.
- If a core check remains for the next turn and budget remains, make that check
  the adaptive follow-up. Do not end the run merely by disclosing the gap.
- If a core check requires unavailable access or a user decision, pause and name
  the blocker with `finish --step k --reason paused`. If the step budget is
  exhausted, use `finish --step k --reason limit` and report the gap.
- If the requested outcome and its core checks are verified, call
  `finish --step k --reason complete`, including for early completion. Optional
  future improvements are not blockers.

The helper records your decision; it does not independently establish that the
page works. Do not fill a step budget just to consume turns, or claim completion
because a budget is available or exhausted.

Otherwise write the next prompt as plain text to a temporary file and call:

```
python3 <helper> stage --step k --prompt-file <file>
```

The helper adds `/g (Step k+1/N)` and binds delivery to `CODEX_THREAD_ID`. Never
override task identity or use another task's state. It returns a native message
ID only after Codex acknowledges queueing. If the CLI cannot be found, supply
`--codex-bin` with the installed runtime supporting `codex queue`.

Stage exactly one prompt as the last substantive action, immediately before the
final answer. Then finish promptly with the results and, when helpful, a short
“Next: …” sentence. Do not wait on your own queue or do more work after staging.
The desktop owns the pending-message UI; do not render a fake chip or claim
visual verification from the CLI receipt.

If delivery is uncertain, report it and stop. Do not automatically retry, switch
delivery mechanisms, or mark the run complete. `status` shows the saved state.
On an interrupted run or removed queue item, check that state before restarting.
