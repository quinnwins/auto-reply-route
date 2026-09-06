from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from auto_reply_route.models import BranchRank, RouteManifest, RouteStep, StepStatus
from auto_reply_route.parser import RouteParser


def test_parse_route_title_and_slug():
    content = """# Autonomous Code Generation Route

1. Scaffold the core package structure and configuration files.
"""
    manifest = RouteParser.parse_string(content)
    assert manifest.title == "Autonomous Code Generation Route"
    assert manifest.route_id == "autonomous_code_generation_route"
    assert manifest.state == StepStatus.PENDING
    assert len(manifest.steps) == 1


def test_parse_missing_header_fallback():
    content = """1. Build the data models with strict typing.
2. Build the state machine with checkpointing.
"""
    manifest = RouteParser.parse_string(content, route_id="custom_playbook")
    assert manifest.title == "Custom Playbook"
    assert manifest.route_id == "custom_playbook"
    assert len(manifest.steps) == 2


def test_parse_empty_content():
    manifest = RouteParser.parse_string("")
    assert manifest.title == "Untitled Route"
    assert manifest.route_id == "untitled_route"
    assert len(manifest.steps) == 0


def test_parse_step_title_extraction():
    content = """# Title Extraction Suite

1. Implement user authentication and session management in the auth module.
2. Database Setup: Configure connection pooling and migrations.
3. **Smoke Testing**: Execute quick test assertions on health endpoints.
4. Run tests.
"""
    manifest = RouteParser.parse_string(content)
    assert len(manifest.steps) == 4

    step0 = manifest.steps[0]
    words0 = step0.title.split()
    assert 3 <= len(words0) <= 6
    assert step0.title.startswith("Implement user authentication")

    step1 = manifest.steps[1]
    assert step1.title == "Database Setup"

    step2 = manifest.steps[2]
    assert step2.title == "Smoke Testing"

    step3 = manifest.steps[3]
    assert step3.title == "Run tests"


def test_parse_multiline_primary_prompts():
    content = """# Multiline Route

1. Build the main application engine.
   Ensure all functions have type signatures.
   Make sure to write regression tests for all edge cases.
"""
    manifest = RouteParser.parse_string(content)
    step = manifest.steps[0]
    assert "Build the main application engine." in step.primary_prompt
    assert "Ensure all functions have type signatures." in step.primary_prompt
    assert "Make sure to write regression tests for all edge cases." in step.primary_prompt


def test_parse_indented_alternatives_with_ranks():
    content = """# Alternatives Route

1. Build the feature according to standard architecture.
   - *Quick Spike*: Build a minimal working prototype in scratch.
   - *QA Defensive*: Add boundary checks and comprehensive assertions.
   - *Alternative*: Use SQLite instead of PostgreSQL.
"""
    manifest = RouteParser.parse_string(content)
    step = manifest.steps[0]
    assert len(step.alternatives) == 3

    alt1 = step.alternatives[0]
    assert alt1.rank == BranchRank.QA_DEFENSIVE  # rank 2
    assert alt1.label == "Quick Spike"
    assert alt1.prompt_template == "Build a minimal working prototype in scratch."

    alt2 = step.alternatives[1]
    assert alt2.rank == BranchRank.ALTERNATIVE_ARCH  # rank 3
    assert alt2.label == "QA Defensive"
    assert alt2.prompt_template == "Add boundary checks and comprehensive assertions."

    alt3 = step.alternatives[2]
    assert alt3.rank == BranchRank.FALLBACK  # rank 4
    assert alt3.label == "Alternative"
    assert alt3.prompt_template == "Use SQLite instead of PostgreSQL."


def test_parse_multiline_alternative_prompts():
    content = """# Complex Alternative Route

1. Core step implementation.
   - *Quick Spike*: First line of quick spike.
     Second line of quick spike with additional guidance.
     Third line with constraints.
   - Fallback: Simple fallback prompt.
"""
    manifest = RouteParser.parse_string(content)
    step = manifest.steps[0]
    assert len(step.alternatives) == 2

    alt1 = step.alternatives[0]
    assert "First line of quick spike." in alt1.prompt_template
    assert "Second line of quick spike with additional guidance." in alt1.prompt_template
    assert "Third line with constraints." in alt1.prompt_template

    alt2 = step.alternatives[1]
    assert alt2.prompt_template == "Simple fallback prompt."


def test_parse_assertions_and_manifest_ref():
    content = """# Assertions and Subroutes

1. Execute test suite and verify build.
   - Assert: pytest tests/test_parser.py passes
   - Assertion: git status is clean
   - Manifest: playbooks/sub_pipeline.route.md
   - *Quick Spike*: Run only unit tests
"""
    manifest = RouteParser.parse_string(content)
    step = manifest.steps[0]
    assert len(step.assertions) == 2
    assert step.assertions[0] == "pytest tests/test_parser.py passes"
    assert step.assertions[1] == "git status is clean"
    assert step.manifest_ref == "playbooks/sub_pipeline.route.md"
    assert len(step.alternatives) == 1
    assert step.alternatives[0].label == "Quick Spike"


def test_parse_empty_steps_and_whitespace_edge_cases():
    content = """# Route with edge cases

1. 
2. Valid step after empty step.
3. Third step.

"""
    manifest = RouteParser.parse_string(content)
    # The empty step should either be skipped or handled cleanly without crashing
    assert len(manifest.steps) >= 2
    assert manifest.steps[-1].title.startswith("Third step")


def test_parse_file_from_disk():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "deploy_pipeline.route.md"
        file_path.write_text(
            """# Automated Deploy Pipeline

1. Run unit test suite.
   - *Quick Spike*: Run smoke tests only.
2. Deploy artifacts to staging.
""",
            encoding="utf-8",
        )

        manifest = RouteParser.parse_file(str(file_path))
        assert manifest.route_id == "deploy_pipeline"
        assert manifest.title == "Automated Deploy Pipeline"
        assert len(manifest.steps) == 2
        assert manifest.steps[0].index == 0
        assert manifest.steps[1].index == 1
        assert len(manifest.steps[0].alternatives) == 1


def test_parse_canonical_playbook():
    playbook_path = Path(__file__).resolve().parent.parent / "playbooks" / "feature_build.route.md"
    assert playbook_path.is_file()

    manifest = RouteParser.parse_file(str(playbook_path))
    assert manifest.route_id == "feature_build"
    assert manifest.title == "Canonical Feature Build Route"
    assert len(manifest.steps) == 3

    step0 = manifest.steps[0]
    assert step0.index == 0
    assert len(step0.alternatives) == 3
    assert step0.alternatives[0].rank == BranchRank.QA_DEFENSIVE
    assert step0.alternatives[1].rank == BranchRank.ALTERNATIVE_ARCH
    assert step0.alternatives[2].rank == BranchRank.FALLBACK
    assert len(step0.assertions) == 1
    assert "auto_reply_route.models" in step0.assertions[0]
