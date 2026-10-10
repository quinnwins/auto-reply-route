#!/usr/bin/env python3
"""State helper and Stop hook for the /g adaptive loop in Claude Code.

Install: link this skill to ~/.claude/skills/g and register `claude_g.py hook` as a Stop hook
(see references/claude-code.md). Python 3.9+, standard library only.

Model-facing commands (run from Bash inside a /g session):
  g.py start --steps N --objective-file F [--verify CMD] [--subs M|auto]
  g.py next --step K --prompt-file F
  g.py finish --step K --reason complete|paused|limit [--quiet]
  g.py status

Hook entry point (registered as a Stop hook in ~/.claude/settings.json):
  g.py hook   (reads the Stop hook JSON on stdin)

State lives in ~/.claude/g-state/<session_id>.json, one file per session, so
parallel sessions never steer each other.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("G_STATE_DIR", str(Path.home() / ".claude" / "g-state")))
MAX_STEPS = 25
DEFAULT_STEPS = 5
VERIFY_TIMEOUT = 540
STALE_SECONDS = 7 * 24 * 3600
HELPER = str(Path(__file__).resolve())


def state_path(session_id):
    return STATE_DIR / (session_id + ".json")


REQUIRED_KEYS = ("objective", "steps", "step", "status", "pending", "verify", "history")


def load(session_id):
    try:
        state = json.loads(state_path(session_id).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or any(k not in state for k in REQUIRED_KEYS):
        return None  # corrupt state is treated as no run
    return state


def save(session_id, state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = state_path(session_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(state_path(session_id))


def clean_stale():
    if not STATE_DIR.is_dir():
        return
    cutoff = time.time() - STALE_SECONDS
    for f in STATE_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def session_from_env():
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not sid:
        fail("No CLAUDE_CODE_SESSION_ID in the environment; /g only runs inside Claude Code.")
    return sid


def fail(msg):
    print("g: " + msg, file=sys.stderr)
    sys.exit(1)


def read_text_file(path):
    try:
        text = Path(path).read_text().strip()
    except OSError as exc:
        fail("cannot read {}: {}".format(path, exc))
    if not text:
        fail("{} is empty".format(path))
    return text


def active_state(sid, step):
    state = load(sid)
    if not state:
        fail("no /g run in this session.")
    if state["status"] != "active":
        fail("this /g run is already {}.".format(state["status"]))
    if step != state["step"]:
        fail("you are on step {}, not {}.".format(state["step"], step))
    return state


# ---------------------------------------------------------------- commands

def cmd_start(args):
    sid = session_from_env()
    if not 1 <= args.steps <= MAX_STEPS:
        fail("steps must be between 1 and {}.".format(MAX_STEPS))
    if args.subs != "auto" and not (args.subs.isdigit()):
        fail("subs must be a whole number or 'auto'.")
    clean_stale()
    state = {
        "objective": read_text_file(args.objective_file),
        "steps": args.steps,
        "step": 1,
        "status": "active",
        "pending": None,
        "nudged_step": None,
        "verify": (args.verify or "").strip() or None,
        "subs": args.subs if args.subs == "auto" else int(args.subs),
        "cwd": os.getcwd(),
        "history": [],
        "announced": False,
    }
    save(sid, state)
    gate = state["verify"] or "none"
    print("g: run started. Step 1/{}. Done-gate: {}. Subagents: {}".format(args.steps, gate, args.subs))


def cmd_next(args):
    sid = session_from_env()
    state = active_state(sid, args.step)
    if state["step"] >= state["steps"]:
        fail("step budget used up ({}/{}). Run: finish --step {} --reason limit".format(
            state["step"], state["steps"], state["step"]))
    state["pending"] = read_text_file(args.prompt_file)
    save(sid, state)
    print("g: step {}/{} queued. Finish your reply now; it starts when you stop.".format(
        state["step"] + 1, state["steps"]))


def cmd_finish(args):
    sid = session_from_env()
    state = load(sid)
    if not state:
        fail("no /g run in this session.")
    if state["status"] not in ("active", "claimed_complete"):
        print("g: run already {}.".format(state["status"]))
        return
    if state["status"] == "claimed_complete" and args.reason != "paused":
        fail("already marked complete; the done-check runs when you stop.")
    if args.reason != "paused" and args.step != state["step"]:
        fail("you are on step {}, not {}.".format(state["step"], args.step))
    state["pending"] = None
    if args.quiet:
        state["announced"] = True  # the user is right here; no phone ping
    if args.reason == "complete":
        # The Stop hook runs the done-gate before accepting this.
        state["status"] = "claimed_complete"
    else:
        state["status"] = args.reason
    save(sid, state)
    print("g: marked {} at step {}/{}.".format(args.reason, state["step"], state["steps"]))


def cmd_status(_args):
    sid = session_from_env()
    state = load(sid)
    if not state:
        print("g: no /g run in this session.")
        return
    print(json.dumps({k: state[k] for k in ("status", "step", "steps", "verify", "pending", "objective")}, indent=2))


# ---------------------------------------------------------------- stop hook

def emit_block(reason, user_msg):
    print(json.dumps({"decision": "block", "reason": reason, "systemMessage": user_msg}))


def emit_note(user_msg):
    print(json.dumps({"systemMessage": user_msg}))


def announce(sid, state, note):
    """The run just ended: one more short step to tell the user on their phone, so they can
    walk away. State files from older versions have no "announced" key and are never announced."""
    state["announced"] = True
    save(sid, state)
    emit_block(
        "{} Send the user one push notification (the PushNotification tool; load it through "
        "ToolSearch if needed) saying in one line what is done, or what they need to decide. Then "
        "stop and do no other work.".format(note), note)


def run_verify(cmd, cwd):
    # Output goes to a file, not a pipe, so a background child (a dev server or
    # watcher) cannot hold the check open after the command itself exits.
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = proc.wait(timeout=VERIFY_TIMEOUT)
        except subprocess.TimeoutExpired:
            code = None
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
        out.seek(0)
        text = out.read().decode("utf-8", errors="replace").strip()
    if code is None:
        return False, "timed out after {}s\n{}".format(VERIFY_TIMEOUT, text[-3000:])
    return code == 0, "exit {}\n{}".format(code, text[-3000:])


def continue_reason(state, header):
    subs = state.get("subs") or 0
    if subs == "auto":
        team = ("Subagents: you choose for this step. Use more when the step is complex and broad and "
                "parallel agents would finish it faster; use none when it is small or one-track.\n\n")
    elif subs:
        team = "The user asked for {} subagents: use that many for this step's work.\n\n".format(subs)
    else:
        team = ""
    return (
        "{header}\n\n"
        "Original /g objective (stay inside it): {objective}\n\n" + team +
        "First: if the user's latest message changed direction or is unrelated to this run, run "
        "`python3 {h} finish --step {k} --reason paused --quiet` and just answer the user.\n"
        "Otherwise do this step fully. Then look at the real results and either queue exactly one "
        "next step (`python3 {h} next --step {k} --prompt-file <file>`) or end the run "
        "(`python3 {h} finish --step {k} --reason complete|paused|limit`)."
    ).format(header=header, objective=state["objective"], h=HELPER, k=state["step"])


def ended(sid, state, note):
    if state.get("announced") is False:
        announce(sid, state, note)
    else:
        emit_note(note)


def hook(payload):
    if not isinstance(payload, dict):
        return
    sid = str(payload.get("session_id") or "")
    state = load(sid) if sid else None
    if not state:
        return
    status = state["status"]
    steps = state["steps"]

    if status == "claimed_complete":
        if not state["verify"]:
            state["status"] = "complete"
            save(sid, state)
            ended(sid, state, "/g done at step {}/{}.".format(state["step"], steps))
            return
        ok, output = run_verify(state["verify"], state.get("cwd") or payload.get("cwd"))
        if ok:
            state["status"] = "complete"
            save(sid, state)
            ended(sid, state, "/g done at step {}/{}. Check passed: {}".format(state["step"], steps, state["verify"]))
            return
        if state["step"] >= steps:
            state["status"] = "limit"
            save(sid, state)
            ended(sid, state, "/g stopped at step limit {}/{}. Check still FAILS: {}".format(steps, steps, state["verify"]))
            return
        state["step"] += 1
        state["status"] = "active"
        state["history"].append("step {}: done-gate failed".format(state["step"] - 1))
        save(sid, state)
        header = ("/g (Step {}/{}) You marked this complete, but the done-check failed. "
                  "It is not done. Fix what the output shows.\n\nCheck: {}\nOutput:\n{}").format(
                      state["step"], steps, state["verify"], output)
        emit_block(continue_reason(state, header),
                   "/g step {}/{}: done-check failed, continuing".format(state["step"], steps))
        return

    if status != "active":
        if status in ("complete", "paused", "limit") and state.get("announced") is False:
            announce(sid, state, "/g {} at step {}/{}.".format(status, state["step"], steps))
        return

    if state["pending"]:
        prompt = state["pending"]
        state["history"].append("step {}: {}".format(state["step"] + 1, prompt))
        state["step"] += 1
        state["pending"] = None
        save(sid, state)
        header = "/g (Step {}/{}) {}".format(state["step"], steps, prompt)
        emit_block(continue_reason(state, header), header)
        return

    # Active, but the turn ended without queuing a next step or finishing.
    # A second miss in a row pauses; otherwise this turn uses up one step.
    if state.get("nudged_step") == state["step"] or state["step"] >= steps:
        state["status"] = "paused" if state["step"] < steps else "limit"
        save(sid, state)
        ended(sid, state, "/g {} at step {}/{} (no next step chosen).".format(state["status"], state["step"], steps))
        return
    state["step"] += 1
    state["nudged_step"] = state["step"]
    state["history"].append("step {}: nudge".format(state["step"]))
    save(sid, state)
    header = ("/g (Step {}/{}) Last turn ended without queuing a next step or ending the run. "
              "Based on the real results, pick the single best next step and do it now.").format(
                  state["step"], steps)
    emit_block(continue_reason(state, header), "/g step {}/{}: choosing next step".format(state["step"], steps))


def cmd_hook(_args):
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return
    try:
        hook(payload)
    except Exception as exc:  # never wedge the session on a helper bug
        sid = str(payload.get("session_id") or "") if isinstance(payload, dict) else ""
        state = load(sid) if sid else None
        if state:
            state["status"] = "paused"
            save(sid, state)
        emit_note("/g hook error, loop paused: {}".format(exc))


def main():
    p = argparse.ArgumentParser(prog="g.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    s.add_argument("--objective-file", required=True)
    s.add_argument("--verify")
    s.add_argument("--subs", default="auto")
    s.set_defaults(fn=cmd_start)
    n = sub.add_parser("next")
    n.add_argument("--step", type=int, required=True)
    n.add_argument("--prompt-file", required=True)
    n.set_defaults(fn=cmd_next)
    f = sub.add_parser("finish")
    f.add_argument("--step", type=int, required=True)
    f.add_argument("--reason", choices=["complete", "paused", "limit"], required=True)
    f.add_argument("--quiet", action="store_true", help="the user asked to stop: no phone ping")
    f.set_defaults(fn=cmd_finish)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("hook").set_defaults(fn=cmd_hook)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
