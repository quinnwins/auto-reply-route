"""Comprehensive tests for ToolUsageWatcher and Watchdog optimistic concurrency."""

from __future__ import annotations

import pytest

from auto_reply_route.models import RouteManifest, RouteStep, StepStatus
from auto_reply_route.watcher import (
    ToolUsageWatcher,
    WatchdogAction,
    WatchdogConfig,
    WatchdogDecision,
)


@pytest.fixture
def manifest() -> RouteManifest:
    return RouteManifest(
        route_id="sample-watchdog-route",
        title="Sample Watchdog Route",
        steps=[
            RouteStep(index=0, title="Step 1: Scaffolding", primary_prompt="Write initial models in models.py", status=StepStatus.RUNNING),
            RouteStep(index=1, title="Step 2: Verification", primary_prompt="Run pytest tests/", status=StepStatus.PENDING),
            RouteStep(index=2, title="Step 3: Review", primary_prompt="Audit security", status=StepStatus.PENDING),
        ],
        current_step_idx=0,
        state=StepStatus.RUNNING,
    )


@pytest.fixture
def watcher() -> ToolUsageWatcher:
    config = WatchdogConfig(
        inactivity_timeout_seconds=45.0,
        heartbeat_lease_seconds=60.0,
        max_nudges_per_step=2,
        enabled=True,
    )
    return ToolUsageWatcher(config)


class TestToolUsageWatcherBasics:
    def test_normal_activity_remains_noop(self, watcher: ToolUsageWatcher, manifest: RouteManifest):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Write models", now=1000.0)

        # Active within threshold (20s elapsed < 45s threshold)
        decision = watcher.check_watchdog(manifest, now=1020.0)
        assert decision.action == WatchdogAction.NOOP
        assert decision.elapsed_inactivity == 20.0

        # Tool call resets clock
        assert watcher.record_tool_call("write_to_file", {"path": "models.py"}, epoch=1, now=1025.0) is True

        # Now 15s after tool call (1040.0 - 1025.0 = 15.0s) -> NOOP
        decision = watcher.check_watchdog(manifest, now=1040.0)
        assert decision.action == WatchdogAction.NOOP
        assert decision.elapsed_inactivity == 15.0


class TestEpochBasedConcurrency:
    def test_stale_epoch_tool_calls_rejected(self, watcher: ToolUsageWatcher):
        watcher.start_epoch(epoch=2, step_index=1, total_steps=3, step_prompt="Run tests", now=2000.0)

        # Tool call with old epoch 1 is rejected
        assert watcher.record_tool_call("run_command", {}, epoch=1, now=2010.0) is False
        assert watcher.last_tool_timestamp == 2000.0

        # Tool call with current epoch 2 succeeds
        assert watcher.record_tool_call("run_command", {}, epoch=2, now=2010.0) is True
        assert watcher.last_tool_timestamp == 2010.0

    def test_stale_epoch_heartbeats_rejected(self, watcher: ToolUsageWatcher):
        watcher.start_epoch(epoch=3, step_index=2, total_steps=3, step_prompt="Audit", now=3000.0)
        assert watcher.record_heartbeat("subagent", epoch=2, now=3010.0) is False
        assert watcher.record_heartbeat("subagent", epoch=3, now=3010.0) is True


class TestInactivityNudgeEmission:
    def test_nudge_emitted_when_timeout_exceeded_with_remaining_steps(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Write models in models.py", now=100.0)

        # Exceed 45s timeout (50s elapsed)
        decision = watcher.check_watchdog(manifest, now=150.0)
        assert decision.action == WatchdogAction.NUDGE
        assert decision.elapsed_inactivity == 50.0
        assert decision.remaining_steps == 2
        assert decision.nudge_prompt is not None
        assert "WATCHDOG LIVENESS NUDGE 1/2" in decision.nudge_prompt
        assert "50 seconds" in decision.nudge_prompt
        assert "Write models in models.py" in decision.nudge_prompt

    def test_second_nudge_emitted_on_continued_inactivity(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Write models", now=100.0)

        # Nudge 1 at 150.0 (50s elapsed)
        d1 = watcher.check_watchdog(manifest, now=150.0)
        assert d1.action == WatchdogAction.NUDGE
        assert "1/2" in d1.nudge_prompt

        # Nudge 2 at 196.0 (96s elapsed)
        d2 = watcher.check_watchdog(manifest, now=196.0)
        assert d2.action == WatchdogAction.NUDGE
        assert "2/2" in d2.nudge_prompt


class TestBoundedStallHalt:
    def test_trips_stall_halt_after_max_nudges_exhausted(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Write models", now=100.0)

        # Nudge 1
        watcher.check_watchdog(manifest, now=150.0)
        # Nudge 2
        watcher.check_watchdog(manifest, now=200.0)

        # 3rd check: max nudges (2) exhausted -> Safe Fail-Closed Halt
        decision = watcher.check_watchdog(manifest, now=250.0)
        assert decision.action == WatchdogAction.TRIP_STALL_HALT
        assert watcher.is_halted is True
        assert manifest.state == StepStatus.PAUSED
        assert "watchdog_stall_halt" in manifest.metadata
        assert manifest.metadata["watchdog_stall_halt"]["nudges_sent"] == 2

        # Subsequent check remains halted
        d_post = watcher.check_watchdog(manifest, now=300.0)
        assert d_post.action == WatchdogAction.NOOP
        assert "already tripped stall halt" in d_post.explanation


class TestLeaseRenewalDeadMansSwitch:
    def test_active_background_heartbeat_suppresses_tool_inactivity_nudge(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Compiling code", now=500.0)

        # 50s of tool inactivity (exceeds 45s threshold)
        # BUT background compiler emitted a heartbeat at 540.0 (only 10s ago < 60s lease)
        watcher.record_heartbeat(source="compiler_stdout", epoch=1, now=540.0)

        decision = watcher.check_watchdog(manifest, now=550.0)
        assert decision.action == WatchdogAction.NOOP
        assert "suppressed by active background heartbeat lease" in decision.explanation

    def test_expired_heartbeat_lease_restores_nudge(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        watcher.start_epoch(epoch=1, step_index=0, total_steps=3, step_prompt="Compiling code", now=500.0)
        watcher.record_heartbeat(source="compiler_stdout", epoch=1, now=510.0)

        # At 575.0: tool inactivity is 75s (>= 45s) and heartbeat is 65s ago (>= 60s lease)
        # Both tool and lease expired -> NUDGE fires!
        decision = watcher.check_watchdog(manifest, now=575.0)
        assert decision.action == WatchdogAction.NUDGE


class TestTerminalAndRouteCompletion:
    def test_no_nudges_when_all_prompts_complete(
        self,
        watcher: ToolUsageWatcher,
        manifest: RouteManifest,
    ):
        # Set manifest to completed
        manifest.state = StepStatus.COMPLETED
        for s in manifest.steps:
            s.status = StepStatus.COMPLETED

        watcher.start_epoch(epoch=3, step_index=2, total_steps=3, step_prompt="Final review", now=100.0)
        decision = watcher.check_watchdog(manifest, now=200.0)
        assert decision.action == WatchdogAction.NOOP
        assert decision.remaining_steps == 0
