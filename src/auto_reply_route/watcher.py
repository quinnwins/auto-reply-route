"""Tool Usage Watcher & Inactivity Watchdog.

Monitors tool execution activity across route steps. If no tool has been invoked
for a configurable duration and pending steps remain, issues bounded liveness nudges
with epoch-based optimistic concurrency control to prevent split-brain execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Optional

from auto_reply_route.models import RouteManifest, RouteStep, StepStatus


class WatchdogAction(str, Enum):
    """Action recommendation emitted by the Watchdog."""
    NOOP = "NOOP"
    NUDGE = "NUDGE"
    TRIP_STALL_HALT = "TRIP_STALL_HALT"


@dataclass
class WatchdogConfig:
    """Configuration parameters for the tool usage watchdog."""
    inactivity_timeout_seconds: float = 45.0
    heartbeat_lease_seconds: float = 60.0
    max_nudges_per_step: int = 2
    enabled: bool = True


@dataclass
class WatchdogDecision:
    """Decision output produced by the Watchdog evaluation."""
    action: WatchdogAction
    epoch: int
    elapsed_inactivity: float
    explanation: str
    nudge_prompt: Optional[str] = None
    step_index: Optional[int] = None
    remaining_steps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "epoch": self.epoch,
            "elapsed_inactivity": self.elapsed_inactivity,
            "explanation": self.explanation,
            "nudge_prompt": self.nudge_prompt,
            "step_index": self.step_index,
            "remaining_steps": self.remaining_steps,
        }


class ToolUsageWatcher:
    """Monitors agent tool usage and issues context-aware liveness nudges.

    Invariants:
    1. Epoch-Based Concurrency: Rejects stale nudges if generation epoch has advanced.
    2. Dead Man's Switch (Lease Renewal): Streaming tasks refresh their lease.
    3. Bounded Nudges: Caps nudges at max_nudges_per_step before tripping safe halt.
    4. Non-Destructive Fail-Closed: Halts without clobbering dirty working tree.
    """

    def __init__(self, config: Optional[WatchdogConfig] = None):
        self.config = config or WatchdogConfig()
        self.current_epoch: int = 0
        self.last_tool_timestamp: float = time.monotonic()
        self.last_heartbeat_timestamp: Optional[float] = None
        self.nudges_sent_for_epoch: int = 0
        self.is_halted: bool = False
        self.current_step_index: Optional[int] = None
        self.current_step_prompt: Optional[str] = None
        self.total_steps: int = 0

    def start_epoch(
        self,
        epoch: int,
        step_index: int,
        total_steps: int,
        step_prompt: str,
        now: Optional[float] = None,
    ) -> None:
        """Starts a new generation epoch for Step N, resetting inactivity clocks."""
        t = now if now is not None else time.monotonic()
        self.current_epoch = epoch
        self.current_step_index = step_index
        self.total_steps = total_steps
        self.current_step_prompt = step_prompt
        self.last_tool_timestamp = t
        self.last_heartbeat_timestamp = None
        self.nudges_sent_for_epoch = 0
        self.is_halted = False

    def record_tool_call(
        self,
        tool_name: str,
        args: Optional[dict[str, Any]] = None,
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Records that a tool was invoked. Resets the inactivity timer.

        Returns False if the call arrived for an expired epoch.
        """
        if epoch is not None and epoch != self.current_epoch:
            return False  # Ignore tool call from stale epoch

        t = now if now is not None else time.monotonic()
        self.last_tool_timestamp = t
        self.last_heartbeat_timestamp = t
        # Tool call confirms progress; reset nudges for this epoch
        self.nudges_sent_for_epoch = 0
        return True

    def record_heartbeat(
        self,
        source: str = "task_progress",
        epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Renews the active task lease (Dead Man's Switch)."""
        if epoch is not None and epoch != self.current_epoch:
            return False

        t = now if now is not None else time.monotonic()
        self.last_heartbeat_timestamp = t
        return True

    def check_watchdog(
        self,
        manifest: Optional[RouteManifest] = None,
        now: Optional[float] = None,
    ) -> WatchdogDecision:
        """Evaluates whether the route has stalled with pending steps."""
        if not self.config.enabled:
            return WatchdogDecision(
                action=WatchdogAction.NOOP,
                epoch=self.current_epoch,
                elapsed_inactivity=0.0,
                explanation="Watchdog is disabled.",
            )

        if self.is_halted:
            return WatchdogDecision(
                action=WatchdogAction.NOOP,
                epoch=self.current_epoch,
                elapsed_inactivity=0.0,
                explanation="Watchdog has already tripped stall halt.",
            )

        t = now if now is not None else time.monotonic()
        elapsed_tool_inactivity = t - self.last_tool_timestamp
        elapsed_heartbeat = (t - self.last_heartbeat_timestamp) if self.last_heartbeat_timestamp is not None else float("inf")

        # Calculate remaining steps
        remaining = 0
        if manifest is not None:
            if manifest.state in (StepStatus.COMPLETED, StepStatus.PAUSED, StepStatus.FAILED):
                return WatchdogDecision(
                    action=WatchdogAction.NOOP,
                    epoch=self.current_epoch,
                    elapsed_inactivity=elapsed_tool_inactivity,
                    explanation=f"Route is not actively running (state: {manifest.state.value}).",
                )
            remaining = sum(1 for s in manifest.steps if s.status == StepStatus.PENDING)
        elif self.current_step_index is not None and self.total_steps > 0:
            remaining = max(0, self.total_steps - (self.current_step_index + 1))

        if remaining <= 0 and (manifest is None or manifest.current_step_idx >= len(manifest.steps) - 1):
            # No subsequent prompts left to send
            return WatchdogDecision(
                action=WatchdogAction.NOOP,
                epoch=self.current_epoch,
                elapsed_inactivity=elapsed_tool_inactivity,
                explanation="No remaining prompts left in route.",
                remaining_steps=0,
            )

        # Check lease renewal: if background task is actively emitting heartbeats within lease window
        if elapsed_heartbeat < self.config.heartbeat_lease_seconds and elapsed_tool_inactivity >= self.config.inactivity_timeout_seconds:
            # Active lease suppresses stall nudge while async background work streams
            return WatchdogDecision(
                action=WatchdogAction.NOOP,
                epoch=self.current_epoch,
                elapsed_inactivity=elapsed_tool_inactivity,
                explanation=(
                    f"Tool inactivity ({elapsed_tool_inactivity:.1f}s) suppressed by active "
                    f"background heartbeat lease ({elapsed_heartbeat:.1f}s ago)."
                ),
                remaining_steps=remaining,
            )

        # Check if inactivity threshold has elapsed
        if elapsed_tool_inactivity >= self.config.inactivity_timeout_seconds:
            if self.nudges_sent_for_epoch < self.config.max_nudges_per_step:
                self.nudges_sent_for_epoch += 1
                prompt_snippet = (
                    self.current_step_prompt[:120] + "..."
                    if self.current_step_prompt and len(self.current_step_prompt) > 120
                    else (self.current_step_prompt or "Proceed with step execution")
                )

                nudge_text = (
                    f"[WATCHDOG LIVENESS NUDGE {self.nudges_sent_for_epoch}/{self.config.max_nudges_per_step}]\n"
                    f"No tool activity has been detected for {elapsed_tool_inactivity:.0f} seconds.\n"
                    f"There are still {remaining} step(s) remaining in this route.\n\n"
                    f"Please continue by calling the required tools to fulfill the active task:\n"
                    f"\"{prompt_snippet}\""
                )

                return WatchdogDecision(
                    action=WatchdogAction.NUDGE,
                    epoch=self.current_epoch,
                    elapsed_inactivity=elapsed_tool_inactivity,
                    explanation=(
                        f"Inactivity threshold ({self.config.inactivity_timeout_seconds}s) exceeded. "
                        f"Issuing liveness nudge {self.nudges_sent_for_epoch}/{self.config.max_nudges_per_step}."
                    ),
                    nudge_prompt=nudge_text,
                    step_index=self.current_step_index,
                    remaining_steps=remaining,
                )
            else:
                # Max nudges exceeded -> Safe Fail-Closed Halt
                self.is_halted = True
                if manifest is not None:
                    manifest.state = StepStatus.PAUSED
                    manifest.metadata["watchdog_stall_halt"] = {
                        "epoch": self.current_epoch,
                        "step_index": self.current_step_index,
                        "elapsed_inactivity": elapsed_tool_inactivity,
                        "nudges_sent": self.nudges_sent_for_epoch,
                    }

                return WatchdogDecision(
                    action=WatchdogAction.TRIP_STALL_HALT,
                    epoch=self.current_epoch,
                    elapsed_inactivity=elapsed_tool_inactivity,
                    explanation=(
                        f"Stall detected: no tool calls after {self.nudges_sent_for_epoch} nudges "
                        f"({elapsed_tool_inactivity:.0f}s elapsed). Route safely paused without "
                        f"modifying workspace."
                    ),
                    step_index=self.current_step_index,
                    remaining_steps=remaining,
                )

        return WatchdogDecision(
            action=WatchdogAction.NOOP,
            epoch=self.current_epoch,
            elapsed_inactivity=elapsed_tool_inactivity,
            explanation=f"Active within normal threshold ({elapsed_tool_inactivity:.1f}s / {self.config.inactivity_timeout_seconds}s).",
            remaining_steps=remaining,
        )
