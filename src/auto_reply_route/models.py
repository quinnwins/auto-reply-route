from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
import json
import os
from pathlib import Path
from typing import Any, Optional, Union
import uuid


class StepStatus(str, Enum):
    """Execution status for route steps and overall route manifest."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    GATING = "GATING"
    QUARANTINE_RETRY = "QUARANTINE_RETRY"
    PAUSED = "PAUSED"
    PAUSED_BY_USER = "PAUSED_BY_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BranchRank(IntEnum):
    """Hierarchy rank for alternative step execution branches."""
    PRIMARY = 1
    QA_DEFENSIVE = 2
    ALTERNATIVE_ARCH = 3
    FALLBACK = 4

    @classmethod
    def from_value(cls, val: Union[int, str, BranchRank]) -> BranchRank:
        """Resolve a rank from an int, string name/digit, or BranchRank instance."""
        if isinstance(val, cls):
            return val
        if isinstance(val, int):
            return cls(val)
        if isinstance(val, str):
            val_clean = val.strip()
            if val_clean.isdigit():
                return cls(int(val_clean))
            normalized = val_clean.upper().replace(" ", "_").replace("-", "_")
            if hasattr(cls, normalized):
                return cls[normalized]
        raise ValueError(f"Invalid BranchRank value: {val!r}")


@dataclass
class AlternativeBranch:
    """Alternative branch proposal for a step when primary route needs divergence or retry."""
    rank: int
    label: str
    prompt_template: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": int(self.rank),
            "label": self.label,
            "prompt_template": self.prompt_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlternativeBranch:
        return cls(
            rank=int(data.get("rank", 2)),
            label=str(data.get("label", "Alternative")),
            prompt_template=str(data.get("prompt_template", "")),
        )


@dataclass
class RouteStep:
    """Single discrete step within a route manifest."""
    index: int
    title: str
    primary_prompt: str
    alternatives: list[AlternativeBranch] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    retries: int = 0
    max_retries: int = 2
    assertions: list[str] = field(default_factory=list)
    manifest_ref: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "primary_prompt": self.primary_prompt,
            "alternatives": [alt.to_dict() for alt in self.alternatives],
            "status": self.status.value,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "assertions": list(self.assertions),
            "manifest_ref": self.manifest_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteStep:
        raw_status = data.get("status", StepStatus.PENDING)
        status = StepStatus(raw_status) if isinstance(raw_status, str) else raw_status
        alternatives = [
            AlternativeBranch.from_dict(item) if isinstance(item, dict) else item
            for item in data.get("alternatives", [])
        ]
        index = int(data.get("index", 0))
        title = str(data.get("title", f"Step {index + 1}"))
        primary_prompt = str(data.get("primary_prompt", ""))
        return cls(
            index=index,
            title=title,
            primary_prompt=primary_prompt,
            alternatives=alternatives,
            status=status,
            retries=int(data.get("retries", 0)),
            max_retries=int(data.get("max_retries", 2)),
            assertions=list(data.get("assertions", [])),
            manifest_ref=data.get("manifest_ref"),
        )


@dataclass
class RouteManifest:
    """Full operational playbook route containing sequential steps and metadata."""
    route_id: str
    title: str
    steps: list[RouteStep] = field(default_factory=list)
    current_step_idx: int = 0
    state: StepStatus = StepStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "title": self.title,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_idx": self.current_step_idx,
            "state": self.state.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteManifest:
        raw_state = data.get("state", StepStatus.PENDING)
        state = StepStatus(raw_state) if isinstance(raw_state, str) else raw_state
        steps = [
            RouteStep.from_dict(step) if isinstance(step, dict) else step
            for step in data.get("steps", [])
        ]
        route_id = str(data.get("route_id", "route_manifest"))
        title = str(data.get("title", route_id.replace("_", " ").title()))
        return cls(
            route_id=route_id,
            title=title,
            steps=steps,
            current_step_idx=int(data.get("current_step_idx", 0)),
            state=state,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class StepHandoff:
    """Checkpoint summary produced after a step finishes execution for validation and gating."""
    step_index: int
    git_head_sha: str = ""
    files_modified: list[str] = field(default_factory=list)
    assertions_passed: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "git_head_sha": self.git_head_sha,
            "files_modified": list(self.files_modified),
            "assertions_passed": list(self.assertions_passed),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepHandoff:
        return cls(
            step_index=int(data["step_index"]),
            git_head_sha=str(data.get("git_head_sha", "")),
            files_modified=list(data.get("files_modified", [])),
            assertions_passed=list(data.get("assertions_passed", [])),
            summary=str(data.get("summary", "")),
        )


class QueuedMessageStatus(str, Enum):
    """Lifecycle state of an auto-reply message waiting in the queue."""
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


@dataclass
class QueuedMessage:
    """Discrete queued follow-up message to be sent after the agent finishes working."""
    id: str
    prompt: str
    status: QueuedMessageStatus = QueuedMessageStatus.PENDING
    index: int = 0
    domain: str = "general"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status.value,
            "index": self.index,
            "domain": self.domain,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedMessage:
        raw_status = data.get("status", QueuedMessageStatus.PENDING)
        status = QueuedMessageStatus(raw_status) if isinstance(raw_status, str) else raw_status
        return cls(
            id=str(data.get("id", f"msg-{uuid.uuid4().hex[:8]}")),
            prompt=str(data.get("prompt", "")),
            status=status,
            index=int(data.get("index", 0)),
            domain=str(data.get("domain", "general")),
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            completed_at=data.get("completed_at"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class MessageQueueManifest:
    """Queue of follow-up messages automatically dispatched when agent turn concludes.

    Directly matches the 'Queued Messages (N) - Sends after agent finishes working' UI card.
    """
    conversation_id: str
    messages: list[QueuedMessage] = field(default_factory=list)
    active_index: int = 0
    is_paused: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_count(self) -> int:
        return len(self.messages)

    @property
    def pending_count(self) -> int:
        return sum(1 for m in self.messages if m.status == QueuedMessageStatus.PENDING)

    @property
    def is_empty(self) -> bool:
        return len(self.messages) == 0

    @property
    def is_completed(self) -> bool:
        return len(self.messages) > 0 and self.active_index >= len(self.messages)

    def peek_next_message(self) -> Optional[QueuedMessage]:
        """Return the next message to dispatch without advancing."""
        if self.is_paused or self.active_index >= len(self.messages):
            return None
        return self.messages[self.active_index]

    def pop_next_message(self) -> Optional[QueuedMessage]:
        """Advance the queue index and return the dispatched message marked COMPLETED."""
        if self.is_paused or self.active_index >= len(self.messages):
            return None
        msg = self.messages[self.active_index]
        msg.status = QueuedMessageStatus.COMPLETED
        msg.completed_at = datetime.now(timezone.utc).isoformat()
        self.active_index += 1
        return msg

    def add_message(
        self,
        prompt: str,
        domain: str = "general",
        metadata: Optional[dict[str, Any]] = None,
    ) -> QueuedMessage:
        """Append a new follow-up prompt to the end of the queue."""
        new_idx = len(self.messages)
        msg = QueuedMessage(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            prompt=prompt.strip(),
            status=QueuedMessageStatus.PENDING,
            index=new_idx,
            domain=domain,
            metadata=metadata or {},
        )
        self.messages.append(msg)
        return msg

    def remove_message(self, index: int) -> Optional[QueuedMessage]:
        """Remove a message by index and re-index remaining messages."""
        if 0 <= index < len(self.messages):
            removed = self.messages.pop(index)
            for idx, msg in enumerate(self.messages):
                msg.index = idx
            if self.active_index > index and self.active_index > 0:
                self.active_index -= 1
            return removed
        return None

    def pause(self, reason: str = "") -> None:
        """Pause queue execution (e.g. upon human preemption)."""
        self.is_paused = True
        if reason:
            self.metadata["pause_reason"] = reason

    def resume(self) -> None:
        """Resume queue execution."""
        self.is_paused = False
        self.metadata.pop("pause_reason", None)
        self.metadata["resumed"] = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "messages": [m.to_dict() for m in self.messages],
            "active_index": self.active_index,
            "is_paused": self.is_paused,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageQueueManifest:
        messages = [
            QueuedMessage.from_dict(m) if isinstance(m, dict) else m
            for m in data.get("messages", [])
        ]
        return cls(
            conversation_id=str(data.get("conversation_id", "default")),
            messages=messages,
            active_index=int(data.get("active_index", 0)),
            is_paused=bool(data.get("is_paused", False)),
            metadata=dict(data.get("metadata", {})),
        )

    def save_to_file(self, filepath: Union[str, Path]) -> None:
        """Persist queue manifest atomically with APFS/POSIX crash safety."""
        target = Path(filepath).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @classmethod
    def load_from_file(cls, filepath: Union[str, Path]) -> Optional[MessageQueueManifest]:
        """Load queue manifest from disk with directory traversal validation."""
        p = Path(filepath).resolve()
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None
