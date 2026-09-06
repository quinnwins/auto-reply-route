"""Stage /q follow-ups upfront using the same native transport as /g."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from auto_reply_route.codex_queue import (
    CodexQueue, QueueError, QueueLaunchError, QueueUncertainError, native_enqueue,
)


class CodexBatch(CodexQueue):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = self.root / (self.thread_id + ".q.json")

    def read(self):
        if not self.path.exists():
            raise QueueError("No /q batch exists for this task.")
        return super().read()

    def stage_batch(self, objective, prompts, codex_bin=None):
        # Validate the whole batch before making any external call.
        if not isinstance(objective, str) or not objective.strip():
            raise QueueError("Supply the original objective.")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 12:
            raise QueueError("Supply 1–12 follow-up prompts as a JSON list.")
        if any(not isinstance(p, str) or not p.strip() or "\x00" in p or len(p) > 12000 for p in prompts):
            raise QueueError("Each follow-up must be nonempty text of at most 12000 characters.")
        prompts = [p.strip() for p in prompts]
        with self.locked():
            if self.path.exists():
                old = self.read()
                if old["status"] not in ("complete", "paused"):
                    if (old["status"] in ("initial", "queued", "active")
                            and old["objective"] == objective and old["prompts"] == prompts):
                        return old  # Report existing IDs; do not re-stage any messages.
                    raise QueueError("A /q batch already exists. Do not stage another one.")
                if old["status"] == "paused" and len(old["arrived"]) < len(old["receipts"]):
                    raise QueueError("Paused follow-ups are still pending; do not restart yet.")
            state = dict(thread_id=self.thread_id, objective=objective, prompts=prompts,
                         status="staging", active_step=0, completed_step=-1,
                         receipts=[], arrived=[], dispatching_step=None)
            self.save(state)
            for step, prompt in enumerate(prompts, 1):
                state["dispatching_step"] = step
                self.save(state)
                message = f"/q (Follow-up {step}/{len(prompts)}) {prompt}"
                try:
                    message_id = native_enqueue(self.thread_id, message, self.environ, self.runner, codex_bin)
                except (QueueLaunchError, QueueUncertainError) as exc:
                    state["status"] = "uncertain" if isinstance(exc, QueueUncertainError) else "paused"
                    state["error"] = str(exc)
                    self.save(state)
                    raise QueueError(f"Batch stopped after {len(state['receipts'])} confirmed message(s). "
                                     f"Do not retry automatically. {exc}") from exc
                state["receipts"].append(dict(step=step, message_id=message_id))
                state["dispatching_step"] = None
                self.save(state)
            state["status"] = "initial"
            self.save(state)
            return state

    def enter(self, step):
        with self.locked():
            state = self.read()
            if not 1 <= step <= len(state["receipts"]):
                raise QueueError("This follow-up has no confirmed queue receipt.")
            if state["status"] in ("paused", "uncertain"):
                if step not in state["arrived"]:
                    state["arrived"].append(step)
                    self.save(state)
                raise QueueError("This /q batch is stopped. Do not execute the queued work.")
            if state["status"] == "active" and state["active_step"] == step:
                return state
            if state["status"] != "queued" or step != state["completed_step"] + 1:
                raise QueueError("The preceding step has not finished, or this follow-up is stale.")
            state.update(status="active", active_step=step)
            state["arrived"].append(step)
            self.save(state)
            return state

    def finish_step(self, step):
        with self.locked():
            state = self.read()
            if state["status"] not in ("initial", "active") or step != state["active_step"]:
                raise QueueError("This step is not active; cannot mark it finished.")
            state.update(completed_step=step, active_step=None,
                         status="complete" if step == len(state["prompts"]) else "queued")
            self.save(state)
            return state

    def pause(self):
        with self.locked():
            state = self.read()
            # Do not erase uncertainty about a possibly delivered message.
            if state["status"] != "uncertain":
                state["status"] = "paused"
            self.save(state)
            return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("--objective-file", type=Path, required=True)
    stage.add_argument("--prompts-file", type=Path, required=True)
    stage.add_argument("--codex-bin")
    for name in ("enter", "finish"):
        sub.add_parser(name).add_argument("--step", type=int, required=True)
    sub.add_parser("status")
    sub.add_parser("pause")
    args = parser.parse_args(argv)
    try:
        batch = CodexBatch()
        if args.command == "stage":
            result = batch.stage_batch(args.objective_file.read_text(),
                                       json.loads(args.prompts_file.read_text()), args.codex_bin)
        elif args.command == "enter":
            result = batch.enter(args.step)
        elif args.command == "finish":
            result = batch.finish_step(args.step)
        elif args.command == "pause":
            result = batch.pause()
        else:
            result = batch.read()
        print(json.dumps(result, indent=2))
        return 0
    except (QueueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"/q: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
