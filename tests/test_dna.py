"""Comprehensive Tests for Operator DNA Bootstrapper & AGENTS.md Ingestion.

Validates:
1. Priority check: personal_dna.md preservation vs target_path vs operator_dna.md.
2. Git user name extraction and fallback to 'Operator'.
3. Principles ingestion from global and workspace AGENTS.md.
4. Transcript mining using PromptMiner with secret/PII sanitization.
5. Clean Markdown rendering from structured template with 0 syntax defects.
6. CLI `agy-route init-dna` flags (--mine, --force, --output, --dir).
7. Graceful handling of missing directories, corrupt files, and non-git environments.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from auto_reply_route.cli import main
from auto_reply_route.dna import (
    IngestedPrinciples,
    OperatorDNABootstrapper,
    clean_bullet_text,
    default_operator_dna_path,
    ensure_operator_dna,
    extract_git_user_name,
    format_bullet_point,
    ingest_agents_principles,
    mine_transcript_examples,
    parse_agents_markdown,
    personal_dna_path,
    render_operator_dna_matrix,
    strip_markdown_bold,
    synthesize_idea_label,
)


# ============================================================================
# 1. Tests for Git User Name Extraction
# ============================================================================

class TestGitUserExtraction:
    """Tests for extracting git user.name with robust fallbacks."""

    def test_extract_git_user_name_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="Ada Lovelace\n", stderr="")

        monkeypatch.setattr("subprocess.run", mock_run)
        assert extract_git_user_name() == "Ada Lovelace"

    def test_extract_git_user_name_fallback_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="error")

        monkeypatch.setattr("subprocess.run", mock_run)
        assert extract_git_user_name() == "Operator"

    def test_extract_git_user_name_fallback_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: Any, **kwargs: Any) -> None:
            raise FileNotFoundError("git binary not found")

        monkeypatch.setattr("subprocess.run", mock_run)
        assert extract_git_user_name() == "Operator"

    def test_extract_git_user_name_fallback_on_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="   \n", stderr="")

        monkeypatch.setattr("subprocess.run", mock_run)
        assert extract_git_user_name() == "Operator"


# ============================================================================
# 2. Tests for AGENTS.md Markdown Parser & Ingestion
# ============================================================================

class TestAgentsParser:
    """Tests for parsing simplicity laws, living room test, anti-patterns, and invariants."""

    def test_parse_sample_agents_content(self) -> None:
        content = """# Global Antigravity Operating Rules

## Customer-Facing Product & UX Standard (Non-Negotiable)
- **Simplicity Above All:** Anything facing customers must be incredibly simple.
- **Stress-Free & Zero Cognitive Load:** Eliminate friction and confusion.
- **Plain, Clear Language:** Speak like a helpful human using short everyday words.
- **Zero Plumbing & Anti-Overexplaining Law:**
  - **Never expose system mechanics:** Never describe internal algorithms.
  - **Cut the throat-clearing preamble:** Never start copy with In order to.
  - **The Living-Room Test:** If you wouldn't say the sentence to a neighbor over coffee, delete it.

## Anti-Tower-of-Babel & North Star Steering Law
- **Anti-Tower-of-Babel Invariant:** Never construct massive multi-layered abstractions when direct 20-line solution works.
- **Rabbit Hole Circuit Breaker:** Forcefully pull the agent back to North Star.
- **Executive Founder Sanity Check:** What is the least complicated way to build this?
- **Session-History Grounding:** Inspect the last 2-5 turns.
"""
        parsed = parse_agents_markdown(content)

        assert parsed["living_room_test"] == "If you wouldn't say the sentence to a neighbor over coffee, delete it."
        assert any("Simplicity Above All" in s for s in parsed["simplicity_laws"])
        assert any("Never expose system mechanics" in a for a in parsed["anti_patterns"])
        assert any("Anti-Tower-of-Babel" in t for t in parsed["anti_tower_of_babel"])
        assert any("Session-History Grounding" in e for e in parsed["executive_steering"])
        assert "Customer-Facing Product & UX Standard (Non-Negotiable)" in parsed["core_rules"]

    def test_parse_empty_content_returns_defaults(self) -> None:
        parsed = parse_agents_markdown("")
        assert parsed["simplicity_laws"] == []
        assert parsed["living_room_test"] is None

    def test_ingest_principles_fallback_when_files_missing(self, tmp_path: Path) -> None:
        empty_config = tmp_path / "empty_config"
        empty_config.mkdir()
        empty_workspace = tmp_path / "empty_workspace"
        empty_workspace.mkdir()

        principles = ingest_agents_principles(
            workspace_root=empty_workspace,
            global_config_dir=empty_config,
        )

        assert principles.operator_name != ""
        assert len(principles.simplicity_laws) >= 1
        assert len(principles.anti_patterns) >= 1
        assert len(principles.anti_tower_of_babel) >= 1
        assert "neighbor over coffee" in principles.living_room_test

    def test_workspace_agents_augments_global(self, tmp_path: Path) -> None:
        global_dir = tmp_path / "global_config"
        global_dir.mkdir()
        (global_dir / "AGENTS.md").write_text(
            "## Global Rules\n- **Simplicity Above All:** Global simple rule.\n",
            encoding="utf-8",
        )

        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text(
            "## Workspace Rules\n- **Simplicity Above All:** Workspace custom override.\n- **The Living-Room Test:** Ask your grandma.\n",
            encoding="utf-8",
        )

        principles = ingest_agents_principles(
            workspace_root=ws_dir,
            global_config_dir=global_dir,
        )

        assert principles.living_room_test == "Ask your grandma."
        assert any("Workspace custom override" in s for s in principles.simplicity_laws)
        assert len(principles.sources) == 2


# ============================================================================
# 3. Tests for Formatting & Rendering Helpers
# ============================================================================

class TestFormattingAndHelpers:
    """Tests for bullet formatting, idea synthesis, and markdown polish."""

    def test_clean_bullet_text(self) -> None:
        assert clean_bullet_text("- Hello world") == "Hello world"
        assert clean_bullet_text("* Bold text") == "Bold text"
        assert clean_bullet_text("1. Numbered item") == "Numbered item"
        assert clean_bullet_text("1) Alternate numbered item") == "Alternate numbered item"
        assert clean_bullet_text("- **Bold Title:** Body") == "**Bold Title:** Body"

    def test_strip_markdown_bold(self) -> None:
        assert strip_markdown_bold("**Title**") == "Title"
        assert strip_markdown_bold("Plain Title") == "Plain Title"

    def test_format_bullet_point_bold_syntax(self) -> None:
        # Pattern: **Key:** Value
        res = format_bullet_point("**Never expose system mechanics:** Never describe backend.")
        assert res == "- **Never expose system mechanics:** Never describe backend."

        # Pattern: **Key**: Value
        res2 = format_bullet_point("**Never expose system mechanics**: Never describe backend.")
        assert res2 == "- **Never expose system mechanics:** Never describe backend."

        # Plain Key: Value
        res3 = format_bullet_point("Key Concept: Important detail.")
        assert res3 == "- **Key Concept:** Important detail."

        # Plain bullet
        res4 = format_bullet_point("Just a plain statement.")
        assert res4 == "- Just a plain statement."

    def test_synthesize_idea_label(self) -> None:
        idea1 = synthesize_idea_label(
            raw="how can i see this in antigravity work",
            norm="see [PATH:py] in antigravity work",
        )
        assert "Antigravity" in idea1 or "See" in idea1
        assert "[" not in idea1  # No slot mask brackets leaked

        idea2 = synthesize_idea_label(
            raw="switch over all my 5.6 sol calls to 6.0 astra",
            norm="switch over [NUM] sol calls to astra",
        )
        assert "[" not in idea2
        assert len(idea2.split()) <= 6


# ============================================================================
# 4. Tests for Transcript Mining
# ============================================================================

class TestTranscriptMining:
    """Tests for mining user transcripts across intent strata."""

    def test_mine_transcript_examples_from_brain(self, tmp_path: Path) -> None:
        brain_dir = tmp_path / "brain"
        session_dir = brain_dir / "sess-1" / ".system_generated" / "logs"
        session_dir.mkdir(parents=True)
        transcript_file = session_dir / "transcript.jsonl"

        turns = [
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Build the user authentication model</USER_REQUEST>"},
            {"source": "MODEL", "content": "Done building model."},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Run the automated test suite and check edge cases</USER_REQUEST>"},
            {"source": "MODEL", "content": "Tests pass."},
            {"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Fix traceback error in authentication token validation</USER_REQUEST>"},
        ]
        with open(transcript_file, "w", encoding="utf-8") as f:
            for t in turns:
                f.write(json.dumps(t) + "\n")

        examples = mine_transcript_examples(brain_dir=brain_dir, max_examples=3)
        assert len(examples) >= 2
        domains = [ex["domain"] for ex in examples]
        assert any("Architecture" in d or "Build" in d or "Feature" in d for d in domains)
        assert any("Testing" in d or "Quality" in d or "Bug" in d or "Repair" in d for d in domains)

    def test_mine_transcript_missing_brain_returns_empty(self, tmp_path: Path) -> None:
        missing_brain = tmp_path / "does_not_exist"
        examples = mine_transcript_examples(brain_dir=missing_brain)
        assert examples == []


# ============================================================================
# 5. Tests for Rendering Operator DNA Matrix
# ============================================================================

class TestRenderOperatorDNA:
    """Tests for rendering clean Markdown DNA matrix from template."""

    def test_render_with_operator_name(self) -> None:
        principles = IngestedPrinciples(
            operator_name="Grace Hopper",
            simplicity_laws=["**Simplicity Above All:** Keep compiler simple."],
            living_room_test="If you wouldn't say it over coffee, delete it.",
            anti_patterns=["Never expose system mechanics behind the scenes."],
            anti_tower_of_babel=["**Anti-Tower-of-Babel Invariant:** Direct 20-line solution first."],
            executive_steering=["**Session-History Grounding:** Inspect recent turns."],
        )
        md = render_operator_dna_matrix(
            operator_name="Grace Hopper",
            principles=principles,
        )

        assert "# GRACE HOPPER'S OPERATOR DNA MATRIX" in md
        assert "## 1. Voice Identity & Linguistic Fingerprint" in md
        assert "## 2. The 5-Phase Meta-Trajectory" in md
        assert "## 3. Subagent Team Allocation" in md
        assert "## 4. Anti-Pollution & Evolution Invariant" in md
        assert "Grace Hopper's genuine voice" in md
        assert "## 5. Few-Shot Ground Truth Translations" in md
        assert "Grace Hopper's Prompt:" in md
        assert "## 6. Executive Steering & Anti-Overbuild Invariants" in md
        assert "- **Anti-Tower-of-Babel Invariant:** Direct 20-line solution first." in md
        assert "****" not in md  # Zero double-bold syntax defects

    def test_render_with_fallback_operator_name(self) -> None:
        principles = IngestedPrinciples(operator_name="Operator")
        md = render_operator_dna_matrix(operator_name="Operator", principles=principles)
        assert "# OPERATOR DNA MATRIX" in md
        assert "Operator's genuine voice" in md


# ============================================================================
# 6. Tests for `ensure_operator_dna` Priority Resolution
# ============================================================================

class TestEnsureOperatorDNA:
    """Tests for priority resolution, preservation of the operator's DNA, and auto-creation."""

    def test_ensure_operator_dna_preserves_personal_dna_when_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gemini_config = tmp_path / ".gemini" / "config"
        fake_gemini_config.mkdir(parents=True)
        q_file = fake_gemini_config / "personal_dna.md"
        original_content = "# PERSONAL ORIGINAL PRESERVED DNA"
        q_file.write_text(original_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        res = ensure_operator_dna()
        assert res.resolve() == q_file.resolve()
        assert q_file.read_text(encoding="utf-8") == original_content

    def test_ensure_operator_dna_creates_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        res = ensure_operator_dna()
        expected = tmp_path / ".gemini" / "config" / "operator_dna.md"
        assert res.resolve() == expected.resolve()
        assert expected.is_file()
        content = expected.read_text(encoding="utf-8")
        assert "OPERATOR DNA MATRIX" in content
        assert "## 1. Voice Identity" in content
        assert "## 6. Executive Steering" in content

    def test_ensure_operator_dna_with_custom_target_path(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "custom_project_dna.md"
        assert not target.exists()

        res = ensure_operator_dna(target_path=target)
        assert res.resolve() == target.resolve()
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "OPERATOR DNA MATRIX" in content

    def test_ensure_operator_dna_respects_existing_target_without_force(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "existing_dna.md"
        target.write_text("# MY CUSTOM DNA CONTENT", encoding="utf-8")

        res = ensure_operator_dna(target_path=target, force=False)
        assert res.resolve() == target.resolve()
        assert target.read_text(encoding="utf-8") == "# MY CUSTOM DNA CONTENT"

    def test_ensure_operator_dna_overwrites_target_with_force(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "existing_dna.md"
        target.write_text("# OLD CONTENT", encoding="utf-8")

        res = ensure_operator_dna(target_path=target, force=True)
        assert res.resolve() == target.resolve()
        new_content = target.read_text(encoding="utf-8")
        assert "# OLD CONTENT" not in new_content
        assert "OPERATOR DNA MATRIX" in new_content

    def test_ensure_operator_dna_never_overwrites_personal_dna(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_gemini_config = tmp_path / ".gemini" / "config"
        fake_gemini_config.mkdir(parents=True)
        q_file = fake_gemini_config / "personal_dna.md"
        original = "# PERSONAL SACRED FILE"
        q_file.write_text(original, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Even if target_path explicitly points to personal_dna with force=True,
        # it must NEVER overwrite personal_dna.md
        res = ensure_operator_dna(target_path=q_file, force=True)
        assert q_file.read_text(encoding="utf-8") == original
        # Instead, fallback destination was used
        assert res.name == "operator_dna.md"


# ============================================================================
# 7. Tests for `OperatorDNABootstrapper` Class
# ============================================================================

class TestOperatorDNABootstrapperClass:
    """Tests for OperatorDNABootstrapper orchestrator object."""

    def test_bootstrapper_lifecycle(self, tmp_path: Path) -> None:
        target = tmp_path / "class_dna.md"
        bs = OperatorDNABootstrapper(target_path=target)

        assert bs.get_operator_name() != ""
        principles = bs.get_principles()
        assert isinstance(principles, IngestedPrinciples)

        rendered = bs.render()
        assert "OPERATOR DNA MATRIX" in rendered

        bootstrapped_path = bs.bootstrap()
        assert bootstrapped_path.resolve() == target.resolve()
        assert target.is_file()


# ============================================================================
# 8. Tests for CLI `agy-route init-dna`
# ============================================================================

class TestCLIInitDNA:
    """Tests for `agy-route init-dna` subcommand with various flags."""

    def test_cli_init_dna_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["init-dna", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage: agy-route init-dna" in captured.out
        assert "--mine" in captured.out
        assert "--force" in captured.out
        assert "--output" in captured.out

    def test_cli_init_dna_custom_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_file = tmp_path / "cli_test_dna.md"
        exit_code = main(["init-dna", "--output", str(out_file)])
        assert exit_code == 0
        assert out_file.is_file()

        captured = capsys.readouterr()
        assert "Operator DNA Matrix ready at:" in captured.out
        content = out_file.read_text(encoding="utf-8")
        assert "OPERATOR DNA MATRIX" in content

    def test_cli_init_dna_with_mine(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out_file = tmp_path / "cli_mined_dna.md"
        exit_code = main(["init-dna", "--mine", "--output", str(out_file)])
        assert exit_code == 0
        assert out_file.is_file()

        captured = capsys.readouterr()
        assert "Mining enabled: True" in captured.out

    def test_cli_init_dna_preserves_personal_dna(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_config = tmp_path / ".gemini" / "config"
        fake_config.mkdir(parents=True)
        q_file = fake_config / "personal_dna.md"
        q_file.write_text("# PERSONAL DNA UNTOUCHED", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        exit_code = main(["init-dna"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[PRESERVED] the operator's Operator DNA matrix active at:" in captured.out
        assert "the operator's personal DNA file is 100% untouched." in captured.out
        assert q_file.read_text(encoding="utf-8") == "# PERSONAL DNA UNTOUCHED"
