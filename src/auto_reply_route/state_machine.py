from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any, Optional, Union
import uuid

from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)


def _sync_dir(dir_path: Path) -> None:
    """Best-effort POSIX directory sync to guarantee directory entry durability across crashes."""
    try:
        dir_fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, PermissionError):
        pass


class RouteStateMachine:
    """State machine governing execution, step advancement, retries, and branching of a RouteManifest."""

    def __init__(self, manifest: RouteManifest) -> None:
        if not isinstance(manifest, RouteManifest):
            raise TypeError(f"Expected RouteManifest instance, got {type(manifest).__name__}")
        self.manifest = manifest

    @property
    def is_running(self) -> bool:
        return self.manifest.state == StepStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.manifest.state in (StepStatus.PAUSED, StepStatus.PAUSED_BY_USER)

    @property
    def is_completed(self) -> bool:
        return self.manifest.state == StepStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.manifest.state == StepStatus.FAILED

    @property
    def total_steps(self) -> int:
        return len(self.manifest.steps)

    def get_current_step(self) -> Optional[RouteStep]:
        """Return the currently active RouteStep, or None if route is empty or past the end."""
        return self.get_step(self.manifest.current_step_idx)

    def get_step(self, step_idx: int) -> Optional[RouteStep]:
        """Return RouteStep at specific index, or None if out of range."""
        if 0 <= step_idx < len(self.manifest.steps):
            return self.manifest.steps[step_idx]
        return None

    def start(self) -> Optional[RouteStep]:
        """Move state to RUNNING at step 0 and mark step 0 as RUNNING."""
        self.manifest.current_step_idx = 0
        if not self.manifest.steps:
            self.manifest.state = StepStatus.COMPLETED
            return None

        self.manifest.state = StepStatus.RUNNING
        step_0 = self.manifest.steps[0]
        step_0.status = StepStatus.RUNNING
        return step_0

    def advance_step(self) -> Optional[RouteStep]:
        """Mark current step COMPLETED and advance to next step.
        If no more steps remain, mark RouteManifest as COMPLETED and return None.
        """
        current = self.get_current_step()
        if current is not None:
            current.status = StepStatus.COMPLETED

        self.manifest.current_step_idx += 1
        next_step = self.get_current_step()
        if next_step is not None:
            next_step.status = StepStatus.RUNNING
            self.manifest.state = StepStatus.RUNNING
            return next_step

        self.manifest.state = StepStatus.COMPLETED
        return None

    def swap_branch(self, step_idx: int, branch_rank: Union[int, BranchRank]) -> AlternativeBranch:
        """Swap primary prompt of a step with one of its alternative branches."""
        if not (0 <= step_idx < len(self.manifest.steps)):
            raise IndexError(
                f"Step index {step_idx} out of range (total steps: {len(self.manifest.steps)})"
            )

        step = self.manifest.steps[step_idx]
        target_rank = int(branch_rank)

        branch = next((b for b in step.alternatives if int(b.rank) == target_rank), None)
        if branch is None:
            available_ranks = [b.rank for b in step.alternatives]
            raise ValueError(
                f"Alternative branch with rank {branch_rank} not found in step {step_idx}. "
                f"Available ranks: {available_ranks}"
            )

        # Atomic swap of primary prompt with alternative prompt template
        old_primary = step.primary_prompt
        step.primary_prompt = branch.prompt_template
        branch.prompt_template = old_primary

        self.manifest.metadata.setdefault("branch_swaps", []).append({
            "step_idx": step_idx,
            "branch_rank": target_rank,
            "branch_label": branch.label,
        })
        return branch

    def record_retry(
        self,
        reason: str = "",
        transition_on_exhaust: StepStatus = StepStatus.PAUSED,
    ) -> bool:
        """Increment retry count for the active step.
        If retries > max_retries, transitions route to PAUSED (or FAILED) and step to FAILED.
        Returns True if retry is permitted, False if cap is exceeded.
        """
        current = self.get_current_step()
        if current is None:
            return False

        current.retries += 1

        if reason:
            self.manifest.metadata.setdefault("retry_log", []).append({
                "step_idx": self.manifest.current_step_idx,
                "retry_count": current.retries,
                "reason": reason,
            })

        if current.retries <= current.max_retries:
            current.status = StepStatus.QUARANTINE_RETRY
            return True
        else:
            current.status = StepStatus.FAILED
            self.manifest.state = transition_on_exhaust
            if reason:
                self.manifest.metadata["exhausted_reason"] = reason
            return False

    def pause_by_user(self, reason: str = "Human preemption") -> None:
        """Pause route execution due to direct user intervention."""
        self.manifest.state = StepStatus.PAUSED_BY_USER
        current = self.get_current_step()
        if current is not None:
            current.status = StepStatus.PAUSED_BY_USER
        if reason:
            self.manifest.metadata["pause_reason"] = reason

    def pause(self, reason: str = "") -> None:
        """Pause route execution and the current step."""
        self.manifest.state = StepStatus.PAUSED
        current = self.get_current_step()
        if current is not None:
            current.status = StepStatus.PAUSED
        if reason:
            self.manifest.metadata["pause_reason"] = reason

    def resume(self) -> None:
        """Resume execution of a paused route."""
        self.manifest.state = StepStatus.RUNNING
        current = self.get_current_step()
        if current is not None:
            current.status = StepStatus.RUNNING

    def abort(self, reason: str = "") -> None:
        """Abort execution of the route, marking manifest and current step as FAILED."""
        self.manifest.state = StepStatus.FAILED
        current = self.get_current_step()
        if current is not None:
            current.status = StepStatus.FAILED
        if reason:
            self.manifest.metadata["abort_reason"] = reason

    def save_checkpoint(self, filepath: str) -> None:
        """Atomically persist RouteManifest state to disk as JSON with PID/thread-safe tempfile and POSIX sync."""
        if "\0" in str(filepath):
            raise ValueError("NUL byte in filepath")
        target_path = Path(filepath).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = target_path.with_name(
            f".{target_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.manifest.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
            _sync_dir(target_path.parent)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    @classmethod
    def load_checkpoint(cls, filepath: str) -> RouteStateMachine:
        """Atomically load RouteManifest state from disk JSON and return restored state machine."""
        if "\0" in str(filepath):
            raise ValueError("NUL byte in filepath")
        target_path = Path(filepath).resolve()
        if not target_path.is_file():
            raise FileNotFoundError(f"Checkpoint file not found: {filepath}")

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupted checkpoint JSON in {filepath}: {e}") from e

        manifest = RouteManifest.from_dict(data)
        return cls(manifest)
