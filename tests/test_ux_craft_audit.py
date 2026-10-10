"""Automated test script auditing HumanIntentClassifier against 10 raw UX and design critiques.

Evaluates whether design complaints, AI slop callouts, and UI ergonomics requests
correctly route to 'ux_craft_audit' (Tier 1) with 3 suggested steps.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from auto_reply_route.classifier import HumanIntentClassifier, PromptIntentTier


# The 10 raw design critiques from the prompt
AUDIT_PROMPTS: List[str] = [
    "I hate this ai slop design",
    "how can we improve the ux",
    "this screen looks terrible and amateur",
    "make this feel more human and less robotic",
    "fix this styling clutter on the dashboard",
    "the colors and typography look like generic ai slop",
    "clean up the ui and make it look professional",
    "why does this feel so clunky and ugly",
    "run a design critique on our landing page",
    "give this interface some visual polish",
]


def audit_all_critiques() -> List[Tuple[str, bool, PromptIntentTier, int, str]]:
    """Runs all 10 critiques through HumanIntentClassifier and returns structured results."""
    results = []
    for prompt in AUDIT_PROMPTS:
        classification = HumanIntentClassifier.classify(prompt)
        is_tier_match = classification.tier == PromptIntentTier.UX_CRAFT_AUDIT
        is_steps_match = classification.suggested_steps == 3
        passed = is_tier_match and is_steps_match
        results.append((prompt, passed, classification.tier, classification.suggested_steps, classification.reason))
    return results


def print_audit_report() -> None:
    """Formats and prints an exhaustive audit report."""
    results = audit_all_critiques()
    passed_count = sum(1 for _, passed, _, _, _ in results if passed)
    total_count = len(results)

    print("=" * 80)
    print("HUMAN INTENT CLASSIFIER - UX & ANTI-SLOP DESIGN CRITIQUE AUDIT REPORT")
    print("=" * 80)
    print(f"Target Tier: {PromptIntentTier.UX_CRAFT_AUDIT.value} (Tier 1)")
    print(f"Target Suggested Steps: 3")
    print(f"Total Test Cases: {total_count}")
    print(f"Passed: {passed_count}/{total_count} ({passed_count / total_count * 100:.1f}%)")
    print(f"Slipped Through / Misclassified: {total_count - passed_count}/{total_count}\n")

    for i, (prompt, passed, tier, steps, reason) in enumerate(results, 1):
        status_label = "PASS" if passed else "MISCLASSIFIED [FAIL]"
        print(f"[{i:02d}] Status: {status_label}")
        print(f"     Prompt:          \"{prompt}\"")
        print(f"     Actual Tier:     {tier.value}")
        print(f"     Suggested Steps: {steps}")
        print(f"     Reason:          {reason}")
        if not passed:
            print(f"     >>> REGRESSION / SLIP-THROUGH: Expected {PromptIntentTier.UX_CRAFT_AUDIT.value} (3 steps), got {tier.value} ({steps} steps)")
        print("-" * 80)


@pytest.mark.parametrize("prompt", AUDIT_PROMPTS)
def test_ux_critique_routing(prompt: str):
    """Parametrized pytest checking each critique routes to ux_craft_audit with 3 steps."""
    classification = HumanIntentClassifier.classify(prompt)
    assert classification.tier == PromptIntentTier.UX_CRAFT_AUDIT, (
        f"Prompt '{prompt}' misclassified as {classification.tier.value} "
        f"(expected {PromptIntentTier.UX_CRAFT_AUDIT.value}). Reason: {classification.reason}"
    )
    assert classification.suggested_steps == 3, (
        f"Prompt '{prompt}' suggested {classification.suggested_steps} steps (expected 3)"
    )


if __name__ == "__main__":
    print_audit_report()
