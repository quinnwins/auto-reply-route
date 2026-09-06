from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.state_machine import RouteStateMachine


def _create_sample_manifest() -> RouteManifest:
    step0 = RouteStep(
        index=0,
        title="Setup Environment",
        primary_prompt="Install dependencies and setup environment.",
        alternatives=[
            AlternativeBranch(
                rank=BranchRank.QA_DEFENSIVE,
                label="Quick Spike",
                prompt_template="Install minimal mock dependencies.",
            ),
            AlternativeBranch(
                rank=BranchRank.ALTERNATIVE_ARCH,
                label="Docker Compose",
                prompt_template="Launch isolated docker container environment.",
            ),
        ],
        status=StepStatus.PENDING,
        retries=0,
        max_retries=2,
    )
    step1 = RouteStep(
        index=1,
        title="Build Feature",
        primary_prompt="Implement core business logic.",
        alternatives=[
            AlternativeBranch(
                rank=BranchRank.QA_DEFENSIVE,
                label="Defensive Logic",
                prompt_template="Implement logic with parameter checks.",
            )
        ],
        status=StepStatus.PENDING,
        retries=0,
        max_retries=2,
    )
    return RouteManifest(
        route_id="test_route",
        title="Sample Test Route",
        steps=[step0, step1],
        current_step_idx=0,
        state=StepStatus.PENDING,
        metadata={"author": "specialist"},
    )


def test_state_machine_initialization():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    assert sm.manifest.route_id == "test_route"
    assert sm.manifest.state == StepStatus.PENDING
    assert sm.total_steps == 2
    assert not sm.is_running
    assert not sm.is_completed


def test_start_transitions():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)

    current = sm.start()
    assert sm.is_running
    assert sm.manifest.state == StepStatus.RUNNING
    assert sm.manifest.current_step_idx == 0
    assert current is not None
    assert current.index == 0
    assert current.status == StepStatus.RUNNING


def test_start_empty_manifest():
    manifest = RouteManifest(
        route_id="empty_route",
        title="Empty Route",
        steps=[],
    )
    sm = RouteStateMachine(manifest)
    current = sm.start()
    assert current is None
    assert sm.is_completed
    assert sm.manifest.state == StepStatus.COMPLETED


def test_step_advancement():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    sm.start()

    # Step 0 is active
    assert sm.get_current_step().index == 0
    assert sm.get_current_step().status == StepStatus.RUNNING

    # Advance to Step 1
    next_step = sm.advance_step()
    assert next_step is not None
    assert next_step.index == 1
    assert next_step.status == StepStatus.RUNNING
    assert manifest.steps[0].status == StepStatus.COMPLETED
    assert sm.is_running

    # Advance past Step 1 -> Route completion
    final_step = sm.advance_step()
    assert final_step is None
    assert sm.is_completed
    assert sm.manifest.state == StepStatus.COMPLETED
    assert manifest.steps[1].status == StepStatus.COMPLETED


def test_branch_swapping():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    sm.start()

    step0 = sm.get_current_step()
    original_primary = step0.primary_prompt
    expected_alt_prompt = "Install minimal mock dependencies."

    # Swap with QA_DEFENSIVE branch (rank 2)
    swapped_branch = sm.swap_branch(step_idx=0, branch_rank=BranchRank.QA_DEFENSIVE)
    assert step0.primary_prompt == expected_alt_prompt
    assert swapped_branch.prompt_template == original_primary
    assert "branch_swaps" in sm.manifest.metadata
    assert len(sm.manifest.metadata["branch_swaps"]) == 1

    # Swap back
    sm.swap_branch(step_idx=0, branch_rank=2)
    assert step0.primary_prompt == original_primary
    assert swapped_branch.prompt_template == expected_alt_prompt
    assert len(sm.manifest.metadata["branch_swaps"]) == 2


def test_branch_swapping_errors():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)

    # Step index out of range
    with pytest.raises(IndexError):
        sm.swap_branch(step_idx=99, branch_rank=2)

    # Rank not present in step
    with pytest.raises(ValueError):
        sm.swap_branch(step_idx=0, branch_rank=BranchRank.FALLBACK)


def test_retry_cap_enforcement_2_retries():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    sm.start()

    step0 = sm.get_current_step()
    assert step0.retries == 0
    assert step0.max_retries == 2

    # Retry 1: permitted
    permitted_1 = sm.record_retry(reason="Unit tests failed on assertion 1")
    assert permitted_1 is True
    assert step0.retries == 1
    assert step0.status == StepStatus.QUARANTINE_RETRY
    assert sm.is_running

    # Retry 2: permitted (at cap)
    permitted_2 = sm.record_retry(reason="Build timed out")
    assert permitted_2 is True
    assert step0.retries == 2
    assert step0.status == StepStatus.QUARANTINE_RETRY
    assert sm.is_running

    # Retry 3: exceeds max_retries (2) -> cap enforcement
    permitted_3 = sm.record_retry(reason="Persistent regression encountered")
    assert permitted_3 is False
    assert step0.retries == 3
    assert step0.status == StepStatus.FAILED
    assert sm.is_paused
    assert sm.manifest.state == StepStatus.PAUSED
    assert "exhausted_reason" in sm.manifest.metadata


def test_pause_resume_abort_controls():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    sm.start()

    # Pause
    sm.pause(reason="Manual intervention requested")
    assert sm.is_paused
    assert sm.manifest.state == StepStatus.PAUSED
    assert sm.get_current_step().status == StepStatus.PAUSED
    assert sm.manifest.metadata.get("pause_reason") == "Manual intervention requested"

    # Resume
    sm.resume()
    assert sm.is_running
    assert sm.manifest.state == StepStatus.RUNNING
    assert sm.get_current_step().status == StepStatus.RUNNING

    # Abort
    sm.abort(reason="Fatal unrecoverable state")
    assert sm.is_failed
    assert sm.manifest.state == StepStatus.FAILED
    assert sm.get_current_step().status == StepStatus.FAILED
    assert sm.manifest.metadata.get("abort_reason") == "Fatal unrecoverable state"


def test_atomic_checkpoint_persistence():
    manifest = _create_sample_manifest()
    sm = RouteStateMachine(manifest)
    sm.start()
    sm.record_retry(reason="First test retry")
    sm.swap_branch(step_idx=0, branch_rank=BranchRank.QA_DEFENSIVE)

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_file = str(Path(tmpdir) / "state" / "checkpoint.json")

        # Save checkpoint
        sm.save_checkpoint(checkpoint_file)
        assert Path(checkpoint_file).is_file()

        # Load checkpoint into new state machine instance
        restored_sm = RouteStateMachine.load_checkpoint(checkpoint_file)
        assert restored_sm.manifest.route_id == "test_route"
        assert restored_sm.manifest.title == "Sample Test Route"
        assert restored_sm.manifest.state == StepStatus.RUNNING
        assert restored_sm.manifest.current_step_idx == 0

        restored_step0 = restored_sm.get_current_step()
        assert restored_step0 is not None
        assert restored_step0.retries == 1
        assert restored_step0.status == StepStatus.QUARANTINE_RETRY
        assert restored_step0.primary_prompt == "Install minimal mock dependencies."
        assert len(restored_sm.manifest.metadata["branch_swaps"]) == 1

        # Restored machine can advance smoothly
        next_step = restored_sm.advance_step()
        assert next_step is not None
        assert next_step.index == 1
        assert next_step.status == StepStatus.RUNNING
        assert restored_sm.manifest.steps[0].status == StepStatus.COMPLETED
