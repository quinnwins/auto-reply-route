from __future__ import annotations

import io
from pathlib import Path
import tempfile
import pytest

from auto_reply_route.builder import (
    MilestoneBlueprint,
    PromptDecomposition,
    RouteBuilder,
    SemanticPromptAnalyzer,
    main,
)
from auto_reply_route.cli import RouteValidator
from auto_reply_route.miner import IntentStratum
from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.parser import RouteParser


# ============================================================================
# 1. Semantic Prompt Analysis Tests
# ============================================================================

class TestSemanticPromptAnalyzer:
    @pytest.fixture
    def analyzer(self) -> SemanticPromptAnalyzer:
        return SemanticPromptAnalyzer()

    def test_analyze_scaffold_prompt_with_explicit_file(self, analyzer: SemanticPromptAnalyzer):
        raw = "Scaffold JWT token authentication in auth.py with zero external dependencies"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.SCAFFOLD_BUILD
        assert decomp.target_file == "auth.py"
        assert decomp.target_module == "auth"
        assert decomp.test_file == "tests/test_auth.py"
        assert decomp.action_verb in ("scaffold", "implement", "build")
        assert "jwt token authentication" in decomp.subject.lower()

    def test_analyze_bugfix_prompt(self, analyzer: SemanticPromptAnalyzer):
        raw = "Fix race condition in websocket event handler in server.py"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.DEBUG_REPAIR
        assert decomp.is_bugfix is True
        assert decomp.target_file == "server.py"
        assert decomp.target_module == "server"
        assert decomp.test_file == "tests/test_server.py"
        assert decomp.action_verb == "fix"

    def test_analyze_arch_refactor_prompt(self, analyzer: SemanticPromptAnalyzer):
        raw = "Refactor database query engine to support distributed read replicas in db.py"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.ARCH_DESIGN
        assert decomp.is_architecture is True
        assert decomp.target_file == "db.py"
        assert decomp.target_module == "db"

    def test_analyze_qa_verify_prompt(self, analyzer: SemanticPromptAnalyzer):
        raw = "Run tests and audit benchmark performance in router.py"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.VERIFY_QA
        assert decomp.is_testing is True
        assert decomp.target_module == "router"

    def test_analyze_release_ops_prompt(self, analyzer: SemanticPromptAnalyzer):
        raw = "Bump package version to 2.1.0 and ship release tag"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.RELEASE_OPS
        assert decomp.is_ops is True

    def test_analyze_prompt_without_explicit_file(self, analyzer: SemanticPromptAnalyzer):
        raw = "Build a fast in-memory cache system"
        decomp = analyzer.analyze(raw)

        assert decomp.stratum == IntentStratum.SCAFFOLD_BUILD
        assert "cache" in decomp.target_module
        assert decomp.test_file.startswith("tests/test_")


# ============================================================================
# 2. RouteBuilder Trajectory Generation Tests
# ============================================================================

class TestRouteBuilderGeneration:
    @pytest.fixture
    def builder(self) -> RouteBuilder:
        return RouteBuilder()

    def test_build_route_default_5_steps(self, builder: RouteBuilder):
        prompt = "Scaffold user authentication and session management in auth.py"
        manifest = builder.build_route_from_prompt(prompt, num_steps=5, min_alternatives=3)

        assert isinstance(manifest, RouteManifest)
        assert len(manifest.steps) == 5
        assert manifest.current_step_idx == 0
        assert manifest.state == StepStatus.PENDING
        assert "auth" in manifest.route_id.lower()

        for idx, step in enumerate(manifest.steps):
            assert step.index == idx
            assert step.status == StepStatus.PENDING
            assert len(step.title) > 0
            assert len(step.primary_prompt) > 0
            # Check 3 alternatives per step with ranks 2, 3, 4
            assert len(step.alternatives) >= 3
            assert step.alternatives[0].rank == BranchRank.QA_DEFENSIVE
            assert step.alternatives[0].label == "QA Defensive"
            assert step.alternatives[1].rank == BranchRank.ALTERNATIVE_ARCH
            assert step.alternatives[1].label == "Quick Spike"
            assert step.alternatives[2].rank == BranchRank.FALLBACK
            assert step.alternatives[2].label == "Fallback"
            # Check assertions
            assert len(step.assertions) > 0
            for assertion in step.assertions:
                assert "passes" in assertion or "assert" in assertion.lower() or "python" in assertion

    def test_build_route_debug_repair_trajectory(self, builder: RouteBuilder):
        prompt = "Fix deadlock exception in connection pool in pool.py"
        manifest = builder.build_route_from_prompt(prompt, num_steps=5)

        assert manifest.metadata["stratum"] == IntentStratum.DEBUG_REPAIR.value
        step_titles = [s.title.lower() for s in manifest.steps]

        # Milestone 1: Defect Reproduction
        assert any("reproduction" in t or "defect" in t for t in step_titles)
        # Milestone 2: Root Cause Analysis
        assert any("root cause" in t or "analysis" in t for t in step_titles)
        # Milestone 3: Surgical Defect Fix
        assert any("fix" in t or "surgical" in t for t in step_titles)
        # Milestone 4: Regression Verification
        assert any("regression" in t or "verification" in t for t in step_titles)
        # Milestone 5: Clean Workspace / Commit
        assert any("clean" in t or "commit" in t or "release" in t for t in step_titles)

    def test_build_route_arch_design_trajectory(self, builder: RouteBuilder):
        prompt = "Refactor storage layer to decoupled repository pattern in repo.py"
        manifest = builder.build_route_from_prompt(prompt, num_steps=5)

        assert manifest.metadata["stratum"] == IntentStratum.ARCH_DESIGN.value
        step_titles = [s.title.lower() for s in manifest.steps]
        assert any("blueprint" in t or "specification" in t for t in step_titles)
        assert any("abstraction" in t or "modular" in t for t in step_titles)

    def test_build_route_elastic_scaling_fewer_steps(self, builder: RouteBuilder):
        prompt = "Build a simple parser in parser.py"
        # 1 step
        m1 = builder.build_route_from_prompt(prompt, num_steps=1)
        assert len(m1.steps) == 1

        # 2 steps
        m2 = builder.build_route_from_prompt(prompt, num_steps=2)
        assert len(m2.steps) == 2

        # 3 steps
        m3 = builder.build_route_from_prompt(prompt, num_steps=3)
        assert len(m3.steps) == 3

        # 4 steps
        m4 = builder.build_route_from_prompt(prompt, num_steps=4)
        assert len(m4.steps) == 4

    def test_build_route_elastic_scaling_more_steps(self, builder: RouteBuilder):
        prompt = "Build a distributed transaction coordinator in coord.py"
        # 7 steps: should inject concurrency and optimization sub-milestones
        m7 = builder.build_route_from_prompt(prompt, num_steps=7)
        assert len(m7.steps) == 7
        titles = [s.title for s in m7.steps]
        assert any("Concurrency" in t or "Performance" in t or "Adversarial" in t for t in titles)

    def test_build_route_min_alternatives_expansion(self, builder: RouteBuilder):
        prompt = "Scaffold API endpoint in api.py"
        # Request 5 alternatives
        manifest = builder.build_route_from_prompt(prompt, num_steps=3, min_alternatives=5)
        for step in manifest.steps:
            assert len(step.alternatives) == 5
            ranks = [a.rank for a in step.alternatives]
            assert ranks == [2, 3, 4, 5, 6]

    def test_build_route_empty_prompt_fallback(self, builder: RouteBuilder):
        manifest = builder.build_route_from_prompt("", num_steps=3)
        assert len(manifest.steps) == 3
        assert manifest.title != ""

    def test_build_route_classmethod_access(self):
        # Can be invoked directly on the class
        manifest = RouteBuilder.build_route_from_prompt("Implement feature in core.py", num_steps=3)
        assert len(manifest.steps) == 3


# ============================================================================
# 3. Export to Playbook (.route.md) and Roundtrip Tests
# ============================================================================

class TestPlaybookExportAndRoundtrip:
    @pytest.fixture
    def builder(self) -> RouteBuilder:
        return RouteBuilder()

    def test_export_to_playbook_string_format(self, builder: RouteBuilder):
        manifest = builder.build_route_from_prompt("Scaffold user auth in auth.py", num_steps=3)
        md_text = RouteBuilder.export_to_playbook(manifest)

        assert md_text.startswith(f"# {manifest.title}")
        assert "1. " in md_text
        assert "2. " in md_text
        assert "3. " in md_text
        assert "- *QA Defensive*:" in md_text
        assert "- *Quick Spike*:" in md_text
        assert "- *Fallback*:" in md_text
        assert "- Assert:" in md_text

    def test_exported_playbook_passes_route_validator(self, builder: RouteBuilder):
        manifest = builder.build_route_from_prompt(
            "Fix race condition in background queue worker.py",
            num_steps=5,
            min_alternatives=3,
        )
        md_text = RouteBuilder.export_to_playbook(manifest)

        # Validate with existing RouteValidator
        val_result = RouteValidator.validate_content(md_text)
        assert val_result.is_valid is True, f"Validation errors: {val_result.errors}"
        assert len(val_result.errors) == 0
        assert len(val_result.warnings) == 0

    def test_exported_playbook_roundtrip_with_route_parser(self, builder: RouteBuilder):
        original = builder.build_route_from_prompt(
            "Implement streaming tokenizer in tokenizer.py",
            num_steps=4,
            min_alternatives=3,
        )
        md_text = RouteBuilder.export_to_playbook(original)

        # Parse back using RouteParser
        reconstructed = RouteParser.parse_string(md_text)

        assert reconstructed.title == original.title
        assert len(reconstructed.steps) == len(original.steps)

        for orig_step, parsed_step in zip(original.steps, reconstructed.steps):
            assert parsed_step.index == orig_step.index
            # Alternatives count and ranks preserved
            assert len(parsed_step.alternatives) == len(orig_step.alternatives)
            for orig_alt, parsed_alt in zip(orig_step.alternatives, parsed_step.alternatives):
                assert parsed_alt.rank == orig_alt.rank
                assert parsed_alt.label == orig_alt.label
                assert orig_alt.prompt_template in parsed_alt.prompt_template
            # Assertions preserved
            assert len(parsed_step.assertions) == len(orig_step.assertions)

    def test_export_to_file(self, builder: RouteBuilder):
        manifest = builder.build_route_from_prompt("Build CLI commands in cli.py", num_steps=2)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "sub" / "my_feature.route.md"
            returned_text = RouteBuilder.export_to_playbook(manifest, filepath=str(out_file))

            assert out_file.is_file()
            file_content = out_file.read_text(encoding="utf-8")
            assert file_content == returned_text


# ============================================================================
# 4. Interactive CLI Constructor Tests
# ============================================================================

class TestInteractiveBuild:
    @pytest.fixture
    def builder(self) -> RouteBuilder:
        return RouteBuilder()

    def test_interactive_build_accept_all_primary(self, builder: RouteBuilder):
        inputs = ["", "", ""]  # 3 enters to accept primary for 3 steps
        input_iter = iter(inputs)

        manifest = builder.interactive_build(
            "Build database models in models.py",
            num_steps=3,
            input_fn=lambda prompt: next(input_iter),
            print_fn=lambda *args, **kwargs: None,
        )

        assert len(manifest.steps) == 3
        # Primary prompts retained
        assert "domain data models" in manifest.steps[0].primary_prompt.lower()

    def test_interactive_build_swap_alternative_2(self, builder: RouteBuilder):
        # Step 1: swap in 2 (QA Defensive)
        # Step 2: accept primary
        inputs = ["2", ""]
        input_iter = iter(inputs)

        manifest = builder.interactive_build(
            "Build database models in models.py",
            num_steps=2,
            input_fn=lambda prompt: next(input_iter),
            print_fn=lambda *args, **kwargs: None,
        )

        assert len(manifest.steps) == 2
        # Step 1 primary prompt is now the QA Defensive template
        assert "boundary validation" in manifest.steps[0].primary_prompt.lower()
        # Original primary prompt became swapped alternative
        assert any("swapped" in a.label.lower() for a in manifest.steps[0].alternatives)

    def test_interactive_build_customize_prompt(self, builder: RouteBuilder):
        # Step 1: 'c', then custom text
        # Step 2: accept primary
        inputs = ["c", "My custom hand-crafted primary prompt for step 1", ""]
        input_iter = iter(inputs)

        manifest = builder.interactive_build(
            "Build cache in cache.py",
            num_steps=2,
            input_fn=lambda prompt: next(input_iter),
            print_fn=lambda *args, **kwargs: None,
        )

        assert manifest.steps[0].primary_prompt == "My custom hand-crafted primary prompt for step 1"

    def test_interactive_build_finish_early(self, builder: RouteBuilder):
        # Step 1: accept
        # Step 2: 's' (stop early)
        inputs = ["", "s"]
        input_iter = iter(inputs)

        manifest = builder.interactive_build(
            "Build feature in feature.py",
            num_steps=5,
            input_fn=lambda prompt: next(input_iter),
            print_fn=lambda *args, **kwargs: None,
        )

        assert len(manifest.steps) == 2

    def test_interactive_build_eof_handling(self, builder: RouteBuilder):
        def raising_input(prompt: str):
            raise EOFError()

        manifest = builder.interactive_build(
            "Build feature in feature.py",
            num_steps=3,
            input_fn=raising_input,
            print_fn=lambda *args, **kwargs: None,
        )

        # Handled gracefully, returns initial step
        assert len(manifest.steps) >= 1


# ============================================================================
# 5. CLI Entry Point Tests
# ============================================================================

class TestBuilderCLI:
    def test_cli_main_stdout(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
        ret = main(["Scaffold JWT authentication in auth.py", "--steps", "3"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "# " in captured.out
        assert "1. " in captured.out
        assert "2. " in captured.out
        assert "3. " in captured.out

    def test_cli_main_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "output.route.md"
            ret = main([
                "Fix buffer overflow in parser.py",
                "--steps", "2",
                "--output", str(out_file),
            ])
            assert ret == 0
            assert out_file.is_file()
            content = out_file.read_text(encoding="utf-8")
            assert "# " in content
            assert "- *QA Defensive*:" in content
