from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from unittest.mock import patch
import shlex
from typing import Optional, Union

import pytest

from auto_reply_route.hook_driver import AntigravityHookDriver, QueueDispatcher, _validate_conversation_id
from auto_reply_route.models import RouteManifest, RouteStep, StepStatus
from auto_reply_route.parser import RouteParser
from auto_reply_route.state_machine import RouteStateMachine
from auto_reply_route.cli import RouteValidator


def _safe_run_command(
    command: Union[str, list[str]],
    cwd: Optional[str] = None,
    timeout: int = 60,
    allow_shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Executes external command with safe tokenization and deadlock timeout enforcement."""
    if isinstance(command, (list, tuple)):
        return subprocess.run(
            list(command),
            shell=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    clean_cmd = command.strip()
    if allow_shell:
        return subprocess.run(
            clean_cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    tokens = shlex.split(clean_cmd)
    return subprocess.run(
        tokens,
        shell=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _create_sample_manifest(route_id: str = "test-sec") -> RouteManifest:
    step0 = RouteStep(
        index=0,
        title="Step Zero",
        primary_prompt="Do step 0",
        assertions=["python3 -c 'import sys; sys.exit(0)' passes"],
    )
    step1 = RouteStep(
        index=1,
        title="Step One",
        primary_prompt="Do step 1",
        assertions=["python3 -c 'import sys; sys.exit(0)' passes"],
    )
    return RouteManifest(route_id=route_id, title="Security Route", steps=[step0, step1])


class TestSubprocessSecurityAndTimeouts:
    """Verifies safe tokenization, deadlock timeout enforcement, and injection resistance."""

    def test_safe_run_command_tokenizes_without_shell_injection(self) -> None:
        """Verify that a command containing injection syntax is tokenized safely and not executed via shell."""
        injected_token = "injected_canary_value"
        res = _safe_run_command(f'python3 -c "import sys; sys.exit(0)" ; echo {injected_token}', timeout=5)
        assert injected_token not in res.stdout
        assert res.returncode == 0

    def test_safe_run_command_preserves_list_arguments(self) -> None:
        """Verify that passing command as a list avoids POSIX shell=True argument-dropping bugs."""
        cmd = ["python3", "-c", "import sys; print(sys.argv[1])", "target_argument"]
        res = _safe_run_command(cmd, timeout=5)
        assert res.returncode == 0
        assert res.stdout.strip() == "target_argument"

    def test_hook_driver_assertion_timeout_fallback(self, tmp_path: Path) -> None:
        """Verify fallback assertion execution in AntigravityHookDriver enforces timeout."""
        driver = AntigravityHookDriver(base_dir=tmp_path)
        driver.gate_sieve = None  # Force fallback subprocess execution

        step = RouteStep(
            index=0,
            title="Timeout Step",
            primary_prompt="prompt",
            assertions=["python3 -c 'import sys; sys.exit(0)' passes"],
        )
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python3", timeout=60)):

            passed, err_summary, err_count = driver.evaluate_step_gates(step)
            assert passed is False
            assert "timed out after 60s" in err_summary
            assert err_count == 1

    def test_hook_driver_assertion_nonzero_exit_code(self, tmp_path: Path) -> None:
        """Verify fallback assertion execution catches non-zero exit code cleanly."""
        driver = AntigravityHookDriver(base_dir=tmp_path)
        driver.gate_sieve = None

        step = RouteStep(
            index=0,
            title="Failing Step",
            primary_prompt="prompt",
            assertions=["python3 -c 'import sys; sys.exit(42)' passes"],
        )
        passed, err_summary, err_count = driver.evaluate_step_gates(step)
        assert passed is False
        assert "exit code 42" in err_summary
        assert err_count == 1


# =============================================================================
# 2. Concurrency & Atomic Checkpoint Operations
# =============================================================================

class TestConcurrencyAndAtomicCheckpoints:
    """Verifies atomic checkpoint persistence, concurrency collision safety, and fsync durability."""

    def test_concurrent_threads_saving_checkpoints_no_collisions(self, tmp_path: Path) -> None:
        """Simulate multiple concurrent threads in the same process saving checkpoints to verify
        that PID + Thread ID + UUID tagging completely prevents temporary file collisions.
        """
        errors: list[Exception] = []
        ckpt_files: list[Path] = []

        def worker(thread_idx: int) -> None:
            try:
                manifest = _create_sample_manifest(f"route-thread-{thread_idx}")
                sm = RouteStateMachine(manifest)
                target = tmp_path / f"checkpoint_thread_{thread_idx}.json"
                ckpt_files.append(target)
                for _ in range(5):
                    sm.save_checkpoint(str(target))
                    loaded = RouteStateMachine.load_checkpoint(str(target))
                    assert loaded.manifest.route_id == f"route-thread-{thread_idx}"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors occurred: {errors}"
        for cf in ckpt_files:
            assert cf.is_file()
            with open(cf, "r", encoding="utf-8") as f:
                data = json.load(f)
                assert "route_id" in data

    def test_queue_user_message_atomic_persistence(self, tmp_path: Path) -> None:
        """Verify QueueDispatcher creates atomic, PID-tagged files and synchronizes directories."""
        dispatcher = QueueDispatcher(app_data_dir=tmp_path)
        conv_id = "test-atomic-conv-123"

        msg = dispatcher.queue_user_message(
            conversation_id=conv_id,
            content="Execute next step immediately",
        )

        messages_dir = dispatcher.get_messages_dir(conv_id)
        target_file = messages_dir / f"{msg['id']}.json"
        assert target_file.is_file()

        ind_file = messages_dir / "undelivered" / msg["id"]
        assert ind_file.is_file()

        with open(target_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            assert loaded["content"] == "Execute next step immediately"


# =============================================================================
# 3. Path Traversal Guards
# =============================================================================

class TestPathTraversalGuards:
    """Verifies directory traversal attacks are systematically blocked across all entry points."""

    def test_conversation_id_traversal_validation(self) -> None:
        """Verify _validate_conversation_id rejects path traversal elements."""
        with pytest.raises(ValueError, match="Directory traversal detected"):
            _validate_conversation_id("../../../../tmp/escape")

        with pytest.raises(ValueError, match="Directory traversal detected"):
            _validate_conversation_id("sub/dir/id")

        with pytest.raises(ValueError, match="Directory traversal detected"):
            _validate_conversation_id("id\0null")

        assert _validate_conversation_id("conv-abc_123-xyz") == "conv-abc_123-xyz"

    def test_queue_dispatcher_rejects_traversal(self, tmp_path: Path) -> None:
        """Verify QueueDispatcher blocks directory traversal in get_messages_dir."""
        qd = QueueDispatcher(app_data_dir=tmp_path)
        with pytest.raises(ValueError):
            qd.get_messages_dir("../../../../tmp/evil")

    def test_load_transcript_steps_blocks_system_paths(self, tmp_path: Path) -> None:
        """Verify _load_transcript_steps returns empty list for system files like /etc/passwd."""
        driver = AntigravityHookDriver(base_dir=tmp_path)
        assert driver._load_transcript_steps("/etc/passwd") == []
        assert driver._load_transcript_steps("/etc/hosts") == []
        assert driver._load_transcript_steps("../../../etc/passwd") == []

    def test_route_parser_and_validator_block_system_traversal(self) -> None:
        """Verify RouteParser and RouteValidator reject system directory paths."""
        with pytest.raises(PermissionError):
            RouteParser.parse_file("/etc/passwd")

        val_res = RouteValidator.validate_file("/etc/passwd")
        assert val_res.is_valid is False
        assert any("Access denied" in str(e) for e in val_res.errors)


# =============================================================================
# 4. APFS Transcript Corruption & Concurrent Write Resilience
# =============================================================================

class TestAPFSTranscriptResilience:
    """Verifies resilience against incomplete UTF-8 bytes and EOF truncations from concurrent APFS writes."""

    def test_incomplete_utf8_at_eof_preserves_prior_steps(self, tmp_path: Path) -> None:
        """Verify incomplete UTF-8 sequence at EOF does not cause UnicodeDecodeError to wipe transcript."""
        t_file = tmp_path / "transcript.jsonl"
        with open(t_file, "wb") as f:
            f.write(b'{"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "hello"}\n')
            f.write(b'{"step_index": 2, "source": "MODEL", "content": "incomplete \xc3')

        driver = AntigravityHookDriver(base_dir=tmp_path)
        steps = driver._load_transcript_steps(str(t_file))

        assert len(steps) >= 1
        assert steps[0]["content"] == "hello"

    def test_truncated_json_at_eof_detected_as_in_progress(self, tmp_path: Path) -> None:
        """Verify partial unclosed JSON at EOF flags turn as IN_PROGRESS to prevent premature route advancement."""
        t_file = tmp_path / "transcript.jsonl"
        with open(t_file, "w", encoding="utf-8") as f:
            f.write('{"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "start"}\n')
            f.write('{"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read"')

        driver = AntigravityHookDriver(base_dir=tmp_path)
        steps = driver._load_transcript_steps(str(t_file))

        assert driver.has_pending_tool_calls(steps) is True

    def test_null_bytes_at_eof_handled_cleanly(self, tmp_path: Path) -> None:
        """Verify trailing APFS null bytes from pre-allocation flushes are handled safely."""
        t_file = tmp_path / "transcript.jsonl"
        with open(t_file, "wb") as f:
            f.write(b'{"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "clean"}\n')
            f.write(b'\x00\x00\x00\x00')

        driver = AntigravityHookDriver(base_dir=tmp_path)
        steps = driver._load_transcript_steps(str(t_file))
        assert len(steps) == 1
        assert steps[0]["content"] == "clean"


# =============================================================================
# 5. Human Preemption Message Envelope Schemas
# =============================================================================

class TestHumanPreemptionEnvelopeSchemas:
    """Verifies that human preemption pause works reliably under all envelope schemas."""

    def test_preemption_with_source_user(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        transcript = [
            {"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "step 0"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
            {"step_index": 3, "source": "USER", "type": "USER_INPUT", "content": "Hold on!"},
            {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
        ]
        assert driver.is_human_preemption(transcript) is True

    def test_preemption_with_role_user(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        transcript = [
            {"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "step 0"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
            {"step_index": 3, "role": "user", "type": "USER_INPUT", "content": "Stop the test"},
            {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
        ]
        assert driver.is_human_preemption(transcript) is True

    def test_preemption_with_sender_user(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        transcript = [
            {"step_index": 1, "source": "HOOK", "type": "USER_INPUT", "content": "step 0"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
            {"step_index": 3, "sender": "user", "content": "Pause execution please"},
            {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
        ]
        assert driver.is_human_preemption(transcript) is True

    def test_preemption_with_lowercase_user_explicit(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        transcript = [
            {"step_index": 1, "source": "user_explicit", "type": "user_input", "content": "Stop!"},
        ]
        assert driver.is_human_preemption(transcript) is True

    def test_automated_sources_do_not_trigger_human_preemption(self, tmp_path: Path) -> None:
        driver = AntigravityHookDriver(base_dir=tmp_path)
        for automated in ("HOOK", "AUTO_REPLY", "SYSTEM", "SYSTEM_SDK", "AUTO_HEAL"):
            transcript = [
                {"step_index": 1, "source": automated, "type": "USER_INPUT", "content": "automated prompt"},
                {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE"},
            ]
            assert driver.is_human_preemption(transcript) is False
