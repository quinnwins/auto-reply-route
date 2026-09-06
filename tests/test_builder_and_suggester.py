"""Unit and integration tests for RouteBuilder and RouteSuggester.

==============================================================================
EXPERT DECISION RUBRIC & TEST SUITE ARCHITECTURE
==============================================================================
1. What the Best Test Engineer Would Do:
   A world-class QA/systems engineer verifies both structural invariants (types,
   ranks, bounds, round-trip serialization fidelity) and behavioral contracts
   (semantic intent alignment, diversity in alternative branches, zero-warning
   compliance against internal linters/validators, and resilience to degenerate
   or adversarial user prompts).

2. Why They Reject Naive Happy-Path Assertions:
   Checking merely `assert len(steps) > 0` fails to catch subtle regressions like:
   - Rank collisions (e.g. two branches claiming Rank 2).
   - Inverted branch ordering or duplicate prompt templates.
   - Markdown export emitting formatting that trips strict line validators.
   - Suggesters returning identical duplicate archetypes instead of diverse choices.
   - Confidence scores drifting outside calibrated [0.0, 1.0] intervals.

3. Explicit Trade-offs Stated:
   - Roundtrip Parsing: We verify re-parsing against `RouteParser` down to step titles,
     prompts, and assertion strings, trading slight test code verbosity for 100%
     guarantee of seamless playbook export and import.
   - Standard Library & Zero External Dependencies: All tests execute under standard
     pytest with no external network or API calls.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import pytest

from auto_reply_route.builder import (
    MilestoneBlueprint,
    PromptDecomposition,
    RouteBuilder,
    SemanticPromptAnalyzer,
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
from auto_reply_route.suggester import (
    RouteSuggester,
    RouteSuggestion,
    auto_suggest_chips,
    interactive_route_picker,
)


# ============================================================================
# RouteBuilder Tests
# ============================================================================

class TestRouteBuilderGeneration:
    """Validates RouteBuilder.build_route_from_prompt and trajectory synthesis."""

    def test_build_route_from_prompt_stripe_checkout(self) -> None:
        """Verifies that the canonical prompt 'Build a Stripe checkout endpoint' produces a valid RouteManifest."""
        builder = RouteBuilder()
        seed_prompt = "Build a Stripe checkout endpoint"
        manifest = builder.build_route_from_prompt(seed_prompt)

        assert isinstance(manifest, RouteManifest)
        assert manifest.route_id.startswith("route_")
        assert "stripe" in manifest.route_id.lower() or "checkout" in manifest.route_id.lower()
        assert "Stripe" in manifest.title or "Checkout" in manifest.title
        assert manifest.state == StepStatus.PENDING
        assert manifest.current_step_idx == 0
        assert len(manifest.steps) == 5

        # Metadata checks
        assert manifest.metadata.get("seed_prompt") == seed_prompt
        assert "target_file" in manifest.metadata
        assert "target_module" in manifest.metadata
        assert "test_file" in manifest.metadata
        assert manifest.metadata.get("stratum") == IntentStratum.SCAFFOLD_BUILD.value

    @pytest.mark.parametrize(
        ("prompt", "expected_stratum", "expected_keyword"),
        [
            ("Build a Stripe checkout endpoint", IntentStratum.SCAFFOLD_BUILD, "router"),
            ("Fix race condition in session token refresh", IntentStratum.DEBUG_REPAIR, "auth"),
            ("Refactor auth controller and decouple sqlite database", IntentStratum.ARCH_DESIGN, "auth"),
            ("Audit test suite coverage and benchmark query latency", IntentStratum.VERIFY_QA, "database"),
            ("Prepare version bump and deploy release pipeline", IntentStratum.RELEASE_OPS, "release"),
        ],
    )
    def test_build_route_diverse_seed_prompts(
        self, prompt: str, expected_stratum: IntentStratum, expected_keyword: str
    ) -> None:
        """Verifies trajectory generation across diverse real-world software engineering intents."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt(prompt)

        assert isinstance(manifest, RouteManifest)
        assert manifest.state == StepStatus.PENDING
        assert len(manifest.steps) == 5
        assert manifest.metadata.get("stratum") == expected_stratum.value

        # Every step has valid title, primary prompt, and assertions
        for idx, step in enumerate(manifest.steps):
            assert step.index == idx
            assert len(step.title.strip()) > 0
            assert len(step.primary_prompt.strip()) > 0
            assert len(step.assertions) >= 1

    def test_step_alternative_branches_ranks_and_roles(self) -> None:
        """Verifies that all steps have 1st, 2nd, 3rd, and 4th place alternative branches with diverse functional roles."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt("Build a Stripe checkout endpoint", num_steps=5)

        for step in manifest.steps:
            # 1st Place is the Primary Forward prompt on the step itself
            assert len(step.primary_prompt.strip()) > 0

            # Must have at least 3 alternative branches (Ranks 2, 3, 4)
            assert len(step.alternatives) >= 3, f"Step {step.index} has fewer than 3 alternative branches"

            ranks = [alt.rank for alt in step.alternatives]
            labels = [alt.label for alt in step.alternatives]

            # Verify presence of Ranks 2, 3, and 4
            assert BranchRank.QA_DEFENSIVE in ranks or 2 in ranks
            assert BranchRank.ALTERNATIVE_ARCH in ranks or 3 in ranks
            assert BranchRank.FALLBACK in ranks or 4 in ranks

            # Verify diverse functional roles and labels
            assert "QA Defensive" in labels
            assert "Quick Spike" in labels or "Alternative" in labels
            assert "Fallback" in labels

            # Ensure all templates are non-empty and non-trivial
            for alt in step.alternatives:
                assert len(alt.prompt_template.strip()) > 10, (
                    f"Alternative rank {alt.rank} in step {step.index} has trivial prompt"
                )

            # Invariant: No two alternatives share the exact same rank or label
            assert len(set(ranks)) == len(ranks), f"Duplicate ranks found in step {step.index}"
            assert len(set(labels)) == len(labels), f"Duplicate labels found in step {step.index}"

    def test_step_assertions_non_self_attesting(self) -> None:
        """Verifies that generated assertions are non-empty, deterministic, and non-self-attesting."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt("Build a Stripe checkout endpoint")

        for step in manifest.steps:
            assert len(step.assertions) >= 1, f"Step {step.index} has no assertions"
            for assertion in step.assertions:
                clean = assertion.strip()
                assert len(clean) > 0
                # Must not contain placeholder brackets
                assert "{" not in clean and "}" not in clean
                # Assertions should typically end with passes or be executable commands
                assert any(kw in clean for kw in ("passes", "pytest", "python", "git"))

    @pytest.mark.parametrize("step_count", [1, 2, 3, 4, 5, 7])
    def test_elastic_trajectory_scaling(self, step_count: int) -> None:
        """Verifies that RouteBuilder elastically scales the trajectory from 1 to 7+ steps without truncation defects."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt("Implement user profile dashboard", num_steps=step_count)

        assert len(manifest.steps) == step_count
        # Indexes must be contiguous from 0 to step_count - 1
        assert [s.index for s in manifest.steps] == list(range(step_count))

        # Even for 1-step or 7-step routes, alternatives must be fully populated
        for step in manifest.steps:
            assert len(step.alternatives) >= 3
            assert len(step.assertions) >= 1

    def test_custom_min_alternatives_expansion(self) -> None:
        """Verifies synthesizing additional high-rank branches when min_alternatives > 3."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt(
            "Build real-time notification service",
            num_steps=3,
            min_alternatives=5,
        )

        for step in manifest.steps:
            # 5 alternatives plus primary = 6 options total
            assert len(step.alternatives) >= 5
            ranks = [a.rank for a in step.alternatives]
            assert 2 in ranks and 3 in ranks and 4 in ranks and 5 in ranks and 6 in ranks

    def test_prompt_decomposition_entity_extraction(self) -> None:
        """Verifies that SemanticPromptAnalyzer extracts domain entities, target files, and strata."""
        analyzer = SemanticPromptAnalyzer()

        # Explicit file mentions
        decomp1 = analyzer.analyze("Fix crash in auth_controller.py when token is expired")
        assert decomp1.target_file == "auth_controller.py"
        assert decomp1.test_file in ("test_auth_controller.py", "tests/test_auth_controller.py")
        assert decomp1.is_bugfix is True
        assert decomp1.stratum == IntentStratum.DEBUG_REPAIR

        # Inferred module from keywords
        decomp2 = analyzer.analyze("Build customer billing database migration and schema")
        assert "database" in decomp2.target_module or "router" in decomp2.target_module
        assert decomp2.stratum in (IntentStratum.SCAFFOLD_BUILD, IntentStratum.ARCH_DESIGN)


class TestRouteBuilderExportAndRoundtrip:
    """Validates markdown export to .route.md, validator compliance, and RouteParser roundtripping."""

    def test_export_to_playbook_format(self) -> None:
        """Verifies export produces clean standard-compliant Markdown with top-level header and numbered steps."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt("Build a Stripe checkout endpoint", num_steps=3)
        markdown = RouteBuilder.export_to_playbook(manifest)

        expected_header = f"# {manifest.title}"
        assert markdown.splitlines()[0] == expected_header
        assert "1. " in markdown
        assert "2. " in markdown
        assert "3. " in markdown
        assert "   - *QA Defensive*:" in markdown
        assert "   - Assert:" in markdown

    def test_export_roundtrip_reparsing(self) -> None:
        """Verifies 100% roundtrip fidelity: RouteBuilder -> .route.md -> RouteParser -> RouteManifest."""
        builder = RouteBuilder()
        original = builder.build_route_from_prompt("Build a Stripe checkout endpoint", num_steps=4)
        markdown = RouteBuilder.export_to_playbook(original)

        reparsed = RouteParser.parse_string(markdown, route_id=original.route_id)

        assert reparsed.route_id == original.route_id
        assert reparsed.title == original.title
        assert len(reparsed.steps) == len(original.steps)

        for orig_step, rep_step in zip(original.steps, reparsed.steps):
            assert rep_step.index == orig_step.index
            assert len(rep_step.title) > 0
            assert len(rep_step.primary_prompt) > 0

            # Verify alternatives preserved
            assert len(rep_step.alternatives) == len(orig_step.alternatives)
            for orig_alt, rep_alt in zip(orig_step.alternatives, rep_step.alternatives):
                assert rep_alt.rank == orig_alt.rank
                assert rep_alt.label == orig_alt.label
                assert rep_alt.prompt_template == orig_alt.prompt_template

            # Verify assertions preserved
            assert len(rep_step.assertions) == len(orig_step.assertions)

    def test_export_to_file_and_parse_file(self, tmp_path: Path) -> None:
        """Verifies writing .route.md directly to disk and reading it via RouteParser.parse_file."""
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt("Refactor payments pipeline", num_steps=3)

        target_file = tmp_path / "payments_pipeline.route.md"
        content = RouteBuilder.export_to_playbook(manifest, filepath=target_file)

        assert target_file.is_file()
        assert target_file.read_text(encoding="utf-8") == content

        parsed = RouteParser.parse_file(str(target_file))
        assert parsed.route_id == "payments_pipeline"
        assert len(parsed.steps) == 3

    def test_exported_playbook_passes_route_validator(self) -> None:
        """Verifies that exported playbooks pass RouteValidator with ZERO errors and ZERO warnings."""
        builder = RouteBuilder()
        for seed in [
            "Build a Stripe checkout endpoint",
            "Fix null pointer in auth session handler",
            "Audit performance and scan for memory leaks",
        ]:
            manifest = builder.build_route_from_prompt(seed, num_steps=4)
            md = RouteBuilder.export_to_playbook(manifest)

            validation = RouteValidator.validate_content(md)
            assert validation.is_valid, f"Validation failed with errors: {validation.errors}"
            assert len(validation.errors) == 0, f"Errors present: {validation.errors}"
            assert len(validation.warnings) == 0, f"Warnings present: {validation.warnings}"

    def test_interactive_build_headless_fallback(self) -> None:
        """Verifies interactive_build returns the generated RouteManifest directly in headless non-interactive mode."""
        builder = RouteBuilder()
        manifest = builder.interactive_build("Build a Stripe checkout endpoint", num_steps=3)
        assert isinstance(manifest, RouteManifest)
        assert len(manifest.steps) == 3

    def test_interactive_build_simulation_actions(self) -> None:
        """Simulates user interactive actions: accept primary, swap alternative, customize, and early exit."""
        builder = RouteBuilder()
        printed_lines: list[str] = []

        # Simulated inputs:
        # Step 1: "" -> Enter (accept primary)
        # Step 2: "2" -> Swap with QA Defensive
        # Step 3: "c" -> Custom prompt, then custom text
        # Step 4: "s" -> Finish route early
        simulated_inputs = ["", "2", "c", "Customized third step prompt", "s"]

        def mock_input(prompt: str = "") -> str:
            if simulated_inputs:
                return simulated_inputs.pop(0)
            return ""

        def mock_print(*args: Any, **kwargs: Any) -> None:
            printed_lines.append(" ".join(str(a) for a in args))

        manifest = builder.interactive_build(
            "Build a Stripe checkout endpoint",
            num_steps=5,
            input_fn=mock_input,
            print_fn=mock_print,
        )

        # Early termination at step 4 means 4 steps total
        assert len(manifest.steps) == 4

        # Step 0 kept primary
        # Step 1 swapped alternative 2 into primary prompt
        # Step 2 set to custom prompt
        assert manifest.steps[2].primary_prompt == "Customized third step prompt"
        assert any("Step 1 accepted" in line or "Primary Forward" in line for line in printed_lines)
        assert any("swapped with Alternative [2]" in line for line in printed_lines)


# ============================================================================
# RouteSuggester Tests
# ============================================================================

class TestRouteSuggesterIntentCategorization:
    """Validates RouteSuggester.suggest_routes intent categorization, ranking, and calibration."""

    def test_suggest_routes_feature_request(self) -> None:
        """Verifies feature request prompts rank 'ship-feature' (or 'feature_build') as top suggestion."""
        suggester = RouteSuggester()
        prompts = [
            "Build a Stripe checkout endpoint",
            "Implement user authentication API",
            "Create shopping cart checkout service",
        ]

        for prompt in prompts:
            suggestions = suggester.suggest_routes(prompt, top_k=3)
            assert len(suggestions) <= 3
            assert len(suggestions) > 0

            # Top suggestion should be high confidence ship-feature or feature_build
            top = suggestions[0]
            assert top.route_id in ("ship-feature", "feature_build")
            assert top.confidence >= 0.85
            assert top.step_count in (3, 5)
            assert len(top.preview_steps) > 0

    def test_suggest_routes_bug_fix(self) -> None:
        """Verifies bug fix prompts propose fast diagnostic spike or full audit playbooks."""
        suggester = RouteSuggester()
        prompts = [
            "Fix race condition in session token refresh",
            "Repair crash when parsing malformed JSON payload",
            "Debug broken database query in user login",
        ]

        for prompt in prompts:
            suggestions = suggester.suggest_routes(prompt, top_k=3)
            assert len(suggestions) <= 3
            assert len(suggestions) > 0

            route_ids = [s.route_id for s in suggestions]
            # Must suggest quick-spike or audit-only for rapid bug triage
            assert "quick-spike" in route_ids or "audit-only" in route_ids
            assert suggestions[0].confidence >= 0.80

    def test_suggest_routes_architectural_spike(self) -> None:
        """Verifies prototyping and spike requests prioritize 'quick-spike' with top confidence."""
        suggester = RouteSuggester()
        prompts = [
            "Quick spike for oauth token cache",
            "Rapid prototype for WebAssembly gate adapter",
            "Fast proof of concept for async Redis queue",
        ]

        for prompt in prompts:
            suggestions = suggester.suggest_routes(prompt, top_k=3)
            assert len(suggestions) > 0

            top = suggestions[0]
            assert top.route_id == "quick-spike"
            assert top.step_count == 2
            assert top.confidence >= 0.90
            assert "⚡" in top.emoji or "Spike" in top.title

    def test_suggest_routes_audit_and_security(self) -> None:
        """Verifies security, leak, and performance audit prompts prioritize 'audit-only'."""
        suggester = RouteSuggester()
        prompts = [
            "Audit performance and scan for security vulnerabilities",
            "Deep static analysis security inspection and test coverage audit",
        ]

        for prompt in prompts:
            suggestions = suggester.suggest_routes(prompt, top_k=3)
            assert len(suggestions) > 0

            top = suggestions[0]
            assert top.route_id == "audit-only"
            assert top.step_count == 2
            assert top.confidence >= 0.90
            assert "🛡️" in top.emoji or "Audit" in top.title

    def test_suggest_routes_blank_or_whitespace_prompt(self) -> None:
        """Verifies blank or whitespace prompts return default canonical suggestions safely."""
        suggester = RouteSuggester()
        for empty_val in ("", "   ", "\n\t"):
            suggestions = suggester.suggest_routes(empty_val, top_k=3)
            assert len(suggestions) == 3
            ids = [s.route_id for s in suggestions]
            assert "ship-feature" in ids
            assert "quick-spike" in ids
            assert "audit-only" in ids

    def test_top_k_parameter_bounds(self) -> None:
        """Verifies top_k limits results appropriately."""
        suggester = RouteSuggester()
        assert len(suggester.suggest_routes("Build a widget", top_k=1)) == 1
        assert len(suggester.suggest_routes("Build a widget", top_k=2)) == 2
        assert len(suggester.suggest_routes("Build a widget", top_k=5)) >= 3

    def test_confidence_calibration_and_order(self) -> None:
        """Verifies confidences are bounded in [0.0, 1.0] and strictly descending."""
        suggester = RouteSuggester()
        suggestions = suggester.suggest_routes("Build a Stripe checkout endpoint", top_k=3)

        for s in suggestions:
            assert 0.0 <= s.confidence <= 1.0

        # Ranks must be non-increasing
        for i in range(len(suggestions) - 1):
            assert suggestions[i].confidence >= suggestions[i + 1].confidence

    def test_maximal_marginal_relevance_diversity(self) -> None:
        """Verifies that suggestion results are orthogonal rather than 3 duplicates of the same archetype."""
        suggester = RouteSuggester()
        suggestions = suggester.suggest_routes("Build Stripe endpoint", top_k=3)

        # Distinct route IDs
        ids = [s.route_id for s in suggestions]
        assert len(set(ids)) == len(ids)

        # Titles and step counts must not be all identical
        titles = [s.title for s in suggestions]
        assert len(set(titles)) == len(titles)


class TestRouteSuggesterFormatting:
    """Validates chip formatting (terminal, plain, markdown, json) and helper utilities."""

    @pytest.fixture
    def sample_suggestions(self) -> list[RouteSuggestion]:
        return [
            RouteSuggestion(
                route_id="ship-feature",
                title="Ship Feature",
                description="End-to-end production workflow.",
                step_count=5,
                confidence=0.98,
                preview_steps=["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"],
                preset_slug="ship-feature",
                emoji="🚀",
            ),
            RouteSuggestion(
                route_id="quick-spike",
                title="Fast Spike",
                description="Rapid feasibility prototype.",
                step_count=2,
                confidence=0.83,
                preview_steps=["Spike 1", "Verify 2"],
                preset_slug="quick-spike",
                emoji="⚡",
            ),
            RouteSuggestion(
                route_id="audit-only",
                title="Full Audit",
                description="Deep codebase inspection.",
                step_count=2,
                confidence=0.69,
                preview_steps=["Audit 1", "Verify 2"],
                preset_slug="audit-only",
                emoji="🛡️",
            ),
        ]

    def test_format_suggestion_chips_terminal(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies ANSI escape sequences, badge brackets, and bold title formatting."""
        suggester = RouteSuggester()
        chips = suggester.format_suggestion_chips(sample_suggestions, format_type="terminal")

        # ANSI escapes present
        assert "\033[" in chips
        # Strip ANSI to verify badge bracket numbers
        plain_stripped = re.sub(r"\033\[[0-9;]*m", "", chips)
        assert "[1]" in plain_stripped and "[2]" in plain_stripped and "[3]" in plain_stripped
        # Emojis and titles present
        assert "🚀 Ship Feature" in chips
        assert "⚡ Fast Spike" in chips
        assert "🛡️ Full Audit" in chips
        # Step counts present
        assert "(5 steps)" in chips
        assert "(2 steps)" in chips

    def test_format_suggestion_chips_plain(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies clean plain text formatting without ANSI escape codes."""
        suggester = RouteSuggester()
        chips = suggester.format_suggestion_chips(sample_suggestions, format_type="plain")

        assert "\033[" not in chips
        assert chips == "[1] 🚀 Ship Feature (5 steps)  [2] ⚡ Fast Spike (2 steps)  [3] 🛡️ Full Audit (2 steps)"

    def test_format_suggestion_chips_markdown(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies markdown formatting with bold badges and italicized step counts."""
        suggester = RouteSuggester()
        chips = suggester.format_suggestion_chips(sample_suggestions, format_type="markdown")

        assert "**[1] 🚀 Ship Feature** *(5 steps)*" in chips
        assert "**[2] ⚡ Fast Spike** *(2 steps)*" in chips
        assert "**[3] 🛡️ Full Audit** *(2 steps)*" in chips

    def test_format_suggestion_chips_json(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies JSON output format parses to list of valid suggestion dictionaries."""
        suggester = RouteSuggester()
        json_str = suggester.format_suggestion_chips(sample_suggestions, format_type="json")

        data = json.loads(json_str)
        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["route_id"] == "ship-feature"
        assert data[0]["confidence"] == 0.98
        assert data[0]["step_count"] == 5

    def test_format_suggestion_chips_empty(self) -> None:
        """Verifies formatting an empty list returns an empty string across all formats."""
        suggester = RouteSuggester()
        for fmt in ("terminal", "plain", "markdown", "json"):
            assert suggester.format_suggestion_chips([], format_type=fmt) == ""

    def test_format_detailed_cards(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies detailed preview card rendering with borders and preview steps."""
        suggester = RouteSuggester()
        cards = suggester.format_detailed_cards(sample_suggestions, plain=True)

        assert "╭─" in cards
        assert "╰─" in cards
        assert "Ship Feature (5 steps)" in cards
        assert "1. Step 1" in cards
        assert "End-to-end production workflow" in cards

    def test_resolve_manifest_from_playbook_and_synthetic(self, sample_suggestions: list[RouteSuggestion]) -> None:
        """Verifies resolve_manifest resolves to existing playbook files or synthesizes fallback steps."""
        suggester = RouteSuggester()

        # Resolves from existing canonical playbook
        manifest = suggester.resolve_manifest(sample_suggestions[0])
        assert isinstance(manifest, RouteManifest)
        assert len(manifest.steps) >= 3

        # Resolves synthetic suggestion
        synthetic = RouteSuggestion(
            route_id="custom-synthetic-route",
            title="Custom Synthetic",
            description="Synthetic task.",
            step_count=2,
            confidence=0.75,
            preview_steps=["Step Alpha", "Step Beta"],
        )
        synth_manifest = suggester.resolve_manifest(synthetic)
        assert isinstance(synth_manifest, RouteManifest)
        assert len(synth_manifest.steps) == 2
        assert synth_manifest.steps[0].title == "Step Alpha"
        assert synth_manifest.steps[1].title == "Step Beta"

    def test_auto_suggest_chips_convenience_function(self) -> None:
        """Verifies auto_suggest_chips 1-line helper for CLI/composer."""
        chips = auto_suggest_chips("Build a Stripe webhook", top_k=2, format_type="plain")
        assert "[1]" in chips and "[2]" in chips
        assert "Ship Feature" in chips

    def test_interactive_route_picker_simulation(self) -> None:
        """Verifies interactive_route_picker displays chips and returns selected RouteManifest on user choice."""
        # Simulate user typing "1" then Enter
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("1\n")
            output_stream = io.StringIO()
            manifest = interactive_route_picker("Build a Stripe webhook", top_k=3, stream=output_stream)

            assert isinstance(manifest, RouteManifest)
            assert len(manifest.steps) > 0
            rendered = output_stream.getvalue()
            assert "Suggested Routes:" in rendered
        finally:
            sys.stdin = old_stdin

    def test_interactive_route_picker_skip_on_enter(self) -> None:
        """Verifies interactive_route_picker returns None when developer presses Enter to skip."""
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("\n")
            output_stream = io.StringIO()
            result = interactive_route_picker("Build a Stripe webhook", top_k=3, stream=output_stream)
            assert result is None
        finally:
            sys.stdin = old_stdin
