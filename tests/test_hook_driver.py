from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from auto_reply_route.hook_driver import (
    AntigravityHookDriver,
    AutoHealController,
    GateResult,
    QueueDispatcher,
    QuarantineAutoHealController,
    handle_stop_hook,
)
from auto_reply_route.models import (
    AlternativeBranch,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.state_machine import RouteStateMachine


def _create_sample_manifest(route_id: str = "test-route") -> RouteManifest:
    step_0 = RouteStep(
        index=0,
        title="Step One",
        primary_prompt="Implement initial prototype in app.py",
        status=StepStatus.RUNNING,
        assertions=["python3 -c 'import sys; sys.exit(0)'"],
    )
    step_1 = RouteStep(
        index=1,
        title="Step Two",
        primary_prompt="Add comprehensive unit tests for app.py",
        status=StepStatus.PENDING,
        assertions=["python3 -c 'import sys; sys.exit(0)'"],
    )
    return RouteManifest(
        route_id=route_id,
        title="Test Multi-Step Feature Route",
        steps=[step_0, step_1],
        current_step_idx=0,
        state=StepStatus.RUNNING,
    )


def _write_transcript(path: Path, steps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s) + "\n")


class TestDisambiguation:
    """Tests disambiguating true turn completion vs intermediate tool steps."""

    def test_ignores_non_model_stop(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-1",
            "terminationReason": "tool_use",
            "fullyIdle": True,
            "transcriptPath": str(tmp_path / "transcript.jsonl"),
        }
        res = driver.handle_stop_hook(hook_input)
        assert res == {"decision": "allow"}

    def test_ignores_not_fully_idle(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-1",
            "terminationReason": "model_stop",
            "fullyIdle": False,
            "transcriptPath": str(tmp_path / "transcript.jsonl"),
        }
        res = driver.handle_stop_hook(hook_input)
        assert res == {"decision": "allow"}

    def test_ignores_when_transcript_has_pending_tool_calls(self, tmp_path: Path) -> None:
        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": "Start step",
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls"}}],
                },
            ],
        )

        manifest = _create_sample_manifest()
        state_file = tmp_path / ".route_state_conv-1.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-1",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }
        res = driver.handle_stop_hook(hook_input)
        assert res == {"decision": "allow"}

        # Verify step was not advanced prematurely
        sm = RouteStateMachine.load_checkpoint(str(state_file))
        assert sm.manifest.current_step_idx == 0


class TestFastPath:
    """Tests fast-path in-band step advancement and route completion."""

    def test_advances_to_next_step_prompt(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        state_file = tmp_path / ".route_state_conv-fast.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[0].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Prototype implemented.",
                    "tool_calls": [],
                },
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-fast",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        res = driver.handle_stop_hook(hook_input)

        assert res["decision"] == "continue"
        assert res["reason"] == manifest.steps[1].primary_prompt

        # Verify state machine progressed to step 1
        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.manifest.current_step_idx == 1
        assert reloaded.manifest.steps[0].status == StepStatus.COMPLETED
        assert reloaded.manifest.steps[1].status == StepStatus.RUNNING
        assert reloaded.is_running

    def test_completion_when_all_steps_finish(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        # Set to last step
        manifest.current_step_idx = 1
        manifest.steps[0].status = StepStatus.COMPLETED
        manifest.steps[1].status = StepStatus.RUNNING

        state_file = tmp_path / ".route_state_conv-complete.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[1].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Unit tests added and verified.",
                    "tool_calls": [],
                },
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-complete",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        res = driver.handle_stop_hook(hook_input)

        # Finished route returns allow
        assert res == {"decision": "allow"}

        # State machine is COMPLETED
        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.is_completed
        assert reloaded.manifest.steps[1].status == StepStatus.COMPLETED

        # Milestone summary was generated
        assert "milestone_summary" in reloaded.manifest.metadata
        milestone_content = reloaded.manifest.metadata["milestone_summary"]
        assert "Route Completed" in milestone_content

        milestone_file = tmp_path / ".route_milestone_conv-complete.md"
        assert milestone_file.is_file()


class TestHumanPreemption:
    """Tests pausing route execution when human user types a message."""

    def test_pauses_route_on_user_explicit(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        state_file = tmp_path / ".route_state_conv-preempt.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        # User explicitly intervened during the run
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[0].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Working on step 0",
                    "tool_calls": [],
                },
                {
                    "step_index": 3,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": "Wait! Can you change the database schema before proceeding?",
                },
                {
                    "step_index": 4,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "I see your message, what schema changes would you like?",
                    "tool_calls": [],
                },
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-preempt",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        res = driver.handle_stop_hook(hook_input)

        # Must yield control to user with allow
        assert res == {"decision": "allow"}

        # Manifest is paused by user
        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.manifest.state == StepStatus.PAUSED_BY_USER
        assert reloaded.manifest.steps[0].status == StepStatus.PAUSED_BY_USER
        assert "Human preemption" in reloaded.manifest.metadata.get("pause_reason", "")


class TestAutoHealAndCircuitBreaker:
    """Tests quarantine auto-heal retries and divergence circuit breaker."""

    def test_auto_heal_turn_injection_on_first_gate_failure(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        # Failing assertion
        manifest.steps[0].assertions = ["python3 -c 'import sys; sys.exit(1)'"]
        state_file = tmp_path / ".route_state_conv-heal1.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[0].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Finished implementing prototype.",
                    "tool_calls": [],
                },
            ],
        )

        driver = AntigravityHookDriver(base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-heal1",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        res = driver.handle_stop_hook(hook_input)

        assert res["decision"] == "continue"
        assert "[AUTO-HEAL ATTEMPT 1]" in res["reason"]
        assert "Gate check failed" in res["reason"]
        assert "Fix this issue" in res["reason"]

        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.manifest.steps[0].retries == 1
        assert reloaded.manifest.steps[0].status == StepStatus.QUARANTINE_RETRY

    def test_circuit_breaker_pause_on_divergence(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        manifest.steps[0].assertions = ["python3 -c 'import sys; sys.exit(1)'"]
        state_file = tmp_path / ".route_state_conv-div.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[0].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Turn 1",
                    "tool_calls": [],
                },
            ],
        )

        controller = QuarantineAutoHealController()
        # Simulate attempt 1 had 1 error
        controller.record_failure("error 1", error_count=1)

        # Hook driver with pre-seeded controller where attempt 2 has >= errors (divergence)
        driver = AntigravityHookDriver(heal_controller=controller, base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-div",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        res = driver.handle_stop_hook(hook_input)

        # Divergence halts execution and yields to user
        assert res == {"decision": "allow"}

        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.manifest.state == StepStatus.PAUSED
        assert reloaded.manifest.metadata.get("breaker_status") == "DIVERGENCE_HALT"

        # Living-room explanation written
        living_room = reloaded.manifest.metadata.get("living_room_explanation", "")
        assert "We paused on Step 1" in living_room
        assert "couldn't" not in living_room.lower() or "safely saved" in living_room

        exp_file = tmp_path / ".route_explanation_conv-div.txt"
        assert exp_file.is_file()

    def test_circuit_breaker_pause_on_exceeded_retries(self, tmp_path: Path) -> None:
        manifest = _create_sample_manifest()
        manifest.steps[0].assertions = ["python3 -c 'import sys; sys.exit(1)'"]
        state_file = tmp_path / ".route_state_conv-exceed.json"
        RouteStateMachine(manifest).save_checkpoint(str(state_file))

        t_file = tmp_path / "transcript.jsonl"
        _write_transcript(
            t_file,
            [
                {
                    "step_index": 1,
                    "source": "HOOK",
                    "type": "USER_INPUT",
                    "content": manifest.steps[0].primary_prompt,
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "content": "Turn 1",
                    "tool_calls": [],
                },
            ],
        )

        controller = QuarantineAutoHealController()
        controller.record_failure("error 1", error_count=2)
        controller.record_failure("error 2", error_count=1)  # improved, retry 2 allowed

        driver = AntigravityHookDriver(heal_controller=controller, base_dir=tmp_path)
        hook_input = {
            "conversationId": "conv-exceed",
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "transcriptPath": str(t_file),
            "activeRouteFile": str(state_file),
        }

        # Attempt 3 exceeds max_retries limit
        res = driver.handle_stop_hook(hook_input)
        assert res == {"decision": "allow"}

        reloaded = RouteStateMachine.load_checkpoint(str(state_file))
        assert reloaded.manifest.state == StepStatus.PAUSED
        assert reloaded.manifest.metadata.get("breaker_status") == "EXHAUSTED_HALT"

        living_room = reloaded.manifest.metadata.get("living_room_explanation", "")
        assert "We paused on Step 1" in living_room
        assert "3 tries" in living_room or "3 attempts" in living_room


class TestQueueDispatcher:
    """Tests slow-path user message queue dispatcher."""

    def test_queue_user_message(self, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        dispatcher = QueueDispatcher(app_data_dir=app_data)
        conv_id = "test-conv-queue"

        payload = dispatcher.queue_user_message(
            conversation_id=conv_id,
            content="Next prompt via slow path queue",
        )

        assert payload["recipient"] == conv_id
        assert payload["content"] == "Next prompt via slow path queue"
        assert payload["priority"] == "MESSAGE_PRIORITY_HIGH"
        msg_id = payload["id"]

        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        msg_file = messages_dir / f"{msg_id}.json"
        assert msg_file.is_file()

        with open(msg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["id"] == msg_id
        assert data["content"] == "Next prompt via slow path queue"

        # Check undelivered indicator touched
        undelivered_file = messages_dir / "undelivered" / msg_id
        assert undelivered_file.is_file()

    def test_dispatch_slow_path_with_task_id(self, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        dispatcher = QueueDispatcher(app_data_dir=app_data)
        conv_id = "test-conv-task"

        payload = dispatcher.dispatch_slow_path(
            conversation_id=conv_id,
            next_step_prompt="Run regression test step",
            task_id="task-42",
        )

        assert "[BACKGROUND TASK task-42 COMPLETED]" in payload["content"]
        assert "Run regression test step" in payload["content"]

    def test_handle_task_completion_failure(self, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        dispatcher = QueueDispatcher(app_data_dir=app_data)
        conv_id = "test-conv-fail"

        payload = dispatcher.handle_task_completion(
            conversation_id=conv_id,
            task_id="task-99",
            next_step_prompt="Next step",
            exit_code=1,
            output="Error: test suite timed out",
        )

        assert "[BACKGROUND TASK task-99 FAILED with code 1]" in payload["content"]
        assert "Error: test suite timed out" in payload["content"]


class TestModuleLevelDispatcher:
    """Tests module-level hook function and CLI integration."""

    def test_handle_stop_hook_function(self, tmp_path: Path) -> None:
        res = handle_stop_hook({
            "conversationId": "none",
            "terminationReason": "tool_use",
            "fullyIdle": True,
        })
        assert res == {"decision": "allow"}
