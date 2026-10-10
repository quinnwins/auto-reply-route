from __future__ import annotations

import json
from pathlib import Path
import pytest

from auto_reply_route.cli import main
from auto_reply_route.suggester import RouteSuggester, auto_suggest_chips


class TestCLISuggestCommand:
    """End-to-end tests for `agy-route suggest` CLI command and formatting options."""

    def test_suggest_cli_terminal_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Build a Stripe webhook"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Ship Feature" in captured.out
        assert "Fast Spike" in captured.out
        assert "[1]" in captured.out

    def test_suggest_cli_plain_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Refactor auth controller", "--format", "plain"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "\033[" not in captured.out
        assert "[1]" in captured.out
        assert "Ship Feature" in captured.out

    def test_suggest_cli_json_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Audit performance and query latency", "--format", "json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) >= 2
        assert data[0]["route_id"] == "audit-only"
        assert "confidence" in data[0]
        assert "preview_steps" in data[0]

    def test_suggest_cli_markdown_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Quick spike prototype", "--format", "markdown"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "**[1]" in captured.out
        assert "Fast Spike" in captured.out

    def test_suggest_cli_cards_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Build a Stripe webhook", "--cards"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "╭─" in captured.out
        assert "╰─" in captured.out or "╰" in captured.out
        assert "Ship Feature" in captured.out

    def test_suggest_cli_empty_seed_prompt(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[1]" in captured.out
        assert "Ship Feature" in captured.out

    def test_suggest_cli_top_k_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["suggest", "Build a Stripe webhook", "--top-k", "1", "--format", "plain"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[1]" in captured.out
        assert "[2]" not in captured.out

    def test_auto_suggest_chips_helper(self) -> None:
        chips = auto_suggest_chips("Build Stripe webhook", format_type="plain")
        assert "[1]" in chips
        assert "Ship Feature" in chips
