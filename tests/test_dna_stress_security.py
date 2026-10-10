"""Stress, Boundary, and Security Test Suite for Operator DNA (dna.py).

Covers:
1. Security & ReDoS / Token Bloat Attack:
   - Massive 50,000-line AGENTS.md with deeply nested bullet lists and repetitive regex triggers.
   - Parsing time strictly < 100ms.
   - Token budget strictly < 3,000 chars and <= 10 rules per section.
   - Adversarial ultra-long lines and extreme nesting depth.
2. Non-UTF8 & Malformed Data:
   - Corrupt byte sequences in global and workspace AGENTS.md.
   - Corrupt bytes and malformed JSON in session transcripts.
   - Null bytes and replacement character handling.
3. Path Traversal & Permissions:
   - Target path in read-only directory.
   - Target path pointing to an existing directory.
   - Target path pointing to an invalid filesystem path.
   - Path traversal targeting the operator's protected DNA file.
   - Verifies CLI exits 1 with clean error and zero leaked stack traces.
   - Verifies Python API raises clear standard exceptions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Any
import pytest

from auto_reply_route.cli import main
from auto_reply_route.dna import (
    MAX_RULES_PER_SECTION,
    MAX_TOTAL_BUDGET_CHARS,
    OperatorDNABootstrapper,
    ensure_operator_dna,
    ingest_agents_principles,
    mine_transcript_examples,
    parse_agents_markdown,
    personal_dna_path,
    render_operator_dna_matrix,
)


# ============================================================================
# 1. Security & ReDoS / Token Bloat Attack Tests
# ============================================================================

class TestReDoSTokenBloatAndStress:
    """Tests resilience against ReDoS, token bloat, and massive inputs."""

    def test_50k_lines_deeply_nested_bullets_performance_and_budget(self) -> None:
        """50,000-line AGENTS.md with nested bullets and repetitive triggers finishes < 100ms
        and strictly honors the token budget (<3,000 chars, <=10 rules per section).
        """
        triggers = [
            "- **Simplicity Above All:** Everything facing users must be completely intuitive {i}.",
            "- **Never expose system mechanics:** Hide internal database queries and locks {i}.",
            "- **Anti-Tower-of-Babel Invariant:** Prefer a direct 20-line solution over bloat {i}.",
            "- **Executive Founder Sanity Check:** What is the least complicated way to build {i}?",
            "## Header Section Rule {i}",
        ]

        lines: list[str] = []
        for i in range(50000):
            indent = "  " * (i % 16)  # Deeply nested up to 16 indentation levels
            trigger_tmpl = triggers[i % len(triggers)]
            lines.append(f"{indent}{trigger_tmpl.format(i=i)}")

        content = "\n".join(lines)

        t0 = time.perf_counter()
        parsed = parse_agents_markdown(content)
        duration_ms = (time.perf_counter() - t0) * 1000

        # Empirical Performance Verification: strictly < 100ms
        assert duration_ms < 100.0, f"Parsing 50,000 lines took {duration_ms:.2f}ms (exceeds 100ms threshold)"

        # Token Budget: <= 10 rules per section
        assert len(parsed["simplicity_laws"]) <= MAX_RULES_PER_SECTION
        assert len(parsed["anti_patterns"]) <= MAX_RULES_PER_SECTION
        assert len(parsed["anti_tower_of_babel"]) <= MAX_RULES_PER_SECTION
        assert len(parsed["executive_steering"]) <= MAX_RULES_PER_SECTION
        assert len(parsed["core_rules"]) <= MAX_RULES_PER_SECTION

        # Token Budget: total character count strictly < 3,000 chars
        total_chars = (
            sum(len(x) for x in parsed["simplicity_laws"])
            + sum(len(x) for x in parsed["anti_patterns"])
            + sum(len(x) for x in parsed["anti_tower_of_babel"])
            + sum(len(x) for x in parsed["executive_steering"])
            + (len(parsed["living_room_test"]) if parsed.get("living_room_test") else 0)
        )
        assert total_chars < 3000, f"Extracted text totaled {total_chars} chars (exceeds 3,000 char budget)"

    def test_50k_lines_worst_case_triggers_at_tail(self) -> None:
        """Forces full linear scan by placing triggers only in the last 10 lines of 50,000 lines.
        Must still finish < 100ms.
        """
        lines = [f"  - Plain non-trigger conversational statement number {i}." for i in range(49990)]
        lines.extend([
            "- **Simplicity Above All:** Clear and simple.",
            "- **Never expose system mechanics:** Don't leak internals.",
            "- **Anti-Tower-of-Babel Invariant:** Direct 20-line solution.",
            "- **Executive Founder Sanity Check:** What is the least complicated way?",
            "- The Living-Room Test: Ask your neighbor over a cup of coffee.",
        ])
        content = "\n".join(lines)

        t0 = time.perf_counter()
        parsed = parse_agents_markdown(content)
        duration_ms = (time.perf_counter() - t0) * 1000

        assert duration_ms < 100.0, f"Scanning 50,000 lines to tail took {duration_ms:.2f}ms (exceeds 100ms)"
        assert len(parsed["simplicity_laws"]) >= 1
        assert len(parsed["anti_patterns"]) >= 1
        assert len(parsed["anti_tower_of_babel"]) >= 1
        assert parsed["living_room_test"] is not None

    def test_adversarial_mega_line_length_bounds(self) -> None:
        """Protects against memory bloat if a single bullet line is 100,000 characters long."""
        mega_line = "- **Simplicity Above All:** " + ("A" * 100000)
        content = f"{mega_line}\n- Regular rule\n"

        parsed = parse_agents_markdown(content)
        assert len(parsed["simplicity_laws"]) == 1
        extracted = parsed["simplicity_laws"][0]
        # Must be bounded to prevent blowing up the token budget
        assert len(extracted) <= 300
        assert extracted.endswith("...")

    def test_repetitive_regex_pattern_no_catastrophic_backtracking(self) -> None:
        """Verifies regexes do not suffer from catastrophic backtracking on pathological inputs."""
        pathological = "- The Living-Room Test:" + ("*" * 500) + ("   " * 500) + "Coffee test."
        t0 = time.perf_counter()
        parsed = parse_agents_markdown(pathological)
        duration_ms = (time.perf_counter() - t0) * 1000

        assert duration_ms < 20.0
        assert parsed["living_room_test"] is not None


# ============================================================================
# 2. Non-UTF8 & Malformed Data Tests
# ============================================================================

class TestNonUTF8AndMalformedData:
    """Tests handling of invalid byte sequences, corrupt files, and malformed data."""

    def test_corrupt_non_utf8_agents_markdown(self, tmp_path: Path) -> None:
        """Corrupt invalid UTF-8 bytes in AGENTS.md are gracefully replaced without crashing,
        allowing valid markdown rules to be extracted.
        """
        agents_file = tmp_path / "AGENTS.md"
        # Mixed payload: valid text + invalid raw byte sequence (\xff\xfe\xfa\x80) + valid rule
        payload = (
            b"# Corrupted AGENTS.md\n"
            b"\xff\xfe\xfa\x80\xc0\xc1\n"
            b"- **Simplicity Above All:** This rule is valid despite corrupt bytes above.\n"
            b"- The Living-Room Test: Tell your neighbor over coffee.\n"
        )
        agents_file.write_bytes(payload)

        # Ingestion must not raise UnicodeDecodeError
        principles = ingest_agents_principles(workspace_root=tmp_path)

        assert any("Simplicity Above All" in r for r in principles.simplicity_laws)
        assert principles.living_room_test == "Tell your neighbor over coffee."

    def test_completely_binary_junk_agents_md(self, tmp_path: Path) -> None:
        """Completely random non-text binary file in AGENTS.md falls back cleanly to defaults."""
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_bytes(os.urandom(8192))

        principles = ingest_agents_principles(workspace_root=tmp_path)
        assert len(principles.simplicity_laws) >= 1
        assert principles.operator_name != ""

    def test_corrupt_non_utf8_session_transcripts(self, tmp_path: Path) -> None:
        """Corrupt non-UTF8 bytes and invalid JSON lines in transcript.jsonl do not crash mining."""
        brain_dir = tmp_path / "brain"
        sess_dir = brain_dir / "sess-corrupt" / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True)

        transcript_file = sess_dir / "transcript.jsonl"
        # Line 1: corrupt raw binary bytes
        # Line 2: malformed JSON
        # Line 3: valid JSON with corrupt bytes in content
        # Line 4: valid genuine prompt
        payload = (
            b"\x80\x81\xff\xfe\n"
            b"{not valid json\n"
            b'{"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Build \xff\xfe app</USER_REQUEST>"}\n'
            b'{"source": "USER_EXPLICIT", "content": "<USER_REQUEST>Run the automated tests and verify edge cases</USER_REQUEST>"}\n'
        )
        transcript_file.write_bytes(payload)

        # Mining must run cleanly without throwing exceptions
        examples = mine_transcript_examples(brain_dir=brain_dir, max_examples=3)
        assert isinstance(examples, list)
        if examples:
            assert all(isinstance(ex.get("prompt"), str) for ex in examples)

    def test_parse_agents_markdown_null_bytes(self) -> None:
        """Null bytes inside markdown content do not crash parser."""
        content = "## Rules\x00\n- **Simplicity Above All:**\x00 Keep simple\x00.\n"
        parsed = parse_agents_markdown(content)
        assert len(parsed["simplicity_laws"]) >= 1


# ============================================================================
# 3. Path Traversal & Permissions Tests
# ============================================================================

class TestPathTraversalAndPermissions:
    """Tests security boundaries, read-only permissions, and path traversal protection."""

    def test_read_only_target_directory_cli_graceful_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Target path in a read-only directory fails gracefully: exits code 1, clean message, no stack trace."""
        ro_dir = tmp_path / "read_only_dir"
        ro_dir.mkdir()
        # Mark read-only
        ro_dir.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

        target_file = ro_dir / "operator_dna.md"

        try:
            exit_code = main(["init-dna", "--output", str(target_file), "--force"])
            assert exit_code == 1

            captured = capsys.readouterr()
            # Clean error on stderr
            assert "Failed to bootstrap Operator DNA" in captured.err
            assert "Permission denied" in captured.err
            # Stack trace invariants: no Python traceback leaked
            assert "Traceback (most recent call last)" not in captured.err
            assert "Traceback (most recent call last)" not in captured.out
        finally:
            # Restore permissions for clean cleanup
            ro_dir.chmod(stat.S_IRWXU)

    def test_read_only_target_python_api_raises_clear_exception(self, tmp_path: Path) -> None:
        """Python API raises clear PermissionError when target directory is read-only."""
        ro_dir = tmp_path / "ro_api_dir"
        ro_dir.mkdir()
        ro_dir.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

        target_file = ro_dir / "target.md"

        try:
            with pytest.raises(PermissionError):
                ensure_operator_dna(target_path=target_file, force=True)
        finally:
            ro_dir.chmod(stat.S_IRWXU)

    def test_target_is_existing_directory_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Passing an existing directory as --output fails cleanly with code 1 and no stack trace."""
        dir_target = tmp_path / "my_dir"
        dir_target.mkdir()

        exit_code = main(["init-dna", "--output", str(dir_target), "--force"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Failed to bootstrap Operator DNA" in captured.err
        assert "is a directory" in captured.err.lower()
        assert "Traceback (most recent call last)" not in captured.err

    def test_invalid_filesystem_path_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Invalid filesystem mount path fails cleanly with code 1 and no stack trace."""
        invalid_path = "/nonexistent_root_fs_abc123/sub/operator_dna.md"

        exit_code = main(["init-dna", "--output", invalid_path, "--force"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Failed to bootstrap Operator DNA" in captured.err
        assert "Traceback (most recent call last)" not in captured.err

    def test_path_traversal_targeting_personal_dna_is_neutralized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path traversal (e.g. ../../personal_dna.md) cannot overwrite the operator's protected DNA file."""
        mock_home = tmp_path / "home"
        config_dir = mock_home / ".gemini" / "config"
        config_dir.mkdir(parents=True)
        q_file = config_dir / "personal_dna.md"
        sacred_content = "# PERSONAL SACRED UNTOUCHED OPERATOR DNA\n"
        q_file.write_text(sacred_content, encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: mock_home)

        # Attempt path traversal from a 4-level nested subfolder targeting personal_dna.md
        nested_dir = tmp_path / "workspace" / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        traversal_target = nested_dir / ".." / ".." / ".." / ".." / "home" / ".gemini" / "config" / "personal_dna.md"

        res = ensure_operator_dna(target_path=traversal_target, force=True)

        # Sacred file is 100% untouched
        assert q_file.read_text(encoding="utf-8") == sacred_content
        # Destination redirected away from the operator's file
        assert res.name == "operator_dna.md"
        assert res.resolve() != q_file.resolve()
