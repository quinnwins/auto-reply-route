"""Unit tests for SubagentTeamOrchestrator and canonical executive flow playbook."""

from __future__ import annotations

import pytest
from auto_reply_route import (
    AgentPersona,
    PersonaCritique,
    SubagentTeam,
    SubagentTeamOrchestrator,
    TeamReviewVerdict,
)
from auto_reply_route.models import BranchRank, StepStatus
from auto_reply_route.parser import RouteParser
from auto_reply_route.state_machine import RouteStateMachine


def test_orchestrator_initialization_and_teams():
    orchestrator = SubagentTeamOrchestrator()
    teams = orchestrator.list_teams()

    assert "qa_team" in teams
    assert "qa_team_2" in teams
    assert "executive_team" in teams
    assert "system_integration_team" in teams
    assert "visual_proof_team" in teams

    # Verify team personas
    qa_team = orchestrator.get_team("qa_team")
    assert len(qa_team.personas) == 3
    persona_roles = [p.role for p in qa_team.personas]
    assert "edge_case_auditor" in persona_roles
    assert "security_auditor" in persona_roles
    assert "test_coverage_specialist" in persona_roles

    exec_team = orchestrator.get_team("executive_team")
    assert len(exec_team.personas) == 3
    exec_roles = [p.role for p in exec_team.personas]
    assert "simplicity_auditor" in exec_roles
    assert "technical_debt_officer" in exec_roles
    assert "product_director" in exec_roles

    integration_team = orchestrator.get_team("system_integration_team")
    assert len(integration_team.personas) == 3
    int_roles = [p.role for p in integration_team.personas]
    assert "wiring_logic_auditor" in int_roles
    assert "regressions_checker" in int_roles
    assert "state_sync_specialist" in int_roles

    visual_team = orchestrator.get_team("visual_proof_team")
    assert len(visual_team.personas) == 2
    vis_roles = [p.role for p in visual_team.personas]
    assert "screenshot_verifier" in vis_roles
    assert "walkthrough_auditor" in vis_roles


def test_team_alias_resolution():
    orchestrator = SubagentTeamOrchestrator()

    assert orchestrator.get_team("qa").team_id == "qa_team"
    assert orchestrator.get_team("3_person_qa").team_id == "qa_team"
    assert orchestrator.get_team("qa_team_1").team_id == "qa_team"
    assert orchestrator.get_team("qa_team_2").team_id == "qa_team_2"
    assert orchestrator.get_team("another_3_person_qa").team_id == "qa_team_2"
    assert orchestrator.get_team("executive").team_id == "executive_team"
    assert orchestrator.get_team("exec").team_id == "executive_team"
    assert orchestrator.get_team("wiring").team_id == "system_integration_team"
    assert orchestrator.get_team("integration").team_id == "system_integration_team"
    assert orchestrator.get_team("visual").team_id == "visual_proof_team"
    assert orchestrator.get_team("screenshot").team_id == "visual_proof_team"

    with pytest.raises(KeyError):
        orchestrator.get_team("non_existent_team")


def test_build_team_prompt():
    orchestrator = SubagentTeamOrchestrator()
    prompt = orchestrator.build_team_prompt("qa_team", "def add(a, b): return a + b")

    assert "Multi-Persona Subagent Dispatch: 3-Person QA Team" in prompt
    assert "Edge Case Auditor" in prompt
    assert "Security Auditor" in prompt
    assert "Test Coverage Specialist" in prompt
    assert "def add(a, b): return a + b" in prompt


def test_qa_team_synthesis_clean_pass():
    orchestrator = SubagentTeamOrchestrator()
    clean_output = """
    Successfully implemented safe token lookup with bounds validation.
    All 42 unit tests passed with 100% assertion coverage.
    No skipped tests, no secrets, no race conditions detected.
    """
    verdict = orchestrator.synthesize_team_review("qa_team", clean_output)

    assert verdict.passed is True
    assert bool(verdict) is True
    assert len(verdict.defects) == 0
    assert len(verdict.critiques) == 3
    assert all(c.passed for c in verdict.critiques)
    assert "solid" in verdict.living_room_verdict.lower()


def test_qa_team_synthesis_edge_case_and_security_defects():
    orchestrator = SubagentTeamOrchestrator()
    flawed_output = """
    Added feature using eval(input_str) for dynamic expression evaluation.
    Warning: unhandled null pointer exception if input is empty.
    Test suite passed:
        assert True
    """
    verdict = orchestrator.synthesize_team_review("qa_team", flawed_output)

    assert verdict.passed is False
    assert bool(verdict) is False
    assert len(verdict.defects) >= 2

    # Check that individual personas caught their respective vectors
    edge_critique = next(c for c in verdict.critiques if c.role == "edge_case_auditor")
    assert edge_critique.passed is False

    sec_critique = next(c for c in verdict.critiques if c.role == "security_auditor")
    assert sec_critique.passed is False

    test_critique = next(c for c in verdict.critiques if c.role == "test_coverage_specialist")
    assert test_critique.passed is False

    assert "flagged" in verdict.living_room_verdict.lower()


def test_qa_team_synthesis_skipped_tests_detected():
    orchestrator = SubagentTeamOrchestrator()
    skipped_output = """
    Tests completed with skips:
    @pytest.mark.skip(reason="Fails under race conditions, will fix later")
    def test_concurrent_writes():
        pass
    """
    verdict = orchestrator.synthesize_team_review("qa_team", skipped_output)

    assert verdict.passed is False
    assert any("skipped" in d.lower() for d in verdict.defects)


def test_executive_team_synthesis_clean_pass():
    orchestrator = SubagentTeamOrchestrator()
    clean_output = """
    Refactored the authentication workflow into a direct linear 30-line function.
    Eliminated three layers of redundant wrapper classes.
    User gets clear, instant error guidance without technical jargon.
    Zero TODOs or temporary workarounds remain.
    """
    verdict = orchestrator.synthesize_team_review("executive_team", clean_output)

    assert verdict.passed is True
    assert len(verdict.compromises) == 0
    assert "zero compromises" in verdict.living_room_verdict.lower()


def test_executive_team_synthesis_compromises_rejected():
    orchestrator = SubagentTeamOrchestrator()
    compromised_output = """
    Implemented payment gateway.
    TODO: hack - temporary workaround for now until upstream fixes race condition.
    User sees: 'Internal server error: database connection failed'.
    """
    verdict = orchestrator.synthesize_team_review("executive_team", compromised_output)

    assert verdict.passed is False
    assert len(verdict.compromises) >= 2
    assert any("temporary hack" in c.lower() for c in verdict.compromises)
    assert any("plumbing" in c.lower() for c in verdict.compromises)
    assert "rejected" in verdict.living_room_verdict.lower()


def test_system_integration_synthesis_wiring_defect():
    orchestrator = SubagentTeamOrchestrator()
    wiring_output = """
    Integration test failed:
    TypeError: dispatch_event() missing 2 required positional arguments: 'event_type' and 'payload'
    wiring defect identified between API controller and worker dispatcher.
    """
    verdict = orchestrator.synthesize_team_review("system_integration_team", wiring_output)

    assert verdict.passed is False
    assert len(verdict.defects) >= 1
    assert any("wiring" in d.lower() or "signature" in d.lower() for d in verdict.defects)
    assert "integration issue" in verdict.living_room_verdict.lower()


def test_system_integration_synthesis_clean_pass():
    orchestrator = SubagentTeamOrchestrator()
    clean_output = """
    All 15 module callers verified against updated signatures.
    __all__ export list matches public symbol tables.
    Atomic file writes use POSIX sync. Existing regression tests pass 100%.
    """
    verdict = orchestrator.synthesize_team_review("system_integration_team", clean_output)

    assert verdict.passed is True
    assert len(verdict.defects) == 0
    assert "fully wired" in verdict.living_room_verdict.lower()


def test_visual_proof_synthesis_craft_defects():
    orchestrator = SubagentTeamOrchestrator()
    craft_flawed_output = """
    Captured screenshots of the mobile checkout screen.
    Found sub-44px tap target on the submit button (hitbox: 32px).
    Spacing uses arbitrary 5px off-grid padding.
    """
    verdict = orchestrator.synthesize_team_review("visual_proof_team", craft_flawed_output)

    assert verdict.passed is False
    assert any("sub-44px" in d.lower() for d in verdict.defects)
    assert any("off-grid" in d.lower() for d in verdict.defects)
    assert "visual check found" in verdict.living_room_verdict.lower()


def test_visual_proof_synthesis_clean_pass():
    orchestrator = SubagentTeamOrchestrator()
    clean_output = """
    Visual inspection verified in iOS simulator and desktop Safari.
    Concentric corner radii match 8px inner on 16px outer with 8px padding.
    Spatial rhythm conforms strictly to 8pt grid.
    All touch hitboxes exceed 48x48px. Contrast ratio is 7.2:1 (AAA).
    Walkthrough demonstrates flawless user journey from entry to completion.
    """
    verdict = orchestrator.synthesize_team_review("visual_proof_team", clean_output)

    assert verdict.passed is True
    assert len(verdict.defects) == 0
    assert "looks great" in verdict.living_room_verdict.lower()


def test_generate_screenshot_evidence_manifest():
    orchestrator = SubagentTeamOrchestrator()
    images = ["artifacts/step6/checkout_desktop.png", "artifacts/step6/checkout_mobile.png"]
    summary = "User clicks checkout, selects Apple Pay, and receives instant visual confirmation."

    manifest = orchestrator.generate_screenshot_evidence_manifest(
        image_paths=images,
        walkthrough_summary=summary,
        step_index=6,
        feature_name="Apple Pay Checkout",
    )

    assert "## 📍 Visual Proof Milestone Manifest — Step 6: Apple Pay Checkout" in manifest
    assert "Stratum 3" in manifest
    assert "**Screenshots Verified:** 2" in manifest
    assert "checkout_desktop.png" in manifest
    assert "checkout_mobile.png" in manifest
    assert "Concentric Radii" in manifest
    assert "Strict 4/8pt Rhythm" in manifest
    assert "Touch Ergonomics" in manifest
    assert summary in manifest
    assert "Context Ledger Anchor" in manifest


def test_evaluate_step_convenience_method():
    orchestrator = SubagentTeamOrchestrator()

    # Step 1: QA Team 1
    v1 = orchestrator.evaluate_step(1, "Clean unit tests with full bounds validation.")
    assert v1.team_type == "qa_team"
    assert v1.passed is True

    # Step 3: Executive Review Team
    v3 = orchestrator.evaluate_step(3, "Clean simple implementation without workarounds.")
    assert v3.team_type == "executive_team"
    assert v3.passed is True

    # Step 4: System Integration Team
    v4 = orchestrator.evaluate_step(4, "All modules wired without regressions.")
    assert v4.team_type == "system_integration_team"
    assert v4.passed is True

    # Step 5: Visual Proof Team
    v5 = orchestrator.evaluate_step(
        5,
        "Clean walkthrough verified.",
        image_paths=["screen1.png"],
    )
    assert v5.team_type == "visual_proof_team"
    assert "milestone_card" in v5.metadata


def test_canonical_playbook_parsing_and_branch_swapping(tmp_path):
    manifest = RouteParser.parse_file("playbooks/original-executive-flow.route.md")

    assert manifest.route_id == "original-executive-flow"
    assert manifest.title == "Original Executive Flow Route"
    assert len(manifest.steps) == 6

    # Verify each step has 4 alternative branches and concrete assertions
    for step in manifest.steps:
        assert len(step.alternatives) == 4
        assert len(step.assertions) >= 1

    # Step 4 check: verify presence of Strict Security Audit
    step4 = manifest.steps[3]
    assert any("Strict Security Audit" in alt.label for alt in step4.alternatives)

    # Test state machine execution and branch swapping at Step 4
    sm = RouteStateMachine(manifest)
    sm.start()
    assert sm.manifest.current_step_idx == 0

    # Advance to step 3 (0-indexed: Step 4)
    sm.advance_step()  # Step 2
    sm.advance_step()  # Step 3
    active_step4 = sm.advance_step()  # Step 4
    assert active_step4.index == 3

    # Swap branch to rank 2 (Strict Security Audit)
    swapped = sm.swap_branch(step_idx=3, branch_rank=2)
    assert swapped.label == "Strict Security Audit"
    assert "security" in active_step4.primary_prompt.lower()
