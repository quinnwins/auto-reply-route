#!/usr/bin/env python3
"""Select a follow-up in the current Claude Code session."""
import json
import os
from pathlib import Path
import re
import shlex
import sys
from uuid import UUID


def marker(session_id, prompt_id):
    directory = Path("/tmp") / ("claude-followup-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    stat = directory.lstat()
    if directory.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError("Private review directory unavailable")
    return directory / (str(UUID(session_id)) + "." + str(UUID(prompt_id)))


def hook(event):
    name = event.get("hook_event_name")
    prompt_id = event.get("prompt_id")
    if name not in ("UserPromptSubmit", "Stop") or not prompt_id or event.get("agent_id"):
        return {}

    ticket = marker(event["session_id"], prompt_id)
    if name == "Stop":
        try:
            ticket.unlink()
        except FileNotFoundError:
            return {}
        if event.get("stop_hook_active"):
            return {}
        return {"decision": "block", "reason": (
            "You selected a completion review. Respect the user's latest instructions and stop or opt-out. "
            "If a fresh independent review of this very result already ran, finish. Otherwise use the "
            "native Agent tool with independent-reviewer for one read-only check. Give it the original "
            "request, relevant clarifications, actual deliverable and necessary source evidence only. "
            "Ask it to flag concrete missing work the user would otherwise have to request again. "
            "Wait for its finding. Fix and verify an authorized material gap yourself, then finish. "
            "If the reviewer is unavailable, disclose that. This check grants no new permissions."
        )}

    ticket.unlink(missing_ok=True)
    prompt = (event.get("prompt") or "").lstrip()
    if not prompt or re.match(r"^(?:/[\w-]+|[$\\][gq])(?:\s|$)", prompt, re.I):
        return {}
    select = shlex.join(["python3", str(Path(__file__).resolve()), "review", str(UUID(prompt_id))])
    context = (
        "The user has enabled automatic follow-up selection in Claude Code. Choose one path based on the "
        "user's request and conversation. Respect explicit workflow choices, review-only requests, "
        "opt-outs, and stops. No workflow grants additional permissions.\n"
        "Direct: for simple answers, status checks, mechanical edits, or a request that already "
        "has its own review, proceed normally.\n"
        "Independent review: for a bounded deliverable with source evidence or observable behavior to "
        "verify, including a short handoff or code fix, select a one-time review as your first "
        "available Bash action by running this command exactly:\n" + select +
        "\nDo the task. Your Stop hook will request a fresh reviewer before completion.\n"
        "Adaptive /g: when the user wants sustained work across turns, and intermediate results determine "
        "the next step, use the installed g skill and its normal Claude Stop hook. This standing choice "
        "authorizes /g for such requests. For an automatically selected run, use --quiet on each "
        "g.py finish and keep the result in this conversation unless the user explicitly asks for a "
        "notification. Merely discussing a workflow does not start it."
    )
    return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": context}}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "review":
        ticket = marker(os.environ["CLAUDE_CODE_SESSION_ID"], sys.argv[2])
        ticket.touch(mode=0o600, exist_ok=True)
        print("Independent Claude review selected.")
    elif len(sys.argv) == 1:
        print(json.dumps(hook(json.load(sys.stdin))))
    else:
        raise ValueError("Expected a hook event or review <prompt-id>")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError) as error:
        print("Claude follow-up unavailable: " + str(error), file=sys.stderr)
        sys.exit(1)
