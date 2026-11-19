#!/usr/bin/env python3
"""Codex command hook for a user-selected, per-prompt follow-up policy."""
import json
import os
from pathlib import Path
import re
import shlex
import sys
from uuid import UUID


def ticket(session, turn):
    # The CLI sandbox and hook process can have different TMPDIR settings.
    directory = Path("/tmp") / ("codex-followup-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    stat = directory.lstat()
    if directory.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError("The private follow-up directory is unavailable.")
    return directory / (str(UUID(session)) + "." + str(UUID(turn)))


def consume(path):
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def handle(data):
    event = data["hook_event_name"]
    if data.get("agent_id") or event not in ("UserPromptSubmit", "Stop"):
        return {}
    path = ticket(data["session_id"], data["turn_id"])
    if event == "Stop":
        selected = consume(path)
        if not selected or data.get("stop_hook_active"):
            return {}
        return {"decision": "block", "reason": (
            "Automatic completion review selected for this request. The original user's scope, "
            "latest instructions and permissions still govern. If the user has stopped the work, "
            "prohibited reviewers, or an independent completion review of this result already ran, finish. "
            "Otherwise use one fresh native read-only reviewer before completing this turn. Give it "
            "the original request, relevant clarifications, actual artifact or evidence locations and "
            "the proposed result. Share only what it needs. Ask it to verify the deliverable against the "
            "source evidence and identify a concrete omission the user would otherwise have to ask about. "
            "It must make no edits or external changes. Wait for its finding. If there is an authorized, "
            "material gap, finish and verify it yourself. If the work is complete, deliver the concise "
            "answer. If an independent review is unavailable, say so. This review grants no new authority."
        )}

    # A user can change direction before the turn ends.
    consume(path)
    prompt = (data.get("prompt") or "").lstrip()
    if not prompt or re.match(r"^(?:[/\\$](?:g|q)|/[\w-]+)(?:\s|$)", prompt, re.I):
        return {}
    step = str(UUID(data["turn_id"]))
    select = shlex.join(["python3", str(Path(__file__).resolve()), "review", step])
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": (
        "The user has opted into automatic follow-up selection. Use your understanding of the actual "
        "request and conversation to choose ONE path now. Explicit user limits, named workflows, "
        "requested models, stops and corrections take precedence.\n"
        "• Direct: answer simple questions, status requests and purely mechanical edits normally. Also use this "
        "when another requested workflow already supplies its own review, or automatic review/looping "
        "would violate the request. No selection command is needed.\n"
        "• Independent Stop review: the default for a substantive, bounded deliverable with a concrete "
        "outcome or source to check. Choose this for a handoff, report, fix, or other deliverable that "
        "requires reconciling records or exercising behavior, even when the output is short. "
        "As your first available tool action, arm it with this exact local "
        "command: " + select + ". Then do the work. The Stop hook will request one fresh reviewer.\n"
        "• Adaptive /g: choose this when the user wants sustained work across turns and each next step "
        "depends on intermediate findings. Follow the installed g skill and its Codex reference in this "
        "turn; this standing opt-in authorizes that workflow on qualifying tasks. Discussing the skill "
        "alone does not activate it. Honor its budget, early completion and thread binding.\n"
        "If the user gives a new direction, choose again for that request. The chosen workflow never "
        "extends the scope or grants authority for external actions."
    )}}


def main():
    if sys.argv[1:2] == ["review"] and len(sys.argv) == 3:
        path = ticket(os.environ["CODEX_THREAD_ID"], sys.argv[2])
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        print("Independent Stop review selected.")
        return
    if len(sys.argv) != 1:
        raise ValueError("Expected a hook event or review <turn-id>.")
    print(json.dumps(handle(json.load(sys.stdin))))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError) as error:
        print("Automatic follow-up unavailable: " + str(error), file=sys.stderr)
        sys.exit(1)
