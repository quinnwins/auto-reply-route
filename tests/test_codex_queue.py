"""Behavioral tests: task-bound native dispatch, budgets, and ambiguous delivery."""
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from auto_reply_route.codex_queue import CodexQueue, QueueError


@pytest.fixture
def setup_queue(tmp_path):
    thread = str(uuid4())
    env = {**os.environ, "CODEX_THREAD_ID": thread, "CODEX_SESSION_ID": thread}
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, f"Queued message {uuid4()} for thread {thread}.\n", "")

    queue = CodexQueue(tmp_path, env, runner)
    return queue, calls


def test_start_does_not_queue_and_preserves_objective(setup_queue):
    queue, calls = setup_queue
    state = queue.start("Review only; do not implement.", 3)
    assert state["step"] == 1 and state["status"] == "active"
    assert state["objective"] == "Review only; do not implement."
    assert not calls


def test_dispatch_uses_current_task_literal_prompt_and_native_receipt(setup_queue):
    queue, calls = setup_queue
    queue.start("Test a feature", 3)
    prompt = "Investigate the failing assertion; preserve $(secret) and `literal` text.\nUse the actual result."
    result = queue.stage(prompt, 1, "/installed/codex")
    argv, kwargs = calls[0]
    assert argv == ["/installed/codex", "queue", "--thread", queue.thread_id,
                    "--message", "/g (Step 2/3) " + prompt]
    assert "shell" not in kwargs
    assert kwargs["timeout"] == 20
    assert result["status"] == "queued"
    assert result["step"] == 1  # queued is not executed
    assert result["pending"]["message_id"] == result["receipts"][0]["message_id"]
    assert queue.enter(2)["step"] == 2
    assert queue.read()["pending"] is None


def test_duplicate_dispatch_sends_once_even_across_instances(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 3)
    def send(_):
        other = CodexQueue(queue.root, queue.environ, queue.runner)
        return other.stage("Check the actual failed test", 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(send, range(4)))
    assert len(calls) == 1
    assert len({s["pending"]["message_id"] for s in states}) == 1
    with pytest.raises(QueueError):
        queue.stage("A different prompt", 1)


def test_budget_stops_without_claiming_completion(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 2)
    queue.stage("Fix the test", 1)
    queue.enter(2)
    state = queue.stage("More work remains", 2)
    assert state["status"] == "limit"
    assert len(calls) == 1


def test_complete_early_prevents_further_queueing(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 5)
    queue.finish("complete", 1)
    with pytest.raises(QueueError):
        queue.stage("Unnecessary work", 1)
    assert not calls


def test_pause_rejects_arriving_native_message(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 3)
    queue.stage("Check test result", 1)
    queue.finish("paused", 1)
    with pytest.raises(QueueError):
        queue.start("Different task", 3)
    with pytest.raises(QueueError, match="paused"):
        queue.enter(2)
    assert queue.read()["pending"] is None
    assert len(calls) == 1


def test_wrong_task_and_stale_steps_cannot_advance(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 3)
    with pytest.raises(QueueError):
        queue.stage("Wrong step", 2)
    with pytest.raises(QueueError):
        queue.enter(2)
    with pytest.raises(QueueError):
        queue.finish("limit", 1)
    state = queue.read()
    state["thread_id"] = str(uuid4())
    queue.save(state)
    with pytest.raises(QueueError, match="task ID"):
        queue.stage("Wrong task", 1)
    assert not calls


@pytest.mark.parametrize("failure", ["timeout", "failure", "bad_receipt", "wrong_thread"])
def test_uncertain_delivery_cannot_be_retried(setup_queue, failure):
    queue, calls = setup_queue
    queue.start("Test", 3)
    def fail(argv, **kwargs):
        calls.append(argv)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 20)
        stdout = "unrecognized output"
        if failure == "wrong_thread":
            stdout = f"Queued message {uuid4()} for thread {uuid4()}."
        return subprocess.CompletedProcess(argv, 1 if failure == "failure" else 0, stdout, "")
    queue.runner = fail
    with pytest.raises(QueueError):
        queue.stage("Check failure", 1)
    assert queue.read()["status"] == "uncertain"
    with pytest.raises(QueueError):
        queue.stage("Check failure", 1)
    with pytest.raises(QueueError):
        queue.finish("complete", 1)
    assert len(calls) == 1


def test_executable_missing_is_not_recorded_as_queued(setup_queue):
    queue, calls = setup_queue
    queue.start("Test", 3)
    def missing(*args, **kwargs):
        raise FileNotFoundError("missing")
    queue.runner = missing
    with pytest.raises(QueueError):
        queue.stage("Check", 1, "/missing/codex")
    assert queue.read()["status"] == "active"
    assert queue.read()["pending"] is None


@pytest.mark.parametrize("thread", ["", "../other-task", "not-a-uuid"])
def test_requires_valid_current_task(tmp_path, thread):
    with pytest.raises(QueueError):
        CodexQueue(tmp_path, {"CODEX_THREAD_ID": thread})


def test_rejects_conflicting_session_identity(tmp_path):
    with pytest.raises(QueueError):
        CodexQueue(tmp_path, {"CODEX_THREAD_ID": str(uuid4()), "CODEX_SESSION_ID": str(uuid4())})


@pytest.mark.parametrize("limit", [0, 13, -1])
def test_invalid_budget_cannot_create_run(setup_queue, limit):
    queue, calls = setup_queue
    with pytest.raises(QueueError):
        queue.start("Test", limit)
    assert not queue.path.exists()


def test_cli_runs_real_queue_subprocess_with_literal_arguments(tmp_path):
    """An executable fixture checks the production subprocess boundary, not a mock call."""
    thread = str(uuid4())
    env = {**os.environ, "CODEX_THREAD_ID": thread, "CODEX_SESSION_ID": thread,
           "CODEX_HOME": str(tmp_path), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    executable = tmp_path / "codex-fixture"
    captured = tmp_path / "arguments.json"
    executable.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
                          f"Path({str(captured)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                          f"print('Queued message {uuid4()} for thread {thread}.')\n")
    executable.chmod(0o700)
    objective = tmp_path / "objective.txt"
    objective.write_text("Check the fixture")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Inspect $(do_not_execute) and `literal` output")
    base = [sys.executable, "-m", "auto_reply_route.codex_queue"]
    first = subprocess.run(base + ["start", "--objective-file", str(objective), "--steps", "2"],
                           env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(base + ["stage", "--step", "1", "--prompt-file", str(prompt),
                                   "--codex-bin", str(executable)], env=env, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert json.loads(captured.read_text())[-1] == "/g (Step 2/2) " + prompt.read_text()
    assert json.loads(second.stdout)["status"] == "queued"
