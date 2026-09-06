"""Context Hygiene & Tombstone Receipt Engine.

Implements the Four Strata of Context, tool log tombstoning, transcript pruning,
and structured milestone ledger generation.
"""

from __future__ import annotations

import copy
from enum import IntEnum
import json
from typing import Any, Optional


class ContextStratum(IntEnum):
    """The Four Strata of Context Retention and Lifecycle.

    Stratum 0: Immutable Core - System prompt, base rules, invariant directives (never pruned).
    Stratum 1: Disk Reality - Files on disk, artifacts, persistent logs (zero active context footprint).
    Stratum 2: Ephemeral Tool Execution Logs - Verbose tool stdout/stderr (pruned & tombstoned post-turn).
    Stratum 3: Structured Milestone Manifests - Compact persistent cards anchoring turn accomplishments.
    """

    IMMUTABLE_CORE = 0
    DISK_REALITY = 1
    EPHEMERAL_TOOL_LOGS = 2
    MILESTONE_MANIFESTS = 3


STRATUM_POLICIES: dict[ContextStratum, dict[str, str]] = {
    ContextStratum.IMMUTABLE_CORE: {
        "name": "Immutable Core",
        "description": "System prompt, base rules, and core directives.",
        "retention": "NEVER_PRUNED",
        "footprint": "Constant base context overhead.",
    },
    ContextStratum.DISK_REALITY: {
        "name": "Disk Reality",
        "description": "Source files, test files, and raw log files persisted to disk.",
        "retention": "PERSISTENT_ON_DISK",
        "footprint": "Zero in-memory context tokens until loaded.",
    },
    ContextStratum.EPHEMERAL_TOOL_LOGS: {
        "name": "Ephemeral Tool Execution Logs",
        "description": "Verbose stdout/stderr, command executions, and file inspection outputs.",
        "retention": "PRUNED_POST_TURN",
        "footprint": "Replaced by compact tombstone receipts once turn completes.",
    },
    ContextStratum.MILESTONE_MANIFESTS: {
        "name": "Structured Milestone Manifests",
        "description": "Compact typed Markdown cards anchoring verified state across turns.",
        "retention": "PERSISTENT_COMPACT",
        "footprint": "~200-300 tokens per milestone.",
    },
}


def extract_tool_target(tool_name: str, args: Any) -> str:
    """Extract a concise target identifier from tool invocation arguments."""
    if not args:
        return "N/A"

    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                args = parsed
            else:
                return str(args)[:120]
        except Exception:
            return str(args)[:120]

    if not isinstance(args, dict):
        return str(args)[:120]

    # Priority target keys based on common tool signatures
    target_keys = [
        "CommandLine",
        "command",
        "cmd",
        "AbsolutePath",
        "TargetFile",
        "file_path",
        "path",
        "Url",
        "url",
        "SearchPath",
        "SearchDirectory",
        "target",
        "Pattern",
        "Query",
        "query",
        "Recipient",
        "recipient",
    ]

    for key in target_keys:
        if key in args and args[key]:
            val = str(args[key])
            if key in ("SearchPath", "SearchDirectory") and ("Query" in args or "Pattern" in args):
                pattern = args.get("Query") or args.get("Pattern")
                return f"{val} (pattern: {pattern})"
            return val

    # Fallback to first scalar value or JSON string
    if args:
        first_val = next(iter(args.values()))
        if isinstance(first_val, (str, int, float, bool)):
            return str(first_val)
    try:
        return json.dumps(args, default=str)
    except Exception:
        return str(args)


def tombstone_tool_call(
    tool_name: str,
    args: Any = None,
    raw_output: Any = "",
    disk_log_path: Optional[str] = None,
    max_preview_lines: int = 4,
    status: str = "Completed",
    max_line_chars: int = 500,
) -> str:
    """Replaces verbose raw tool output with a compact, deterministic receipt.

    Format:
    [Tool Execution Receipt]
    Tool: <tool_name>
    Target: <target>
    Status: <status>
    Summary: <summary or first N lines>
    Log Ref: <disk_log_path>
    """
    args = args or {}
    target = extract_tool_target(tool_name, args)

    if isinstance(raw_output, (bytes, bytearray)):
        if b"\x00" in raw_output:
            raw_text = f"<binary data: {len(raw_output)} bytes>"
        else:
            try:
                raw_text = raw_output.decode("utf-8")
            except UnicodeDecodeError:
                raw_text = raw_output.decode("utf-8", errors="replace")
    elif raw_output is not None:
        raw_text = str(raw_output)
    else:
        raw_text = ""

    cleaned_lines = [
        line.strip()[:max_line_chars] for line in raw_text.splitlines() if line.strip()
    ]

    if not cleaned_lines:
        summary_text = "(no output)"
    else:
        preview_lines = cleaned_lines[: max(1, max_preview_lines)]
        summary_text = "\n".join(preview_lines)

    log_ref_str = str(disk_log_path) if disk_log_path else "None"

    return (
        f"[Tool Execution Receipt]\n"
        f"Tool: {tool_name}\n"
        f"Target: {target}\n"
        f"Status: {status}\n"
        f"Summary: {summary_text}\n"
        f"Log Ref: {log_ref_str}"
    )


def classify_stratum(step: dict[str, Any]) -> ContextStratum:
    """Classify a conversation step into one of the Four Strata of Context."""
    if not isinstance(step, dict):
        return ContextStratum.EPHEMERAL_TOOL_LOGS

    # Explicit stratum tag
    if "stratum" in step:
        try:
            val = step["stratum"]
            if isinstance(val, ContextStratum):
                return val
            if isinstance(val, int):
                return ContextStratum(val)
            if isinstance(val, str) and val.isdigit():
                return ContextStratum(int(val))
        except (ValueError, KeyError):
            pass

    step_type = str(step.get("type", "")).upper()
    role = str(step.get("role", "")).lower()
    source = str(step.get("source", "")).upper()
    content = str(step.get("content", ""))

    # Stratum 3: Milestone manifests
    if step_type in ("MILESTONE", "MANIFEST", "MILESTONE_MANIFEST") or (
        "Milestone Manifest" in content or "Stratum 3" in content
    ):
        return ContextStratum.MILESTONE_MANIFESTS

    # Stratum 0: Immutable core (system rules, user prompts)
    if (
        step_type in ("SYSTEM", "SYSTEM_PROMPT", "RULES", "USER_INPUT")
        or role in ("system", "user")
        or source in ("USER_EXPLICIT", "SYSTEM")
    ):
        return ContextStratum.IMMUTABLE_CORE

    # Stratum 1: Disk reality (explicit file references or disk manifests)
    if step_type in ("DISK_FILE", "DISK_ARTIFACT", "FILE_ON_DISK") or step.get("disk_path"):
        return ContextStratum.DISK_REALITY

    # Stratum 2: Ephemeral tool execution logs
    return ContextStratum.EPHEMERAL_TOOL_LOGS


def _is_error_notice(step: dict[str, Any]) -> bool:
    """Check whether a step represents an error notice that must be preserved."""
    if step.get("is_error") is True:
        return True
    status = str(step.get("status", "")).upper()
    if status in ("ERROR", "FAILED", "FAILURE"):
        return True
    step_type = str(step.get("type", "")).upper()
    if step_type in ("ERROR", "ERROR_NOTICE", "TOOL_ERROR"):
        return True
    return False


def _is_tool_execution_step(step: dict[str, Any]) -> bool:
    """Determine whether a step contains ephemeral tool execution output."""
    step_type = str(step.get("type", "")).upper()
    role = str(step.get("role", "")).lower()
    source = str(step.get("source", "")).upper()

    if step_type in (
        "TOOL_RESULT",
        "TOOL_OUTPUT",
        "TOOL_RESPONSE",
        "TOOL_EXECUTION",
        "TOOL",
    ):
        return True
    if role == "tool" or source == "TOOL":
        return True
    if "tool_name" in step or "tool_call_id" in step:
        return True
    return False


def _assign_turn_indices(steps: list[dict[str, Any]]) -> list[int]:
    """Determine the turn index for each step in a transcript."""
    # Check if steps already possess explicit turn keys
    has_explicit_turns = any(
        ("turn" in s or "turn_index" in s or "turn_id" in s) for s in steps
    )
    if has_explicit_turns:
        turn_indices: list[int] = []
        current = 0
        for s in steps:
            val = s.get("turn", s.get("turn_index", s.get("turn_id")))
            if val is not None:
                try:
                    current = int(val)
                except (ValueError, TypeError):
                    pass
            turn_indices.append(current)
        return turn_indices

    # Check if user inputs exist to demarcate turns
    has_user_inputs = any(
        (
            s.get("type") in ("USER_INPUT", "user")
            or s.get("role") == "user"
            or s.get("source") == "USER_EXPLICIT"
        )
        for s in steps
    )

    if has_user_inputs:
        turn_indices = []
        turn_counter = -1
        for s in steps:
            is_user = (
                s.get("type") in ("USER_INPUT", "user")
                or s.get("role") == "user"
                or s.get("source") == "USER_EXPLICIT"
            )
            if is_user:
                turn_counter += 1
            turn_indices.append(max(0, turn_counter))
        return turn_indices

    # Fallback to step_index or index position
    return [int(s.get("step_index", i)) for i, s in enumerate(steps)]


def prune_turn_transcript(
    transcript_steps: list[dict[str, Any]],
    completed_turn_cutoff: Optional[int] = None,
    max_preview_lines: int = 4,
    cutoff: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Prunes tool execution logs for turns older than the cutoff.

    Preserves:
      - Stratum 0: User prompts & system instructions.
      - Final assistant summaries for all turns.
      - Error notices (failures and stack traces remain visible).
      - Active / latest turns (turns >= completed_turn_cutoff).

    Replaces verbose raw tool output in older turns with compact tombstone receipts.
    """
    if not transcript_steps:
        return []

    actual_cutoff = cutoff if cutoff is not None else completed_turn_cutoff
    if actual_cutoff is None:
        raise ValueError("Must specify completed_turn_cutoff or cutoff")

    # Deep copy to ensure input immutability
    pruned_steps: list[dict[str, Any]] = copy.deepcopy(transcript_steps)
    turn_indices = _assign_turn_indices(pruned_steps)

    # Find the final assistant step index for each turn to ensure final summaries are preserved
    final_assistant_idx_by_turn: dict[int, int] = {}
    for idx, (step, turn) in enumerate(zip(pruned_steps, turn_indices)):
        step_type = str(step.get("type", "")).upper()
        role = str(step.get("role", "")).lower()
        if (
            step_type in ("PLANNER_RESPONSE", "ASSISTANT")
            or role == "assistant"
        ) and not _is_tool_execution_step(step):
            final_assistant_idx_by_turn[turn] = idx

    for idx, (step, turn) in enumerate(zip(pruned_steps, turn_indices)):
        # Active or recent turns (>= cutoff) are preserved intact
        if turn >= actual_cutoff:
            continue

        # Stratum 0: User input or system prompt is never pruned
        stratum = classify_stratum(step)
        if stratum == ContextStratum.IMMUTABLE_CORE:
            continue

        # Error notices are preserved intact to retain failure context
        if _is_error_notice(step):
            continue

        # Handle embedded tool_calls with output/result fields inside assistant steps
        if "tool_calls" in step and isinstance(step["tool_calls"], list):
            for call in step["tool_calls"]:
                if isinstance(call, dict) and ("output" in call or "result" in call):
                    func_info = call.get("function") if isinstance(call.get("function"), dict) else {}
                    call_name = call.get("name") or func_info.get("name") or "tool"
                    call_args = (
                        call.get("args")
                        or call.get("arguments")
                        or func_info.get("arguments")
                        or func_info.get("args")
                        or {}
                    )
                    output_field = "output" if "output" in call else "result"
                    raw_call_output = call[output_field]
                    call[output_field] = tombstone_tool_call(
                        tool_name=call_name,
                        args=call_args,
                        raw_output=raw_call_output,
                        max_preview_lines=max_preview_lines,
                        status="Completed",
                    )
                    call["is_tombstoned"] = True

        # Final assistant summaries are preserved intact
        if idx == final_assistant_idx_by_turn.get(turn):
            continue

        # Tombstone tool execution steps
        if _is_tool_execution_step(step):
            tool_name = step.get("tool_name", step.get("name", "unknown_tool"))
            args = step.get("args") or step.get("arguments") or {}
            raw_output = step.get("content", "")
            disk_log_path = step.get("disk_log_path") or step.get("log_ref")
            status = step.get("status", "Completed")

            step["content"] = tombstone_tool_call(
                tool_name=tool_name,
                args=args,
                raw_output=raw_output,
                disk_log_path=disk_log_path,
                max_preview_lines=max_preview_lines,
                status=status,
            )
            step["is_tombstoned"] = True
            step["pruned_stratum"] = int(ContextStratum.EPHEMERAL_TOOL_LOGS)

    return pruned_steps


def generate_milestone_manifest(
    step_index: int,
    title: str,
    files_modified: list[str],
    test_summary: str,
    git_sha: Optional[str] = None,
) -> str:
    """Generates a compact, typed Markdown milestone card (~200-300 tokens).

    Anchors verified state for subsequent turns with minimal context footprint.
    """
    git_line = f"- **Git Commit:** `{git_sha}`\n" if git_sha else "- **Git Commit:** `N/A`\n"

    if files_modified:
        files_block = "\n".join(f"- `{f}`" for f in files_modified)
    else:
        files_block = "*No files modified in this step.*"

    return (
        f"## 📍 Milestone Manifest — Step {step_index}: {title}\n\n"
        f"- **Stratum:** Stratum 3 (Structured Milestone Manifest)\n"
        f"- **Step Index:** {step_index}\n"
        f"{git_line}\n"
        f"### 📁 Files Modified ({len(files_modified)})\n"
        f"{files_block}\n\n"
        f"### 🧪 Verification Summary\n"
        f"{test_summary}\n\n"
        f"---\n"
        f"*Context Ledger Anchor: Compact persistent milestone handoff for subsequent turns.*"
    )


def calculate_token_reduction(
    original_steps: list[dict[str, Any]], pruned_steps: list[dict[str, Any]]
) -> dict[str, Any]:
    """Calculates character and estimated token savings (tokens ~= chars // 4)."""
    original_chars = sum(len(json.dumps(s, default=str)) for s in original_steps)
    pruned_chars = sum(len(json.dumps(s, default=str)) for s in pruned_steps)
    saved_chars = max(0, original_chars - pruned_chars)

    original_tokens = original_chars // 4
    pruned_tokens = pruned_chars // 4
    saved_tokens = max(0, original_tokens - pruned_tokens)

    reduction_ratio = (saved_chars / original_chars) if original_chars > 0 else 0.0
    reduction_percent = round(reduction_ratio * 100.0, 2)

    return {
        "original_chars": original_chars,
        "pruned_chars": pruned_chars,
        "saved_chars": saved_chars,
        "original_tokens": original_tokens,
        "pruned_tokens": pruned_tokens,
        "saved_tokens": saved_tokens,
        "reduction_ratio": reduction_ratio,
        "reduction_percent": reduction_percent,
        "savings_ratio": reduction_ratio,
        "savings_percent": reduction_percent,
    }


class _HybridPrunerMethod:
    """Descriptor enabling prune_turn_transcript to work seamlessly as both
    an instance method (respecting default_max_preview_lines) and a class/static method.
    """

    def __get__(self, obj: Optional[ContextPruner], cls: type[ContextPruner]) -> Any:
        if obj is None:
            def class_call(
                transcript_steps: list[dict[str, Any]],
                completed_turn_cutoff: Optional[int] = None,
                max_preview_lines: int = 4,
                cutoff: Optional[int] = None,
                **kwargs: Any,
            ) -> list[dict[str, Any]]:
                actual_cutoff = cutoff if cutoff is not None else completed_turn_cutoff
                return prune_turn_transcript(
                    transcript_steps=transcript_steps,
                    completed_turn_cutoff=actual_cutoff,
                    max_preview_lines=max_preview_lines,
                )
            return class_call
        else:
            def instance_call(
                transcript_steps: list[dict[str, Any]],
                completed_turn_cutoff: Optional[int] = None,
                max_preview_lines: Optional[int] = None,
                cutoff: Optional[int] = None,
                **kwargs: Any,
            ) -> list[dict[str, Any]]:
                actual_cutoff = cutoff if cutoff is not None else completed_turn_cutoff
                lines = (
                    max_preview_lines
                    if max_preview_lines is not None
                    else obj.default_max_preview_lines
                )
                return prune_turn_transcript(
                    transcript_steps=transcript_steps,
                    completed_turn_cutoff=actual_cutoff,
                    max_preview_lines=lines,
                )
            return instance_call


class ContextPruner:
    """Context Pruner and Milestone Engine implementing the Four Strata of Context."""

    prune_turn_transcript = _HybridPrunerMethod()

    def __init__(self, default_max_preview_lines: int = 4) -> None:
        self.default_max_preview_lines = default_max_preview_lines

    def tombstone_tool_call(
        self,
        tool_name: str,
        args: Optional[dict[str, Any]] = None,
        raw_output: str = "",
        disk_log_path: Optional[str] = None,
        max_preview_lines: Optional[int] = None,
        status: str = "Completed",
    ) -> str:
        """Replace verbose tool output with a deterministic tombstone receipt."""
        lines = (
            max_preview_lines
            if max_preview_lines is not None
            else self.default_max_preview_lines
        )
        return tombstone_tool_call(
            tool_name=tool_name,
            args=args,
            raw_output=raw_output,
            disk_log_path=disk_log_path,
            max_preview_lines=lines,
            status=status,
        )

    def generate_milestone_manifest(
        self,
        step_index: int,
        title: str,
        files_modified: list[str],
        test_summary: str,
        git_sha: Optional[str] = None,
    ) -> str:
        """Generate a structured milestone card (~200-300 tokens)."""
        return generate_milestone_manifest(
            step_index=step_index,
            title=title,
            files_modified=files_modified,
            test_summary=test_summary,
            git_sha=git_sha,
        )

    def calculate_token_reduction(
        self,
        original_steps: list[dict[str, Any]],
        pruned_steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute character and token reduction metrics."""
        return calculate_token_reduction(original_steps, pruned_steps)

    def classify_stratum(self, step: dict[str, Any]) -> ContextStratum:
        """Classify a step into one of the Four Strata."""
        return classify_stratum(step)

    def get_stratum_policy(self, stratum: ContextStratum | int) -> dict[str, str]:
        """Retrieve policy and description for a given stratum."""
        s = ContextStratum(stratum)
        return STRATUM_POLICIES.get(s, {})
