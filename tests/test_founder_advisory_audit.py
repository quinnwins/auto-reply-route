"""Automated test script auditing HumanIntentClassifier against real founder advisory questions.

Evaluates whether strategic, business, advisory, and GTM questions from non-technical founders
correctly route to 'direct_answer' (Tier 0) with bypass_route_generation=True and 0 steps.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, NamedTuple, Tuple

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from auto_reply_route.classifier import HumanIntentClassifier, IntentClassification, PromptIntentTier


# The 10 real founder questions from the user specification
FOUNDER_AUDIT_PROMPTS: List[str] = [
    "what feature are we missing here",
    "do you think this project is heading in the right direction",
    "what kind of go to market strategy should i have",
    "how should we price this for small businesses",
    "should we launch on product hunt next tuesday",
    "who are the main competitors in this space",
    "how does our architecture compare to supabase",
    "what are the biggest risks with this roadmap",
    "is this ready to show to angel investors",
    "what metrics should we track in week 1",
]

# Additional non-technical founder edge case questions probing polysemous action verbs and phrasing
FOUNDER_EDGE_CASE_PROMPTS: List[str] = [
    "how should we build our pricing model",
    "how can we write a compelling pitch deck",
    "should we test this with 5 beta users",
    "how do we fix our churn rate",
    "how should we deploy our marketing budget",
    "how do we connect with angel investors",
    "is our valuation realistic for pre-seed",
    "can we pitch this to angels yet",
    "what is our competitive moat against incumbents",
    "should we pivot to enterprise customers",
]


class AuditResult(NamedTuple):
    prompt: str
    passed: bool
    classification: IntentClassification
    failure_details: str = ""


def evaluate_prompt(prompt: str) -> AuditResult:
    """Evaluates a single prompt against the Tier 0 Direct Answer contract."""
    classification = HumanIntentClassifier.classify(prompt)
    is_tier_match = classification.tier == PromptIntentTier.DIRECT_ANSWER
    is_bypass_match = classification.bypass_route_generation is True
    is_steps_match = classification.suggested_steps == 0

    passed = is_tier_match and is_bypass_match and is_steps_match
    failure_details = ""
    if not passed:
        reasons = []
        if not is_tier_match:
            reasons.append(f"tier={classification.tier.value} (expected {PromptIntentTier.DIRECT_ANSWER.value})")
        if not is_bypass_match:
            reasons.append(f"bypass_route_generation={classification.bypass_route_generation} (expected True)")
        if not is_steps_match:
            reasons.append(f"suggested_steps={classification.suggested_steps} (expected 0)")
        failure_details = ", ".join(reasons)

    return AuditResult(
        prompt=prompt,
        passed=passed,
        classification=classification,
        failure_details=failure_details,
    )


def audit_prompts(prompts: List[str]) -> List[AuditResult]:
    """Runs a batch of prompts through HumanIntentClassifier and returns evaluation results."""
    return [evaluate_prompt(p) for p in prompts]


def print_audit_report() -> bool:
    """Formats and prints an exhaustive audit report for the 10 founder questions and edge cases."""
    results = audit_prompts(FOUNDER_AUDIT_PROMPTS)
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)

    print("=" * 88)
    print("HUMAN INTENT CLASSIFIER - NON-TECHNICAL FOUNDER ADVISORY AUDIT REPORT")
    print("=" * 88)
    print(f"Target Tier:                   {PromptIntentTier.DIRECT_ANSWER.value} (Tier 0)")
    print(f"Target Bypass Route Gen:       True")
    print(f"Target Suggested Steps:        0")
    print(f"Total Canonical Test Cases:    {total_count}")
    print(f"Passed:                        {passed_count}/{total_count} ({passed_count / total_count * 100:.1f}%)")
    print(f"Misclassified / Regressions:   {total_count - passed_count}/{total_count}\n")

    for i, res in enumerate(results, 1):
        status_label = "PASS" if res.passed else "FAIL [MISCLASSIFIED]"
        c = res.classification
        print(f"[{i:02d}] Status:         {status_label}")
        print(f"     Prompt:         \"{res.prompt}\"")
        print(f"     Actual Tier:    {c.tier.value}")
        print(f"     Bypass Gen:     {c.bypass_route_generation}")
        print(f"     Steps:          {c.suggested_steps}")
        print(f"     Confidence:     {c.confidence:.2f}")
        print(f"     Reason:         {c.reason}")
        if not res.passed:
            print(f"     >>> REGRESSION: {res.failure_details}")
        print("-" * 88)

    # Edge cases evaluation
    edge_results = audit_prompts(FOUNDER_EDGE_CASE_PROMPTS)
    edge_passed = sum(1 for r in edge_results if r.passed)
    edge_total = len(edge_results)

    print("\n" + "=" * 88)
    print("EXTENDED FOUNDER EDGE CASES (ACTION VERB AMBIGUITY & ADVISORY TOPICS)")
    print("=" * 88)
    print(f"Total Edge Cases:              {edge_total}")
    print(f"Passed:                        {edge_passed}/{edge_total} ({edge_passed / edge_total * 100:.1f}%)\n")

    for i, res in enumerate(edge_results, 1):
        status_label = "PASS" if res.passed else "FAIL [MISCLASSIFIED]"
        c = res.classification
        print(f"[E{i:02d}] Status:        {status_label}")
        print(f"      Prompt:        \"{res.prompt}\"")
        print(f"      Actual Tier:   {c.tier.value}")
        print(f"      Bypass Gen:    {c.bypass_route_generation}")
        print(f"      Steps:         {c.suggested_steps}")
        print(f"      Reason:        {c.reason}")
        if not res.passed:
            print(f"      >>> ISSUE:     {res.failure_details}")
        print("-" * 88)

    all_passed = (passed_count == total_count)
    return all_passed


# ---------------------------------------------------------------------------
# Pytest Test Cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", FOUNDER_AUDIT_PROMPTS)
def test_founder_questions_classify_as_direct_answer(prompt: str):
    """Parametrized test ensuring EVERY founder question classifies as direct_answer with bypass=True and 0 steps."""
    res = evaluate_prompt(prompt)
    assert res.passed, (
        f"Prompt '{prompt}' failed Tier 0 classification contract: {res.failure_details}. "
        f"Classification: {res.classification}"
    )


@pytest.mark.parametrize("prompt", FOUNDER_EDGE_CASE_PROMPTS)
def test_founder_edge_cases_classify_as_direct_answer(prompt: str):
    """Parametrized test checking common founder questions with action verbs also route to direct_answer."""
    res = evaluate_prompt(prompt)
    assert res.passed, (
        f"Edge-case prompt '{prompt}' failed Tier 0 classification contract: {res.failure_details}. "
        f"Classification: {res.classification}"
    )


if __name__ == "__main__":
    success = print_audit_report()
    sys.exit(0 if success else 1)
