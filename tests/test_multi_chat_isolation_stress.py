"""Multi-Chat Isolation and Cross-Chat Pollution Stress Test.

Simulates multiple concurrent Antigravity chats (Chat Alpha, Chat Beta, Chat Gamma)
and rigorously verifies:
1. Strict chat boundary isolation: messages from Chat Alpha NEVER land in Chat Beta or Gamma.
2. Anti-hijacking invariant: even if an agent naively passes --delivery-mode gui from a tool call,
   it is intercepted and strictly routed to the originating chat's mailbox without firing
   OS-level keystrokes or touching the clipboard.
3. First-class /g integrity: /g commands are never multiplied into 5 template steps.
4. Concurrent multi-chat dispatch: simultaneous background dispatches preserve individual mailbox integrity.
5. Subprocess CLI validation: tests the actual queue_paster CLI executable in isolated environments.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

from auto_reply_route.queue_paster import (
    is_g_command,
    parse_queue_command,
    queue_prompts_into_antigravity,
    resolve_conversation_id,
)


def _setup_mock_app_data(tmp_path: Path, chat_ids: list[str]) -> Path:
    """Sets up realistic Antigravity filesystem layout with multiple conversation brains."""
    app_data = tmp_path / "antigravity"
    brain_dir = app_data / "brain"
    for cid in chat_ids:
        c_dir = brain_dir / cid
        (c_dir / ".system_generated" / "messages" / "undelivered").mkdir(parents=True, exist_ok=True)
        (c_dir / ".system_generated" / "logs").mkdir(parents=True, exist_ok=True)
        (c_dir / "walkthrough.md").write_text(f"# Walkthrough for {cid}\n", encoding="utf-8")
    return app_data


def test_cross_chat_hijack_prevention(tmp_path):
    """Scenario: User is actively working in Chat Beta.
    Chat Alpha finishes a task in the background and tries to dispatch a /g prompt using --delivery-mode gui.
    VERIFY:
    - Chat Alpha's prompt lands ONLY in Chat Alpha's mailbox.
    - Chat Beta's mailbox remains 100% untouched.
    - Zero AppleScript keystrokes were triggered.
    - Zero clipboard modification.
    """
    chats = ["chat-alpha-background", "chat-beta-active-user", "chat-gamma-idle"]
    app_data = _setup_mock_app_data(tmp_path, chats)

    alpha_id = "chat-alpha-background"
    beta_id = "chat-beta-active-user"
    gamma_id = "chat-gamma-idle"

    with patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity") as mock_keystroke, \
         patch("auto_reply_route.queue_paster.set_clipboard") as mock_set_clip:

        # Simulate Chat Alpha tool execution environment
        alpha_env = {
            "ANTIGRAVITY_SOURCE_METADATA": json.dumps({
                "tool": {
                    "conversationId": alpha_id,
                    "stepIndex": 42,
                }
            })
        }

        staged = queue_prompts_into_antigravity(
            prompt="/g (Step 2/4) wire doctor forensics into hud and menubar, build orphan reaper command, run tests",
            delivery_mode="gui",  # Naively requested by agent or rule
            countdown_seconds=0.0,
            app_data_dir=app_data,
            environ=alpha_env,
        )

        assert len(staged) == 1
        assert staged[0] == "/g (Step 2/4) wire doctor forensics into hud and menubar, build orphan reaper command, run tests"

        # 1. AppleScript and clipboard must NEVER be touched
        mock_keystroke.assert_not_called()
        mock_set_clip.assert_not_called()

        # 2. Check Chat Alpha mailbox (must have exactly 1 message)
        alpha_messages = list((app_data / "brain" / alpha_id / ".system_generated" / "messages").glob("*.json"))
        assert len(alpha_messages) == 1
        with open(alpha_messages[0]) as f:
            msg_data = json.load(f)
            assert msg_data["recipient"] == alpha_id
            assert msg_data["content"] == staged[0]
            assert msg_data["deliveryStrategy"] == "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE"

        # 3. Check Chat Beta mailbox (must be COMPLETELY EMPTY - zero cross-chat pollution!)
        beta_messages = list((app_data / "brain" / beta_id / ".system_generated" / "messages").glob("*.json"))
        assert len(beta_messages) == 0, f"Cross-chat pollution detected in Chat Beta! Found: {beta_messages}"

        # 4. Check Chat Gamma mailbox (must be COMPLETELY EMPTY)
        gamma_messages = list((app_data / "brain" / gamma_id / ".system_generated" / "messages").glob("*.json"))
        assert len(gamma_messages) == 0


def test_concurrent_multi_chat_dispatch(tmp_path):
    """Scenario: Multiple background chats dispatching /g and /q prompts simultaneously.
    VERIFY:
    - Every chat's messages are delivered strictly to its own mailbox without any collisions or cross-talk.
    """
    chats = [f"concurrent-chat-{i}" for i in range(5)]
    app_data = _setup_mock_app_data(tmp_path, chats)

    def dispatch_for_chat(cid: str, prompt_text: str):
        env = {
            "ANTIGRAVITY_CONVERSATION_ID": cid,
        }
        return queue_prompts_into_antigravity(
            prompt=prompt_text,
            delivery_mode="auto",
            countdown_seconds=0.0,
            app_data_dir=app_data,
            environ=env,
        )

    # Dispatch concurrently across 5 threads
    prompts_map = {
        cid: f"/g (Step 2/3) specialized task for {cid}"
        for cid in chats
    }

    with patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity") as mock_keystroke:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(dispatch_for_chat, cid, p): cid
                for cid, p in prompts_map.items()
            }
            for fut in concurrent.futures.as_completed(futures):
                fut.result()

        mock_keystroke.assert_not_called()

        # Verify strict 1:1 mapping in every chat's mailbox
        for cid in chats:
            msg_files = list((app_data / "brain" / cid / ".system_generated" / "messages").glob("*.json"))
            assert len(msg_files) == 1, f"Expected 1 message for {cid}, found {len(msg_files)}"
            with open(msg_files[0]) as f:
                data = json.load(f)
                assert data["recipient"] == cid
                assert data["content"] == prompts_map[cid]


def test_cli_subprocess_cross_chat_isolation(tmp_path):
    """Scenario: CLI invocation via subprocess running `python3 -m auto_reply_route.queue_paster`
    with ANTIGRAVITY_SOURCE_METADATA set to Chat A.
    VERIFY:
    - Subprocess exits 0.
    - Output explicitly shows targeted delivery promotion and zero GUI keystrokes.
    - Chat A receives the message, Chat B remains empty.
    """
    chats = ["cli-chat-alpha", "cli-chat-beta"]
    app_data = _setup_mock_app_data(tmp_path, chats)

    alpha_id = "cli-chat-alpha"
    beta_id = "cli-chat-beta"

    env = dict(os.environ)
    env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data)
    env["ANTIGRAVITY_CONVERSATION_ID"] = alpha_id
    env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({
        "tool": {
            "conversationId": alpha_id,
            "stepIndex": 99,
        }
    })

    prompt_cmd = "/g (Step 3/4) build orphan reaper command, run tests"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "auto_reply_route.queue_paster",
            prompt_cmd,
            "--delivery-mode",
            "gui",  # Even with explicit --delivery-mode gui, it must auto-promote
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert proc.returncode == 0
    assert "Promoting from GUI paste to Targeted Mailbox Delivery" in proc.stdout
    assert f"Enqueued to conversation {alpha_id}" in proc.stdout

    # Verify Chat Alpha has the message
    alpha_files = list((app_data / "brain" / alpha_id / ".system_generated" / "messages").glob("*.json"))
    assert len(alpha_files) == 1
    with open(alpha_files[0]) as f:
        data = json.load(f)
        assert data["recipient"] == alpha_id
        assert data["content"] == prompt_cmd

    # Verify Chat Beta has ZERO messages
    beta_files = list((app_data / "brain" / beta_id / ".system_generated" / "messages").glob("*.json"))
    assert len(beta_files) == 0


def test_no_guessing_fallback_when_unspecified(tmp_path):
    """Scenario: User runs queue_paster from terminal without any conversation ID.
    If GUI keystrokes fail, it must NEVER guess another chat directory by mtime;
    it must write to a scratch recovery file instead.
    """
    app_data = tmp_path / "antigravity"
    # Create an existing chat directory
    chat_dir = app_data / "brain" / "some-existing-chat"
    chat_dir.mkdir(parents=True)

    with patch("auto_reply_route.queue_paster.get_clipboard", return_value=""), \
         patch("auto_reply_route.queue_paster.set_clipboard", return_value=True), \
         patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity", return_value=False):

        prompts = queue_prompts_into_antigravity(
            prompt="Q 2 followups for database sharding",
            steps=2,
            delivery_mode="gui",
            countdown_seconds=0.0,
            app_data_dir=app_data,
            environ={},  # Clean environment (external terminal)
        )

        assert len(prompts) == 2

        # The existing chat mailbox must NOT have received anything!
        msg_dir = chat_dir / ".system_generated" / "messages"
        assert not msg_dir.exists() or len(list(msg_dir.glob("*.json"))) == 0

        # The scratch fallback file must exist
        fallback_file = app_data / "scratch" / "staged_prompts_fallback.json"
        assert fallback_file.exists()
        with open(fallback_file) as f:
            data = json.load(f)
            assert len(data) == 2


def test_concurrent_cli_processes_isolation(tmp_path):
    """Stress test: 3 distinct chat sessions invoking queue_paster CLI subprocesses concurrently.
    Verifies that under OS subprocess scheduling:
    - Every chat's message is placed in its own mailbox.
    - Zero cross-contamination between chats.
    - Every subprocess succeeds with exit code 0.
    """
    chats = ["chat-red", "chat-green", "chat-blue"]
    app_data = _setup_mock_app_data(tmp_path, chats)

    def run_cli_for_chat(cid: str):
        env = dict(os.environ)
        env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data)
        env["ANTIGRAVITY_CONVERSATION_ID"] = cid
        env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"conversationId": cid}})
        prompt = f"/g (Step 2/4) execute tasks for {cid}"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "auto_reply_route.queue_paster",
                prompt,
                "--delivery-mode",
                "gui",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        return cid, proc.returncode, proc.stdout

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run_cli_for_chat, chats))

    for cid, ret, stdout in results:
        assert ret == 0
        assert f"Enqueued to conversation {cid}" in stdout

    # Verify mailbox contents: exactly 1 message per chat, zero in wrong mailboxes
    for cid in chats:
        msg_files = list((app_data / "brain" / cid / ".system_generated" / "messages").glob("*.json"))
        assert len(msg_files) == 1, f"Expected exactly 1 message for {cid}, found {len(msg_files)}"
        with open(msg_files[0]) as f:
            d = json.load(f)
            assert d["recipient"] == cid
            assert cid in d["content"]

