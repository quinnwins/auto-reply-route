from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

import pytest

from auto_reply_route.cli import main as cli_main
from auto_reply_route.hook_driver import AntigravityHookDriver
from auto_reply_route.models import (
    MessageQueueManifest,
    QueuedMessage,
    QueuedMessageStatus,
)
from auto_reply_route.queue_watcher import QueueWatcher


def _write_transcript(path: Path, steps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s) + "\n")


class TestWorkspaceHookVerificationAndSimulation:
    """Task 1: End-to-end Antigravity workspace hook initialization and simulation."""

    def test_init_workspace_creates_hooks_and_skill(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cli_main(["init", "--dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "INITIALIZED" in captured.out

        hooks_file = tmp_path / ".agents" / "hooks.json"
        skill_file = tmp_path / ".agents" / "skills" / "route-runner" / "SKILL.md"

        assert hooks_file.is_file()
        assert skill_file.is_file()

        # Parse and verify hooks JSON schema
        hooks_data = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert "hooks" in hooks_data
        assert "Stop" in hooks_data["hooks"]
        stop_hook_entry = hooks_data["hooks"]["Stop"][0]
        assert stop_hook_entry["command"] == "agy-route hook"

        # Verify skill content
        skill_text = skill_file.read_text(encoding="utf-8")
        assert "Route Runner Skill" in skill_text
        assert "100% Attention Allocation" in skill_text

    def test_e2e_multi_turn_simulation_with_human_preemption(self, tmp_path: Path) -> None:
        """Simulate: Turn 0 seed -> Turn 1 complete -> Turn 2 auto-dispatch -> Human interrupt -> Resume."""
        conv_id = "sim-e2e-trajectory"
        transcript_file = tmp_path / "transcripts" / f"{conv_id}.jsonl"
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"

        driver = AntigravityHookDriver(base_dir=tmp_path)

        # Step 0: User sets up a 3-step queue
        exit_code = cli_main([
            "queue",
            "--auto-generate", "3",
            "Design high-throughput payment settlement engine in Go",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code == 0
        assert queue_file.is_file()

        # Turn 1: Agent completes work
        _write_transcript(transcript_file, [
            {"source": "USER", "type": "USER_INPUT", "content": "Design high-throughput payment settlement engine in Go"},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Settlement engine core implemented."},
        ])

        hook_payload = {
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "activeQueueFile": str(queue_file),
        }
        res1 = driver.handle_stop_hook(hook_payload)
        assert res1["decision"] == "continue"
        assert "reason" in res1
        # First follow-up was dispatched
        q1 = MessageQueueManifest.load_from_file(queue_file)
        assert q1 is not None
        assert q1.active_index == 1
        assert q1.messages[0].status == QueuedMessageStatus.COMPLETED

        # Turn 2: Agent completes Turn 2
        _write_transcript(transcript_file, [
            {"source": "USER", "type": "USER_INPUT", "content": "Design high-throughput payment settlement engine in Go"},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Settlement engine core implemented."},
            {"source": "HOOK", "type": "USER_INPUT", "content": res1["reason"]},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Security audit passed."},
        ])

        res2 = driver.handle_stop_hook(hook_payload)
        assert res2["decision"] == "continue"
        q2 = MessageQueueManifest.load_from_file(queue_file)
        assert q2 is not None
        assert q2.active_index == 2
        assert q2.messages[1].status == QueuedMessageStatus.COMPLETED

        # Human Interrupt: User types into chat during Turn 3
        _write_transcript(transcript_file, [
            {"source": "USER", "type": "USER_INPUT", "content": "Design high-throughput payment settlement engine in Go"},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Settlement engine core implemented."},
            {"source": "HOOK", "type": "USER_INPUT", "content": res1["reason"]},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Security audit passed."},
            {"source": "HOOK", "type": "USER_INPUT", "content": res2["reason"]},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": [], "content": "Chaos testing in progress."},
            {"source": "USER", "type": "USER_INPUT", "content": "Wait, let us use Postgres instead of MySQL!"},
        ])

        res3 = driver.handle_stop_hook(hook_payload)
        # Hook must pause queue and allow human response without crashing
        assert res3["decision"] == "allow"
        q3 = MessageQueueManifest.load_from_file(queue_file)
        assert q3 is not None
        assert q3.is_paused is True
        assert "pause_reason" in q3.metadata

        # Resume queue via CLI
        exit_resume = cli_main([
            "queue",
            "resume",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_resume == 0
        q4 = MessageQueueManifest.load_from_file(queue_file)
        assert q4 is not None
        assert q4.is_paused is False

        # Final turn completion after resume
        res4 = driver.handle_stop_hook(hook_payload)
        assert res4["decision"] == "continue"
        q5 = MessageQueueManifest.load_from_file(queue_file)
        assert q5 is not None
        assert q5.is_completed is True


class TestQueueManagementCLIPolish:
    """Task 2: Queue Management CLI Polish, Ergonomics, and --json Support."""

    def test_queue_auto_generate_flag_and_status(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        conv_id = "auto-gen-test"
        exit_code = cli_main([
            "queue",
            "--auto-generate", "4",
            "Investigate transient tooth pain after cold beverages",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "QUEUE GENERATED & SAVED" in captured.out
        assert "4 follow-up message(s)" in captured.out

        # Status check
        exit_status = cli_main([
            "queue",
            "status",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_status == 0
        captured_status = capsys.readouterr()
        assert "QUEUED MESSAGES MONITOR" in captured_status.out
        assert "4/4" in captured_status.out or "0/4" in captured_status.out

    def test_queue_short_alias_a_and_pop(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        conv_id = "alias-test"
        exit_code = cli_main([
            "queue",
            "-a", "2",
            "Refactor authentication middleware",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code == 0
        capsys.readouterr()

        # Pop Turn 1
        exit_pop = cli_main([
            "queue",
            "pop",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_pop == 0
        captured_pop = capsys.readouterr()
        assert "POPPED MESSAGE" in captured_pop.out
        assert "1/2" in captured_pop.out

    def test_queue_json_output_across_commands(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        conv_id = "json-test"
        # Generate with --json
        exit_gen = cli_main([
            "queue",
            "--auto-generate", "3",
            "Build accessible modal dialog",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_gen == 0
        captured_gen = capsys.readouterr()
        gen_data = json.loads(captured_gen.out.strip())
        assert gen_data["conversation_id"] == conv_id
        assert len(gen_data["messages"]) == 3

        # Status with --json
        exit_status = cli_main([
            "queue",
            "status",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_status == 0
        captured_status = capsys.readouterr()
        status_data = json.loads(captured_status.out.strip())
        assert status_data["total"] == 3
        assert status_data["pending"] == 3
        assert status_data["status"] == "ACTIVE"

        # Pause with --json
        exit_pause = cli_main([
            "queue",
            "pause",
            "Reviewing test suite before continuation",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_pause == 0
        captured_pause = capsys.readouterr()
        pause_data = json.loads(captured_pause.out.strip())
        assert pause_data["is_paused"] is True

        # Pop with --json
        exit_pop = cli_main([
            "queue",
            "pop",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_pop == 0
        captured_pop = capsys.readouterr()
        pop_data = json.loads(captured_pop.out.strip())
        # While paused, pop returns None
        assert pop_data["popped"] is None

        # Resume with --json
        exit_resume = cli_main([
            "queue",
            "resume",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_resume == 0
        captured_resume = capsys.readouterr()
        resume_data = json.loads(captured_resume.out.strip())
        assert resume_data["is_paused"] is False

        # Pop again after resume
        exit_pop2 = cli_main([
            "queue",
            "pop",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_pop2 == 0
        captured_pop2 = capsys.readouterr()
        pop_data2 = json.loads(captured_pop2.out.strip())
        assert pop_data2["popped"] is not None
        assert pop_data2["remaining"] == 2

        # Clear with --json
        exit_clear = cli_main([
            "queue",
            "clear",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--json",
        ])
        assert exit_clear == 0
        captured_clear = capsys.readouterr()
        clear_data = json.loads(captured_clear.out.strip())
        assert clear_data["cleared"] is True


class TestHeadlessWatcherMode:
    """Task 3: Headless Daemon / Watcher Mode Verification."""

    def test_watch_once_visual_and_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        conv_id = "watcher-test"
        # Create queue
        cli_main([
            "queue",
            "--auto-generate", "2",
            "Implement binary search tree with rebalancing",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        capsys.readouterr()

        # Run watch --once
        exit_watch = cli_main([
            "watch",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--once",
        ])
        assert exit_watch == 0
        captured_watch = capsys.readouterr()
        assert "QUEUED MESSAGES MONITOR" in captured_watch.out
        assert "Turn 1 of 2" in captured_watch.out

        # Run watch --once --json
        exit_watch_json = cli_main([
            "watch",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
            "--once",
            "--json",
        ])
        assert exit_watch_json == 0
        captured_watch_json = capsys.readouterr()
        watch_data = json.loads(captured_watch_json.out.strip())
        assert watch_data["total"] == 2
        assert watch_data["exists"] is True
        assert watch_data["status"] == "ACTIVE"

    def test_watcher_detects_state_update(self, tmp_path: Path) -> None:
        conv_id = "watcher-update-test"
        watcher = QueueWatcher(target_dir=tmp_path, conversation_id=conv_id)

        # Initial: not found
        snap1 = watcher.snapshot()
        assert snap1["exists"] is False

        # Create queue
        q = MessageQueueManifest(conversation_id=conv_id)
        q.add_message("Step 1")
        q.save_to_file(watcher.queue_file)

        snap2 = watcher.snapshot()
        assert snap2["exists"] is True
        assert snap2["total"] == 1
        assert snap2["status"] == "ACTIVE"

        # Advance queue
        q.pop_next_message()
        q.save_to_file(watcher.queue_file)

        snap3 = watcher.snapshot()
        assert snap3["completed"] == 1
        assert snap3["status"] == "COMPLETED"
