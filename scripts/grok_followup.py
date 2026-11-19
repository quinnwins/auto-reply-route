"""Select one native review or a bounded adaptive continuation in a T3 Grok turn."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys


REVIEW = (
    "Run the one independent completion review selected for the user's original request. "
    "Honor later corrections, stop instructions and any work-alone limit. If a fresh "
    "independent reviewer already checked this exact result, finish. Otherwise use one "
    "fresh native read-only Grok subagent. Pass the request and only the necessary actual "
    "evidence. Ask for a concrete unmet requirement a real user would have to ask about. "
    "Wait, correct and verify any authorized omission, then deliver the final answer. "
    "If no reviewer is available, disclose that. This grants no new authority."
)
NEXT = (
    "Continue the specific remaining step for the original user request based on the "
    "actual findings. Respect the latest user direction and every permission boundary. "
    "Verify the result. Stop when complete or blocked. Only request another native "
    "continuation when a concrete authorized core step remains."
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def update(path, mode, event):
    state = json.loads(path.read_text()) if path.exists() else {}
    if mode:
        if not state:
            return "Native Grok hooks unavailable for this turn. Use the in-turn path."
        if state.get("reviewed") or (mode == "next" and state["steps"] >= 4):
            return "Follow-up limit reached. Finish this turn and report any remaining gap."
        state["choice"] = mode
        path.write_text(json.dumps(state))
        return "Independent Stop review selected." if mode == "review" else "Adaptive continuation selected."

    name = event.get("hook_event_name")
    if event.get("subagentType") or not event.get("sessionId") or not event.get("promptId"):
        return {}
    turn = digest(json.dumps([event["sessionId"], event["promptId"]]))
    if name == "UserPromptSubmit":
        path.write_text(json.dumps({"turn": turn, "choice": "", "steps": 0}))
        return {}
    if state.get("turn") != turn:
        return {}
    if name in ("StopFailure", "StopCancelled"):
        path.unlink()
        return {}
    if name != "Stop" or event.get("reason") != "end_turn":
        return {}
    choice = state["choice"]
    if not choice:
        path.unlink()
        return {}
    state["choice"] = ""
    if choice == "review":
        state["reviewed"] = True
        reason = REVIEW
    else:
        state["steps"] += 1
        reason = NEXT
    path.write_text(json.dumps(state))
    return {"decision": "block", "reason": reason}


def main():
    args = sys.argv[1:]
    mode = args[0] if args in (["review"], ["next"]) else None
    if args and not mode:
        raise ValueError("Expected review, next, or a hook event on stdin.")
    thread = os.environ.get("T3CODE_THREAD_ID")
    if not thread or os.environ.get("GROK_OAUTH2_REFERRER") != "t3code":
        print("Native Grok hooks unavailable for this turn. Use the in-turn path." if mode else "{}")
        return
    event = {} if mode else json.load(sys.stdin)
    # The ACP process and its model's shell may have different temporary directories.
    directory = Path("/tmp") / ("t3-grok-followup-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private follow-up state directory unavailable.")
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        result = update(directory / digest(thread), mode, event)
    finally:
        os.close(fd)
    print(result if mode else json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit("Grok follow-up unavailable: " + str(error))
