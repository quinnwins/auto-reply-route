"""Exact Lifecycle & Timing Verification Tests for /g Adaptive Guidance.

Verifies:
1. Under /g, prompt dispatch occurs strictly at the END of the turn, NOT at the beginning.
2. At the beginning of a /g turn, Zero Upfront Staging is strictly enforced.
3. Task execution and test runs occur BEFORE end-of-turn evaluation.
4. Synthesized follow-up prompt dynamically adapts to actual test/task findings.
5. Prefix contains '/g (Step k/N)' for continuous looping.
6. When step budget is exhausted or all tasks pass, termination is clean with NO prompt dispatched.
7. Contrast: under /q, upfront staging happens immediately at the START of the turn.
8. Pending tool calls inhibit premature turn conclusion or dispatch.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_reply_route.guidance import (
    AdaptiveGuidanceController,
    GuidanceMode,
    TurnPhase,
)
from auto_reply_route.hook_driver import AntigravityHookDriver


class TestAdaptiveGuidanceTimingAndOrdering:
    """Exact behavioral verification of /g vs /q lifecycle timing."""

    def test_g_sends_prompt_at_end_of_turn_never_at_beginning(self) -> None:
        """Proves that /g dispatches at the END of the turn and NEVER at the beginning."""
        dispatched_prompts: list[dict[str, Any]] = []

        def mock_dispatch(prompt: str) -> bool:
            dispatched_prompts.append({
                "prompt": prompt,
                "timestamp": time.time(),
            })
            return True

        controller = AdaptiveGuidanceController(default_budget=5, dispatch_fn=mock_dispatch)

        # 1. Start of Turn
        command = "/g build stripe webhook 5 steps"
        state, can_dispatch_upfront = controller.start_turn(command)

        # Invariant 1: At the beginning of the turn, upfront staging is forbidden
        assert can_dispatch_upfront is False, "Zero Upfront Staging: /g must not allow dispatch at start of turn"
        assert len(dispatched_prompts) == 0, "No prompts must be sent at the beginning of a /g turn"

        # 2. Task Execution Phase
        task_executed = False
        task_start_time = 0.0
        task_end_time = 0.0

        def dummy_task():
            nonlocal task_executed, task_start_time, task_end_time
            task_start_time = time.time()
            time.sleep(0.01)  # Simulate real test/tool work
            task_executed = True
            task_end_time = time.time()
            return {"success": True, "tests_passed": 4, "error": None}

        task_result = controller.execute_task(dummy_task, state)
        assert task_executed is True
        assert len(dispatched_prompts) == 0, "No prompts must be sent during tool/task execution"

        # 3. End-of-Turn Evaluation Phase
        eval_message, should_dispatch = controller.evaluate_and_steer(state, task_result)
        assert should_dispatch is True
        assert eval_message.startswith("/g (Step 2/5)")
        assert len(dispatched_prompts) == 0, "Evaluation synthesizes prompt but does not dispatch until turn end"

        # 4. Turn End / Conclusion Phase
        dispatched = controller.end_turn(state, should_dispatch)

        # Invariant 2: Dispatch only occurs at the very end of the turn
        assert len(dispatched_prompts) == 1
        assert dispatched == dispatched_prompts[0]["prompt"]
        assert dispatched.startswith("/g (Step 2/5)")

        # Verify strict chronological timeline:
        # Task start < Task end < Dispatch time
        dispatch_time = dispatched_prompts[0]["timestamp"]
        assert task_start_time < task_end_time <= dispatch_time

        # Verify the event log order
        phases = [event.phase for event in controller.events]
        assert phases == [
            TurnPhase.TURN_START,
            TurnPhase.TURN_START,
            TurnPhase.TASK_EXECUTION,
            TurnPhase.TASK_EXECUTION,
            TurnPhase.EVALUATION,
            TurnPhase.EVALUATION,
            TurnPhase.TURN_END,
            TurnPhase.TURN_END,
            TurnPhase.COMPLETED,
        ]

    def test_q_fast_queue_dispatches_upfront_at_start_of_turn(self) -> None:
        """Contrasts with /q: verifies that /q allows upfront staging at turn start."""
        dispatched_prompts: list[str] = []

        def mock_dispatch(prompt: str) -> bool:
            dispatched_prompts.append(prompt)
            return True

        controller = AdaptiveGuidanceController(default_budget=5, dispatch_fn=mock_dispatch)

        # Start of Turn with /q
        command = "/q build stripe webhook 3 steps"
        state, can_dispatch_upfront = controller.start_turn(command)

        # Invariant: /q explicitly allows upfront staging at turn start
        assert state.mode == GuidanceMode.FAST_QUEUE
        assert can_dispatch_upfront is True, "/q must permit upfront staging at the beginning of the turn"

    def test_g_adapts_next_prompt_to_real_test_failure_at_turn_end(self) -> None:
        """Verifies that the prompt sent at turn end adapts dynamically to actual test results."""
        dispatched_prompts: list[str] = []
        controller = AdaptiveGuidanceController(default_budget=4, dispatch_fn=dispatched_prompts.append)

        # Turn 1: Starts with Step 1
        state, _ = controller.start_turn("/g (Step 1/4) implement payment route")

        # Simulate task execution failing a specific assertion
        def failing_task():
            return {
                "success": False,
                "error": "stripe signature validation returned HTTP 400",
                "failed_test": "test_stripe_webhook_signature",
            }

        result = controller.execute_task(failing_task, state)
        next_prompt, should_dispatch = controller.evaluate_and_steer(state, result)
        controller.end_turn(state, should_dispatch)

        # The prompt dispatched at turn end specifically targeted the failure
        assert len(dispatched_prompts) == 1
        assert dispatched_prompts[0] == "/g (Step 2/4) fix stripe signature validation returned HTTP 400 discovered in tests and verify clean pass"

    def test_g_bounded_termination_stops_cleanly_without_dispatch(self) -> None:
        """Verifies that when all tasks are satisfied or step budget is reached, no prompt is sent."""
        dispatched_prompts: list[str] = []
        controller = AdaptiveGuidanceController(default_budget=3, dispatch_fn=dispatched_prompts.append)

        # Case A: Step budget exhausted (Step 3/3)
        state, _ = controller.start_turn("/g (Step 3/3) finalize documentation")
        result = controller.execute_task(lambda: {"success": True}, state)
        msg, should_dispatch = controller.evaluate_and_steer(state, result)
        dispatched = controller.end_turn(state, should_dispatch)

        assert msg == "DONE: All tasks satisfied."
        assert should_dispatch is False
        assert dispatched is None
        assert len(dispatched_prompts) == 0, "Must not send follow-up prompt when budget is exhausted"

        # Case B: All tasks satisfied early
        state_early, _ = controller.start_turn("/g (Step 1/5) build component")
        result_early = controller.execute_task(lambda: {"success": True, "all_tasks_satisfied": True}, state_early)
        msg_early, should_dispatch_early = controller.evaluate_and_steer(state_early, result_early)
        dispatched_early = controller.end_turn(state_early, should_dispatch_early)

        assert msg_early == "DONE: All tasks satisfied."
        assert should_dispatch_early is False
        assert dispatched_early is None
        assert len(dispatched_prompts) == 0, "Must not send follow-up prompt when all tasks are satisfied early"

    def test_pending_tool_calls_prevent_premature_turn_dispatch(self, tmp_path) -> None:
        """Proves that intermediate tool execution prevents turn completion and prompt dispatch."""
        driver = AntigravityHookDriver(base_dir=tmp_path)

        # Case 1: In-flight tool call present in transcript
        steps_with_active_tool = [
            {"step_index": 1, "source": "USER", "type": "USER_INPUT", "content": "/g run tests"},
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "RUNNING",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest"}}],
            },
        ]
        assert driver.has_pending_tool_calls(steps_with_active_tool) is True

        # Hook handler must return 'allow' (no continue/dispatch) while tools are active
        res = driver.handle_stop_hook({
            "conversationId": "test-conv",
            "terminationReason": "tool_use",  # Not model_stop yet
            "fullyIdle": False,
        })
        assert res == {"decision": "allow"}, "Must not advance or dispatch prompt while tools are in-flight"

        # Case 2: Model has finished all tool calls and reached model_stop
        steps_finished = [
            {"step_index": 1, "source": "USER", "type": "USER_INPUT", "content": "/g run tests"},
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "tool_calls": [],
            },
        ]
        assert driver.has_pending_tool_calls(steps_finished) is False
