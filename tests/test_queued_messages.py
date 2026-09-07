from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pytest

from auto_reply_route.builder import generate_followup_queue
from auto_reply_route.cli import main as cli_main
from auto_reply_route.hook_driver import AntigravityHookDriver
from auto_reply_route.models import (
    MessageQueueManifest,
    QueuedMessage,
    QueuedMessageStatus,
)


def _write_transcript(path: Path, steps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s) + "\n")


class TestMessageQueueManifest:
    """Test suite for MessageQueueManifest data structures and persistence."""

    def test_queue_initialization_and_properties(self) -> None:
        queue = MessageQueueManifest(conversation_id="conv-123")
        assert queue.is_empty
        assert queue.total_count == 0
        assert queue.pending_count == 0
        assert not queue.is_completed

        msg1 = queue.add_message("Review research findings", domain="research")
        assert msg1.index == 0
        assert msg1.status == QueuedMessageStatus.PENDING
        assert queue.total_count == 1
        assert queue.pending_count == 1
        assert not queue.is_empty

    def test_queue_peeking_and_popping(self) -> None:
        queue = MessageQueueManifest(conversation_id="conv-456")
        queue.add_message("Prompt 1")
        queue.add_message("Prompt 2")

        # Peek does not advance
        peeked = queue.peek_next_message()
        assert peeked is not None
        assert peeked.prompt == "Prompt 1"
        assert queue.active_index == 0

        # Pop advances
        popped = queue.pop_next_message()
        assert popped is not None
        assert popped.prompt == "Prompt 1"
        assert popped.status == QueuedMessageStatus.COMPLETED
        assert popped.completed_at is not None
        assert queue.active_index == 1

        # Second pop
        popped2 = queue.pop_next_message()
        assert popped2 is not None
        assert popped2.prompt == "Prompt 2"
        assert queue.is_completed

        # Third pop on exhausted queue returns None
        assert queue.pop_next_message() is None

    def test_queue_pause_and_resume(self) -> None:
        queue = MessageQueueManifest(conversation_id="conv-789")
        queue.add_message("Prompt 1")
        assert queue.peek_next_message() is not None

        queue.pause(reason="User stopped by typing")
        assert queue.is_paused
        assert queue.peek_next_message() is None
        assert queue.pop_next_message() is None

        queue.resume()
        assert not queue.is_paused
        assert queue.peek_next_message() is not None

    def test_atomic_file_persistence(self, tmp_path: Path) -> None:
        target_file = tmp_path / "queue.json"
        queue = MessageQueueManifest(conversation_id="conv-atomic")
        queue.add_message("Task A", domain="code")
        queue.add_message("Task B", domain="ux")
        queue.save_to_file(target_file)

        assert target_file.is_file()
        loaded = MessageQueueManifest.load_from_file(target_file)
        assert loaded is not None
        assert loaded.conversation_id == "conv-atomic"
        assert len(loaded.messages) == 2
        assert loaded.messages[0].prompt == "Task A"
        assert loaded.messages[1].domain == "ux"


class TestFollowupQueueGeneration:
    """Test suite for domain-agnostic follow-up queue generation."""

    def test_default_count_is_one(self) -> None:
        prompt = "limitations of rigid STL-derived custom trays in the presence of dynamic dental changes"
        queue = generate_followup_queue(prompt)
        assert len(queue.messages) == 1
        msg = queue.messages[0]
        assert "review and research" in msg.prompt.lower()
        assert "refute earlier claims" in msg.prompt
        assert "subagent" not in msg.prompt.lower()  # Default assumes NO subagents
        assert msg.domain == "research"

    def test_subagent_directive_only_when_requested(self) -> None:
        prompt = "dental cavitation device"
        # No subagents
        q_no_sub = generate_followup_queue(prompt, count=3, max_subagents=0)
        for m in q_no_sub.messages:
            assert "subagent" not in m.prompt.lower()

        # With subagents
        q_sub = generate_followup_queue(prompt, count=3, max_subagents=3)
        for m in q_sub.messages:
            assert "subagent" in m.prompt.lower()

    def test_expanding_to_five_matches_user_screenshot_methodology(self) -> None:
        prompt = "limitations of rigid STL-derived custom trays in the presence of dynamic dental changes"
        queue = generate_followup_queue(prompt, count=5)
        assert len(queue.messages) == 5

        # Phase 1: Research & Refutation
        assert "refute earlier claims" in queue.messages[0].prompt.lower()
        # Phase 2: Least Complicated Prototype
        assert "prototype this" in queue.messages[1].prompt.lower()
        assert "least complicated way" in queue.messages[1].prompt.lower()
        # Phase 3: Feasibility & Probability
        assert "probability of success" in queue.messages[2].prompt.lower()
        # Phase 4: Adversarial Go / No-Go
        assert "go or no go" in queue.messages[3].prompt.lower()
        # Phase 5: Final Report
        assert "final report" in queue.messages[4].prompt.lower()

    def test_code_domain_generation(self) -> None:
        prompt = "Implement a Stripe webhook dispatcher in api/webhooks.py"
        queue = generate_followup_queue(prompt, count=3)
        assert len(queue.messages) == 3
        assert queue.messages[0].domain == "code"
        p0 = queue.messages[0].prompt.lower()
        assert "qa" in p0 or "review" in p0
        assert "prototype" in queue.messages[1].prompt.lower()
        p2 = queue.messages[2].prompt.lower()
        assert "slop" in p2 or "minimal code" in p2

    def test_ux_domain_generation(self) -> None:
        prompt = "Fix ugly styling and micro-craft spacing on settings modal dialog"
        queue = generate_followup_queue(prompt, count=2)
        assert len(queue.messages) == 2
        assert queue.messages[0].domain == "ux"
        assert "44px" in queue.messages[0].prompt.lower() or "concentric" in queue.messages[0].prompt.lower()
        assert "transitions" in queue.messages[1].prompt.lower() or "loading" in queue.messages[1].prompt.lower()

    def test_canvassing_routing_feature_prompt_defaults_to_code(self) -> None:
        """Verifies complex feature development tasks never leak venture capital or biomedical templates."""
        prompt = "Reconcile canvassing routing audit, implement crew screen resumability, and benchmark whole-itinerary optimization"
        queue = generate_followup_queue(prompt, count=5, max_subagents=3)
        assert len(queue.messages) == 5
        assert queue.messages[0].domain == "code"

        # Verify all 5 prompts are software engineering tasks
        for m in queue.messages:
            p_lower = m.prompt.lower()
            # Assert zero venture pitch or biomedical leaks
            assert "investment" not in p_lower
            assert "go or no go" not in p_lower
            assert "others that have failed" not in p_lower
            assert "dental" not in p_lower
            assert "cavitation" not in p_lower
            assert "subagent" in p_lower  # 3 subagents requested

    def test_unclassified_prompts_default_to_code(self) -> None:
        """Verifies unclassified developer prompts default to code rather than research."""
        prompt = "implement OAuth2 authentication flow"
        queue = generate_followup_queue(prompt, count=3)
        assert len(queue.messages) == 3
        assert queue.messages[0].domain == "code"
        assert "investment" not in queue.messages[2].prompt.lower()


class TestStopHookQueueDispatcher:
    """Test suite verifying Antigravity Stop Hook automatically dispatches queued messages."""

    def test_hook_dispatches_queued_messages_sequentially(self, tmp_path: Path) -> None:
        conv_id = "test-session-1"
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"
        transcript_file = tmp_path / "transcript.jsonl"

        # Initialize queue with 2 messages
        queue = MessageQueueManifest(conversation_id=conv_id)
        queue.add_message("Step 1: Run research subagents", domain="research")
        queue.add_message("Step 2: Prototype minimal design", domain="research")
        queue.save_to_file(queue_file)

        # Transcript simulating completed model turn without pending tools
        _write_transcript(
            transcript_file,
            [
                {"source": "USER", "type": "USER_INPUT", "content": "Initial prompt"},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)

        # --- Turn 1 Stop Event ---
        res1 = driver.handle_stop_hook({
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
        })
        assert res1["decision"] == "continue"
        assert res1["reason"] == "Step 1: Run research subagents"

        # Verify queue advanced on disk
        loaded_q = MessageQueueManifest.load_from_file(queue_file)
        assert loaded_q is not None
        assert loaded_q.active_index == 1

        # Simulate Antigravity executing Turn 1 and model completing response
        _write_transcript(
            transcript_file,
            [
                {"source": "USER", "type": "USER_INPUT", "content": "Initial prompt"},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
                {"source": "HOOK", "type": "USER_INPUT", "content": res1["reason"]},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
            ],
        )

        # --- Turn 2 Stop Event ---
        res2 = driver.handle_stop_hook({
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
        })
        assert res2["decision"] == "continue"
        assert res2["reason"] == "Step 2: Prototype minimal design"

        # Simulate Antigravity executing Turn 2 and model completing response
        _write_transcript(
            transcript_file,
            [
                {"source": "USER", "type": "USER_INPUT", "content": "Initial prompt"},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
                {"source": "HOOK", "type": "USER_INPUT", "content": res1["reason"]},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
                {"source": "HOOK", "type": "USER_INPUT", "content": res2["reason"]},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
            ],
        )

        # --- Turn 3 Stop Event (Queue now exhausted) ---
        res3 = driver.handle_stop_hook({
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
        })
        assert res3["decision"] == "allow"

    def test_human_preemption_pauses_queue(self, tmp_path: Path) -> None:
        conv_id = "test-session-preempt"
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"
        transcript_file = tmp_path / "transcript.jsonl"

        queue = MessageQueueManifest(conversation_id=conv_id)
        queue.add_message("Autonomous step 1")
        queue.save_to_file(queue_file)

        # Human user entered a message during the turn
        _write_transcript(
            transcript_file,
            [
                {"source": "USER", "type": "USER_INPUT", "content": "Wait, let's stop here!"},
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        res = driver.handle_stop_hook({
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
        })

        assert res["decision"] == "allow"
        loaded_q = MessageQueueManifest.load_from_file(queue_file)
        assert loaded_q is not None
        assert loaded_q.is_paused

    def test_domain_elastic_gating_allows_non_code_steps(self, tmp_path: Path) -> None:
        conv_id = "test-elastic-gate"
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"
        transcript_file = tmp_path / "transcript.jsonl"

        # Scientific research step has NO code assertions
        queue = MessageQueueManifest(conversation_id=conv_id)
        queue.add_message("Evaluate bioacoustics wave dispersion", domain="research")
        queue.save_to_file(queue_file)

        _write_transcript(
            transcript_file,
            [
                {"source": "USER", "type": "USER_INPUT", "content": "Analyze bioacoustics"},
                {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "COMPLETED", "tool_calls": []},
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        res = driver.handle_stop_hook({
            "conversationId": conv_id,
            "transcriptPath": str(transcript_file),
            "terminationReason": "model_stop",
            "fullyIdle": True,
        })

        # Must pass cleanly without failing on pytest or git checks
        assert res["decision"] == "continue"
        assert "Evaluate bioacoustics" in res["reason"]


class TestCLIInitAndQueue:
    """Test suite for agy-route init and agy-route queue subcommands."""

    def test_cli_init_creates_agents_hooks_and_skill(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cli_main(["init", "--dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "INITIALIZED" in captured.out

        hooks_json = tmp_path / ".agents" / "hooks.json"
        skill_md = tmp_path / ".agents" / "skills" / "route-runner" / "SKILL.md"
        assert hooks_json.is_file()
        assert skill_md.is_file()

        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        assert "hooks" in data
        assert "Stop" in data["hooks"]
        assert data["hooks"]["Stop"][0]["command"] == "agy-route hook"

    def test_cli_queue_generate_and_list(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        conv_id = "cli-test-session"
        exit_code = cli_main([
            "queue",
            "generate",
            "Prototype acoustic transducer for dental plaque removal",
            "--count", "3",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "QUEUE GENERATED & SAVED" in captured.out

        # Verify queue file exists
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"
        assert queue_file.is_file()

        # List queue
        exit_code2 = cli_main([
            "queue",
            "list",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code2 == 0
        captured2 = capsys.readouterr()
        assert "Queued Messages (3)" in captured2.out

        # Clear queue
        exit_code3 = cli_main([
            "queue",
            "clear",
            "--conversation-id", conv_id,
            "--dir", str(tmp_path),
        ])
        assert exit_code3 == 0
        assert not queue_file.exists()
