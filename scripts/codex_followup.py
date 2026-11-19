#!/usr/bin/env python3
"""Codex command hook for a user-selected, per-prompt follow-up policy."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from uuid import UUID

from planning_council import PREMERGE_QA, SCOPING, goal_intake


def ticket(session, turn):
    # The CLI sandbox and hook process can have different TMPDIR settings.
    directory = Path("/tmp") / ("codex-followup-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    stat = directory.lstat()
    if directory.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError("The private follow-up directory is unavailable.")
    return directory / (str(UUID(session)) + "." + str(UUID(turn)))


def chatgpt_sharing():
    # T3 runs Codex on a shared ChatGPT plan under this provider name. That plan rejects
    # the messages Codex's built-in sub-agents send back, and no setting removes the tool.
    pid = os.getppid()
    for _ in range(4):
        row = subprocess.run(["ps", "-o", "ppid=,args=", "-p", str(pid)],
                             capture_output=True, text=True).stdout.split(None, 1)
        if len(row) < 2:
            return False
        if " app-server " in row[1] and 'model_provider="openai_token_sharing"' in row[1]:
            return True
        pid = int(row[0])
    return False


SHARING_NOTE = (
    "This Codex session runs on a shared ChatGPT plan, which rejects Codex's built-in "
    "sub-agents (spawn_agent): the request fails. Start any helper or reviewer with T3's "
    "delegate_task instead."
)


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
    sharing = chatgpt_sharing()
    if event == "Stop":
        selected = consume(path)
        if not selected or data.get("stop_hook_active"):
            return {}
        return {"decision": "block", "reason": (
            "Automatic completion review selected for this request. The original user's scope, "
            "latest instructions and permissions still govern. Honor stops and reviewer opt-outs. "
            "If a fresh reviewer checked the requested artifact and source evidence, resolve its findings and summarize "
            "the verdict without another reviewer. Recheck only materially changed evidence, work or claims. "
            "Otherwise use one fresh "
            + ("read-only reviewer started with T3's delegate_task (built-in sub-agents fail on this "
               "shared ChatGPT plan)" if sharing else "native read-only reviewer")
            + " before completing this turn. Give it "
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
        context = "\n".join(filter(None, [goal_intake(prompt), sharing and SHARING_NOTE]))
        if context:
            return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
        return {}
    step = str(UUID(data["turn_id"]))
    select = shlex.join(["python3", str(Path(__file__).resolve()), "review", step])
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": (
        "The user has opted into automatic follow-up selection. Use your understanding of the actual "
        "request and conversation to choose ONE path now. Explicit user limits, named workflows, "
        "requested models, stops and corrections take precedence.\n"
        f"{PREMERGE_QA}\n"
        f"• {SCOPING}\n"
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
        + ("\n" + SHARING_NOTE if sharing else "")
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
