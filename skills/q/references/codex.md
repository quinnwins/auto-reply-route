# /q in Codex desktop

`/q` chooses and stages the follow-up sequence upfront, then executes the user's
initial request in the same turn. Codex's native queue runs the follow-ups after
the initial answer. Do not use `/g`'s end-of-turn generation for this mode.

The helper is `../scripts/codex_q.py` relative to this reference; a linked user
installation uses `~/.codex/skills/q/scripts/codex_q.py`. Use Python 3.9+.

## Invocation and staging

Activate only for `/q`, `$q`, or an explicit request for this queued workflow.
Accept `\q` as the user's backslash spelling too. Discussion of the skill does
not start a batch. For `/q stop` (or `\q stop`), call the helper's `pause` command
and stop; never treat `stop` as a new objective.

Read the last few turns and operator DNA if available. Choose bespoke follow-up
prompts grounded in the actual objective. Default: five follow-ups, in addition
to the initial turn. An explicit count from 1–12 overrides this. Only add subagent
instructions if the user requested subagents. Do not expand the authorization:
review remains review, and generated prompts do not authorize commits, deploys,
purchases, or external communications.

Write the original objective to a UTF-8 text file and the ordered prompt strings
to a JSON array file. Queue the entire sequence before doing the initial work:

```
python3 <helper> stage --objective-file <file> --prompts-file <json-file>
```

Check the returned state: `initial` means every prompt has a native queue receipt.
Report a failed or partial batch honestly, call no alternate sender, and never
automatically re-stage it. A repeat call with the same active batch returns the
existing receipt IDs. The helper binds delivery to the current `CODEX_THREAD_ID`.
Use `--codex-bin` only if necessary to locate the installed `codex queue` runtime.

Now do the initial work fully; do not finish just because the queue was staged.
When it is ready, call `finish --step 0` and give the initial answer. If blocked or
the user stops, call `pause`; don't mark the work finished merely to advance.

## Receiving follow-ups

A message beginning `/q (Follow-up k/N)` is an existing queued step, **not** an
instruction to stage a fresh batch. First call:

```
python3 <helper> enter --step k
```

Proceed only on success. Read the original objective and actual preceding results.
Respect the user's latest instructions. A prewritten prompt may be obsolete:
skip irrelevant work with an explanation, or pause if the next action needs the
user's decision. Do not blindly execute it or fabricate missing prerequisites.
When the step's work is complete, call `finish --step k` and give the answer.
Queue nothing else. The remaining messages already exist in the native queue.
The last finish records `complete`.

`pause` makes all remaining arriving follow-ups refuse execution. It does not
delete native queued items or interrupt running commands; the app owns those
controls. Do not claim the chip's appearance or controls were visually verified
from a CLI receipt. No clipboard, keyboard simulation, hook, or watcher is used.

Partial dispatch is not atomic. The helper saves each acknowledged receipt and
stops on error. Already queued prompts refuse work when the batch is stopped.
An uncertain send is not retried, since that could duplicate work. Use `status`
to inspect the recorded receipts. Do not manually overwrite the state to resume.
