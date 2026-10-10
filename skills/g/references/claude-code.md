# /g in Claude Code

A Stop hook runs the loop. Each time you finish a reply, it either starts the step you
queued or checks your "done" claim. When the run ends, it asks for one push notification,
so the user can walk away and come back only when the work is done or needs them.

The helper is `../scripts/claude_g.py`, relative to this reference. In a linked
installation it is `~/.claude/skills/g/scripts/claude_g.py`. State lives in
`~/.claude/g-state/<session_id>.json`, one file per session, so parallel sessions never
steer each other.

Only start a run when the user types `/g` or clearly asks for this loop. Talking about
`/g` does not start one.

## Start

- `/g stop`: run `finish --step <current> --reason paused --quiet` (use `status` to see the
  step). Say it is paused. If no run exists, say so. `stop` is never a new task.
- `/g` with no task: use the current unfinished objective. If nothing is left, just answer.
- Steps (total turns, including this one): if the user gives a number, use it (max 25).
  Otherwise size it yourself from how hard the task is:
  - 1: trivial and certain (a typo, a one-line change, a quick lookup).
  - 2–3: a small fix plus a check.
  - 4–6: a normal feature or bug across a few files.
  - 7–9: a multi-part feature, a hard bug with an unclear cause, or risky changes.
  - 10–12: the hardest work: ambiguous, cross-system, or needs research, a build, and deep checks.
  - 13–25: very large work the user wants finished without coming back: big multi-part
    features, migrations, or several hard parts in a row.
  Once the run starts, never raise the number. Stop early when the work is verified done.
- Subagents: if the user gives a number ("M sub"), pass `--subs M` and use M on every step.
  Otherwise pass `--subs auto` and choose again each step: more when a step is broad and
  separate agents can work in parallel (many files, independent parts, wide audits), none
  when the work is small or has to happen in order. Give each agent its own files. Only you
  run the helper. Subagents share this session's ID, so never tell them about it.
- After `start`, tell the user your pick in one line (e.g. "6 steps, subagents as needed").
- Done-check: choose one shell command that proves the objective, if one exists (the repo's
  test command or a targeted test file). Pass it as `--verify`. The hook runs it before it
  accepts "complete". Leave it out for audits, research, or writing.

Write the objective to a temp file, then:

```
python3 ~/.claude/skills/g/scripts/claude_g.py start --steps N --objective-file <file> [--verify "<cmd>"] --subs <M|auto>
```

Then do the work fully.

## End of every step: pick one move

After the work, look at the real results: test output, errors, findings, and the user's
latest messages. Do not assume success. Then do exactly one of these as your last action
before the final reply:

1. **Verified done.** Every core part of the objective is checked, not just built. Run
   `finish --step K --reason complete`. If a done-check exists, the hook runs it. If the
   check fails, the run reopens with the failure output.
2. **More work remains and budget remains.** Write the single most useful next prompt
   (10–25 plain words, in the user's voice) to a temp file. Then run
   `next --step K --prompt-file <file>`. It starts right after your reply.
3. **Blocked on the user** (a decision, access, credentials, or anything outside your
   authority): don't stop at the first question. Finish every part you can without the
   answer, and make reversible choices yourself (say which you made). Pause only when
   nothing useful is left: run `finish --step K --reason paused`, then ask every open
   question at once, each with your recommended answer.
4. **Budget used up:** run `finish --step K --reason limit` and list what is still open.

Rules:
- Stay inside the original objective. An audit does not become permission to implement.
  Generated prompts never authorize commits, git pushes, deploys, purchases, or messages to
  people. Those need the user's own instruction; a standing rule in the user's CLAUDE.md
  counts, so follow it without pausing to ask.
- Do not mark "complete" while any core check is still "untested" or "not verified". If it
  can be checked now, check it now. Otherwise make that check the next step.
- Do not fill the budget just to use turns. Stop as soon as the work is verified done.
- After `next` or `finish`, give a short reply and stop. Do no more work in that turn.
- When a `/g (Step k/N)` message arrives from the hook, that step is yours. Do it, then pick
  one move again.
- When the run ends, the hook asks for one more short step: send the user one push
  notification saying what is done or what they need to decide, then stop. Claude Code
  skips the push when the user is already at the terminal. Runs the user stopped
  (`--quiet`) send nothing.
