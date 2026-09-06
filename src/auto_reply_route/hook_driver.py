from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
from typing import Any, Optional, Union
import uuid

from auto_reply_route.models import (
    MessageQueueManifest,
    QueuedMessage,
    QueuedMessageStatus,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.state_machine import RouteStateMachine


def _validate_conversation_id(conv_id: str) -> str:
    """Validate conversation ID against path traversal vectors."""
    if not conv_id or not isinstance(conv_id, str):
        raise ValueError("Invalid conversation ID: must be non-empty string")
    clean = conv_id.strip()
    if ".." in clean or "/" in clean or "\\" in clean or "\0" in clean:
        raise ValueError(f"Directory traversal detected in conversation_id: {conv_id!r}")
    if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
        raise ValueError(f"Invalid characters in conversation_id: {conv_id!r}")
    return clean


def _sync_dir(dir_path: Path) -> None:
    """Best-effort POSIX directory sync to guarantee directory entry durability."""
    try:
        dir_fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, PermissionError):
        pass

DeterministicGateSieve = None  # type: ignore


class GateResult:
    """Gate result returned by assertion checks."""

    def __init__(self, passed: bool, message: str, details: Optional[dict[str, Any]] = None) -> None:
        self.passed = passed
        self.message = message
        self.details = details or {}

    def __bool__(self) -> bool:
        return self.passed


FallbackGateResult = GateResult


class AutoHealDecision:
    """Auto-heal decision produced by auto-heal controller."""

    def __init__(
        self,
        attempt: int,
        should_retry: bool,
        status: str,
        reason: str,
        error_count: int,
    ) -> None:
        self.attempt = attempt
        self.should_retry = should_retry
        self.status = status
        self.reason = reason
        self.error_count = error_count

    def __bool__(self) -> bool:
        return self.should_retry


FallbackAutoHealDecision = AutoHealDecision


class QuarantineAutoHealController:
    """Built-in 2-shot auto heal controller with divergence detection."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries
        self.attempt = 0
        self.previous_error_count: Optional[int] = None

    def record_failure(self, error_log: str, error_count: int = 1) -> AutoHealDecision:
        self.attempt += 1
        if self.attempt == 1:
            self.previous_error_count = error_count
            return AutoHealDecision(
                attempt=1,
                should_retry=True,
                status="RETRY",
                reason=f"Attempt 1 failed with {error_count} error(s).",
                error_count=error_count,
            )
        elif self.attempt == 2:
            prev = self.previous_error_count if self.previous_error_count is not None else error_count
            if error_count >= prev:
                return AutoHealDecision(
                    attempt=2,
                    should_retry=False,
                    status="DIVERGENCE_HALT",
                    reason=f"Divergence breaker triggered: errors {error_count} >= previous {prev}",
                    error_count=error_count,
                )
            self.previous_error_count = error_count
            return AutoHealDecision(
                attempt=2,
                should_retry=True,
                status="RETRY",
                reason="Attempt 2 improved, final retry allowed.",
                error_count=error_count,
            )
        else:
            return AutoHealDecision(
                attempt=self.attempt,
                should_retry=False,
                status="EXHAUSTED_HALT",
                reason=f"Exhausted max retry budget ({self.attempt} > {self.max_retries}).",
                error_count=error_count,
            )

    def record_success(self) -> None:
        pass


AutoHealController = QuarantineAutoHealController
FallbackAutoHealController = QuarantineAutoHealController


class AntigravityHookDriver:
    """Native Antigravity Stop hook driver and reactive workflow orchestrator.

    Executes synchronously within Antigravity's `.agents/hooks.json` Stop hook event,
    evaluating turn completion, human preemption, deterministic step gates, fast-path
    in-band prompt injection, and bounded quarantine auto-healing.
    """

    def __init__(
        self,
        gate_sieve: Optional[Any] = None,
        heal_controller: Optional[Any] = None,
        base_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd()
        if gate_sieve is not None:
            self.gate_sieve = gate_sieve
        elif DeterministicGateSieve is not None:
            self.gate_sieve = DeterministicGateSieve()
        else:
            self.gate_sieve = None

        self._injected_heal_controller = heal_controller
        self._step_heal_controllers: dict[int, Any] = {}

    def _get_auto_heal_controller(self, step_idx: int) -> Any:
        """Retrieve or initialize the bounded auto-heal controller for a step."""
        if self._injected_heal_controller is not None:
            return self._injected_heal_controller
        if step_idx not in self._step_heal_controllers:
            if QuarantineAutoHealController is not None:
                self._step_heal_controllers[step_idx] = QuarantineAutoHealController()
            else:
                self._step_heal_controllers[step_idx] = FallbackAutoHealController()
        return self._step_heal_controllers[step_idx]

    AUTOMATED_SOURCES = {
        "HOOK",
        "AUTO_REPLY",
        "AUTO_HEAL",
        "SYSTEM",
        "SYSTEM_SDK",
        "SYSTEM_AUTO_REPLY",
        "AGENT",
        "BOT",
    }
    AUTOMATED_SENDERS = {"hook", "auto_reply", "system", "bot", "agent"}

    @classmethod
    def _is_human_turn_step(cls, step: dict[str, Any]) -> bool:
        """Determines if a transcript step originated from a human user across all envelope schemas."""
        source = str(step.get("source", "")).strip().upper()
        step_type = str(step.get("type", "")).strip().upper()
        role = str(step.get("role", "")).strip().lower()
        sender = str(step.get("sender", "")).strip().lower()

        # If marked with automated source/sender or system role, it is not human
        if source in cls.AUTOMATED_SOURCES or sender in cls.AUTOMATED_SENDERS or role == "system":
            return False

        # Positive human indicators across envelope schemas:
        if source in ("USER_EXPLICIT", "USER", "HUMAN", "CLIENT"):
            return True
        if step_type in ("USER_INPUT", "USER"):
            return True
        if role == "user" or sender == "user":
            return True

        return False

    def _load_transcript_steps(self, transcript_path: Optional[str]) -> list[dict[str, Any]]:
        """Safely parse JSON Lines transcript file into memory with APFS concurrency resilience
        and directory traversal protections.
        """
        if not transcript_path:
            return []

        p_str = str(transcript_path).strip()
        if "\0" in p_str:
            return []

        path = Path(p_str).resolve()
        forbidden_roots = ("/etc", "/var", "/private/etc", "/dev", "/proc", "/sys")
        if any(str(path).startswith(fb) for fb in forbidden_roots):
            return []

        if not path.is_file():
            return []

        steps: list[dict[str, Any]] = []
        truncated_eof = False
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                clean = line.strip().replace("\x00", "")
                if not clean:
                    continue
                try:
                    steps.append(json.loads(clean))
                except json.JSONDecodeError:
                    if idx == len(lines) - 1:
                        truncated_eof = True
        except Exception:
            return []

        if truncated_eof:
            # Active write in-flight at EOF on APFS: mark turn as IN_PROGRESS to prevent premature advancement
            steps.append({
                "step_index": len(steps) + 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "IN_PROGRESS",
                "tool_calls": [],
                "_truncated_eof": True,
            })

        return steps

    def has_pending_tool_calls(self, transcript_steps: list[dict[str, Any]]) -> bool:
        """Validates that the transcript's last turn has no pending or unhandled tool calls."""
        if not transcript_steps:
            return False

        # If any step is actively running, waiting, or has an in-flight write at EOF
        for s in transcript_steps:
            status = str(s.get("status", "")).upper()
            if status in ("RUNNING", "WAITING", "IN_PROGRESS"):
                return True

        # Check latest model response in transcript
        for step in reversed(transcript_steps):
            step_type = str(step.get("type", "")).upper()
            source = str(step.get("source", "")).upper()
            if step_type == "PLANNER_RESPONSE" or source == "MODEL":
                tool_calls = step.get("tool_calls") or []
                if isinstance(tool_calls, list) and len(tool_calls) > 0:
                    return True
                return False

        return False

    def is_human_preemption(self, transcript_steps: list[dict[str, Any]]) -> bool:
        """Check if the latest user turn was explicitly typed by a human across all message envelope schemas."""
        if not transcript_steps:
            return False

        # If the very last step is explicit user input
        if self._is_human_turn_step(transcript_steps[-1]):
            return True

        # Search backward for the most recent user turn trigger
        for step in reversed(transcript_steps):
            source = str(step.get("source", "")).strip().upper()
            step_type = str(step.get("type", "")).strip().upper()
            role = str(step.get("role", "")).strip().lower()
            sender = str(step.get("sender", "")).strip().lower()

            is_turn_trigger = (
                source in (
                    "USER_EXPLICIT",
                    "USER",
                    "HUMAN",
                    "CLIENT",
                    "SYSTEM",
                    "HOOK",
                    "AUTO_REPLY",
                    "SYSTEM_SDK",
                    "AUTO_HEAL",
                )
                or step_type in ("USER_INPUT", "USER")
                or role in ("user", "system")
                or sender in ("user", "hook", "system")
            )

            if is_turn_trigger:
                return self._is_human_turn_step(step)

        return False

    def _find_route_file(
        self, conversation_id: str, active_route_file: Optional[str]
    ) -> Optional[Path]:
        """Locate the route state checkpoint file on disk with directory traversal validation."""
        if active_route_file:
            rf_str = str(active_route_file).strip()
            if "\0" not in rf_str:
                rf = Path(rf_str).resolve()
                forbidden_roots = ("/etc", "/var", "/private/etc", "/dev", "/proc", "/sys")
                if not any(str(rf).startswith(fb) for fb in forbidden_roots):
                    if rf.is_file():
                        return rf

        try:
            safe_conv_id = _validate_conversation_id(conversation_id)
        except ValueError:
            safe_conv_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(conversation_id))

        candidates = [
            self.base_dir / f".route_state_{safe_conv_id}.json",
            Path.cwd() / f".route_state_{safe_conv_id}.json",
            self.base_dir / ".route_state.json",
            Path.cwd() / ".route_state.json",
            self.base_dir / ".agy-route-state.json",
            Path.cwd() / ".agy-route-state.json",
        ]

        for cand in candidates:
            if cand.is_file():
                return cand.resolve()
        return None

    def _find_queue_file(
        self, conversation_id: str, active_queue_file: Optional[str] = None
    ) -> Optional[Path]:
        """Locate the queued messages file on disk with directory traversal validation."""
        if active_queue_file:
            qf_str = str(active_queue_file).strip()
            if "\0" not in qf_str:
                qf = Path(qf_str).resolve()
                forbidden_roots = ("/etc", "/var", "/private/etc", "/dev", "/proc", "/sys")
                if not any(str(qf).startswith(fb) for fb in forbidden_roots):
                    if qf.is_file():
                        return qf

        try:
            safe_conv_id = _validate_conversation_id(conversation_id)
        except ValueError:
            safe_conv_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(conversation_id))

        candidates = [
            self.base_dir / f".queued_messages_{safe_conv_id}.json",
            Path.cwd() / f".queued_messages_{safe_conv_id}.json",
            self.base_dir / ".queued_messages.json",
            Path.cwd() / ".queued_messages.json",
        ]

        for cand in candidates:
            if cand.is_file():
                return cand.resolve()
        return None

    def evaluate_step_gates(
        self, step: RouteStep, repo_path: Optional[Union[str, Path]] = None
    ) -> tuple[bool, str, int]:
        """Evaluate deterministic gates for a route step via DeterministicGateSieve.

        Returns (passed, error_summary, error_count).
        """
        cwd_path = str(repo_path) if repo_path else str(self.base_dir)

        # Allow injected or custom evaluate_step method
        if self.gate_sieve is not None and hasattr(self.gate_sieve, "evaluate_step"):
            res = self.gate_sieve.evaluate_step(step, cwd_path)
            if hasattr(res, "passed"):
                return bool(res.passed), str(getattr(res, "message", "")), 0 if res.passed else 1
            if isinstance(res, tuple):
                return res[0], res[1], 0 if res[0] else 1
            if isinstance(res, bool):
                return res, "" if res else "Step gate evaluation failed", 0 if res else 1

        if not step.assertions:
            # No assertions required for this step
            return True, "", 0

        # Evaluate each assertion against the sieve
        for assertion in step.assertions:
            assertion_clean = assertion.strip()
            if not assertion_clean:
                continue

            # Strip natural language assertion suffixes if present (e.g. 'passes', 'is clean')
            exec_cmd = assertion_clean
            for suffix in (" passes", " succeeds", " is clean", " is 0"):
                if exec_cmd.lower().endswith(suffix):
                    exec_cmd = exec_cmd[:-len(suffix)].strip()
                    break

            if self.gate_sieve is None:
                # Fallback subprocess execution if no sieve configured
                clean_cmd = exec_cmd.strip()
                try:
                    tokens = shlex.split(clean_cmd)
                except Exception as exc:
                    return False, f"Assertion command could not be safely tokenized: {exc}", 1

                if not tokens:
                    return False, f"Invalid empty assertion command: {exec_cmd}", 1

                try:
                    run_res = subprocess.run(
                        tokens,
                        shell=False,
                        cwd=cwd_path,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                except subprocess.TimeoutExpired:
                    return False, f"Assertion execution timed out after 60s: {exec_cmd}", 1
                except Exception as e:
                    return False, f"Assertion execution failed: {e}", 1

                if run_res.returncode != 0:
                    err = run_res.stderr.strip() or run_res.stdout.strip()
                    summary = f"Assertion failed with exit code {run_res.returncode}: {exec_cmd}"
                    if err:
                        summary += f" ({err[:200]})"
                    return False, summary, 1
                continue

            # Route assertion to appropriate sieve layer
            lower_assert = exec_cmd.lower()
            if "pytest" in lower_assert or "unittest" in lower_assert:
                res = self.gate_sieve.check_test_suite(exec_cmd, cwd=cwd_path)
            elif lower_assert.startswith("syntax:") or lower_assert.startswith("ast:"):
                try:
                    files = shlex.split(exec_cmd.split(":", 1)[1].strip())
                except Exception:
                    files = exec_cmd.split(":", 1)[1].strip().split()
                res = self.gate_sieve.check_syntax(files)
            elif "blast_radius" in lower_assert or "blast-radius" in lower_assert:
                res = self.gate_sieve.check_blast_radius(cwd_path)
            elif lower_assert.startswith("smoke:") or lower_assert.startswith("smoke_test:"):
                cmd = exec_cmd.split(":", 1)[1].strip()
                res = self.gate_sieve.check_runtime_smoke(cmd, cwd=cwd_path)
            else:
                res = self.gate_sieve.check_types_or_compilation(exec_cmd, cwd=cwd_path)

            if not res.passed:
                err_summary = res.message
                if hasattr(res, "details") and isinstance(res.details, dict):
                    extra = res.details.get("stderr") or res.details.get("error") or ""
                    if extra and str(extra).strip() not in err_summary:
                        err_summary = f"{err_summary} ({str(extra).strip()[:150]})"
                return False, err_summary, 1

        return True, "", 0

    def _write_living_room_explanation(
        self,
        conversation_id: str,
        step: RouteStep,
        attempt: int,
        reason: str,
        status: str,
        route_file: Optional[Path],
    ) -> str:
        """Constructs and writes a clear, plain-language Living-Room explanation.

        Follows the Anti-Overexplaining Law: Zero plumbing talk, zero system mechanics,
        and plain everyday language that passes the neighbor coffee test.
        """
        step_num = step.index + 1
        step_title = step.title or f"Step {step_num}"

        if status == "DIVERGENCE_HALT":
            explanation = (
                f"We paused on Step {step_num} ({step_title}) because the issue wasn't clearing up "
                f"and seemed to be spreading. Everything has been safely saved right where you left it "
                f"so you can take a look, make any adjustments you'd like, and continue whenever you're ready."
            )
        else:
            explanation = (
                f"We paused on Step {step_num} ({step_title}) because the automatic checks didn't pass "
                f"after {attempt} tries. Everything is safely saved right here for your review "
                f"whenever you'd like to continue."
            )

        safe_conv_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(conversation_id))
        target_dir = route_file.parent if route_file else self.base_dir
        exp_file = target_dir / f".route_explanation_{safe_conv_id}.txt"
        temp_exp = target_dir / f".route_explanation_{safe_conv_id}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(temp_exp, "w", encoding="utf-8") as f:
                f.write(explanation + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_exp, exp_file)
            _sync_dir(target_dir)
        except Exception:
            pass

        return explanation

    def handle_stop_hook(self, hook_input: dict[str, Any]) -> dict[str, Any]:
        """Core Stop hook handler executing inside Antigravity's Stop event lifecycle.

        Input:
            {"conversationId": str, "transcriptPath": str, "terminationReason": str,
             "fullyIdle": bool, "activeRouteFile": Optional[str]}

        Output:
            {"decision": "continue", "reason": "<Prompt>"} OR {"decision": "allow"}
        """
        conv_id = str(hook_input.get("conversationId") or hook_input.get("conversation_id", "default"))
        transcript_path = hook_input.get("transcriptPath") or hook_input.get("transcript_path")
        term_reason = hook_input.get("terminationReason") or hook_input.get("termination_reason", "")
        fully_idle = hook_input.get("fullyIdle")
        if fully_idle is None:
            fully_idle = hook_input.get("fully_idle", False)
        active_route_file = hook_input.get("activeRouteFile") or hook_input.get("active_route_file")

        # 1. Disambiguate true turn completion
        if term_reason != "model_stop" or not fully_idle:
            return {"decision": "allow"}

        transcript_steps = self._load_transcript_steps(transcript_path)
        if self.has_pending_tool_calls(transcript_steps):
            return {"decision": "allow"}

        # 2A. Check for active Queued Messages manifest (First priority)
        active_queue_file = hook_input.get("activeQueueFile") or hook_input.get("active_queue_file")
        queue_path = self._find_queue_file(conv_id, active_queue_file)

        # Auto-inception of queue if enabled or requested
        if (not queue_path or not queue_path.is_file()) and hook_input.get("auto_queue"):
            seed_prompt = hook_input.get("seedPrompt") or hook_input.get("prompt", "")
            if seed_prompt:
                try:
                    from auto_reply_route.builder import generate_followup_queue
                    auto_q = generate_followup_queue(
                        seed_prompt,
                        count=int(hook_input.get("count", 1)),
                        conversation_id=conv_id,
                    )
                    safe_conv = re.sub(r"[^a-zA-Z0-9_\-]", "_", conv_id)
                    q_dest = self.base_dir / f".queued_messages_{safe_conv}.json"
                    auto_q.save_to_file(q_dest)
                    queue_path = q_dest
                except Exception:
                    pass

        if queue_path and queue_path.is_file():
            queue = MessageQueueManifest.load_from_file(queue_path)
            if queue and not queue.is_completed and not queue.is_paused and not queue.is_empty:
                # Check for human preemption:
                # If the queue was just resumed by user, acknowledge and clear flag
                just_resumed = bool(queue.metadata.pop("resumed", False))
                if just_resumed:
                    queue.save_to_file(queue_path)

                if not just_resumed:
                    # Preemption applies if the queue is in-flight and user interrupted
                    is_unhandled_human_turn = self._is_human_turn_step(transcript_steps[-1]) if transcript_steps else False
                    is_in_flight_preemption = queue.active_index > 0 and self.is_human_preemption(transcript_steps)
                    if is_unhandled_human_turn or is_in_flight_preemption:
                        queue.pause(reason="Human preemption: user entered message")
                        queue.save_to_file(queue_path)
                        return {"decision": "allow"}

                next_msg = queue.peek_next_message()
                if next_msg is not None:
                    # Domain-elastic gating:
                    assertions = next_msg.metadata.get("assertions", [])
                    gate_passed = True
                    err_summary = ""
                    if assertions:
                        dummy_step = RouteStep(
                            index=next_msg.index,
                            title=f"Queued Step {next_msg.index + 1}",
                            primary_prompt=next_msg.prompt,
                            assertions=assertions,
                        )
                        gate_passed, err_summary, _ = self.evaluate_step_gates(
                            dummy_step, repo_path=queue_path.parent
                        )

                    if gate_passed:
                        popped = queue.pop_next_message()
                        queue.save_to_file(queue_path)
                        if popped:
                            return {
                                "decision": "continue",
                                "reason": popped.prompt,
                            }
                    else:
                        return {
                            "decision": "continue",
                            "reason": f"[GATE CHECK FAILED: {err_summary}] Fix this before proceeding to next queued message.",
                        }
                return {"decision": "allow"}

        # 2B. Fall back to standard RouteManifest state machine
        route_path = self._find_route_file(conv_id, active_route_file)
        if not route_path or not route_path.is_file():
            return {"decision": "allow"}

        try:
            state_machine = RouteStateMachine.load_checkpoint(str(route_path))
        except Exception:
            return {"decision": "allow"}

        # If route is already completed, paused, or failed, yield
        if (
            state_machine.is_completed
            or state_machine.is_failed
            or state_machine.manifest.state in (StepStatus.PAUSED, StepStatus.PAUSED_BY_USER)
        ):
            return {"decision": "allow"}

        # 3. Check for human preemption
        if self.is_human_preemption(transcript_steps):
            state_machine.manifest.state = StepStatus.PAUSED_BY_USER
            current = state_machine.get_current_step()
            if current is not None:
                current.status = StepStatus.PAUSED_BY_USER
            state_machine.manifest.metadata["pause_reason"] = "Human preemption: user entered message"
            state_machine.save_checkpoint(str(route_path))
            return {"decision": "allow"}

        current_step = state_machine.get_current_step()
        if current_step is None:
            return {"decision": "allow"}

        # 4. Run step gates via DeterministicGateSieve
        gate_passed, error_summary, error_count = self.evaluate_step_gates(
            current_step, repo_path=route_path.parent
        )

        # 5. Fast-Path (< 10s validation)
        if gate_passed:
            # Advance to next step
            next_step = state_machine.advance_step()

            if next_step is not None:
                state_machine.save_checkpoint(str(route_path))
                return {
                    "decision": "continue",
                    "reason": next_step.primary_prompt,
                }
            else:
                # Route completed
                milestone_card = (
                    f"## 🏁 Milestone Manifest: Route Completed\n\n"
                    f"- **Route ID:** `{state_machine.manifest.route_id}`\n"
                    f"- **Title:** {state_machine.manifest.title}\n"
                    f"- **Total Steps Completed:** {len(state_machine.manifest.steps)}\n"
                    f"- **Status:** COMPLETED\n\n"
                    f"### Summary of Executed Steps:\n"
                )
                for s in state_machine.manifest.steps:
                    milestone_card += f"- **Step {s.index + 1}:** {s.title} (Status: {s.status.value})\n"

                state_machine.manifest.metadata["milestone_summary"] = milestone_card
                safe_conv_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(conv_id))
                milestone_file = route_path.parent / f".route_milestone_{safe_conv_id}.md"
                temp_ms = route_path.parent / f".route_milestone_{safe_conv_id}.{os.getpid()}.{threading.get_ident()}.tmp"
                try:
                    with open(temp_ms, "w", encoding="utf-8") as f:
                        f.write(milestone_card + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp_ms, milestone_file)
                    _sync_dir(route_path.parent)
                except Exception:
                    pass

                state_machine.save_checkpoint(str(route_path))
                return {"decision": "allow"}

        # 6. Auto-Heal / Failure Path
        controller = self._get_auto_heal_controller(current_step.index)
        heal_decision = controller.record_failure(error_summary, error_count=max(1, error_count))

        if heal_decision.should_retry and current_step.retries < current_step.max_retries:
            state_machine.record_retry(reason=f"Gate check failed: {error_summary}")
            state_machine.save_checkpoint(str(route_path))
            retry_prompt = (
                f"[AUTO-HEAL ATTEMPT {heal_decision.attempt}] Gate check failed: "
                f"{error_summary}. Fix this issue."
            )
            return {
                "decision": "continue",
                "reason": retry_prompt,
            }
        else:
            # Breaker tripped or max retries exceeded
            state_machine.pause(reason=f"Circuit breaker tripped: {heal_decision.reason}")
            state_machine.manifest.metadata["breaker_status"] = heal_decision.status
            living_room = self._write_living_room_explanation(
                conversation_id=conv_id,
                step=current_step,
                attempt=heal_decision.attempt,
                reason=heal_decision.reason,
                status=heal_decision.status,
                route_file=route_path,
            )
            state_machine.manifest.metadata["living_room_explanation"] = living_room
            state_machine.save_checkpoint(str(route_path))
            return {"decision": "allow"}


class QueueDispatcher:
    """Helper implementing the slow-path dispatcher for Antigravity's User Message Queue.

    Dispatches prompts directly into `.system_generated/messages` when asynchronous
    long-running background tasks finish, waking Antigravity reactively.
    """

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        app_data_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd()
        env_app_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
        if app_data_dir:
            self.app_data_dir = Path(app_data_dir).resolve()
        elif env_app_dir:
            self.app_data_dir = Path(env_app_dir).resolve()
        else:
            self.app_data_dir = Path.home() / ".gemini" / "antigravity"

    def get_messages_dir(self, conversation_id: str) -> Path:
        """Return the target messages directory for a specific conversation with traversal protection."""
        safe_conv_id = _validate_conversation_id(conversation_id)
        target = (self.app_data_dir / "brain" / safe_conv_id / ".system_generated" / "messages").resolve()
        allowed_root = (self.app_data_dir / "brain").resolve()
        if not str(target).startswith(str(allowed_root)):
            raise ValueError(f"Path traversal detected: {conversation_id!r} escapes {allowed_root}")
        return target

    def queue_user_message(
        self,
        conversation_id: str,
        content: str,
        priority: str = "MESSAGE_PRIORITY_HIGH",
        sender: str = "user",
        delivery_strategy: str = "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE",
    ) -> dict[str, Any]:
        """Atomically enqueue a user-scoped message into Antigravity's queue."""
        safe_conv_id = _validate_conversation_id(conversation_id)
        messages_dir = self.get_messages_dir(safe_conv_id)
        undelivered_dir = messages_dir / "undelivered"

        messages_dir.mkdir(parents=True, exist_ok=True)
        undelivered_dir.mkdir(parents=True, exist_ok=True)

        msg_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        msg_payload = {
            "id": msg_id,
            "recipient": safe_conv_id,
            "sender": sender,
            "priority": priority,
            "timestamp": timestamp,
            "content": content,
            "deliveryStrategy": delivery_strategy,
        }

        target_file = messages_dir / f"{msg_id}.json"
        temp_file = messages_dir / f".{msg_id}.{os.getpid()}.{threading.get_ident()}.tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(msg_payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_file, target_file)
        _sync_dir(messages_dir)

        # Touch the undelivered indicator file for reactive file watchers
        indicator_file = undelivered_dir / msg_id
        temp_ind = undelivered_dir / f".{msg_id}.{os.getpid()}.tmp"
        with open(temp_ind, "w", encoding="utf-8") as f:
            f.write("")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_ind, indicator_file)
        _sync_dir(undelivered_dir)

        return msg_payload

    def dispatch_slow_path(
        self,
        conversation_id: str,
        next_step_prompt: str,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Dispatches next step prompt into the queue after a slow background task finishes."""
        wrapped_prompt = next_step_prompt
        if task_id:
            wrapped_prompt = f"[BACKGROUND TASK {task_id} COMPLETED]\n{next_step_prompt}"
        return self.queue_user_message(conversation_id, wrapped_prompt)

    def handle_task_completion(
        self,
        conversation_id: str,
        task_id: str,
        next_step_prompt: str,
        exit_code: int = 0,
        output: str = "",
    ) -> dict[str, Any]:
        """Handle background task completion event."""
        if exit_code == 0:
            return self.dispatch_slow_path(conversation_id, next_step_prompt, task_id=task_id)
        else:
            fail_prompt = (
                f"[BACKGROUND TASK {task_id} FAILED with code {exit_code}]\n"
                f"Output: {output[:300]}\n"
                f"Please inspect the error and rectify."
            )
            return self.queue_user_message(conversation_id, fail_prompt)


def handle_stop_hook(hook_input: dict[str, Any]) -> dict[str, Any]:
    """Module-level Stop hook convenience dispatcher."""
    driver = AntigravityHookDriver()
    return driver.handle_stop_hook(hook_input)


def main() -> int:
    """CLI entrypoint reading hook input from stdin and emitting decision JSON on stdout."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    driver = AntigravityHookDriver()
    res = driver.handle_stop_hook(payload)
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
