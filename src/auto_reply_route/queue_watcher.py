"""Headless Queue Watcher & Live Terminal Monitor for Queued Messages.

Live-tails `.queued_messages_<conv_id>.json` manifests and renders high-visibility,
human-readable terminal status cards as turns complete and subagent teams report back.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Optional

from auto_reply_route.models import MessageQueueManifest, QueuedMessage, QueuedMessageStatus

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _supports_color() -> bool:
    """Determine if current terminal environment supports ANSI color escapes."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def _color(code: str, text: str) -> str:
    """Format text with ANSI color code if supported."""
    if not _supports_color():
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _bold(text: str) -> str:
    return _color("1", text)


def _green(text: str) -> str:
    return _color("32", text)


def _blue(text: str) -> str:
    return _color("34", text)


def _cyan(text: str) -> str:
    return _color("36", text)


def _yellow(text: str) -> str:
    return _color("33", text)


def _red(text: str) -> str:
    return _color("31", text)


def _magenta(text: str) -> str:
    return _color("35", text)


def _dim(text: str) -> str:
    return _color("2", text)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text to calculate visible length."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _pad_line(content: str, width: int) -> str:
    """Pad content to target visual width, ignoring non-printing ANSI escape sequences."""
    clean = _strip_ansi(content)
    visible_len = len(clean)
    if visible_len > width:
        content = clean[: max(0, width - 3)] + "..."
        visible_len = len(content)
    padding = max(0, width - visible_len)
    return content + (" " * padding)


class QueueWatcher:
    """Monitors and live-tails active Queued Messages for a workspace conversation."""

    def __init__(
        self,
        target_dir: Path | str = ".",
        conversation_id: str = "default",
        poll_interval: float = 0.5,
    ) -> None:
        self.target_dir = Path(target_dir).resolve()
        self.conversation_id = conversation_id
        safe_conv = re.sub(r"[^a-zA-Z0-9_\-]", "_", conversation_id)
        self.queue_file = self.target_dir / f".queued_messages_{safe_conv}.json"
        self.poll_interval = max(0.1, poll_interval)
        self.last_mtime: Optional[float] = None
        self.last_state_hash: Optional[int] = None

    def load_manifest(self) -> Optional[MessageQueueManifest]:
        """Load manifest from disk if it exists."""
        if not self.queue_file.is_file():
            return None
        return MessageQueueManifest.load_from_file(self.queue_file)

    def snapshot(self) -> dict[str, Any]:
        """Return structured machine-readable snapshot of current queue state."""
        manifest = self.load_manifest()
        if not manifest:
            return {
                "conversation_id": self.conversation_id,
                "exists": False,
                "total": 0,
                "completed": 0,
                "active_index": 0,
                "pending": 0,
                "is_paused": False,
                "status": "NOT_FOUND",
                "file": str(self.queue_file),
            }

        total = manifest.total_count
        completed = sum(1 for m in manifest.messages if m.status == QueuedMessageStatus.COMPLETED)
        pending = manifest.pending_count
        active_msg = manifest.peek_next_message()

        status = "PAUSED" if manifest.is_paused else ("COMPLETED" if manifest.is_completed else "ACTIVE")
        if manifest.is_empty:
            status = "EMPTY"

        return {
            "conversation_id": manifest.conversation_id,
            "exists": True,
            "total": total,
            "completed": completed,
            "active_index": manifest.active_index,
            "pending": pending,
            "is_paused": manifest.is_paused,
            "pause_reason": manifest.metadata.get("pause_reason"),
            "status": status,
            "active_message": active_msg.to_dict() if active_msg else None,
            "file": str(self.queue_file),
        }

    def format_progress_bar(self, completed: int, total: int, width: int = 20) -> str:
        """Render a smooth Unicode progress bar."""
        if total <= 0:
            return f"[{'░' * width}] 0%"
        pct = min(1.0, max(0.0, completed / total))
        filled = int(round(width * pct))
        unfilled = width - filled
        bar = ("█" * filled) + ("░" * unfilled)
        pct_str = f"{int(pct * 100)}%"
        return f"[{bar}] {pct_str} ({completed}/{total})"

    def format_status_card(self, manifest: Optional[MessageQueueManifest] = None) -> str:
        """Render a terminal-formatted status card for the current queue."""
        if manifest is None:
            manifest = self.load_manifest()

        card_width = 74
        border_h = "─" * card_width
        border_top = f"┌{border_h}┐"
        border_mid = f"├{border_h}┤"
        border_bot = f"└{border_h}┘"

        def _box_line(content: str) -> str:
            return f"│ {_pad_line(content, card_width - 2)} │"

        lines: list[str] = []
        lines.append(border_top)

        # Header Title
        title_text = f"⚡ QUEUED MESSAGES MONITOR — Scope: {self.conversation_id}"
        if len(title_text) > card_width - 2:
            title_text = title_text[: card_width - 5] + "..."
        lines.append(_box_line(_bold(_blue(title_text))))
        lines.append(border_mid)

        if not manifest or manifest.is_empty:
            lines.append(_box_line(_dim("No active queued messages in session.")))
            target_str = f"Target: {self.queue_file.name}"
            if len(target_str) > card_width - 2:
                target_str = target_str[: card_width - 5] + "..."
            lines.append(_box_line(_dim(target_str)))
            lines.append(border_bot)
            return "\n".join(lines)

        total = manifest.total_count
        completed = sum(1 for m in manifest.messages if m.status == QueuedMessageStatus.COMPLETED)
        bar_str = self.format_progress_bar(completed, total, width=18)
        lines.append(_box_line(f"Progress: {_bold(bar_str)}"))

        # Status Line
        if manifest.is_paused:
            reason = manifest.metadata.get("pause_reason", "Human Preemption")
            status_text = f"⏸ PAUSED — {reason}"
            lines.append(_box_line(f"State:    {_yellow(_bold(status_text))}"))
        elif manifest.is_completed:
            status_text = "✔ COMPLETED — All queued turns dispatched"
            lines.append(_box_line(f"State:    {_green(_bold(status_text))}"))
        else:
            turn_num = manifest.active_index + 1
            status_text = f"▶ RUNNING — Turn {turn_num} of {total}"
            lines.append(_box_line(f"State:    {_cyan(_bold(status_text))}"))

        lines.append(border_mid)

        # Active or Next Message
        active_msg = manifest.peek_next_message()
        if active_msg:
            lines.append(_box_line(_bold("Next Auto-Reply Dispatch:")))
            prompt_snip = active_msg.prompt.strip().replace("\n", " ")
            if len(prompt_snip) > card_width - 6:
                prompt_snip = prompt_snip[: card_width - 9] + "..."
            lines.append(_box_line(f"  {_bold(prompt_snip)}"))
            domain_info = f"Domain: {active_msg.domain} • Index: {active_msg.index + 1}/{total}"
            if len(domain_info) > card_width - 6:
                domain_info = domain_info[: card_width - 9] + "..."
            lines.append(_box_line(f"  {_dim(domain_info)}"))
        elif manifest.is_completed:
            lines.append(_box_line(_green("✨ All follow-up turns completed successfully.")))

        # Subagent Team Allocation
        if not manifest.is_completed:
            turn_idx = manifest.active_index
            team_names = [
                "3-Person QA (Edge Case, Security, Test Coverage)",
                "Fresh Chaos QA (Chaos Auditor, Threat Model, Contract)",
                "Executive Simplicity (Simplicity Auditor, Debt, Product)",
                "Wiring Logic (Wiring Logic, Regressions, State Sync)",
                "Visual Proof (Screenshot/Simulator, Visual Quality, Docs)",
            ]
            team_label = team_names[turn_idx] if turn_idx < len(team_names) else "Specialized Subagent Trio"
            max_team_len = card_width - 2 - len("Subagents: ")
            if len(team_label) > max_team_len:
                team_label = team_label[: max_team_len - 3] + "..."
            lines.append(_box_line(f"{_dim('Subagents:')} {_magenta(team_label)}"))

        lines.append(border_bot)
        return "\n".join(lines)

    def watch(
        self,
        once: bool = False,
        max_iterations: Optional[int] = None,
        out_stream: Optional[Any] = None,
    ) -> None:
        """Run watcher loop, printing formatted updates when manifest state updates."""
        stream = sys.stdout if out_stream is None else out_stream
        iterations = 0
        try:
            while True:
                manifest = self.load_manifest()
                current_mtime = self.queue_file.stat().st_mtime if self.queue_file.is_file() else None
                state_data = manifest.to_dict() if manifest else {}
                current_hash = hash(json.dumps(state_data, sort_keys=True))

                should_render = (
                    self.last_mtime is None
                    or current_mtime != self.last_mtime
                    or current_hash != self.last_state_hash
                )

                if should_render:
                    self.last_mtime = current_mtime
                    self.last_state_hash = current_hash
                    card = self.format_status_card(manifest)
                    print(card, file=stream)
                    if hasattr(stream, "flush"):
                        stream.flush()

                iterations += 1
                if once:
                    break
                if max_iterations is not None and iterations >= max_iterations:
                    break

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print(f"\n{_dim('✔ Watcher stopped cleanly.')}", file=stream)
