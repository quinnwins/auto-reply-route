"""Comprehensive Tests for Inline Step Budget Prefix Configuration (1-12, Default 1)."""

import pytest
from auto_reply_route.miner import PromptNormalizer
from auto_reply_route.prompt_matrix import MatrixBeamRouter, PromptMatrixCatalog
from auto_reply_route.cli import cmd_build
import argparse


def test_extract_step_budget_bracketed():
    steps, clean = PromptNormalizer.extract_step_budget("[4] Build real-time canvas")
    assert steps == 4
    assert clean == "Build real-time canvas"

    steps, clean = PromptNormalizer.extract_step_budget("[12] Implement multi-region locking")
    assert steps == 12
    assert clean == "Implement multi-region locking"

    steps, clean = PromptNormalizer.extract_step_budget("[1] Fix typo in header")
    assert steps == 1
    assert clean == "Fix typo in header"


def test_extract_step_budget_colon_and_leading_integer():
    steps, clean = PromptNormalizer.extract_step_budget("4: Build real-time canvas")
    assert steps == 4
    assert clean == "Build real-time canvas"

    steps, clean = PromptNormalizer.extract_step_budget("6 steps: Build canvas")
    assert steps == 6
    assert clean == "Build canvas"

    steps, clean = PromptNormalizer.extract_step_budget("4 Build real-time canvas")
    assert steps == 4
    assert clean == "Build real-time canvas"


def test_extract_step_budget_default_is_one():
    steps, clean = PromptNormalizer.extract_step_budget("Build real-time collaborative canvas")
    assert steps == 1
    assert clean == "Build real-time collaborative canvas"


def test_extract_step_budget_technical_false_positive_guards():
    """Guarantees that 404, 2FA, 3D, 500, etc. are NOT misinterpreted as step budgets."""
    prompts = [
        "404 error page",
        "500 internal server error",
        "2FA auth flow",
        "3D canvas render",
        "4K video pipeline",
        "5G socket protocol",
        "100x benchmark",
        "128-bit cipher",
        # Retain previous variations as well
        "404 error page handler",
        "2FA authentication flow",
        "3D canvas rendering",
        "100x stress benchmark",
        "500 internal server error retry",
    ]
    for prompt in prompts:
        steps, clean = PromptNormalizer.extract_step_budget(prompt)
        assert steps == 1, f"Expected step budget 1 for {prompt!r}, got {steps}"
        assert clean == prompt, f"Expected clean prompt {prompt!r}, got {clean!r}"



def test_extract_step_budget_adversarial_boundaries():
    """Adversarially probe boundary conditions and verify safe fallback to 1."""
    # Boundary valid values (1-12)
    assert PromptNormalizer.extract_step_budget("[1]") == (1, "")
    assert PromptNormalizer.extract_step_budget("[12]") == (12, "")
    assert PromptNormalizer.extract_step_budget("12: foo") == (12, "foo")
    assert PromptNormalizer.extract_step_budget("1: bar") == (1, "bar")
    assert PromptNormalizer.extract_step_budget("12 foo") == (12, "foo")
    assert PromptNormalizer.extract_step_budget("1 foo") == (1, "foo")

    # Boundary invalid values (out of 1-12 range, negative, zero, large integers)
    assert PromptNormalizer.extract_step_budget("[0]") == (1, "[0]")
    assert PromptNormalizer.extract_step_budget("[13]") == (1, "[13]")
    assert PromptNormalizer.extract_step_budget("[-5]") == (1, "[-5]")
    assert PromptNormalizer.extract_step_budget("[999]") == (1, "[999]")

    # Extended boundary cases
    assert PromptNormalizer.extract_step_budget("0: foo") == (1, "0: foo")
    assert PromptNormalizer.extract_step_budget("13: foo") == (1, "13: foo")
    assert PromptNormalizer.extract_step_budget("0 foo") == (1, "0 foo")
    assert PromptNormalizer.extract_step_budget("13 foo") == (1, "13 foo")


def test_catalog_12_phases_supported():
    """Verify matrix catalog supports all 12 phases up to 2,016 nodes."""
    catalog = PromptMatrixCatalog()
    assert len(catalog.nodes) >= 2000
    router = MatrixBeamRouter(catalog)

    manifest_12 = router.map_route_from_matrix("Implement distributed consensus", num_steps=12)
    assert len(manifest_12.steps) == 12

    manifest_1 = router.map_route_from_matrix("Implement health check", num_steps=1)
    assert len(manifest_1.steps) == 1


def test_cli_build_respects_inline_prefix(tmp_path):
    output_file = tmp_path / "test_route.route.md"
    args = argparse.Namespace(
        prompt="[4] Build real-time canvas in frontend/canvas.tsx",
        steps=None,
        output=str(output_file),
        matrix=True,
        interactive=False,
        fast_review=False,
        max_subagents=3,
    )
    rc = cmd_build(args)
    assert rc == 0
    content = output_file.read_text()
    assert "4. Concurrency & Chaos Fuzzing" in content or "4. " in content
    # Count numbered steps
    import re
    numbered_steps = re.findall(r"^\d+\.\s+", content, re.MULTILINE)
    assert len(numbered_steps) == 4


def test_cli_build_defaults_to_one_step_when_no_prefix(tmp_path):
    output_file = tmp_path / "test_route_1.route.md"
    args = argparse.Namespace(
        prompt="Build real-time canvas in frontend/canvas.tsx",
        steps=None,
        output=str(output_file),
        matrix=True,
        interactive=False,
        fast_review=False,
        max_subagents=3,
    )
    rc = cmd_build(args)
    assert rc == 0
    content = output_file.read_text()
    import re
    numbered_steps = re.findall(r"^\d+\.\s+", content, re.MULTILINE)
    assert len(numbered_steps) == 1
