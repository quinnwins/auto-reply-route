"""Comprehensive Automated Test Suite for Auto-Reply Route Prototype.

Verifies:
1. Automated demo execution (`demo --auto` and `run_demo(auto=True)`).
2. JSON snapshot output mode and machine-readable schema.
3. State transition correctness (staging -> active -> paused -> resumed -> completed).
4. Context hygiene receipt generation, stratum classification, and token reduction.
5. Concentric visual rhythm (76-column box card formatting).
6. UX standards: zero plumbing jargon and living-room test compliance.
7. CLI entry points (`agy-route demo` and `python3 -m auto_reply_route.prototype`).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

import pytest

from auto_reply_route.cli import main as cli_main
from auto_reply_route.models import MessageQueueManifest, QueuedMessageStatus
from auto_reply_route.prototype import (
    DEFAULT_PROMPT,
    generate_5phase_prompts,
    main as prototype_main,
    run_demo,
    run_prototype,
    simulate_context_hygiene,
    simulate_turn_execution,
)
from auto_reply_route.queue_watcher import QueueWatcher


# Regex helper to strip ANSI escape codes for pure length / content analysis
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


class TestPrototypeCoreSimulation:
    """Task 1: Core simulation functions in prototype.py."""

    def test_generate_5phase_prompts_default(self) -> None:
        """Verify default 5-phase prompts conform to Operator DNA trajectory."""
        phases = generate_5phase_prompts("")
        assert len(phases) == 5
        domains = [p["domain"] for p in phases]
        assert domains == ["architecture", "core", "product", "qa", "executive"]

        # Each prompt formats the default prompt
        for p in phases:
            assert DEFAULT_PROMPT in p["prompt"]
            assert len(p["prompt"]) > 20

    def test_generate_5phase_prompts_custom(self) -> None:
        """Verify custom prompt is properly injected into all 5 phases."""
        custom = "Build an SQLite sync engine for mobile"
        phases = generate_5phase_prompts(custom)
        assert len(phases) == 5
        for p in phases:
            assert custom in p["prompt"]
            assert p["phase"].startswith("Phase ")

    def test_simulate_turn_execution_quality_gates(self) -> None:
        """Verify turn execution simulates 6-lens UI/UX quality gates and passes."""
        phase_info = {"phase": "Phase 1: Refutation", "domain": "architecture"}
        res = simulate_turn_execution(1, phase_info)
        assert res["turn"] == 1
        assert res["phase"] == "Phase 1: Refutation"
        assert "run_command (pytest)" in res["tools_executed"]
        assert res["stop_hook"]["triggered"] is True
        assert res["stop_hook"]["event"] == "on_turn_end"

        # 6-Lens Autonomous UI/UX Micro-Craft Standard
        qg = res["quality_gates"]
        assert qg["concentric_radii"] == "PASS"
        assert qg["strict_8pt_rhythm"] == "PASS"
        assert qg["state_completeness"] == "PASS"
        assert qg["touch_ergonomics"] == "PASS"
        assert qg["high_intent_action_copy"] == "PASS"
        assert qg["anti_overexplaining_law"] == "PASS"
        assert qg["overall"] == "PASSED"

    def test_simulate_context_hygiene_and_receipt(self) -> None:
        """Verify context hygiene prunes tool outputs, returns receipts, and achieves >70% token savings."""
        hygiene = simulate_context_hygiene()
        assert hygiene["original_steps"] == 5
        assert hygiene["pruned_steps"] == 5

        # Receipt content
        receipt = hygiene["sample_receipt"]
        assert "[Tool Execution Receipt]" in receipt
        assert "Tool: run_command" in receipt
        assert "Target: pytest -vv tests/" in receipt
        assert "Status: Completed" in receipt

        # Token savings
        stats = hygiene["stats"]
        assert stats["reduction_percent"] > 70.0
        assert stats["saved_tokens"] > 1000
        assert stats["saved_chars"] > 4000
        assert stats["reduction_ratio"] > 0.70


class TestPrototypeExecutionModes:
    """Task 2: Automated and Interactive demo execution."""

    def test_run_demo_auto_mode(self, tmp_path: Path) -> None:
        """Verify automated demo execution runs without pauses and returns success summary."""
        res = run_demo(
            prompt="Ship automated billing notifications",
            auto=True,
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        assert res["status"] == "success"
        assert res["initial_prompt"] == "Ship automated billing notifications"
        assert len(res["phases"]) == 5
        assert res["is_completed"] is True
        assert res["total_turns"] == 5
        assert res["completed_turns"] == 5
        assert res["state_transitions"] == ["staged", "active", "paused", "resumed", "completed"]
        assert res["preemption_handled"] is True
        assert res["turn_execution"]["quality_gates"]["overall"] == "PASSED"

    def test_run_prototype_interactive_mode(self, tmp_path: Path) -> None:
        """Verify interactive mode steps through user confirmation prompts."""
        prompts_received: list[str] = []

        def mock_input(prompt_str: str = "") -> str:
            prompts_received.append(prompt_str)
            return ""

        with patch("builtins.input", side_effect=mock_input):
            res = run_prototype(
                prompt="Interactive audit",
                mode="interactive",
                workspace_dir=tmp_path,
                delay=0.0,
                cleanup=True,
            )

        assert res["status"] == "success"
        # Verify multiple step prompts were requested
        assert len(prompts_received) >= 5
        assert any("stage 5 follow-up prompts" in p for p in prompts_received)
        assert any("simulate Agent Turn 1 execution" in p for p in prompts_received)
        assert any("simulate Human Preemption" in p for p in prompts_received)
        assert any("resume queue execution" in p for p in prompts_received)

    def test_run_demo_no_cleanup_persists_manifest(self, tmp_path: Path) -> None:
        """Verify cleanup=False leaves the valid .queued_messages file on disk."""
        conv_id = "test-persist-conv"
        queue_file = tmp_path / f".queued_messages_{conv_id}.json"

        run_demo(
            prompt="Verify persistence",
            conv_id=conv_id,
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=False,
        )

        assert queue_file.is_file()
        manifest = MessageQueueManifest.load_from_file(queue_file)
        assert manifest is not None
        assert manifest.conversation_id == conv_id
        assert manifest.total_count == 5
        assert manifest.is_completed is True
        assert all(m.status == QueuedMessageStatus.COMPLETED for m in manifest.messages)

        # Clean up afterwards
        queue_file.unlink()

    def test_run_demo_custom_conv_id(self, tmp_path: Path) -> None:
        """Verify custom conversation ID scope is preserved in manifest and output."""
        res = run_demo(
            prompt="Scoped conversation run",
            conv_id="custom-scope-42",
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        assert res["conversation_id"] == "custom-scope-42"


class TestPrototypeJsonSnapshot:
    """Task 3: Machine-readable JSON output mode."""

    def test_run_prototype_output_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify output_json=True produces clean, parseable JSON on stdout."""
        run_prototype(
            prompt="Test JSON snapshot mode",
            output_json=True,
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        captured = capsys.readouterr()
        raw_output = captured.out.strip()

        # Must parse as valid JSON
        data = json.loads(raw_output)
        assert data["status"] == "success"
        assert data["initial_prompt"] == "Test JSON snapshot mode"
        assert "phases" in data
        assert len(data["phases"]) == 5
        assert data["is_completed"] is True
        assert data["total_turns"] == 5
        assert data["completed_turns"] == 5
        assert data["state_transitions"] == ["staged", "active", "paused", "resumed", "completed"]
        assert "turn_execution" in data
        assert "context_hygiene" in data
        assert data["context_hygiene"]["reduction_percent"] > 70.0

    def test_cli_demo_json_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify agy-route demo --json produces 100% parseable JSON output."""
        exit_code = cli_main(["demo", "--json", "--dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        raw_json = captured.out.strip()
        parsed = json.loads(raw_json)
        assert parsed["status"] == "success"
        assert parsed["preemption_handled"] is True


class TestPrototypeStateTransitions:
    """Task 4: Complete state transitions: staging -> active -> paused -> resumed -> completed."""

    def test_state_transitions_sequence_and_cards(self, tmp_path: Path) -> None:
        """Verify exact status card rendering for every phase of the lifecycle."""
        conv_id = "state-cycle-test"
        queue_path = tmp_path / f".queued_messages_{conv_id}.json"
        watcher = QueueWatcher(target_dir=tmp_path, conversation_id=conv_id)

        # 1. Staged / Active
        manifest = MessageQueueManifest(conversation_id=conv_id)
        phases = generate_5phase_prompts("Test state cycle")
        for p in phases:
            manifest.add_message(prompt=p["prompt"], domain=p["domain"])
        manifest.save_to_file(queue_path)

        card_active = watcher.format_status_card(manifest)
        clean_active = _strip_ansi(card_active)
        assert "State:    ▶ RUNNING — Turn 1 of 5" in clean_active
        assert "[░░░░░░░░░░░░░░░░░░] 0% (0/5)" in clean_active

        # 2. Advance 1 Turn
        manifest.pop_next_message()
        manifest.save_to_file(queue_path)
        card_turn2 = watcher.format_status_card(manifest)
        clean_turn2 = _strip_ansi(card_turn2)
        assert "State:    ▶ RUNNING — Turn 2 of 5" in clean_turn2
        assert "20% (1/5)" in clean_turn2

        # 3. Paused (Human Preemption)
        manifest.pause(reason="Human override: verify test coverage")
        manifest.save_to_file(queue_path)
        card_paused = watcher.format_status_card(manifest)
        clean_paused = _strip_ansi(card_paused)
        assert "State:    ⏸ PAUSED — Human override: verify test coverage" in clean_paused

        # 4. Resumed
        manifest.resume()
        manifest.save_to_file(queue_path)
        card_resumed = watcher.format_status_card(manifest)
        clean_resumed = _strip_ansi(card_resumed)
        assert "State:    ▶ RUNNING — Turn 2 of 5" in clean_resumed

        # 5. Completed
        while not manifest.is_completed:
            manifest.pop_next_message()
        manifest.save_to_file(queue_path)
        card_completed = watcher.format_status_card(manifest)
        clean_completed = _strip_ansi(card_completed)
        assert "State:    ✔ COMPLETED — All queued turns dispatched" in clean_completed
        assert "100% (5/5)" in clean_completed
        assert "✨ All follow-up turns completed successfully." in clean_completed

        queue_path.unlink()

    def test_concentric_visual_rhythm_76_columns(self, tmp_path: Path) -> None:
        """Verify concentric visual rhythm: all rendered card lines are exactly 76 characters wide."""
        conv_id = "rhythm-audit"
        watcher = QueueWatcher(target_dir=tmp_path, conversation_id=conv_id)
        manifest = MessageQueueManifest(conversation_id=conv_id)
        manifest.add_message("Prompt 1")
        manifest.add_message("Prompt 2")

        for state in ["active", "paused", "completed"]:
            if state == "active":
                pass
            elif state == "paused":
                manifest.pause(reason="Auditing box width")
            elif state == "completed":
                manifest.resume()
                manifest.pop_next_message()
                manifest.pop_next_message()

            card = watcher.format_status_card(manifest)
            clean_card = _strip_ansi(card)
            lines = clean_card.splitlines()

            # The card has header, borders, content
            assert len(lines) >= 5
            for idx, line in enumerate(lines):
                assert len(line) == 76, (
                    f"Line {idx} in state '{state}' has length {len(line)} (expected 76): '{line}'"
                )


class TestPrototypeCliIntegration:
    """Task 5: CLI dispatch and flags."""

    def test_cli_demo_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify agy-route demo runs smoothly with zero arguments."""
        exit_code = cli_main(["demo", "--dir", str(tmp_path), "--delay", "0.0"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[Auto-Reply Route] Goal Intake & 5-Phase Plan" in captured.out
        assert "QUEUED MESSAGES MONITOR" in captured.out
        assert "COMPLETED" in captured.out
        assert "Prototype demonstration completed successfully." in captured.out

    def test_cli_demo_auto_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify agy-route demo --auto flag."""
        exit_code = cli_main(["demo", "--auto", "--dir", str(tmp_path), "--delay", "0.0"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Goal Intake" in captured.out

    def test_cli_demo_with_custom_prompt(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify agy-route demo --prompt passes custom goal into trajectory."""
        custom_goal = "Refactor Authentication Architecture"
        exit_code = cli_main([
            "demo",
            "--prompt", custom_goal,
            "--dir", str(tmp_path),
            "--delay", "0.0",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert f"Goal: {custom_goal}" in captured.out

    def test_standalone_prototype_module_main(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify python3 -m auto_reply_route.prototype entrypoint."""
        exit_code = prototype_main(["--json", "--delay", "0.0", "--dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["status"] == "success"


class TestPrototypeUxAndLanguageCompliance:
    """Task 6: Anti-Overexplaining and Zero Plumbing Jargon compliance."""

    def test_zero_plumbing_jargon_in_terminal_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify terminal output has zero system mechanics jargon."""
        run_demo(
            prompt="Build invoice generator",
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        captured = capsys.readouterr()
        out = captured.out.lower()

        # Forbidden plumbing mechanics terms
        forbidden_terms = [
            "antigravity stop hook",
            "processing algorithm",
            "fetching records",
            "aerial vectors",
            "in order to",
            "please note that",
            "this section allows you to",
        ]
        for term in forbidden_terms:
            assert term not in out, f"Forbidden plumbing jargon found in prototype output: '{term}'"

    def test_no_double_phase_stutter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify phase numbers are not duplicated (e.g. 'Phase 1: Phase 1:')."""
        run_demo(
            prompt="Build dashboard",
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        captured = capsys.readouterr()
        out = captured.out

        # Ensure no stuttering like 'Phase 1: Phase 1:'
        for i in range(1, 6):
            assert f"Phase {i}: Phase {i}:" not in out
            assert f"Phase {i}:" in out

    def test_living_room_test_phrasing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify clean, friendly, human-centric messaging."""
        run_demo(
            prompt="Launch client portal",
            workspace_dir=tmp_path,
            delay=0.0,
            cleanup=True,
        )
        captured = capsys.readouterr()
        out = captured.out

        # Required human-friendly labels
        assert "Goal:" in out
        assert "Turn 1 Complete — Automated Quality Checks Passed" in out
        assert "Operator Intervened: Paused auto-reply queue" in out
        assert "Operator Resumed: Resuming auto-reply queue" in out
        assert "All 5 turns completed successfully" in out
        assert "Smart Context Pruning & History Receipts:" in out
        assert "Token Savings:" in out
