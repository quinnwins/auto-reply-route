from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from auto_reply_route.cli import (
    RouteValidator,
    SteppingDeckHUD,
    build_parser,
    main,
)
from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.parser import RouteParser
from auto_reply_route.state_machine import RouteStateMachine


# ============================================================================
# 1. Tests for `agy-route validate`
# ============================================================================

class TestCLIValidate:
    """Tests for playbook validation command and RouteValidator linter."""

    def test_validate_ship_feature_playbook(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["validate", "playbooks/ship-feature.route.md"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out
        assert "Ship Feature Route" in captured.out
        assert "Steps Verified:      5" in captured.out
        assert "Branch Alternatives: 15" in captured.out
        assert "Assertions Checked:  5" in captured.out

    def test_validate_quick_spike_playbook(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["validate", "playbooks/quick-spike.route.md"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out
        assert "Quick Spike Route" in captured.out
        assert "Steps Verified:      2" in captured.out
        assert "Assertions Checked:  2" in captured.out

    def test_validate_audit_only_playbook(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["validate", "playbooks/audit-only.route.md"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out
        assert "Audit Only Route" in captured.out
        assert "Steps Verified:      2" in captured.out
        assert "Assertions Checked:  2" in captured.out

    def test_validate_feature_build_playbook(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["validate", "playbooks/feature_build.route.md"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out
        assert "Canonical Feature Build Route" in captured.out
        assert "Steps Verified:      3" in captured.out

    def test_validate_nonexistent_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["validate", "nonexistent/path/does_not_exist.route.md"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Playbook file not found" in captured.out
        assert "Validation FAILED" in captured.out

    def test_validate_empty_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        empty_file = tmp_path / "empty.route.md"
        empty_file.write_text("", encoding="utf-8")
        exit_code = main(["validate", str(empty_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Playbook file is empty" in captured.out
        assert "Validation FAILED" in captured.out

    def test_validate_missing_header(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        broken_file = tmp_path / "no_header.route.md"
        broken_file.write_text(
            "1. First Step\n   Do something.\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Missing top-level route title header" in captured.out

    def test_validate_non_sequential_step_numbering(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken_file = tmp_path / "non_seq.route.md"
        broken_file.write_text(
            "# Route Title\n\n1. First Step\n   Body.\n\n3. Third Step Skipping Two\n   Body.\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Non-sequential step numbering: expected step 2, but found 3" in captured.out

    def test_validate_duplicate_step_numbering(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken_file = tmp_path / "duplicate.route.md"
        broken_file.write_text(
            "# Route Title\n\n1. First Step\n   Body.\n\n1. Duplicate Step 1\n   Body.\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Duplicate step number 1 detected" in captured.out

    def test_validate_empty_step_prompt(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken_file = tmp_path / "empty_step.route.md"
        broken_file.write_text(
            "# Route Title\n\n1.\n\n2. Second Step\n   Body.\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "has an empty primary prompt" in captured.out

    def test_validate_empty_assertion(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken_file = tmp_path / "empty_assert.route.md"
        broken_file.write_text(
            "# Route Title\n\n1. First Step\n   Valid prompt body.\n   - Assert:\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "has an empty assertion condition" in captured.out

    def test_validate_bullet_formatting_warnings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        warn_file = tmp_path / "warn_bullet.route.md"
        warn_file.write_text(
            "# Route Title\n\n1. First Step\n   Valid prompt.\n   - Random bullet without any colon format at all\n",
            encoding="utf-8",
        )
        exit_code = main(["validate", str(warn_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Validation PASSED" in captured.out
        assert "does not match standard label format" in captured.out


# ============================================================================
# 2. Tests for `agy-route run --dry-run` and Stepping Deck HUD
# ============================================================================

class TestCLIRunDryRun:
    """Tests for dry-run simulation, Stepping Deck HUD rendering, and branch swapping."""

    def test_run_dry_run_ship_feature(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["run", "playbooks/ship-feature.route.md", "--dry-run"])
        assert exit_code == 0
        captured = capsys.readouterr()
        output = captured.out

        # Verify HUD Frame and Header
        assert "┌──────────────────────────────────────────────────────────────────────────────┐" in output
        assert "🚀 AUTO-REPLY ROUTE: Ship Feature Route" in output
        assert "Mode: DRY-RUN" in output

        # Verify Active Step 1 and its Details
        assert "▶ ACTIVE STEP 1: Build the requested feature" in output
        assert "Primary Instruction Prompt:" in output
        assert "Build the requested feature cleanly with minimal blast radius." in output
        assert "Assertions (1):" in output
        assert "python3 -m pytest tests/ -v passes" in output

        # Verify Branch Alternatives
        assert "Alternative Branch Options (3):" in output
        assert "[Rank 2] *Quick Spike*" in output
        assert "[Rank 3] *QA Defensive*" in output
        assert "[Rank 4] *Fallback*" in output

        # Verify Simulated Step Transitions
        assert "👉 [DRY-RUN] Advancing Step 1/5: Build the requested feature" in output
        assert "👉 [DRY-RUN] Advancing Step 2/5: Review implementation with 3-agent" in output
        assert "👉 [DRY-RUN] Advancing Step 3/5: Review for executive-level compromises" in output
        assert "👉 [DRY-RUN] Advancing Step 4/5: Verify end-to-end functionality and capture" in output
        assert "👉 [DRY-RUN] Advancing Step 5/5: Review visual walkthrough evidence" in output

        # Verify Completed State in Final HUD
        assert "State: COMPLETED" in output
        assert "🎉 ROUTE EXECUTION COMPLETE: All steps verified and finished." in output
        assert "✨ [DRY-RUN COMPLETE] Successfully simulated all 5 steps with 0 errors." in output

    def test_run_dry_run_quick_spike(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["run", "playbooks/quick-spike.route.md", "--dry-run"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "🚀 AUTO-REPLY ROUTE: Quick Spike Route" in captured.out
        assert "👉 [DRY-RUN] Advancing Step 1/2: Create a rapid working prototype spike" in captured.out
        assert "👉 [DRY-RUN] Advancing Step 2/2: Verify basic end-to-end execution" in captured.out
        assert "✨ [DRY-RUN COMPLETE] Successfully simulated all 2 steps with 0 errors." in captured.out

    def test_run_dry_run_branch_swap(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Swap Step 1 (index 0) with Rank 2 (*Quick Spike*)
        exit_code = main(["run", "playbooks/ship-feature.route.md", "--dry-run", "--swap", "0:2"])
        assert exit_code == 0
        captured = capsys.readouterr()
        output = captured.out

        assert "Swapped Step 1 with branch Rank 2: 'Quick Spike'" in output
        # Prompt should now be the Quick Spike alternative text
        assert "Build a minimal working prototype first without optimizations." in output

    def test_run_dry_run_branch_swap_1_based(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Using 1-based index 5 for Step 5
        exit_code = main(["run", "playbooks/ship-feature.route.md", "--dry-run", "--swap", "5:2"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Swapped Step 5 with branch Rank 2: 'Micro Polish'" in captured.out

    def test_run_dry_run_invalid_swap_rank(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["run", "playbooks/ship-feature.route.md", "--dry-run", "--swap", "0:99"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Failed to swap branch '0:99'" in captured.err
        assert "Alternative branch with rank 99 not found" in captured.err

    def test_run_dry_run_invalid_swap_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["run", "playbooks/ship-feature.route.md", "--dry-run", "--swap", "invalid_no_colon"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Invalid --swap format 'invalid_no_colon'" in captured.err

    def test_run_invalid_playbook_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken_file = tmp_path / "broken.route.md"
        broken_file.write_text("No header here.\n", encoding="utf-8")
        exit_code = main(["run", str(broken_file)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Cannot run playbook" in captured.err
        assert "Validation failed" in captured.err


# ============================================================================
# 3. Tests for Live Run & Checkpoints
# ============================================================================

class TestCLIRunLive:
    """Tests for non-interactive live execution and checkpoint persistence."""

    def test_run_non_interactive_creates_checkpoint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ckpt_file = tmp_path / "test_run.checkpoint.json"
        exit_code = main([
            "run",
            "playbooks/quick-spike.route.md",
            "--non-interactive",
            "--checkpoint",
            str(ckpt_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "🚀 AUTO-REPLY ROUTE: Quick Spike Route" in captured.out
        assert "✨ [ROUTE COMPLETED] Execution finished successfully." in captured.out

        # Verify checkpoint was persisted on disk
        assert ckpt_file.is_file()
        data = json.loads(ckpt_file.read_text(encoding="utf-8"))
        assert data["route_id"] == "quick-spike"
        assert data["state"] == StepStatus.COMPLETED.value
        assert len(data["steps"]) == 2
        assert data["steps"][0]["status"] == StepStatus.COMPLETED.value
        assert data["steps"][1]["status"] == StepStatus.COMPLETED.value

    def test_run_resume_from_checkpoint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Create a checkpoint paused at step index 1
        manifest = RouteParser.parse_file("playbooks/ship-feature.route.md")
        sm = RouteStateMachine(manifest)
        sm.start()
        sm.advance_step()  # Now at step index 1 (Step 2)
        sm.pause("Human inspection")

        ckpt_file = tmp_path / "paused.checkpoint.json"
        sm.save_checkpoint(str(ckpt_file))

        # Run with checkpoint
        exit_code = main([
            "run",
            "playbooks/ship-feature.route.md",
            "--non-interactive",
            "--checkpoint",
            str(ckpt_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "✨ [ROUTE COMPLETED] Execution finished successfully." in captured.out

        # Re-read checkpoint and verify completed
        resumed_sm = RouteStateMachine.load_checkpoint(str(ckpt_file))
        assert resumed_sm.is_completed


# ============================================================================
# 4. Tests for `agy-route mine`
# ============================================================================

class TestCLIMine:
    """Tests for offline route mining CLI subcommand and backwards compatibility."""

    def test_mine_with_transcripts_markdown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Create a mock transcript JSONL file
        transcript_file = tmp_path / "transcript.jsonl"
        turns = [
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Build the user authentication model</USER_REQUEST>"},
            {"source": "MODEL", "type": "GENERIC", "content": "Done creating user authentication model."},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Run automated tests and verify</USER_REQUEST>"},
            {"source": "MODEL", "type": "GENERIC", "content": "Tests passing."},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Commit and deploy changes</USER_REQUEST>"},
        ]
        with open(transcript_file, "w", encoding="utf-8") as f:
            for t in turns:
                f.write(json.dumps(t) + "\n")

        out_file = tmp_path / "mined.route.md"
        exit_code = main([
            "mine",
            "--transcripts",
            str(transcript_file),
            "--output",
            str(out_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Discovered 1 route(s) exported to" in captured.out
        assert out_file.is_file()

        content = out_file.read_text(encoding="utf-8")
        assert "# Auto-Reply Route Map:" in content
        assert "```mermaid" in content
        assert "flowchart TD" in content

    def test_mine_json_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        transcript_file = tmp_path / "transcript.jsonl"
        turns = [
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Build the user authentication model</USER_REQUEST>"},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Run automated tests and verify</USER_REQUEST>"},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Commit and deploy changes</USER_REQUEST>"},
        ]
        with open(transcript_file, "w", encoding="utf-8") as f:
            for t in turns:
                f.write(json.dumps(t) + "\n")

        exit_code = main([
            "mine",
            "--transcripts",
            str(transcript_file),
            "--format",
            "json",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "route_id" in data[0]
        assert "steps" in data[0]

    def test_mine_backward_compatibility_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Test calling main(["--transcripts", ...]) directly without 'mine' subcommand
        transcript_file = tmp_path / "transcript.jsonl"
        turns = [
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Build the feature</USER_REQUEST>"},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Run test suite</USER_REQUEST>"},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Commit and release</USER_REQUEST>"},
        ]
        with open(transcript_file, "w", encoding="utf-8") as f:
            for t in turns:
                f.write(json.dumps(t) + "\n")

        exit_code = main(["--transcripts", str(transcript_file), "--format", "json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)


# ============================================================================
# 5. Tests for `agy-route hook`
# ============================================================================

class TestCLIHook:
    """Tests for Stop hook integration via stdin/stdout JSON."""

    def test_hook_non_model_stop(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"terminationReason": "user_cancelled", "executionNum": 1}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

        exit_code = main(["hook"])
        assert exit_code == 0
        captured = capsys.readouterr()
        resp = json.loads(captured.out.strip())
        assert resp == {"decision": "allow"}

    def test_hook_model_stop_no_active_checkpoint(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"terminationReason": "model_stop", "workspacePaths": ["/tmp/nonexistent"]}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

        exit_code = main(["hook"])
        assert exit_code == 0
        captured = capsys.readouterr()
        resp = json.loads(captured.out.strip())
        assert resp == {"decision": "allow"}

    def test_hook_with_active_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Create an active running route checkpoint in tmp_path
        manifest = RouteParser.parse_file("playbooks/quick-spike.route.md")
        sm = RouteStateMachine(manifest)
        sm.start()
        ckpt_path = tmp_path / ".agy-route-state.json"
        sm.save_checkpoint(str(ckpt_path))

        payload = {
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "workspacePaths": [str(tmp_path)],
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

        exit_code = main(["hook"])
        assert exit_code == 0
        captured = capsys.readouterr()
        resp = json.loads(captured.out.strip())

        assert resp["decision"] == "continue"
        assert "Verify basic end-to-end execution" in resp["reason"]

        # Verify checkpoint advanced to Step 2
        updated_sm = RouteStateMachine.load_checkpoint(str(ckpt_path))
        assert updated_sm.manifest.current_step_idx == 1


# ============================================================================
# 6. General CLI Tests (Help, Usage)
# ============================================================================

class TestCLIGeneral:
    """General CLI argument parsing and help output tests."""

    def test_cli_no_args_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "usage: agy-route" in captured.out
        assert "Available subcommands" in captured.out

    def test_cli_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage: agy-route" in captured.out

    def test_build_parser(self) -> None:
        parser = build_parser()
        assert parser.prog == "agy-route"


# ============================================================================
# ============================================================================
# 8. Tests for `agy-route build --max-subagents`
# ============================================================================

class TestCLIBuildSubagents:
    """Tests for subagent team configuration across `agy-route build`."""

    @pytest.mark.parametrize("max_subagents,expected_phrase,unexpected_phrases", [
        (0, None, ["Use as many subagents", "Use 1 subagent", "up to 0 subagents"]),
        (1, "Use 1 subagent if needed to isolate execution context.", ["working as a team", "up to 1 subagents"]),
        (3, "Use as many subagents working as a team as you need (up to 3 subagents).", ["3-person", "3 person"]),
        (5, "Use as many subagents working as a team as you need (up to 5 subagents).", ["3-person", "3 person"]),
    ])
    def test_cli_build_max_subagents_variations(
        self,
        max_subagents: int,
        expected_phrase: str | None,
        unexpected_phrases: list[str],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main([
            "build",
            "Build auth service in src/auth.py",
            "--steps", "3",
            "--max-subagents", str(max_subagents),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        out = captured.out

        # Invariant 1: "3-person" is never hardcoded in route output
        assert "3-person" not in out.lower()
        assert "3 person" not in out.lower()

        # Invariant 2: Team budget correctly phrased
        if expected_phrase:
            assert expected_phrase in out

        # Invariant 3: Disallowed / malformed phrases are omitted
        for unexp in unexpected_phrases:
            assert unexp not in out

    def test_cli_build_max_subagents_zero_cleanly_omits_directive(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_file = tmp_path / "zero_subagents.route.md"
        exit_code = main([
            "build",
            "Implement rate limiter in middleware.py",
            "--steps", "2",
            "--max-subagents", "0",
            "-o", str(out_file),
        ])
        assert exit_code == 0
        assert out_file.is_file()
        content = out_file.read_text(encoding="utf-8")

        # Invariant 1: "3-person" never present
        assert "3-person" not in content.lower()
        assert "3 person" not in content.lower()

        # Invariant 2: No subagent directive appended
        assert "Use as many subagents" not in content
        assert "Use 1 subagent" not in content
        assert "up to 0 subagents" not in content
