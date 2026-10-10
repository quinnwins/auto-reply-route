"""Tests for Operator DNA Bootstrapper with AGENTS.md Ingestion & CLI integration."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from auto_reply_route.cli import build_parser, cmd_init_dna, main
from auto_reply_route.dna import (
    OPERATOR_DNA_FILENAME,
    PERSONAL_DNA_FILENAME,
    IngestedPrinciples,
    OperatorDNABootstrapper,
    clean_bullet_text,
    default_operator_dna_path,
    ensure_operator_dna,
    extract_git_user_name,
    ingest_agents_principles,
    mine_transcript_examples,
    parse_agents_markdown,
    personal_dna_path,
    render_operator_dna_matrix,
    strip_markdown_bold,
)


# ============================================================================
# Sample Fixtures & Data
# ============================================================================

SAMPLE_AGENTS_MD = """# Global Antigravity Operating Rules

## Customer-Facing Product & UX Standard (Non-Negotiable)

- **Simplicity Above All:** Anything facing customers must be **incredibly simple** in terms of both language and user experience.
- **Stress-Free & Zero Cognitive Load:** Eliminate friction, technical jargon, unnecessary choices, and confusing steps. Customers should never feel overwhelmed or have to pause to figure out what to do.
- **Fun & Intuitive:** Every customer-facing surface must feel welcoming, clear, natural, and delightful from the very first second.
- **Plain, Clear Language:** Speak like a helpful human using short, direct, everyday words—no insider terminology, technical phrasing, or corporate speak.
- **Zero Plumbing & Anti-Overexplaining Law:**
  - **Never expose system mechanics:** Never describe what the database, server, or AI is doing behind the scenes. Talk exclusively about what the human gets.
  - **Cut the throat-clearing preamble:** Never start copy with "In order to...", "This section allows you to...". Start directly with the action or benefit.
  - **The Living-Room Test:** If you wouldn't say the sentence to a neighbor over a cup of coffee, delete it.
- **Our Goal as AI Developers:** Deliver customer-facing experiences where complex capabilities feel effortless, intuitive, and stress-free.

## Autonomous UI/UX Micro-Craft Standard (Agent Self-Policing)

- **6-Lens Self-Audit:** Whenever creating or modifying frontend UI, ensure concentric radii, 4/8pt rhythm, snug leading.

## Anti-Tower-of-Babel & North Star Steering Law

- Whenever synthesizing prompts for the queue:
  1. **Session-History Grounding:** Prompts must NEVER be generated in a vacuum. Always evaluate the last 2–5 turns.
  2. **Anti-Tower-of-Babel Invariant:** Never construct massive, speculative multi-layered abstractions, generic plugin architectures, or premature inheritance trees when a direct 20-line solution works. Keep blast radius minimal.
  3. **Rabbit Hole Circuit Breaker:** If a previous turn hit a tangential rabbit hole, forcefully pull the agent back to the user's primary North Star.
  4. **Executive Founder Sanity Check:** Frame every prompt with founder pragmatism: *"What is the least complicated way to build this, prove it works with tests, and ship it?"*
"""

WORKSPACE_AGENTS_MD = """# Project Specific Guidelines

## Simplicity & Anti-Patterns
- **Simplicity Above All:** Make the API dead-simple with zero extra knobs.
- **Never expose system mechanics:** Hide all internal SQLite queries and locks.
- **The Living-Room Test:** Keep all messages friendly and conversational.
- **Anti-Tower-of-Babel Invariant:** Avoid microservice bloat; ship monolithic single-file handlers where possible.
"""


# ============================================================================
# 1. the operator's DNA Preservation Tests
# ============================================================================

class TestPersonalDNAPreservation:
    """Ensures the operator's local personal DNA file is 100% untouched and preserved."""

    def test_personal_dna_exists_returns_file_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the operator's DNA exists, ensure_operator_dna() returns it immediately without modifying it."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        personal_file = mock_gemini_config / PERSONAL_DNA_FILENAME
        original_content = "# PERSONAL OPERATOR DNA MATRIX\nOriginal pristine content.\n"
        personal_file.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        res = ensure_operator_dna()

        assert res.resolve() == personal_file.resolve()
        assert personal_file.exists()
        assert personal_file.read_text(encoding="utf-8") == original_content

    def test_personal_dna_explicit_target_returns_file_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicitly targeting the operator's DNA file returns it untouched."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        personal_file = mock_gemini_config / PERSONAL_DNA_FILENAME
        original_content = "# PERSONAL OPERATOR DNA MATRIX\nStrictly preserve this.\n"
        personal_file.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        res = ensure_operator_dna(target_path=str(personal_file))

        assert res.resolve() == personal_file.resolve()
        assert personal_file.read_text(encoding="utf-8") == original_content

    def test_personal_dna_never_overwritten_even_with_force(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Protection Invariant: force=True must NEVER overwrite personal_dna.md."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        personal_file = mock_gemini_config / PERSONAL_DNA_FILENAME
        original_content = "# PERSONAL OPERATOR DNA MATRIX\nCannot be overwritten by force.\n"
        personal_file.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        # Calling with force=True targeting personal_file must redirect to default operator_dna.md
        res = ensure_operator_dna(target_path=str(personal_file), force=True)

        # the operator's file remains untouched
        assert personal_file.read_text(encoding="utf-8") == original_content
        # Destination was redirected to operator_dna.md
        assert res.name == OPERATOR_DNA_FILENAME
        assert res.exists()
        assert res.resolve() != personal_file.resolve()

    def test_custom_target_leaves_personal_dna_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Specifying an independent target creates the file there while leaving the operator's file untouched."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        personal_file = mock_gemini_config / PERSONAL_DNA_FILENAME
        original_content = "# PERSONAL DNA\nKeep untouched.\n"
        personal_file.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        custom_dest = tmp_path / "custom" / "my_dna.md"
        res = ensure_operator_dna(target_path=custom_dest)

        assert res.resolve() == custom_dest.resolve()
        assert custom_dest.exists()
        assert personal_file.read_text(encoding="utf-8") == original_content


# ============================================================================
# 2. Mock Environment Bootstrap & Structure Tests
# ============================================================================

class TestDNABootstrapMockEnvironment:
    """Verifies auto-creation of operator_dna.md when no DNA exists in a mock environment."""

    def test_bootstrap_creates_operator_dna_and_formats_valid_markdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verifies auto-creates operator_dna.md, extracts rules, and formats valid Markdown."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        # Put global AGENTS.md in mock home
        (mock_gemini_config / "AGENTS.md").write_text(SAMPLE_AGENTS_MD, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)
        monkeypatch.setattr(
            "auto_reply_route.dna.extract_git_user_name",
            lambda ws=None: "Alice Architect",
        )

        res = ensure_operator_dna()

        assert res.name == OPERATOR_DNA_FILENAME
        assert res.exists()

        content = res.read_text(encoding="utf-8")

        # 1. Valid Markdown Structure & Headers
        assert "# ALICE ARCHITECT'S OPERATOR DNA MATRIX" in content
        assert "## 1. Voice Identity & Linguistic Fingerprint" in content
        assert "## 2. The 5-Phase Meta-Trajectory" in content
        assert "## 3. Subagent Team Allocation" in content
        assert "## 4. Anti-Pollution & Evolution Invariant" in content
        assert "## 5. Few-Shot Ground Truth Translations" in content
        assert "## 6. Executive Steering & Anti-Overbuild Invariants" in content

        # 2. Extracted AGENTS.md Rules
        assert "Simplicity Above All" in content
        assert "The living-room test:" in content
        assert "If you wouldn't say the sentence to a neighbor over a cup of coffee, delete it." in content

        # 3. Anti-Patterns
        assert "Never expose system mechanics" in content or "enterprise consultant" in content.lower()

        # 4. Anti-Tower-of-Babel & Steering
        assert "Anti-Tower-of-Babel Invariant" in content
        assert "Rabbit Hole Circuit Breaker" in content
        assert "Executive Founder Sanity Check" in content

    def test_bootstrap_fallback_when_no_git_and_no_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verifies clean bootstrap when neither git nor AGENTS.md exist (zero crashes)."""
        mock_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: mock_home)
        monkeypatch.setattr(
            "auto_reply_route.dna.extract_git_user_name",
            lambda ws=None: "Operator",
        )

        target = tmp_path / "scratch" / "test_dna.md"
        res = ensure_operator_dna(target_path=target)

        assert res.exists()
        content = res.read_text(encoding="utf-8")

        assert "# OPERATOR DNA MATRIX" in content
        assert "## 1. Voice Identity & Linguistic Fingerprint" in content
        assert "## 6. Executive Steering & Anti-Overbuild Invariants" in content
        assert "The living-room test:" in content
        assert "Anti-Tower-of-Babel" in content

    def test_bootstrap_with_workspace_agents_md_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Workspace AGENTS.md augments and overrides global AGENTS.md."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)
        (mock_gemini_config / "AGENTS.md").write_text(SAMPLE_AGENTS_MD, encoding="utf-8")

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        (workspace_dir / "AGENTS.md").write_text(WORKSPACE_AGENTS_MD, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        res = ensure_operator_dna(workspace_root=workspace_dir, target_path=tmp_path / "out.md")
        content = res.read_text(encoding="utf-8")

        assert "dead-simple with zero extra knobs" in content
        assert "monolithic single-file handlers" in content


# ============================================================================
# 3. AGENTS.md Parser Tests (Stance, Simplicity, Anti-Patterns, Token Budget)
# ============================================================================

class TestAgentsParser:
    """Tests parse_agents_markdown for accurate rule extraction and token economy."""

    def test_parse_sample_agents_markdown(self) -> None:
        """Extracts simplicity laws, anti-patterns, anti-tower-of-babel, and living-room test."""
        parsed = parse_agents_markdown(SAMPLE_AGENTS_MD)

        assert isinstance(parsed["simplicity_laws"], list)
        assert isinstance(parsed["anti_patterns"], list)
        assert isinstance(parsed["anti_tower_of_babel"], list)
        assert isinstance(parsed["executive_steering"], list)

        # Check stance and simplicity rules
        simplicity_text = " ".join(parsed["simplicity_laws"])
        assert "Simplicity Above All" in simplicity_text
        assert "Stress-Free" in simplicity_text
        assert "Plain, Clear Language" in simplicity_text

        # Check anti-patterns
        anti_patterns_text = " ".join(parsed["anti_patterns"])
        assert "Never expose system mechanics" in anti_patterns_text or "throat-clearing" in anti_patterns_text

        # Check living room test
        assert "If you wouldn't say the sentence to a neighbor over a cup of coffee, delete it." in parsed["living_room_test"]

        # Check anti-tower-of-babel
        atb_text = " ".join(parsed["anti_tower_of_babel"])
        assert "Anti-Tower-of-Babel Invariant" in atb_text
        assert "Rabbit Hole Circuit Breaker" in atb_text

    def test_parser_token_budget_invariant(self) -> None:
        """Guarantees parser output does not blow the token budget."""
        parsed = parse_agents_markdown(SAMPLE_AGENTS_MD)

        total_chars = (
            sum(len(x) for x in parsed["simplicity_laws"])
            + sum(len(x) for x in parsed["anti_patterns"])
            + sum(len(x) for x in parsed["anti_tower_of_babel"])
            + sum(len(x) for x in parsed["executive_steering"])
            + len(parsed["living_room_test"])
        )
        assert total_chars < 3000, f"Parser extracted {total_chars} chars, exceeding token budget."

        assert len(parsed["simplicity_laws"]) <= 10
        assert len(parsed["anti_patterns"]) <= 10
        assert len(parsed["anti_tower_of_babel"]) <= 10

    def test_parser_handles_empty_and_corrupt_content(self) -> None:
        """Handles empty string, whitespace, or arbitrary text gracefully."""
        empty_res = parse_agents_markdown("")
        assert empty_res["simplicity_laws"] == []
        assert empty_res["anti_patterns"] == []
        assert empty_res["living_room_test"] is None

        whitespace_res = parse_agents_markdown("   \n\n\t  ")
        assert whitespace_res["simplicity_laws"] == []
        assert whitespace_res["living_room_test"] is None

        random_text = "Some random paragraph without any matching rules or headers."
        random_res = parse_agents_markdown(random_text)
        assert random_res["simplicity_laws"] == []
        assert random_res["anti_patterns"] == []
        assert random_res["living_room_test"] is None

    def test_parser_extracts_custom_living_room_test(self) -> None:
        """Parses alternative phrasing of Living-Room Test."""
        content = "## Rules\n- Living-Room Test: Tell your grandma what the feature does in 5 words."
        parsed = parse_agents_markdown(content)
        assert parsed["living_room_test"] == "Tell your grandma what the feature does in 5 words."

    def test_clean_bullet_and_bold_helpers(self) -> None:
        """Tests bullet cleaning and bold stripping helpers."""
        assert clean_bullet_text("- Hello world") == "Hello world"
        assert clean_bullet_text("* Item two") == "Item two"
        assert clean_bullet_text("1. First numbered") == "First numbered"
        assert strip_markdown_bold("**Bold Statement**") == "Bold Statement"
        assert strip_markdown_bold("__Another Bold__") == "Another Bold"


# ============================================================================
# 4. Helper & Mining Tests (Git user name, Prompt Mining, Bootstrapper class)
# ============================================================================

class TestDNAHelpersAndMining:
    """Tests git user extraction, transcript mining, and OperatorDNABootstrapper class."""

    def test_extract_git_user_name_success(self) -> None:
        mock_res = MagicMock(returncode=0, stdout="Jane Developer\n")
        with patch("subprocess.run", return_value=mock_res):
            name = extract_git_user_name()
            assert name == "Jane Developer"

    def test_extract_git_user_name_failure_fallback(self) -> None:
        mock_res = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_res):
            name = extract_git_user_name()
            assert name == "Operator"

    def test_extract_git_user_name_exception_handling(self) -> None:
        with patch("subprocess.run", side_effect=OSError("git not found")):
            name = extract_git_user_name()
            assert name == "Operator"

    def test_mine_transcript_examples_missing_dir(self, tmp_path: Path) -> None:
        """Missing or non-existent brain directory returns empty list with zero crashes."""
        non_existent = tmp_path / "no_such_brain"
        res = mine_transcript_examples(brain_dir=non_existent)
        assert res == []

    def test_operator_dna_bootstrapper_class(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tests the OperatorDNABootstrapper class methods."""
        mock_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: mock_home)
        target = tmp_path / "bootstrapper_dna.md"

        bootstrapper = OperatorDNABootstrapper(
            workspace_root=tmp_path,
            target_path=target,
            global_config_dir=tmp_path,
        )

        name = bootstrapper.get_operator_name()
        assert isinstance(name, str)

        rendered = bootstrapper.render(mine=False)
        assert "# " in rendered
        assert "## 1. Voice Identity & Linguistic Fingerprint" in rendered

        created_path = bootstrapper.bootstrap(force=True)
        assert created_path.resolve() == target.resolve()
        assert created_path.exists()


# ============================================================================
# 5. CLI Command `agy-route init-dna` Tests
# ============================================================================

class TestCLIInitDNA:
    """Tests `agy-route init-dna` subcommand with mock filesystems and options."""

    def test_cli_init_dna_parser_registered(self) -> None:
        """Verifies `init-dna` subcommand is registered in argument parser."""
        parser = build_parser()
        args = parser.parse_args(["init-dna"])
        assert args.command == "init-dna"

    def test_cli_init_dna_preserves_personal_dna(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the operator's DNA exists, `agy-route init-dna` prints preserved notice and exits 0."""
        mock_home = tmp_path / "home"
        mock_gemini_config = mock_home / ".gemini" / "config"
        mock_gemini_config.mkdir(parents=True)

        personal_file = mock_gemini_config / PERSONAL_DNA_FILENAME
        personal_file.write_text("# PERSONAL OPERATOR DNA MATRIX\n", encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        exit_code = main(["init-dna"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "PRESERVED" in captured.out
        assert "the operator's personal DNA file is 100% untouched" in captured.out

    def test_cli_init_dna_custom_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running `agy-route init-dna --output <path>` creates file at destination."""
        mock_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: mock_home)

        output_file = tmp_path / "custom_dir" / "generated_dna.md"
        exit_code = main(["init-dna", "--output", str(output_file)])

        assert exit_code == 0
        assert output_file.exists()
        captured = capsys.readouterr()
        assert "INITIALIZED" in captured.out
        assert str(output_file) in captured.out

    def test_cli_init_dna_with_force_and_mine(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running with --force and --mine executes without error."""
        mock_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: mock_home)

        output_file = tmp_path / "forced_dna.md"
        output_file.write_text("Old content\n", encoding="utf-8")

        exit_code = main(["init-dna", "--output", str(output_file), "--force", "--mine"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "INITIALIZED" in captured.out
        assert "Force overwrite: True" in captured.out
        assert "Mining enabled: True" in captured.out

        new_content = output_file.read_text(encoding="utf-8")
        assert "Old content" not in new_content
        assert "# " in new_content

    def test_cli_init_dna_error_handling(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Handles exceptions during DNA bootstrapping gracefully and returns 1."""
        def mock_error(*args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Access denied to write destination")

        monkeypatch.setattr("auto_reply_route.dna.ensure_operator_dna", mock_error)

        exit_code = main(["init-dna", "--output", "/root/forbidden.md"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Failed to bootstrap Operator DNA" in captured.err
