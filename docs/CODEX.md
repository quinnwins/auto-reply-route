# /g and /q in Codex desktop

`/g` does the requested work, checks what actually happened, and queues one
tailored follow-up immediately before its final answer. Codex runs that message
as the next turn in the same task. Nothing is staged at the start of the work.

The implementation uses the installed CLI's `codex queue --thread … --message …`.
It does not use simulated typing, the clipboard, a Stop hook, another model, or a
separate background service. Native `send_message_to_thread` was tested and steers
an active turn instead, so it is deliberately not used.

`/q` uses the same native transport to stage several follow-ups **upfront**, then
does the original work. Each queued message runs as a separate subsequent turn.
The agent chooses the sequence from your objective and context before starting;
each follow-up still checks actual results and your latest instructions.

The initial `/q` path makes staging its first tool call after reading the skill,
before project inspection, extra references, or subagents. It then prints the actual queued
prompts in commentary so they are visible while the initial work runs. This text
preview is not a native chip. Skill loading and prompt generation still take
model time; this is not an instantaneous app-side slash-command handler.

**Desktop chip limitation:** the inspected desktop version stores composer chips
in a separate `queued-follow-ups` queue and opts out of backend queue-change
notifications. This CLI integration does not populate those composer chips.
Automatic follow-up execution works; native chip display and controls are not
implemented by this port.

| Command | When prompts are chosen | Default budget |
| --- | --- | --- |
| `/g` | One at the end of each turn | Five total turns |
| `/q` | All follow-ups at the start | Five follow-ups plus the initial turn |

## Install

Use a Codex desktop runtime with a working `codex queue` command. Python 3.9+ is
required. In a local checkout, link the bundled skill into your Codex skills
directory (do not overwrite an existing skill):

```sh
ln -s /absolute/path/to/auto_reply_route/skills/g ~/.codex/skills/g
ln -s /absolute/path/to/auto_reply_route/skills/q ~/.codex/skills/q
```

The linked skill resolves its helper back to this checkout. Keep the checkout in
place. This adds no hook definitions or global config changes. In a new Codex task,
invoke `/g <task>` or `$g <task>`. Use a phrase such as `with 3 total steps` to set
the budget. The default is five total steps, including the initial turn; the
supported range is 1–12. Completion can stop earlier.

Example:

```text
/g fix the failing calculator tests and verify the fix, with 3 total steps
```

The agent follows [the Codex instructions](../skills/g/references/codex.md). It
generates the next prompt from real findings. Python only enforces the budget,
keeps task-specific state, and delivers through the native queue.

## Delivery and control

Each queued prompt starts with `/g (Step k/N)`. A successful helper response
includes Codex's native message ID. This proves acceptance, not execution; the
following task turn proves execution. The desktop owns the pending-message UI.
The helper does not create a custom chip or claim its appearance was verified.

State lives under `$CODEX_HOME/auto-reply-route/<task-id>.json`, or
`~/.codex/auto-reply-route/` when `CODEX_HOME` is unset. The helper takes task identity
from the current Codex environment, with no target-task override. Duplicate calls
for the same pending prompt return the existing receipt. File locking prevents
two local callers from sending it twice.

Ask `/g stop` to pause. The agent must honor your new instructions before staging
anything. The `paused` state prevents an already queued continuation from doing
work when it arrives. It does not remove the native queue item or interrupt an
already executing command. The app's Stop and queue controls remain app controls;
their UI behavior must be verified separately.

At verified completion the status is `complete`. If the budget runs out with work
remaining, it is `limit`, not success. If dispatch times out or returns no matching
receipt, the status is `uncertain`. The helper does not resend automatically:
delivery might already have happened. Inspect the task and queue before taking
further action. This favors avoiding duplicate work over automatic recovery.

`/g` must reconcile known unfinished core checks before choosing completion. For
an interactive page, build/type/HTTP checks do not replace viewing the page and
using its main interaction. Do that check now or queue it while budget remains;
pause for unavailable access, or report a limit if out of steps. Optional future
improvements do not require extra turns. This is an agent decision rule, not an
independent browser-verification engine inside the Python helper.

Generated follow-ups retain the original user's scope and permissions. They do
not authorize new commits, deployments, purchases, or external messages.

## /q upfront batches

For `/q`, use `/q <task> with 3 follow-ups` (or `\q` / `$q`). It stages three
follow-ups and then does the initial work, for four turns in total. The supported
follow-up count is 1–12. The agent loads [Codex /q instructions](../skills/q/references/codex.md)
and uses `skills/q/scripts/codex_q.py`. Its separate state file is
`<task-id>.q.json` in the same state directory.

The helper records all native receipt IDs before initial work begins. Initial
work is step 0; follow-ups are 1 through N. A received `/q (Follow-up k/N)` enters
that existing step and never stages a new batch. `/q stop` pauses the batch:
remaining messages may still arrive, but refuse execution. This does not remove
their native queue items. Native chip edit/delete behavior remains a separate
visual check.

Batch dispatch is sequential, not atomic. If a send fails, confirmed earlier
receipts remain recorded, later sends stop, and arriving steps refuse work. An
uncertain batch is not automatically retried, avoiding duplicated native messages.

## Verification

```sh
python3 -m pytest tests/test_codex_queue.py -q
python3 -m pytest tests/test_codex_batch.py -q
python3 -m pytest tests/ -q
```

Focused tests cover real subprocess argument handling, literal prompt content,
task isolation, duplicate dispatch, step limits, early completion, paused
continuations, and ambiguous delivery. Desktop proof must additionally show
distinct sequential turns with final answers before each continuation and no
extra turn after completion. Visual chip verification is a separate claim.
