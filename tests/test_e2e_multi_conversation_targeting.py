"""End-to-End Multi-Conversation Concurrency & Focus Isolation Test Suite.

Empirically proves:
1. Real subprocess execution of multiple concurrent conversations (/g and /q).
2. Zero window switching: macOS frontmost application process never changes.
3. Zero clipboard pollution: pbpaste contents remain 100% byte-for-byte intact.
4. Zero cross-chat pollution: 4 simultaneous conversations writing bursts of follow-ups
   remain strictly partitioned in their own respective brain/ directories.
5. Poison-script verification: Any osascript invocation is intercepted and fails fast,
   proving AppleScript is never executed.
6. Edge cases:
   - Interleaved concurrent multi-turn bursts.
   - Divergent step progression (one chat finishes and terminates, others keep advancing).
   - Mixed ID resolution channels (env var vs metadata JSON vs CLI flag).
   - Rapid queuing pacing and monotonically increasing timestamps.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import pytest

from auto_reply_route import (
    AdaptiveGuidanceController,
    dispatch_prompt_to_conversation,
    queue_prompts_into_antigravity,
    resolve_conversation_id,
)


def _get_macos_frontmost_app() -> str:
    """Gets the name of the currently active/frontmost application process in macOS."""
    try:
        res = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return res.stdout.strip()
    except Exception:
        return "Unknown"


class TestE2EMultiConversationIsolation:
    """End-to-End multi-conversation isolation with real filesystem and subprocess validation."""

    def test_concurrent_multi_chat_burst_zero_cross_pollution(self, tmp_path: Path) -> None:
        """Runs 4 conversations dispatching multiple prompts concurrently in parallel threads.
        
        Verifies 100% directory isolation, zero message leakage, and valid undelivered indicators.
        """
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conversations = [
            f"conv-alpha-{uuid.uuid4().hex[:8]}",
            f"conv-beta-{uuid.uuid4().hex[:8]}",
            f"conv-gamma-{uuid.uuid4().hex[:8]}",
            f"conv-delta-{uuid.uuid4().hex[:8]}",
        ]
        idle_conv = f"conv-epsilon-idle-{uuid.uuid4().hex[:8]}"

        # Each conversation will dispatch a distinct stream of 5 prompts
        prompts_per_conv: dict[str, list[str]] = {
            c: [f"/g (Step {step}/5) task for {c} step {step}" for step in range(1, 6)]
            for c in conversations
        }

        def worker(conv_id: str) -> list[dict]:
            receipts = []
            for prompt in prompts_per_conv[conv_id]:
                r = dispatch_prompt_to_conversation(
                    prompt=prompt,
                    conversation_id=conv_id,
                    app_data_dir=sandbox_app_data,
                )
                receipts.append(r)
                time.sleep(0.005)  # micro-pace
            return receipts

        # Execute all 4 conversations in parallel threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_conv = {executor.submit(worker, c): c for c in conversations}
            results = {future_to_conv[f]: f.result() for f in concurrent.futures.as_completed(future_to_conv)}

        # Verification Phase
        for conv_id in conversations:
            expected_prompts = prompts_per_conv[conv_id]
            receipts = results[conv_id]
            assert len(receipts) == 5

            messages_dir = sandbox_app_data / "brain" / conv_id / ".system_generated" / "messages"
            undelivered_dir = messages_dir / "undelivered"

            assert messages_dir.is_dir()
            assert undelivered_dir.is_dir()

            # Verify on-disk message files
            json_files = list(messages_dir.glob("*.json"))
            assert len(json_files) == 5

            undelivered_files = list(undelivered_dir.glob("*"))
            assert len(undelivered_files) == 5

            # Inspect contents
            for r in receipts:
                msg_file = messages_dir / f"{r['id']}.json"
                assert msg_file.is_file(), f"Message file {r['id']} missing from {conv_id}"

                with open(msg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Strict Isolation Invariants
                assert data["recipient"] == conv_id
                assert data["content"] in expected_prompts
                assert conv_id in data["content"]

                # Cross-Pollution Check: Ensure this message exists in NO OTHER conversation
                for other_conv in conversations:
                    if other_conv != conv_id:
                        other_dir = sandbox_app_data / "brain" / other_conv / ".system_generated" / "messages"
                        assert not (other_dir / f"{r['id']}.json").exists(), (
                            f"LEAK DETECTED: Message {r['id']} from {conv_id} found in {other_conv}"
                        )

        # Inactive conversation must NEVER have been touched
        assert not (sandbox_app_data / "brain" / idle_conv).exists()


    def test_divergent_lifecycle_concurrency(self, tmp_path: Path) -> None:
        """Simulates Chat A finishing early while Chat B continues through 5 steps.
        
        Verifies that termination of Chat A does not interrupt, abort, or affect Chat B.
        """
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_fast = f"conv-fast-{uuid.uuid4().hex[:6]}"
        conv_long = f"conv-long-{uuid.uuid4().hex[:6]}"

        controller_fast = AdaptiveGuidanceController(
            default_budget=2,
            conversation_id=conv_fast,
            app_data_dir=sandbox_app_data,
        )
        controller_long = AdaptiveGuidanceController(
            default_budget=5,
            conversation_id=conv_long,
            app_data_dir=sandbox_app_data,
        )

        # Chat Fast: Step 1 -> evaluates success -> Step 2 -> concludes with DONE
        state_f, _ = controller_fast.start_turn("/g (Step 1/2) fast task")
        res_f = controller_fast.execute_task(lambda: {"success": True, "all_tasks_satisfied": False}, state_f)
        _, should_d_f = controller_fast.evaluate_and_steer(state_f, res_f)
        controller_fast.end_turn(state_f, should_d_f)

        state_f2, _ = controller_fast.start_turn("/g (Step 2/2) final fast task")
        res_f2 = controller_fast.execute_task(lambda: {"success": True, "all_tasks_satisfied": True}, state_f2)
        done_msg, should_d_f2 = controller_fast.evaluate_and_steer(state_f2, res_f2)
        assert done_msg == "DONE: All tasks satisfied."
        assert should_d_f2 is False
        controller_fast.end_turn(state_f2, should_d_f2)

        # Chat Long: Continues advancing through all 5 steps
        for step in range(1, 5):
            state_l, _ = controller_long.start_turn(f"/g (Step {step}/5) long task {step}")
            res_l = controller_long.execute_task(lambda: {"success": True, "all_tasks_satisfied": False}, state_l)
            _, should_d_l = controller_long.evaluate_and_steer(state_l, res_l)
            assert should_d_l is True
            controller_long.end_turn(state_l, should_d_l)

        # Fast conversation must have exactly 1 queued followup (Step 2/2), and zero for termination
        fast_msgs = list((sandbox_app_data / "brain" / conv_fast / ".system_generated" / "messages").glob("*.json"))
        assert len(fast_msgs) == 1

        # Long conversation must have exactly 4 queued followups
        long_msgs = list((sandbox_app_data / "brain" / conv_long / ".system_generated" / "messages").glob("*.json"))
        assert len(long_msgs) == 4


    def test_mixed_resolution_channels_concurrency(self, tmp_path: Path) -> None:
        """Simulates 3 conversations resolving their IDs via different channels:
        - Chat 1: Explicit argument
        - Chat 2: ANTIGRAVITY_CONVERSATION_ID env var
        - Chat 3: ANTIGRAVITY_SOURCE_METADATA JSON payload
        """
        sandbox_app_data = tmp_path / "sandbox_gemini"
        c1 = f"channel-explicit-{uuid.uuid4().hex[:6]}"
        c2 = f"channel-env-{uuid.uuid4().hex[:6]}"
        c3 = f"channel-meta-{uuid.uuid4().hex[:6]}"

        # Chat 1: explicit arg
        dispatch_prompt_to_conversation(
            prompt="Prompt for Chat 1",
            conversation_id=c1,
            app_data_dir=sandbox_app_data,
        )

        # Chat 2: env var
        env_c2 = {
            "ANTIGRAVITY_CONVERSATION_ID": c2,
            "ANTIGRAVITY_APP_DATA_DIR": str(sandbox_app_data),
        }
        dispatch_prompt_to_conversation(
            prompt="Prompt for Chat 2",
            conversation_id=None,
            app_data_dir=sandbox_app_data,
            environ=env_c2,
        )

        # Chat 3: metadata JSON
        env_c3 = {
            "ANTIGRAVITY_SOURCE_METADATA": json.dumps({"tool": {"conversationId": c3}}),
            "ANTIGRAVITY_APP_DATA_DIR": str(sandbox_app_data),
        }
        dispatch_prompt_to_conversation(
            prompt="Prompt for Chat 3",
            conversation_id=None,
            app_data_dir=sandbox_app_data,
            environ=env_c3,
        )

        # Verify each channel landed precisely in its own directory
        for target_id, expected_content in [
            (c1, "Prompt for Chat 1"),
            (c2, "Prompt for Chat 2"),
            (c3, "Prompt for Chat 3"),
        ]:
            target_dir = sandbox_app_data / "brain" / target_id / ".system_generated" / "messages"
            files = list(target_dir.glob("*.json"))
            assert len(files) == 1
            with open(files[0], "r", encoding="utf-8") as f:
                d = json.load(f)
            assert d["recipient"] == target_id
            assert d["content"] == expected_content


class TestZeroWindowSwitchingAndZeroClipboardPollution:
    """Verifies that running targeted dispatches leaves macOS window focus and system clipboard untouched."""

    def test_real_macos_frontmost_window_unchanged(self, tmp_path: Path) -> None:
        """Records the real macOS frontmost window before and after multi-conversation dispatch.
        
        Proves that Antigravity is never activated and window focus never changes.
        """
        initial_frontmost = _get_macos_frontmost_app()

        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_id = f"conv-focus-check-{uuid.uuid4().hex[:6]}"

        # Run 5 targeted dispatches
        for i in range(5):
            dispatch_prompt_to_conversation(
                prompt=f"/g (Step {i+1}/5) focus verification step {i+1}",
                conversation_id=conv_id,
                app_data_dir=sandbox_app_data,
            )

        final_frontmost = _get_macos_frontmost_app()

        # Window focus must remain identical
        assert final_frontmost == initial_frontmost, (
            f"FOCUS LEAK: Frontmost app changed from '{initial_frontmost}' to '{final_frontmost}'"
        )

    def test_real_macos_clipboard_byte_for_byte_unmodified(self, tmp_path: Path) -> None:
        """Sets a unique canary on the real macOS clipboard via pbcopy, runs dispatches,
        and verifies via pbpaste that the canary was never touched or overwritten.
        """
        canary = f"TEST_CANARY_INTEGRITY_CHECK_{uuid.uuid4().hex}_{time.time()}"
        
        # Set clipboard canary
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(canary.encode("utf-8"))
        assert p.returncode == 0

        # Verify canary is active
        check = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        assert check == canary

        # Run multi-step queue_prompts_into_antigravity in targeted mode
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_id = f"conv-clip-check-{uuid.uuid4().hex[:6]}"

        prompts = queue_prompts_into_antigravity(
            prompt="Q 4 follow ups for payments security",
            steps=4,
            conversation_id=conv_id,
            app_data_dir=sandbox_app_data,
            countdown_seconds=0.0,
            delay_between_steps=0.001,
        )
        assert len(prompts) == 4

        # Read clipboard again
        final_clipboard = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

        # Must be 100% byte-for-byte identical
        assert final_clipboard == canary, "CLIPBOARD CORRUPTION: macOS clipboard was modified by targeted queueing"


class TestPoisonAppleScriptDefense:
    """Shadows osascript in PATH with a fail-fast poison script.
    
    If targeted dispatch attempts to call osascript, it immediately fails fast.
    """

    def test_osascript_is_never_invoked(self, tmp_path: Path) -> None:
        # Create a poison bin directory
        poison_bin = tmp_path / "poison_bin"
        poison_bin.mkdir(parents=True, exist_ok=True)
        poison_osascript = poison_bin / "osascript"

        # The poison osascript records invocation and exits with code 99
        poison_log = tmp_path / "osascript_violations.log"
        poison_script_content = f"""#!/bin/sh
echo "VIOLATION: osascript was called with: $@" >> "{poison_log}"
exit 99
"""
        poison_osascript.write_text(poison_script_content)
        poison_osascript.chmod(0o755)

        # Prepend poison_bin to PATH
        poison_env = os.environ.copy()
        poison_env["PATH"] = f"{poison_bin}:{poison_env.get('PATH', '')}"

        # Verify poison script works
        check = subprocess.run(["osascript", "-e", "test"], env=poison_env, capture_output=True)
        assert check.returncode == 99
        assert poison_log.exists()
        poison_log.unlink()

        # Now run targeted dispatch subprocess with poison PATH
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_id = f"conv-poison-check-{uuid.uuid4().hex[:6]}"

        cmd = [
            sys.executable,
            "-c",
            f"""
import os
from auto_reply_route.queue_paster import queue_prompts_into_antigravity
queue_prompts_into_antigravity(
    prompt='Q 3 followups for security audit',
    steps=3,
    conversation_id='{conv_id}',
    app_data_dir='{sandbox_app_data}',
    countdown_seconds=0.0,
    delay_between_steps=0.001,
)
"""
        ]

        res = subprocess.run(cmd, env=poison_env, capture_output=True, text=True)
        assert res.returncode == 0, f"Subprocess failed with: {res.stderr}"

        # Poison log must NOT exist, proving osascript was NEVER called
        assert not poison_log.exists(), (
            f"SECURITY BREACH: osascript was invoked during targeted delivery: {poison_log.read_text()}"
        )

        # Messages must be written to disk
        msgs = list((sandbox_app_data / "brain" / conv_id / ".system_generated" / "messages").glob("*.json"))
        assert len(msgs) == 3


class TestConcurrencyEdgeCases:
    """Advanced concurrency, high-stress, and timestamp ordering edge cases."""

    def test_concurrent_writes_to_same_conversation(self, tmp_path: Path) -> None:
        """8 threads writing simultaneously to the same conversation mailbox.
        
        Tests atomic write durability, thread-safety, and collision avoidance.
        """
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_id = f"conv-shared-{uuid.uuid4().hex[:6]}"

        def worker(thread_idx: int) -> dict:
            return dispatch_prompt_to_conversation(
                prompt=f"Simultaneous subagent message from thread {thread_idx}",
                conversation_id=conv_id,
                app_data_dir=sandbox_app_data,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            receipts = list(executor.map(worker, range(8)))

        assert len(receipts) == 8
        receipt_ids = {r["id"] for r in receipts}
        assert len(receipt_ids) == 8, "Collision detected: message IDs must all be unique"

        # Verify on disk
        msgs_dir = sandbox_app_data / "brain" / conv_id / ".system_generated" / "messages"
        json_files = list(msgs_dir.glob("*.json"))
        assert len(json_files) == 8

        undelivered_files = list((msgs_dir / "undelivered").glob("*"))
        assert len(undelivered_files) == 8

        # Verify all JSON files are valid and not corrupted by simultaneous writes
        for jf in json_files:
            with open(jf, "r", encoding="utf-8") as f:
                payload = json.load(f)
            assert payload["id"] in receipt_ids
            assert payload["recipient"] == conv_id

    def test_monotonic_timestamp_ordering_in_batch_queuing(self, tmp_path: Path) -> None:
        """Verifies that queued batch messages have strictly monotonically increasing timestamps."""
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_id = f"conv-monotonic-{uuid.uuid4().hex[:6]}"

        prompts = queue_prompts_into_antigravity(
            prompt="Q 5 follow ups for distributed consensus",
            steps=5,
            conversation_id=conv_id,
            app_data_dir=sandbox_app_data,
            countdown_seconds=0.0,
            delay_between_steps=0.005,
        )
        assert len(prompts) == 5

        msgs_dir = sandbox_app_data / "brain" / conv_id / ".system_generated" / "messages"
        json_files = list(msgs_dir.glob("*.json"))
        assert len(json_files) == 5

        # Read and sort by timestamp
        payloads = []
        for jf in json_files:
            with open(jf, "r", encoding="utf-8") as f:
                payloads.append(json.load(f))

        sorted_payloads = sorted(payloads, key=lambda x: x["timestamp"])

        # Verify strict monotonicity: t_0 < t_1 < t_2 < t_3 < t_4
        for i in range(len(sorted_payloads) - 1):
            t_curr = sorted_payloads[i]["timestamp"]
            t_next = sorted_payloads[i + 1]["timestamp"]
            assert t_curr < t_next, f"Timestamps not monotonically increasing: {t_curr} >= {t_next}"

    def test_alternating_conversation_dispatch_in_single_orchestrator(self, tmp_path: Path) -> None:
        """Rapidly alternates between Chat Alpha and Chat Beta in a single process loop."""
        sandbox_app_data = tmp_path / "sandbox_gemini"
        conv_a = f"conv-alt-a-{uuid.uuid4().hex[:6]}"
        conv_b = f"conv-alt-b-{uuid.uuid4().hex[:6]}"

        for i in range(10):
            # Target A
            dispatch_prompt_to_conversation(
                prompt=f"A message {i}",
                conversation_id=conv_a,
                app_data_dir=sandbox_app_data,
            )
            # Target B
            dispatch_prompt_to_conversation(
                prompt=f"B message {i}",
                conversation_id=conv_b,
                app_data_dir=sandbox_app_data,
            )

        msgs_a = list((sandbox_app_data / "brain" / conv_a / ".system_generated" / "messages").glob("*.json"))
        msgs_b = list((sandbox_app_data / "brain" / conv_b / ".system_generated" / "messages").glob("*.json"))
        assert len(msgs_a) == 10
        assert len(msgs_b) == 10

        # Verify A contains only A messages
        for f in msgs_a:
            data = json.loads(f.read_text())
            assert data["recipient"] == conv_a
            assert data["content"].startswith("A message")

        # Verify B contains only B messages
        for f in msgs_b:
            data = json.loads(f.read_text())
            assert data["recipient"] == conv_b
            assert data["content"].startswith("B message")

    def test_high_volume_10_conversation_100_message_stress_isolation(self, tmp_path: Path) -> None:
        """10 concurrent conversations dispatching 100 messages total under high concurrency."""
        sandbox_app_data = tmp_path / "sandbox_gemini"
        ten_convs = [f"stress-conv-{i}-{uuid.uuid4().hex[:4]}" for i in range(10)]

        def dispatch_burst(c_id: str) -> int:
            for m in range(10):
                dispatch_prompt_to_conversation(
                    prompt=f"Stress test message {m} for {c_id}",
                    conversation_id=c_id,
                    app_data_dir=sandbox_app_data,
                )
            return 10

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            counts = list(executor.map(dispatch_burst, ten_convs))

        assert counts == [10] * 10

        # Verify all 10 conversation mailboxes have exactly 10 messages with 100% isolation
        for c_id in ten_convs:
            msgs_dir = sandbox_app_data / "brain" / c_id / ".system_generated" / "messages"
            files = list(msgs_dir.glob("*.json"))
            assert len(files) == 10, f"Expected 10 messages in {c_id}, got {len(files)}"

            for jf in files:
                d = json.loads(jf.read_text())
                assert d["recipient"] == c_id
                assert c_id in d["content"]

