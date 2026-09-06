"""Comprehensive tests for Context Hygiene, Tombstoning, and Milestone Ledger."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from auto_reply_route.context_hygiene import (
    ContextPruner,
    ContextStratum,
    STRATUM_POLICIES,
    calculate_token_reduction,
    classify_stratum,
    extract_tool_target,
    generate_milestone_manifest,
    prune_turn_transcript,
    tombstone_tool_call,
)


def test_four_strata_definitions_and_policies():
    """Verify the Four Strata of Context are strictly defined with retention policies."""
    assert ContextStratum.IMMUTABLE_CORE == 0
    assert ContextStratum.DISK_REALITY == 1
    assert ContextStratum.EPHEMERAL_TOOL_LOGS == 2
    assert ContextStratum.MILESTONE_MANIFESTS == 3

    for stratum in ContextStratum:
        assert stratum in STRATUM_POLICIES
        policy = STRATUM_POLICIES[stratum]
        assert "name" in policy
        assert "retention" in policy
        assert "description" in policy

    assert STRATUM_POLICIES[ContextStratum.IMMUTABLE_CORE]["retention"] == "NEVER_PRUNED"
    assert STRATUM_POLICIES[ContextStratum.DISK_REALITY]["retention"] == "PERSISTENT_ON_DISK"
    assert STRATUM_POLICIES[ContextStratum.EPHEMERAL_TOOL_LOGS]["retention"] == "PRUNED_POST_TURN"
    assert STRATUM_POLICIES[ContextStratum.MILESTONE_MANIFESTS]["retention"] == "PERSISTENT_COMPACT"


def test_classify_stratum():
    """Verify automatic classification of steps into their respective strata."""
    # Stratum 0: Immutable Core
    assert classify_stratum({"type": "SYSTEM", "content": "You are an AI."}) == ContextStratum.IMMUTABLE_CORE
    assert classify_stratum({"type": "USER_INPUT", "content": "Fix bug"}) == ContextStratum.IMMUTABLE_CORE
    assert classify_stratum({"role": "system", "content": "Rule"}) == ContextStratum.IMMUTABLE_CORE
    assert classify_stratum({"role": "user", "content": "Hello"}) == ContextStratum.IMMUTABLE_CORE

    # Stratum 1: Disk Reality
    assert classify_stratum({"type": "DISK_FILE", "disk_path": "/var/log/app.log"}) == ContextStratum.DISK_REALITY
    assert classify_stratum({"type": "ARTIFACT", "disk_path": "/path/to/diff.patch"}) == ContextStratum.DISK_REALITY

    # Stratum 2: Ephemeral Tool Logs
    assert classify_stratum({"type": "TOOL_RESULT", "content": "output"}) == ContextStratum.EPHEMERAL_TOOL_LOGS
    assert classify_stratum({"role": "tool", "content": "stdout"}) == ContextStratum.EPHEMERAL_TOOL_LOGS
    assert classify_stratum({"tool_name": "run_command", "content": "ok"}) == ContextStratum.EPHEMERAL_TOOL_LOGS

    # Stratum 3: Milestone Manifests
    manifest_card = generate_milestone_manifest(1, "Init", ["a.py"], "1 passed")
    assert classify_stratum({"type": "MILESTONE", "content": manifest_card}) == ContextStratum.MILESTONE_MANIFESTS
    assert classify_stratum({"type": "PLANNER_RESPONSE", "content": manifest_card}) == ContextStratum.MILESTONE_MANIFESTS


def test_extract_tool_target():
    """Test deterministic target extraction across varied tool argument schemas."""
    # Terminal commands
    assert extract_tool_target("run_command", {"CommandLine": "pytest tests/ -v"}) == "pytest tests/ -v"
    assert extract_tool_target("run_command", {"cmd": "ls -la"}) == "ls -la"

    # File operations
    assert extract_tool_target("view_file", {"AbsolutePath": "/repo/src/main.py"}) == "/repo/src/main.py"
    assert extract_tool_target("write_to_file", {"TargetFile": "/repo/src/app.py"}) == "/repo/src/app.py"
    user_file = str(Path.home() / "project" / "src" / "main.py")
    assert extract_tool_target("view_file", {"AbsolutePath": user_file}) == user_file

    # Search operations
    assert extract_tool_target("grep_search", {"SearchPath": "/repo/src", "Query": "ContextPruner"}) == "/repo/src (pattern: ContextPruner)"

    # Web operations
    assert extract_tool_target("read_url_content", {"Url": "https://api.example.com/v1"}) == "https://api.example.com/v1"

    # Empty or generic args
    assert extract_tool_target("random_tool", {}) == "N/A"
    assert extract_tool_target("custom_tool", {"custom_id": 42}) == "42"


def test_tombstoning_large_command_output():
    """Test tombstoning on large command outputs (>50 lines)."""
    large_lines = [f"test_case_{i:03d} PASSED [ {i}%]" for i in range(1, 85)]
    raw_output = "\n".join(large_lines)
    assert len(large_lines) > 50

    disk_log = str(Path.home() / ".gemini" / "antigravity" / "scratch" / "auto_reply_route" / "logs" / "pytest_run.log")
    receipt = tombstone_tool_call(
        tool_name="run_command",
        args={"CommandLine": "python3 -m pytest tests/ -v"},
        raw_output=raw_output,
        disk_log_path=disk_log,
        max_preview_lines=4,
    )

    # Validate receipt structure and deterministic lines
    assert receipt.startswith("[Tool Execution Receipt]\n")
    assert "Tool: run_command\n" in receipt
    assert "Target: python3 -m pytest tests/ -v\n" in receipt
    assert "Status: Completed\n" in receipt
    assert f"Log Ref: {disk_log}" in receipt

    # Validate preview truncation to exactly max_preview_lines
    receipt_lines = receipt.splitlines()
    summary_idx = receipt_lines.index("Status: Completed") + 1
    assert receipt_lines[summary_idx].startswith("Summary: test_case_001 PASSED")
    assert "test_case_002 PASSED" in receipt
    assert "test_case_003 PASSED" in receipt
    assert "test_case_004 PASSED" in receipt
    # Lines beyond preview limit must NOT appear in receipt
    assert "test_case_005 PASSED" not in receipt
    assert "test_case_050 PASSED" not in receipt
    assert "test_case_084 PASSED" not in receipt


def test_tombstoning_edge_cases():
    """Test tombstoning with empty output and custom preview line lengths."""
    empty_receipt = tombstone_tool_call(
        tool_name="run_command",
        args={"CommandLine": "mkdir -p /tmp/foo"},
        raw_output="",
        disk_log_path=None,
    )
    assert "Summary: (no output)" in empty_receipt
    assert "Log Ref: None" in empty_receipt

    two_line_receipt = tombstone_tool_call(
        tool_name="run_command",
        args={"CommandLine": "echo hello"},
        raw_output="Line A\nLine B\nLine C\nLine D",
        max_preview_lines=2,
    )
    assert "Line A" in two_line_receipt
    assert "Line B" in two_line_receipt
    assert "Line C" not in two_line_receipt


def test_transcript_pruning_multi_turn():
    """Test transcript pruning: ensure old tool responses are tombstoned while latest turn outputs and all user messages remain intact."""
    # Generate 100 lines of verbose tool output
    heavy_log_turn_0 = "\n".join([f"compile_module_{i}: status=OK, cache=HIT" for i in range(100)])
    heavy_log_turn_1 = "\n".join([f"db_migration_{i}: executed in 12ms" for i in range(70)])
    heavy_log_turn_2 = "\n".join([f"active_stream_line_{i}: payload received" for i in range(90)])
    error_log_turn_1 = "Traceback (most recent call last):\n  File 'worker.py', line 12\nValueError: Invalid state"

    steps: list[dict[str, Any]] = [
        # Turn 0 (Old turn - should be pruned)
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "turn": 0,
            "content": "Please compile the project and check dependencies.",
        },
        {
            "step_index": 1,
            "type": "TOOL_RESULT",
            "turn": 0,
            "tool_name": "run_command",
            "args": {"CommandLine": "make build"},
            "content": heavy_log_turn_0,
            "status": "DONE",
        },
        {
            "step_index": 2,
            "type": "PLANNER_RESPONSE",
            "turn": 0,
            "content": "Build complete. All modules compiled successfully with cache hits.",
        },
        # Turn 1 (Old turn - tool output pruned, error notice preserved, assistant summary preserved)
        {
            "step_index": 3,
            "type": "USER_INPUT",
            "turn": 1,
            "content": "Now run the database migrations and check for failures.",
        },
        {
            "step_index": 4,
            "type": "TOOL_RESULT",
            "turn": 1,
            "tool_name": "run_command",
            "args": {"CommandLine": "python3 migrate.py"},
            "content": heavy_log_turn_1,
            "status": "DONE",
        },
        {
            "step_index": 5,
            "type": "TOOL_RESULT",
            "turn": 1,
            "tool_name": "run_command",
            "args": {"CommandLine": "python3 worker.py"},
            "content": error_log_turn_1,
            "status": "ERROR",  # Error notice must NOT be pruned
        },
        {
            "step_index": 6,
            "type": "PLANNER_RESPONSE",
            "turn": 1,
            "content": "Migrations executed. A worker failure was encountered and requires investigation.",
        },
        # Turn 2 (Latest active turn - cutoff is 2, so everything in Turn 2 stays intact)
        {
            "step_index": 7,
            "type": "USER_INPUT",
            "turn": 2,
            "content": "Inspect live worker stream.",
        },
        {
            "step_index": 8,
            "type": "TOOL_RESULT",
            "turn": 2,
            "tool_name": "run_command",
            "args": {"CommandLine": "tail -n 100 stream.log"},
            "content": heavy_log_turn_2,
            "status": "DONE",
        },
        {
            "step_index": 9,
            "type": "PLANNER_RESPONSE",
            "turn": 2,
            "content": "Stream inspected. Live payload is flowing.",
        },
    ]

    steps_backup = copy.deepcopy(steps)
    pruned = prune_turn_transcript(steps, completed_turn_cutoff=2)

    # 1. Immutability guarantee: original steps must remain untouched
    assert steps == steps_backup

    # 2. Stratum 0: All user messages across ALL turns remain intact
    assert pruned[0]["content"] == "Please compile the project and check dependencies."
    assert pruned[3]["content"] == "Now run the database migrations and check for failures."
    assert pruned[7]["content"] == "Inspect live worker stream."

    # 3. Final assistant summaries across ALL turns remain intact
    assert pruned[2]["content"] == "Build complete. All modules compiled successfully with cache hits."
    assert pruned[6]["content"] == "Migrations executed. A worker failure was encountered and requires investigation."
    assert pruned[9]["content"] == "Stream inspected. Live payload is flowing."

    # 4. Error notices in old turns are strictly preserved
    assert pruned[5]["content"] == error_log_turn_1
    assert not pruned[5].get("is_tombstoned", False)

    # 5. Old tool results (Turn 0 and Turn 1 successful tool results) are tombstoned
    assert "[Tool Execution Receipt]" in pruned[1]["content"]
    assert "Tool: run_command" in pruned[1]["content"]
    assert "Target: make build" in pruned[1]["content"]
    assert "compile_module_0" in pruned[1]["content"]
    assert "compile_module_99" not in pruned[1]["content"]
    assert pruned[1].get("is_tombstoned") is True

    assert "[Tool Execution Receipt]" in pruned[4]["content"]
    assert "Target: python3 migrate.py" in pruned[4]["content"]
    assert "db_migration_0" in pruned[4]["content"]
    assert "db_migration_69" not in pruned[4]["content"]
    assert pruned[4].get("is_tombstoned") is True

    # 6. Latest turn tool output (Turn 2 >= completed_turn_cutoff 2) remains fully intact
    assert pruned[8]["content"] == heavy_log_turn_2
    assert "active_stream_line_0" in pruned[8]["content"]
    assert "active_stream_line_89" in pruned[8]["content"]
    assert not pruned[8].get("is_tombstoned", False)


def test_transcript_pruning_embedded_tool_calls():
    """Verify tombstoning of tool calls embedded within assistant response objects."""
    heavy_output = "\n".join([f"file_list_entry_{i}.py" for i in range(80)])
    steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "turn": 0,
            "content": "List files",
        },
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "turn": 0,
            "content": "Running search...",
            "tool_calls": [
                {
                    "name": "find_by_name",
                    "args": {"Pattern": "*.py"},
                    "output": heavy_output,
                }
            ],
        },
        {
            "step_index": 2,
            "type": "PLANNER_RESPONSE",
            "turn": 0,
            "content": "Found 80 files.",
        },
        {
            "step_index": 3,
            "type": "USER_INPUT",
            "turn": 1,
            "content": "Proceed.",
        },
    ]

    pruned = prune_turn_transcript(steps, completed_turn_cutoff=1)
    call_output = pruned[1]["tool_calls"][0]["output"]
    assert "[Tool Execution Receipt]" in call_output
    assert "Tool: find_by_name" in call_output
    assert "file_list_entry_0.py" in call_output
    assert "file_list_entry_75.py" not in call_output
    assert pruned[1]["tool_calls"][0]["is_tombstoned"] is True


def test_milestone_manifest_generation():
    """Test milestone manifest generation, formatting, and token budget."""
    files = [
        "src/auto_reply_route/context_hygiene.py",
        "tests/test_context_hygiene.py",
        "pyproject.toml",
    ]
    test_summary = "12 passed, 0 failed in 0.05s (100% coverage on context_hygiene.py)"
    git_sha = "3fa819e"

    manifest = generate_milestone_manifest(
        step_index=1,
        title="Implement Context Hygiene & Tombstone Specialist Engine",
        files_modified=files,
        test_summary=test_summary,
        git_sha=git_sha,
    )

    # Verify structured Markdown formatting
    assert "## 📍 Milestone Manifest — Step 1: Implement Context Hygiene & Tombstone Specialist Engine" in manifest
    assert "- **Stratum:** Stratum 3 (Structured Milestone Manifest)" in manifest
    assert "- **Step Index:** 1" in manifest
    assert "- **Git Commit:** `3fa819e`" in manifest
    assert "### 📁 Files Modified (3)" in manifest
    for f in files:
        assert f"- `{f}`" in manifest
    assert "### 🧪 Verification Summary" in manifest
    assert test_summary in manifest
    assert "Context Ledger Anchor" in manifest

    # Verify token size budget (~200-300 tokens)
    # 1 token ~= 4 chars, so 200-300 tokens ~= 800-1200 chars
    char_len = len(manifest)
    est_tokens = char_len // 4
    assert 50 <= est_tokens <= 350, f"Expected manifest tokens ~200-300, got {est_tokens}"


def test_milestone_manifest_without_git_sha():
    """Test milestone manifest generation when git_sha is omitted."""
    manifest = generate_milestone_manifest(
        step_index=2,
        title="Clean up temporary logs",
        files_modified=[],
        test_summary="No tests required",
        git_sha=None,
    )
    assert "- **Git Commit:** `N/A`" in manifest
    assert "*No files modified in this step.*" in manifest


def test_token_reduction_calculation_tool_heavy():
    """Test token reduction calculation: verify >= 60% reduction on typical tool-heavy turns."""
    # Construct a typical tool-heavy turn: 3 large commands with 100 lines each (~12,000 chars)
    tool_output_1 = "\n".join([f"2026-09-02 12:00:{i:02d} INFO worker thread {i} processed batch {i*10} items" for i in range(100)])
    tool_output_2 = "\n".join([f"DEBUG compiler symbol table entry {i}: var_{i} -> address 0x7fff{i:04x}" for i in range(100)])
    tool_output_3 = "\n".join([f"TEST result {i:03d}: status=PASSED duration=0.002s memory_delta=+4KB" for i in range(100)])

    original_steps = [
        {"step_index": 0, "type": "USER_INPUT", "turn": 0, "content": "Execute build and test cycle."},
        {"step_index": 1, "type": "TOOL_RESULT", "turn": 0, "tool_name": "run_command", "args": {"CommandLine": "worker_run"}, "content": tool_output_1},
        {"step_index": 2, "type": "TOOL_RESULT", "turn": 0, "tool_name": "run_command", "args": {"CommandLine": "compiler_check"}, "content": tool_output_2},
        {"step_index": 3, "type": "TOOL_RESULT", "turn": 0, "tool_name": "run_command", "args": {"CommandLine": "pytest"}, "content": tool_output_3},
        {"step_index": 4, "type": "PLANNER_RESPONSE", "turn": 0, "content": "Build and test completed with all checks passing."},
        {"step_index": 5, "type": "USER_INPUT", "turn": 1, "content": "Next turn instruction."},
    ]

    pruned_steps = prune_turn_transcript(original_steps, completed_turn_cutoff=1)
    reduction = calculate_token_reduction(original_steps, pruned_steps)

    assert "original_chars" in reduction
    assert "pruned_chars" in reduction
    assert "saved_chars" in reduction
    assert "original_tokens" in reduction
    assert "pruned_tokens" in reduction
    assert "saved_tokens" in reduction
    assert "reduction_percent" in reduction
    assert "reduction_ratio" in reduction

    # Verify reduction calculation correctness
    assert reduction["saved_chars"] == reduction["original_chars"] - reduction["pruned_chars"]
    assert reduction["original_tokens"] == reduction["original_chars"] // 4
    assert reduction["pruned_tokens"] == reduction["pruned_chars"] // 4
    assert reduction["saved_tokens"] == reduction["original_tokens"] - reduction["pruned_tokens"]

    # Verify >= 60% reduction requirement on tool-heavy turn
    assert reduction["reduction_percent"] >= 60.0, f"Expected >= 60% reduction, got {reduction['reduction_percent']}%"
    assert reduction["reduction_ratio"] >= 0.60
    # In practice, with 300 verbose log lines replaced by 3 receipts, reduction is typically > 85%
    assert reduction["reduction_percent"] >= 80.0


def test_context_pruner_wrapper():
    """Verify ContextPruner class methods function identically to module helpers."""
    pruner = ContextPruner(default_max_preview_lines=3)

    sample_path = str(Path.home() / "data.txt")
    receipt = pruner.tombstone_tool_call(
        tool_name="view_file",
        args={"AbsolutePath": sample_path},
        raw_output="L1\nL2\nL3\nL4\nL5",
    )
    assert "Tool: view_file" in receipt
    assert f"Target: {sample_path}" in receipt
    assert "L3" in receipt
    assert "L4" not in receipt  # Limited to default 3 lines

    policy = pruner.get_stratum_policy(ContextStratum.MILESTONE_MANIFESTS)
    assert policy["retention"] == "PERSISTENT_COMPACT"

    strat = pruner.classify_stratum({"type": "USER_INPUT", "content": "hello"})
    assert strat == ContextStratum.IMMUTABLE_CORE


def test_edge_cases_empty_and_zero_division():
    """Verify pruning and reduction calculation with empty structures."""
    assert prune_turn_transcript([], completed_turn_cutoff=1) == []

    empty_reduction = calculate_token_reduction([], [])
    assert empty_reduction["original_chars"] == 0
    assert empty_reduction["pruned_chars"] == 0
    assert empty_reduction["saved_chars"] == 0
    assert empty_reduction["reduction_percent"] == 0.0
    assert empty_reduction["reduction_ratio"] == 0.0

    steps = [{"type": "USER_INPUT", "content": "hello"}]
    identical_reduction = calculate_token_reduction(steps, steps)
    assert identical_reduction["saved_chars"] == 0
    assert identical_reduction["reduction_percent"] == 0.0


def test_turn_assignment_explicit_keys():
    """Verify turn assignment when steps provide turn_index or turn_id."""
    steps = [
        {"turn_id": 0, "type": "TOOL_RESULT", "tool_name": "cat", "content": "long " * 50},
        {"turn_index": 1, "type": "TOOL_RESULT", "tool_name": "cat", "content": "active output"},
    ]
    pruned = prune_turn_transcript(steps, completed_turn_cutoff=1)
    assert "[Tool Execution Receipt]" in pruned[0]["content"]
    assert pruned[1]["content"] == "active output"


def test_pruner_instance_full_workflow():
    """Verify end-to-end workflow using the ContextPruner class directly."""
    pruner = ContextPruner(default_max_preview_lines=2)

    manifest = pruner.generate_milestone_manifest(
        step_index=5,
        title="Verification Completed",
        files_modified=["src/auto_reply_route/context_hygiene.py"],
        test_summary="All tests passed",
    )
    assert "Step 5" in manifest

    heavy_output = "\n".join([f"service_job_{i}: processed status=SUCCESS payload_bytes={i*100}" for i in range(40)])
    steps = [
        {"type": "USER_INPUT", "content": "run task"},
        {"type": "TOOL_RESULT", "tool_name": "run", "content": heavy_output},
        {"type": "PLANNER_RESPONSE", "content": "Task finished."},
    ]
    pruned = pruner.prune_turn_transcript(steps, completed_turn_cutoff=1)
    assert "[Tool Execution Receipt]" in pruned[1]["content"]
    assert "service_job_0" in pruned[1]["content"]
    assert "service_job_1" in pruned[1]["content"]
    assert "service_job_2" not in pruned[1]["content"]  # default_max_preview_lines was 2

    reduction = pruner.calculate_token_reduction(steps, pruned)
    assert reduction["saved_chars"] > 0
    assert reduction["reduction_percent"] >= 70.0
