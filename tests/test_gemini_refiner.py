"""Comprehensive Tests for Gemini Route Refiner with ZERO Network API Calls."""

import copy
import json
import pytest
from auto_reply_route.prompt_matrix import MatrixBeamRouter, PromptMatrixCatalog
from auto_reply_route.refiner import AgyCliBackend, GeminiRouteRefiner, MockGeminiBackend
from auto_reply_route.models import StepStatus


def assert_manifest_uncorrupted(original_manifest, result_manifest):
    """Deeply asserts that result_manifest steps and operational structure match original_manifest."""
    assert len(result_manifest.steps) == len(original_manifest.steps)
    for idx, (orig_step, res_step) in enumerate(zip(original_manifest.steps, result_manifest.steps)):
        assert res_step.index == orig_step.index, f"Step {idx} index mismatch"
        assert res_step.title == orig_step.title, f"Step {idx} title mismatch"
        assert res_step.primary_prompt == orig_step.primary_prompt, f"Step {idx} prompt mismatch"
        assert res_step.status == orig_step.status, f"Step {idx} status mismatch"
        assert res_step.retries == orig_step.retries, f"Step {idx} retries mismatch"
        assert res_step.max_retries == orig_step.max_retries, f"Step {idx} max_retries mismatch"
        assert res_step.assertions == orig_step.assertions, f"Step {idx} assertions mismatch"
        assert res_step.manifest_ref == orig_step.manifest_ref, f"Step {idx} manifest_ref mismatch"
        assert [a.to_dict() for a in res_step.alternatives] == [a.to_dict() for a in orig_step.alternatives], f"Step {idx} alternatives mismatch"
    assert result_manifest.route_id == original_manifest.route_id
    assert result_manifest.title == original_manifest.title
    assert result_manifest.current_step_idx == original_manifest.current_step_idx
    assert result_manifest.state == original_manifest.state
    for k, v in original_manifest.metadata.items():
        assert result_manifest.metadata.get(k) == v, f"Metadata key {k} was corrupted"


@pytest.fixture
def sample_manifest():
    catalog = PromptMatrixCatalog()
    router = MatrixBeamRouter(catalog)
    return router.map_route_from_matrix(
        seed_prompt="Build Discord bot for Solana validator alerts in validator_monitor.go",
        num_steps=6,
        max_subagents=4,
    )


def test_refiner_pass_verdict_leaves_manifest_intact(sample_manifest):
    """When Flash returns PASS, manifest steps are completely unaltered."""
    mock_backend = MockGeminiBackend(canned_response=json.dumps({"status": "PASS", "reason": "Perfect match"}))
    refiner = GeminiRouteRefiner(backend=mock_backend)

    orig_title_1 = sample_manifest.steps[0].title
    orig_prompt_1 = sample_manifest.steps[0].primary_prompt

    refined = refiner.refine_manifest("Build Discord bot", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "PASS_APPROVED"
    assert refined.steps[0].title == orig_title_1
    assert refined.steps[0].primary_prompt == orig_prompt_1
    assert len(refined.steps) == 6
    assert mock_backend.calls_count == 1


def test_refiner_surgical_patch_updates_target_step(sample_manifest):
    """When Flash returns PATCH, only the specified step is updated with domain-tailored content."""
    mock_backend = MockGeminiBackend()  # Default mock patches Solana/Discord
    refiner = GeminiRouteRefiner(backend=mock_backend)

    orig_step2_title = sample_manifest.steps[1].title

    refined = refiner.refine_manifest(
        "Build Discord bot for Solana validator alerts in validator_monitor.go",
        sample_manifest,
    )

    assert "PATCHED" in refined.metadata["refiner_verdict"]
    assert refined.metadata["refiner_reason"] != ""
    # Step 1 was surgically patched
    assert "Solana RPC" in refined.steps[0].title
    assert "Solana RPC block validator monitor" in refined.steps[0].primary_prompt
    # Step 2 remains completely untouched
    assert refined.steps[1].title == orig_step2_title
    assert len(refined.steps) == 6


def test_refiner_preserves_subagent_team_directive(sample_manifest):
    """Even if an LLM patch omits the subagent team sentence, refiner automatically enforces and appends it."""
    bad_patch_response = json.dumps({
        "status": "PATCH",
        "patches": [
            {
                "step_index": 1,
                "field": "primary_prompt",
                "replacement": "Write a pure Golang TCP socket receiver without any team instructions.",
            }
        ]
    })
    mock_backend = MockGeminiBackend(canned_response=bad_patch_response)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Golang TCP receiver", sample_manifest)

    # Invariant: Must still end with the subagent team directive!
    expected_directive = "Use as many subagents working as a team as you need (up to 4 subagents)."
    assert refined.steps[0].primary_prompt.endswith(expected_directive), (
        f"Team directive was lost during patch: {refined.steps[0].primary_prompt}"
    )


def test_refiner_respects_single_and_zero_subagent_budget():
    """Verify refiner formats single subagent directive and cleanly omits directive when max_subagents=0."""
    catalog = PromptMatrixCatalog()
    router = MatrixBeamRouter(catalog)

    patch_response = json.dumps({
        "status": "PATCH",
        "patches": [
            {
                "step_index": 1,
                "field": "primary_prompt",
                "replacement": "Write a pure Golang TCP socket receiver.",
            }
        ]
    })

    # Test max_subagents = 1
    manifest_1 = router.map_route_from_matrix("Build TCP receiver in receiver.go", num_steps=2, max_subagents=1)
    refiner_1 = GeminiRouteRefiner(backend=MockGeminiBackend(canned_response=patch_response))
    refined_1 = refiner_1.refine_manifest("Build TCP receiver", manifest_1)
    assert refined_1.steps[0].primary_prompt.endswith("Use 1 subagent if needed to isolate execution context.")
    assert "working as a team" not in refined_1.steps[0].primary_prompt
    assert "up to 1 subagents" not in refined_1.steps[0].primary_prompt

    # Test max_subagents = 0
    manifest_0 = router.map_route_from_matrix("Build TCP receiver in receiver.go", num_steps=2, max_subagents=0)
    refiner_0 = GeminiRouteRefiner(backend=MockGeminiBackend(canned_response=patch_response))
    refined_0 = refiner_0.refine_manifest("Build TCP receiver", manifest_0)
    assert refined_0.steps[0].primary_prompt == "Write a pure Golang TCP socket receiver."
    assert "subagent" not in refined_0.steps[0].primary_prompt.lower()


def test_refiner_fail_open_on_timeout(sample_manifest):
    """When the LLM takes longer than timeout threshold (timeout_s=0.01), refiner fails open safely in milliseconds."""
    sample_manifest.metadata["pre_existing_key"] = "preserved_value"
    orig_snapshot = copy.deepcopy(sample_manifest)
    mock_backend = MockGeminiBackend(simulate_timeout=True)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Slow request", sample_manifest, timeout_s=0.01)

    assert refined.metadata["refiner_verdict"] == "FAIL_OPEN_UNMODIFIED"
    assert "refiner_latency_ms" in refined.metadata
    assert refined.metadata["refiner_latency_ms"] >= 0.0
    assert_manifest_uncorrupted(orig_snapshot, refined)


def test_refiner_fail_open_on_malformed_json(sample_manifest):
    """When the LLM emits invalid or garbage JSON, refiner fails open safely."""
    sample_manifest.metadata["pre_existing_key"] = "preserved_value"
    orig_snapshot = copy.deepcopy(sample_manifest)
    mock_backend = MockGeminiBackend(simulate_malformed=True)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Broken LLM output", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "FAIL_OPEN_INVALID_JSON"
    assert "refiner_latency_ms" in refined.metadata
    assert refined.metadata["refiner_latency_ms"] >= 0.0
    assert_manifest_uncorrupted(orig_snapshot, refined)


@pytest.mark.parametrize("invalid_payload", [
    "NOT_JSON: Sorry, as an AI model I cannot do that.",
    "{status: PATCH, unquoted_broken_json...",
    "[]",
    "\"a plain json string\"",
    "42",
    json.dumps({"status": 500}),
    json.dumps({"status": "PATCH", "patches": None}),
    json.dumps({"status": "PATCH", "patches": "invalid_string_not_list"}),
    json.dumps({"status": "PATCH", "patches": ["not_a_dict_entry"]}),
])
def test_refiner_fail_open_on_invalid_json_variations(sample_manifest, invalid_payload):
    """When the LLM emits non-JSON text, broken syntax, or malformed schema, refiner fails open safely without corruption."""
    sample_manifest.metadata["pre_existing_key"] = "preserved_value"
    orig_snapshot = copy.deepcopy(sample_manifest)
    mock_backend = MockGeminiBackend(canned_response=invalid_payload)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Adversarial or malformed JSON", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "FAIL_OPEN_INVALID_JSON"
    assert "refiner_latency_ms" in refined.metadata
    assert refined.metadata["refiner_latency_ms"] >= 0.0
    assert_manifest_uncorrupted(orig_snapshot, refined)


def test_refiner_fail_open_when_backend_offline_unavailable_binary(sample_manifest):
    """When the backend binary is offline / missing, refiner fails open safely returning the unmodified candidate manifest."""
    sample_manifest.metadata["pre_existing_key"] = "preserved_value"
    orig_snapshot = copy.deepcopy(sample_manifest)
    offline_backend = AgyCliBackend(agy_binary="/nonexistent/path/to/agy_binary_offline")
    assert not offline_backend.is_available()

    refiner = GeminiRouteRefiner(backend=offline_backend)
    refined = refiner.refine_manifest("Offline backend check", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "FAIL_OPEN_UNMODIFIED"
    assert "refiner_latency_ms" in refined.metadata
    assert refined.metadata["refiner_latency_ms"] >= 0.0
    assert_manifest_uncorrupted(orig_snapshot, refined)


def test_refiner_fail_open_when_backend_raises_offline_exception(sample_manifest):
    """When the backend raises a network or daemon connection exception, refiner fails open safely."""
    class OfflineErrorBackend:
        def generate_review(self, prompt: str, route_summary: str, timeout_s: float = 1.5):
            raise ConnectionError("Gemini daemon offline: Connection refused to unix:///var/run/gemini.sock")

    sample_manifest.metadata["pre_existing_key"] = "preserved_value"
    orig_snapshot = copy.deepcopy(sample_manifest)
    refiner = GeminiRouteRefiner(backend=OfflineErrorBackend())

    refined = refiner.refine_manifest("Offline socket error check", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "FAIL_OPEN_UNMODIFIED"
    assert "refiner_latency_ms" in refined.metadata
    assert refined.metadata["refiner_latency_ms"] >= 0.0
    assert_manifest_uncorrupted(orig_snapshot, refined)


def test_refiner_handles_string_step_index_gracefully(sample_manifest):
    """Refiner coerces numeric string step_index gracefully and applies surgical patch."""
    patch_response = json.dumps({
        "status": "PATCH",
        "reason": "String index coercion test",
        "patches": [
            {
                "step_index": "1",
                "field": "title",
                "replacement": "Architectural Foundation: Solana RPC Setup",
            }
        ]
    })
    mock_backend = MockGeminiBackend(canned_response=patch_response)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Solana setup", sample_manifest)

    assert refined.metadata["refiner_verdict"] == "PATCHED_1_CHANGES"
    assert refined.metadata["refiner_reason"] == "String index coercion test"
    assert refined.steps[0].title == "Architectural Foundation: Solana RPC Setup"


def test_refiner_never_alters_step_counts(sample_manifest):
    """Refiner strictly preserves 6-step invariant even if an adversarial patch tries to out-of-bounds patch."""
    orig_snapshot = copy.deepcopy(sample_manifest)
    out_of_bounds_response = json.dumps({
        "status": "PATCH",
        "patches": [
            {"step_index": 99, "field": "title", "replacement": "Phantom step"}
        ]
    })
    mock_backend = MockGeminiBackend(canned_response=out_of_bounds_response)
    refiner = GeminiRouteRefiner(backend=mock_backend)

    refined = refiner.refine_manifest("Test out of bounds", sample_manifest)
    assert len(refined.steps) == 6
    assert refined.metadata["refiner_verdict"] == "PATCHED_0_CHANGES"
    assert_manifest_uncorrupted(orig_snapshot, refined)
