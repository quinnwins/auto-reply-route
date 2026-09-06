"""Upfront native /q batches: order, initial work, pause, and partial delivery."""
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from auto_reply_route.codex_batch import CodexBatch
from auto_reply_route.codex_queue import CodexQueue, QueueError


@pytest.fixture
def batch_fixture(tmp_path):
    thread = str(uuid4())
    env = {**os.environ, "CODEX_THREAD_ID": thread, "CODEX_SESSION_ID": thread}
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, f"Queued message {uuid4()} for thread {thread}.\n", "")
    return CodexBatch(tmp_path, env, runner), calls


def test_all_prompts_are_queued_upfront_in_order(batch_fixture):
    batch, calls = batch_fixture
    state = batch.stage_batch("Build then verify", ["Check positive values", "Check negative values", "Summarize"])
    assert [c[-1] for c in calls] == [
        "/q (Follow-up 1/3) Check positive values",
        "/q (Follow-up 2/3) Check negative values",
        "/q (Follow-up 3/3) Summarize",
    ]
    assert all(c[1:4] == ["queue", "--thread", batch.thread_id] for c in calls)
    assert state["status"] == "initial" and state["completed_step"] == -1
    assert len(state["receipts"]) == 3
    assert not state["arrived"]


def test_initial_work_must_finish_then_each_step_runs_once(batch_fixture):
    batch, calls = batch_fixture
    batch.stage_batch("Test", ["A", "B"])
    with pytest.raises(QueueError):
        batch.enter(1)
    batch.finish_step(0)
    with pytest.raises(QueueError):
        batch.enter(2)
    batch.enter(1)
    batch.finish_step(1)
    with pytest.raises(QueueError):
        batch.enter(1)
    batch.enter(2)
    state = batch.finish_step(2)
    assert state["status"] == "complete" and state["completed_step"] == 2
    assert len(calls) == 2  # Follow-ups do not stage fresh batches.
    with pytest.raises(QueueError):
        batch.enter(2)


def test_concurrent_duplicate_batch_returns_original_receipts(batch_fixture):
    batch, calls = batch_fixture
    def stage(_):
        return CodexBatch(batch.root, batch.environ, batch.runner).stage_batch("Test", ["A", "B"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(stage, range(3)))
    assert len(calls) == 2
    assert results[0]["receipts"] == results[1]["receipts"] == results[2]["receipts"]
    with pytest.raises(QueueError):
        batch.stage_batch("Different batch", ["X"])


@pytest.mark.parametrize("prompts", [[], ["A", ""], ["A", 1], ["A", "\x00"], "A", ["A"] * 13])
def test_validates_entire_batch_before_sending(batch_fixture, prompts):
    batch, calls = batch_fixture
    with pytest.raises(QueueError):
        batch.stage_batch("Test", prompts)
    assert not calls
    assert not batch.path.exists()


def test_pause_refuses_all_pending_followups(batch_fixture):
    batch, calls = batch_fixture
    batch.stage_batch("Test", ["A", "B"])
    batch.pause()
    with pytest.raises(QueueError):
        batch.stage_batch("Replacement", ["C"])
    for step in (1, 2):
        with pytest.raises(QueueError, match="stopped"):
            batch.enter(step)
    assert batch.read()["arrived"] == [1, 2]
    assert batch.read()["completed_step"] == -1
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["timeout", "error", "wrong_receipt", "launch"])
def test_partial_batch_preserves_receipts_and_does_not_resend(batch_fixture, failure):
    batch, calls = batch_fixture
    working = batch.runner
    def runner(argv, **kwargs):
        if not calls:
            return working(argv, **kwargs)
        calls.append(argv)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 20)
        if failure == "launch":
            raise FileNotFoundError("CLI removed")
        out = f"Queued message {uuid4()} for thread {uuid4()}."
        return subprocess.CompletedProcess(argv, 1 if failure == "error" else 0, out, "")
    batch.runner = runner
    with pytest.raises(QueueError, match="after 1 confirmed"):
        batch.stage_batch("Test", ["A", "B", "C"])
    assert len(calls) == 2  # C was never attempted.
    assert len(batch.read()["receipts"]) == 1
    with pytest.raises(QueueError):
        batch.stage_batch("Test", ["A", "B", "C"])
    assert len(calls) == 2  # A was not duplicated.
    with pytest.raises(QueueError, match="stopped"):
        batch.enter(1)
    if failure != "launch":
        assert batch.pause()["status"] == "uncertain"
        with pytest.raises(QueueError):
            batch.stage_batch("Replacement", ["C"])


def test_q_state_does_not_overwrite_g_state(batch_fixture):
    batch, calls = batch_fixture
    adaptive = CodexQueue(batch.root, batch.environ, batch.runner)
    adaptive.start("Separate g metadata", 2)
    original = adaptive.path.read_bytes()
    batch.stage_batch("Q test", ["A"])
    assert adaptive.path.read_bytes() == original
    assert batch.path != adaptive.path


def test_batch_rejects_wrong_task_state(batch_fixture):
    batch, calls = batch_fixture
    batch.stage_batch("Test", ["A"])
    state = batch.read()
    state["thread_id"] = str(uuid4())
    batch.save(state)
    with pytest.raises(QueueError, match="task ID"):
        batch.finish_step(0)


def test_cli_dispatches_literal_batch_through_real_subprocess(tmp_path):
    thread = str(uuid4())
    env = {**os.environ, "CODEX_THREAD_ID": thread, "CODEX_SESSION_ID": thread,
           "CODEX_HOME": str(tmp_path), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    recorded = tmp_path / "calls.jsonl"
    executable = tmp_path / "codex-fixture"
    executable.write_text(f"#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\n"
                          f"with Path({str(recorded)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                          f"print('Queued message {uuid4()} for thread {thread}.')\n")
    executable.chmod(0o700)
    objective = tmp_path / "objective.txt"
    objective.write_text("Test literals")
    prompts = tmp_path / "prompts.json"
    prompts.write_text(json.dumps(["Keep $(literal) text", "Keep `literal` text"]))
    result = subprocess.run([sys.executable, "-m", "auto_reply_route.codex_batch", "stage",
                             "--objective-file", str(objective), "--prompts-file", str(prompts),
                             "--codex-bin", str(executable)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "initial"
    assert [json.loads(line)[-1] for line in recorded.read_text().splitlines()] == [
        "/q (Follow-up 1/2) Keep $(literal) text", "/q (Follow-up 2/2) Keep `literal` text",
    ]
