from __future__ import annotations

import pytest

from auto_reply_route.grader import (
    PromptGradeReport,
    PromptGrader,
    format_grade_card,
    run_benchmark_suite,
    _score_to_letter,
)


class TestPromptGrader:
    """Unit tests verifying PromptGrader heuristic evaluation engine."""

    def test_score_to_letter_mapping(self) -> None:
        assert _score_to_letter(98) == "A+"
        assert _score_to_letter(94) == "A"
        assert _score_to_letter(91) == "A-"
        assert _score_to_letter(88) == "B+"
        assert _score_to_letter(84) == "B"
        assert _score_to_letter(81) == "B-"
        assert _score_to_letter(77) == "C+"
        assert _score_to_letter(72) == "C"
        assert _score_to_letter(65) == "D"
        assert _score_to_letter(50) == "F"

    def test_grade_ux_prompt(self) -> None:
        report = PromptGrader.grade("/q audit mobile checkout drawer for 44px tap targets and microcopy")
        assert report.domain == "ux"
        assert report.total_score >= 85.0
        assert report.letter_grade in ("A", "A+", "A-", "B+")
        assert report.pillars["domain_fit"].score == 25.0

    def test_grade_research_prompt(self) -> None:
        report = PromptGrader.grade("/q dental cavitation plaque removal device 5 steps")
        assert report.domain == "research"
        assert report.total_score >= 85.0
        assert report.pillars["domain_fit"].score == 25.0

    def test_grade_code_prompt(self) -> None:
        report = PromptGrader.grade("/q build Stripe billing checkout webhook router with 3 subagents and 5 turns")
        assert report.domain == "code"
        assert report.subagents == 3
        assert report.steps == 5
        assert len(report.prompts) == 5

    def test_format_grade_card(self) -> None:
        report = PromptGrader.grade("/q cache")
        card = format_grade_card(report)
        assert "PROMPT TRAJECTORY GRADE CARD" in card
        assert "Domain Stratification" in card
        assert "Anti-Tower-of-Babel" in card

    def test_run_benchmark_suite(self) -> None:
        reports = run_benchmark_suite()
        assert len(reports) == 8
        for r in reports:
            assert isinstance(r, PromptGradeReport)
            assert r.total_score > 60.0
            dict_rep = r.to_dict()
            assert "total_score" in dict_rep
            assert "pillars" in dict_rep
