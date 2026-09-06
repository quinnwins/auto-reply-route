"""One adaptive follow-up, delivered through Codex's native desktop queue.

The agent chooses the prompt at the end of its work. This module only binds it
to the current task, enforces the step limit, and records the delivery receipt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional
from uuid import UUID


class QueueError(ValueError):
    pass


class QueueLaunchError(QueueError):
    """The queue process was not launched; no message was sent by this call."""


class QueueUncertainError(QueueError):
    """Dispatch may have happened, but no matching receipt was obtained."""


def native_enqueue(thread_id, message, environ, runner=None, codex_bin=None):
    """Shared native transport for /g and /q; never interpolates a shell command."""
    binary = codex_bin or environ.get("CODEX_CLI_PATH") or shutil.which("codex")
    if not binary:
        raise QueueLaunchError("Codex CLI is unavailable; nothing was queued.")
    try:
        result = (runner or subprocess.run)(
            [binary, "queue", "--thread", thread_id, "--message", message],
            capture_output=True, text=True, timeout=20, env=environ,
        )
    except OSError as exc:
        raise QueueLaunchError(f"Could not launch Codex: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise QueueUncertainError("Queue timed out. Delivery is uncertain; do not retry automatically.") from exc
    match = re.search(r"Queued message ([0-9a-f-]{36}) for thread ([0-9a-f-]{36})\.", result.stdout)
    if result.returncode or not match or match[2] != thread_id:
        raise QueueUncertainError("Codex returned no matching queue receipt. Do not retry automatically. "
                                  + (result.stderr or result.stdout)[-500:])
    return match[1]


class CodexQueue:
    def __init__(self, root: Optional[Path] = None, environ=None, runner=None):
        self.environ = dict(os.environ if environ is None else environ)
        raw = self.environ.get("CODEX_THREAD_ID", "")
        try:
            self.thread_id = str(UUID(raw))
        except ValueError as exc:
            raise QueueError("Run this inside a Codex task with CODEX_THREAD_ID set.") from exc
        session = self.environ.get("CODEX_SESSION_ID")
        if session and session != self.thread_id:
            raise QueueError("Task and session IDs disagree; nothing was queued.")
        self.root = Path(root) if root else Path(
            self.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        ) / "auto-reply-route"
        self.path = self.root / (self.thread_id + ".json")
        self.runner = runner or subprocess.run

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.root / (self.thread_id + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        if not self.path.exists():
            raise QueueError("No /g run exists for this task. Start one first.")
        state = json.loads(self.path.read_text())
        if state["thread_id"] != self.thread_id:
            raise QueueError("Stored task ID does not match this task.")
        return state

    def save(self, state):
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".g-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def start(self, objective: str, limit: int = 5):
        if not objective.strip() or not 1 <= limit <= 12:
            raise QueueError("Supply an objective and a total step limit from 1 to 12.")
        with self.locked():
            if self.path.exists():
                old = self.read()
                if old["status"] not in ("complete", "limit", "paused"):
                    if old["objective"] == objective and old["limit"] == limit:
                        return old
                    raise QueueError("A /g run already exists. Finish or pause it first.")
                if old.get("pending"):
                    raise QueueError("An old message may still be queued; do not restart this task yet.")
            state = dict(thread_id=self.thread_id, objective=objective, limit=limit,
                         step=1, status="active", pending=None, receipts=[])
            self.save(state)
            return state

    def enter(self, step: int):
        """Acknowledge a delivered follow-up before doing any new work."""
        with self.locked():
            state = self.read()
            if state["status"] == "active" and step == state["step"]:
                return state
            pending = state.get("pending")
            if state["status"] == "paused" and pending and step == pending["step"]:
                state["pending"] = None
                self.save(state)
                raise QueueError("This /g run was paused. Do not execute the queued work.")
            if state["status"] != "queued" or not pending or step != pending["step"]:
                raise QueueError("This step is not an active queued continuation. Do not execute it.")
            state.update(step=step, status="active", pending=None)
            self.save(state)
            return state

    def stage(self, prompt: str, step: int, codex_bin: Optional[str] = None):
        prompt = prompt.strip()
        if not prompt or "\x00" in prompt or len(prompt) > 12000:
            raise QueueError("Supply a nonempty follow-up of at most 12000 characters.")
        with self.locked():
            state = self.read()
            pending = state.get("pending")
            if state["status"] == "queued" and step == state["step"] and pending["prompt"] == prompt:
                return state  # A repeated call returns the existing receipt, never sends twice.
            if state["status"] != "active" or step != state["step"]:
                raise QueueError("Stale or inactive step; nothing was queued.")
            if step >= state["limit"]:
                state["status"] = "limit"
                self.save(state)
                return state
            message = f"/g (Step {step + 1}/{state['limit']}) {prompt}"
            state.update(status="dispatching", pending=dict(step=step + 1, prompt=prompt, message=message))
            self.save(state)
            try:
                message_id = native_enqueue(self.thread_id, message, self.environ, self.runner, codex_bin)
            except QueueLaunchError:
                state.update(status="active", pending=None)
                self.save(state)
                raise
            except QueueUncertainError:
                state["status"] = "uncertain"
                self.save(state)
                raise
            state["status"] = "queued"
            state["pending"]["message_id"] = message_id
            state["receipts"].append(dict(step=step + 1, message_id=message_id))
            self.save(state)
            return state

    def finish(self, reason: str, step: int):
        if reason not in ("complete", "limit", "paused"):
            raise QueueError("Unknown stop reason.")
        with self.locked():
            state = self.read()
            if step != state["step"]:
                raise QueueError("Stale step; cannot finish this run.")
            if reason != "paused" and state["status"] not in ("active", "complete", "limit"):
                raise QueueError("A pending or uncertain delivery must be resolved before completion.")
            if reason == "limit" and step < state["limit"]:
                raise QueueError("The step limit has not been reached.")
            state["status"] = reason
            self.save(state)
            return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--objective-file", type=Path, required=True)
    start.add_argument("--steps", type=int, default=5)
    stage = sub.add_parser("stage")
    stage.add_argument("--prompt-file", type=Path, required=True)
    stage.add_argument("--step", type=int, required=True)
    stage.add_argument("--codex-bin")
    enter = sub.add_parser("enter")
    enter.add_argument("--step", type=int, required=True)
    finish = sub.add_parser("finish")
    finish.add_argument("--step", type=int, required=True)
    finish.add_argument("--reason", choices=["complete", "limit", "paused"], required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    try:
        queue = CodexQueue()
        if args.command == "start":
            result = queue.start(args.objective_file.read_text(), args.steps)
        elif args.command == "stage":
            result = queue.stage(args.prompt_file.read_text(), args.step, args.codex_bin)
        elif args.command == "enter":
            result = queue.enter(args.step)
        elif args.command == "finish":
            result = queue.finish(args.reason, args.step)
        else:
            result = queue.read()
        print(json.dumps(result, indent=2))
        return 0
    except (QueueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"/g: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
