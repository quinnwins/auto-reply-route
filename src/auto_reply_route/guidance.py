"""Adaptive Guidance Engine (/g) and Prompt Lifecycle Controller.

Implements the /g Adaptive Guidance Law and enforces strict execution
ordering invariants between task execution and prompt dispatch:

1. Zero Upfront Staging (Tray Stays Clean): NEVER dispatch at start of turn.
2. Execute Task First: Run audits, subagents, prototypes, and tests.
3. End-of-Turn Evaluation: Inspect live tool logs, test errors, and findings.
4. End-of-Turn Dispatch: Prepend '/g (Step k/N)' and dispatch via queue_paster.
5. Bounded Termination Invariant: When budget N is reached or all tasks pass,
   output 'DONE: All tasks satisfied.' and inhibit queue dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import re
import time
from typing import Any, Callable, Optional, Union


class GuidanceMode(str, Enum):
    ADAPTIVE_GUIDANCE = "ADAPTIVE_GUIDANCE"  # /g: Zero upfront staging, dispatch at turn end
    FAST_QUEUE = "FAST_QUEUE"                # /q: Upfront staging at turn start


class TurnPhase(str, Enum):
    INITIALIZED = "INITIALIZED"
    TURN_START = "TURN_START"
    TASK_EXECUTION = "TASK_EXECUTION"
    EVALUATION = "EVALUATION"
    TURN_END = "TURN_END"
    COMPLETED = "COMPLETED"


@dataclass
class TurnEvent:
    timestamp: float
    phase: TurnPhase
    event_type: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuidanceStepState:
    current_step: int
    step_budget: int
    raw_prompt: str
    cleaned_prompt: str
    mode: GuidanceMode
    is_terminal: bool = False
    next_prompt: Optional[str] = None


class AdaptiveGuidanceController:
    """Controls the turn-by-turn execution lifecycle of /g and /q commands."""

    def __init__(
        self,
        default_budget: int = 5,
        dispatch_fn: Optional[Callable[[str], bool]] = None,
        conversation_id: Optional[str] = None,
        app_data_dir: Optional[Union[str, Path]] = None,
        environ: Optional[dict[str, str]] = None,
    ) -> None:
        self.default_budget = default_budget
        self.dispatch_fn = dispatch_fn
        self.conversation_id = conversation_id
        self.app_data_dir = app_data_dir
        self.environ = environ
        self.events: list[TurnEvent] = []
        self.current_phase = TurnPhase.INITIALIZED

    def _record_event(self, phase: TurnPhase, event_type: str, details: Optional[dict[str, Any]] = None) -> None:
        self.current_phase = phase
        self.events.append(
            TurnEvent(
                timestamp=time.time(),
                phase=phase,
                event_type=event_type,
                details=details or {},
            )
        )

    @classmethod
    def parse_command(cls, text: str, default_budget: int = 5) -> GuidanceStepState:
        """Parses /g or /q commands and extracts (step_k, budget_N, cleaned_prompt).
        
        Examples:
        - '/g (Step 2/6) wire the for-agencies preview form to db' -> step=2, budget=6
        - '/g (3/5) fix race condition' -> step=3, budget=5
        - '/g build stripe webhook 4 steps' -> step=1, budget=4
        - '/g' -> step=1, budget=5
        - '/q build auth 3 steps' -> mode=FAST_QUEUE, step=1, budget=3
        """
        clean = text.strip()
        is_q = bool(re.match(r"^/(?:q|queue\b|queue-prompts\b)", clean, re.IGNORECASE))
        mode = GuidanceMode.FAST_QUEUE if is_q else GuidanceMode.ADAPTIVE_GUIDANCE

        # Strip command prefix
        body = re.sub(r"^/(?:g|q|queue\b|queue-prompts\b)\s*", "", clean, flags=re.IGNORECASE).strip()
        if not body and not is_q:
            # Standalone /g
            return GuidanceStepState(
                current_step=1,
                step_budget=default_budget,
                raw_prompt=text,
                cleaned_prompt="evaluate latest turns and formulate next move",
                mode=mode,
            )

        # Check for explicit step tracker: (Step k/N) or (k/N)
        step_k = 1
        budget_n = default_budget

        m_tracker = re.match(r"^\((?:Step\s+)?(\d+)/(\d+)\)\s*", body, re.IGNORECASE)
        if m_tracker:
            step_k = int(m_tracker.group(1))
            budget_n = int(m_tracker.group(2))
            body = body[m_tracker.end():].strip()
        else:
            # Check for trailing step count
            m_trailing = re.search(r"[\s,\-\(]+(\d+)\s*(?:steps?|turns?|follow\s*ups?|followups?)\)?$", body, re.IGNORECASE)
            if m_trailing:
                budget_n = int(m_trailing.group(1))
                body = body[:m_trailing.start()].strip()

        return GuidanceStepState(
            current_step=step_k,
            step_budget=budget_n,
            raw_prompt=text,
            cleaned_prompt=body or clean,
            mode=mode,
        )

    def start_turn(self, command: str) -> tuple[GuidanceStepState, bool]:
        """Phase 1: Start of Turn.
        
        Enforces:
        - For /g: Zero Upfront Staging. Prompt dispatch is strictly disallowed (can_dispatch=False).
        - For /q: Upfront Staging. Prompt dispatch is allowed immediately (can_dispatch=True).
        """
        state = self.parse_command(command, default_budget=self.default_budget)
        self._record_event(
            TurnPhase.TURN_START,
            "TURN_INITIALIZED",
            {"command": command, "step": state.current_step, "budget": state.step_budget, "mode": state.mode.value},
        )

        if state.mode == GuidanceMode.ADAPTIVE_GUIDANCE:
            # Invariant 1: Zero Upfront Staging
            self._record_event(TurnPhase.TURN_START, "ZERO_UPFRONT_STAGING_ENFORCED")
            return state, False
        else:
            # Fast Queue Stages Upfront
            self._record_event(TurnPhase.TURN_START, "FAST_QUEUE_UPFRONT_STAGING_ALLOWED")
            return state, True

    def execute_task(
        self,
        task_fn: Callable[[], dict[str, Any]],
        state: GuidanceStepState,
    ) -> dict[str, Any]:
        """Phase 2: Task Execution during turn.
        
        Executes tools, tests, audits, or subagent tasks BEFORE any evaluation or dispatch.
        """
        self._record_event(
            TurnPhase.TASK_EXECUTION,
            "TASK_EXECUTION_STARTED",
            {"step": state.current_step, "task": state.cleaned_prompt},
        )

        result = task_fn()

        self._record_event(
            TurnPhase.TASK_EXECUTION,
            "TASK_EXECUTION_FINISHED",
            {"result_keys": list(result.keys()), "success": result.get("success", True)},
        )
        return result

    def evaluate_and_steer(
        self,
        state: GuidanceStepState,
        task_result: dict[str, Any],
        synthesizer_fn: Optional[Callable[[dict[str, Any], int, int], str]] = None,
    ) -> tuple[str, bool]:
        """Phase 3: End-of-Turn Evaluation.
        
        Evaluates real task results, tool logs, or test errors.
        Returns: (message, should_dispatch_followup)
        """
        self._record_event(
            TurnPhase.EVALUATION,
            "EVALUATION_STARTED",
            {"step": state.current_step, "budget": state.step_budget},
        )

        # Invariant: Bounded Termination Invariant
        all_satisfied = task_result.get("all_tasks_satisfied", False)
        budget_exhausted = state.current_step >= state.step_budget

        if all_satisfied or budget_exhausted:
            self._record_event(
                TurnPhase.EVALUATION,
                "TERMINATION_CONDITION_MET",
                {"all_satisfied": all_satisfied, "budget_exhausted": budget_exhausted},
            )
            state.is_terminal = True
            return "DONE: All tasks satisfied.", False

        # Formulate next prompt conditioned on actual test/task findings
        next_step_num = state.current_step + 1
        if synthesizer_fn:
            next_body = synthesizer_fn(task_result, next_step_num, state.step_budget)
        else:
            err = task_result.get("error")
            if err:
                next_body = f"fix {err} discovered in tests and verify clean pass"
            else:
                next_body = f"proceed to next phase of {state.cleaned_prompt}"

        # Prepend /g (Step k/N) prefix
        next_prompt = f"/g (Step {next_step_num}/{state.step_budget}) {next_body}"
        state.next_prompt = next_prompt

        self._record_event(
            TurnPhase.EVALUATION,
            "NEXT_PROMPT_SYNTHESIZED",
            {"next_prompt": next_prompt, "next_step": next_step_num},
        )
        return next_prompt, True

    def end_turn(
        self,
        state: GuidanceStepState,
        should_dispatch: bool,
    ) -> Optional[str]:
        """Phase 4: Conclusion of Turn.
        
        Dispatches the single follow-up prompt ONLY if should_dispatch is True.
        """
        self._record_event(TurnPhase.TURN_END, "TURN_ENDING", {"should_dispatch": should_dispatch})

        dispatched_prompt: Optional[str] = None
        if should_dispatch and state.next_prompt:
            dispatched_prompt = state.next_prompt
            target_conv = self.conversation_id
            if self.dispatch_fn:
                self.dispatch_fn(dispatched_prompt)
            else:
                from auto_reply_route.queue_paster import dispatch_prompt_to_conversation
                receipt = dispatch_prompt_to_conversation(
                    prompt=dispatched_prompt,
                    conversation_id=self.conversation_id,
                    app_data_dir=self.app_data_dir,
                    environ=self.environ,
                )
                target_conv = receipt.get("recipient", self.conversation_id)

            self._record_event(
                TurnPhase.TURN_END,
                "FOLLOW_UP_PROMPT_DISPATCHED",
                {
                    "prompt": dispatched_prompt,
                    "conversation_id": target_conv or "auto-detected",
                },
            )

        self._record_event(TurnPhase.COMPLETED, "TURN_COMPLETED")
        return dispatched_prompt
