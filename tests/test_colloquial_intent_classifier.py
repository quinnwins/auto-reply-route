"""Automated Test Suite for HumanIntentClassifier with Colloquial Non-Coder Prompts.

Verifies:
1. 10 colloquial feature requests without filenames or technical jargon classify as Tier 2 ('code_build').
2. bypass_route_generation is strictly False for all 10 requests.
3. Zero artificial filenames appear in classification outputs or generated route manifests.
4. Robustness against polite/conversational question variations ('Can we make...', 'Could we send...').
5. Contrastive discrimination against Tier 0 (strategic/advisory) and Tier 1 (UX craft audit).
"""

from __future__ import annotations

import re
import pytest

from auto_reply_route.classifier import (
    HumanIntentClassifier,
    IntentClassification,
    PromptIntentTier,
)
from auto_reply_route.prompt_matrix import MatrixBeamRouter


COLLOQUIAL_FEATURE_REQUESTS = [
    "add apple faceid passkeys for user logins",
    "make a stripe checkout page with invoice downloads",
    "set up dark mode toggle in the header",
    "fix the canvas freezing when zooming in",
    "connect google calendar sync for team events",
    "let users export their data to csv",
    "send an email confirmation when someone signs up",
    "add a search bar to the customer list",
    "hook up slack alerts for failed payments",
    "wire up discord notifications for new signups",
]

# Common patterns for artificial filenames that might mistakenly be hallucinated
ARTIFICIAL_FILENAME_PATTERNS = [
    r"\bsrc/feature\.py\b",
    r"\bfeature_core\.py\b",
    r"\bthe primary implementation file\b",
    r"\bsrc/[a-zA-Z0-9_-]+\.py\b",
    r"\btests/test_[a-zA-Z0-9_-]+\.py\b",
]

# Universal filename detector
GENERAL_FILENAME_RE = re.compile(
    r"\b[a-zA-Z0-9_/\\-]+\.(?:py|ts|js|jsx|tsx|html|css|json|sql)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("prompt", COLLOQUIAL_FEATURE_REQUESTS)
def test_colloquial_prompts_classify_as_tier2_code_build(prompt: str):
    """Verify each colloquial feature request classifies as Tier 2 code_build with bypass=False."""
    result: IntentClassification = HumanIntentClassifier.classify(prompt)

    assert result.tier == PromptIntentTier.CODE_BUILD, (
        f"Prompt '{prompt}' classified as {result.tier} instead of {PromptIntentTier.CODE_BUILD}"
    )
    assert result.bypass_route_generation is False, (
        f"Prompt '{prompt}' had bypass_route_generation=True (must be False for code_build)"
    )
    assert result.suggested_steps >= 1, (
        f"Prompt '{prompt}' suggested {result.suggested_steps} steps (expected >= 1)"
    )
    assert result.confidence >= 0.90, (
        f"Prompt '{prompt}' confidence {result.confidence} below 0.90 threshold"
    )


@pytest.mark.parametrize("prompt", COLLOQUIAL_FEATURE_REQUESTS)
def test_zero_artificial_filenames_in_classification(prompt: str):
    """Verify no artificial filenames exist in classification fields."""
    result: IntentClassification = HumanIntentClassifier.classify(prompt)

    for field_name, val in [
        ("extracted_subject", result.extracted_subject),
        ("reason", result.reason),
        ("cleaned_prompt", result.cleaned_prompt),
    ]:
        for pattern in ARTIFICIAL_FILENAME_PATTERNS:
            match = re.search(pattern, str(val))
            assert match is None, (
                f"Artificial filename pattern '{pattern}' matched in {field_name}: '{val}' for prompt '{prompt}'"
            )

        file_matches = GENERAL_FILENAME_RE.findall(str(val))
        assert not file_matches, (
            f"Unexpected filenames {file_matches} found in {field_name}: '{val}' for prompt '{prompt}'"
        )


@pytest.mark.parametrize("prompt", COLLOQUIAL_FEATURE_REQUESTS)
def test_zero_artificial_filenames_in_generated_route_manifest(prompt: str):
    """Verify route manifest generated from prompt contains zero artificial/hallucinated filenames."""
    router = MatrixBeamRouter()
    manifest = router.map_route_from_matrix(prompt, num_steps=6, alternatives_per_step=4)

    # Verify context entities
    entities = manifest.metadata.get("entities", {})
    assert entities.get("has_explicit_file") is False, (
        f"Expected has_explicit_file=False for colloquial prompt without files: {prompt}"
    )
    assert entities.get("target_file") == "", (
        f"Expected empty target_file, got '{entities.get('target_file')}' for: {prompt}"
    )

    # Inspect all step titles, prompts, assertions, and alternative branches
    for step in manifest.steps:
        # Check step title
        for pattern in ARTIFICIAL_FILENAME_PATTERNS:
            assert not re.search(pattern, step.title), (
                f"Artificial filename found in step title: '{step.title}'"
            )
            assert not re.search(pattern, step.primary_prompt), (
                f"Artificial filename found in primary prompt: '{step.primary_prompt}'"
            )
            for assertion in step.assertions:
                assert not re.search(pattern, assertion), (
                    f"Artificial filename found in assertion: '{assertion}'"
                )

        # Check general filename regex: no generated python/ts filenames should appear
        for text, loc in [
            (step.title, "title"),
            (step.primary_prompt, "primary_prompt"),
        ]:
            file_matches = GENERAL_FILENAME_RE.findall(text)
            assert not file_matches, (
                f"Unexpected filename {file_matches} in step {step.index} {loc}: '{text}'"
            )

        # In assertions, ensure fallback to universal checks rather than artificial py_compile
        for assertion in step.assertions:
            assert "py_compile" not in assertion, (
                f"Found file-specific py_compile in assertion: '{assertion}'"
            )

        # Check alternative branches
        for alt in step.alternatives:
            for pattern in ARTIFICIAL_FILENAME_PATTERNS:
                assert not re.search(pattern, alt.prompt_template), (
                    f"Artificial filename in alternative '{alt.label}': '{alt.prompt_template}'"
                )
            file_matches = GENERAL_FILENAME_RE.findall(alt.prompt_template)
            assert not file_matches, (
                f"Unexpected filename {file_matches} in alternative '{alt.label}': '{alt.prompt_template}'"
            )


def test_colloquial_question_variations():
    """Verify polite builder questions with action verbs still classify as code_build."""
    polite_prompts = [
        "Can we make a stripe checkout page with invoice downloads?",
        "Could we send an email confirmation when someone signs up?",
        "Can we let users export their data to csv?",
        "How can we add a search bar to the customer list?",
    ]
    for prompt in polite_prompts:
        result = HumanIntentClassifier.classify(prompt)
        assert result.tier == PromptIntentTier.CODE_BUILD, (
            f"Polite builder prompt '{prompt}' misclassified as {result.tier}"
        )
        assert result.bypass_route_generation is False


def test_tier_contrastive_discrimination():
    """Verify clear distinction against Tier 0 (advisory) and Tier 1 (UX craft)."""
    advisory_prompts = [
        "What features are we missing?",
        "What do you think about our pricing strategy?",
        "What kind of marketing approach should we take?",
    ]
    for p in advisory_prompts:
        res = HumanIntentClassifier.classify(p)
        assert res.tier == PromptIntentTier.DIRECT_ANSWER
        assert res.bypass_route_generation is True

    ux_audit_prompts = [
        "Audit the visual polish and micro-craft of this form",
        "Make this look cleaner and less robotic",
        "Hate this design and cluttered look",
    ]
    for p in ux_audit_prompts:
        res = HumanIntentClassifier.classify(p)
        assert res.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res.bypass_route_generation is False
        assert res.suggested_steps == 3
