"""Real-World Example Chat Simulation: Multi-Chat Isolation and Anti-Cross-Pollution Stress Test.

Creates real example chats in an isolated test environment, executes real CLI subprocesses
simulating active users, background agents, and tool calls, and rigorously asserts that
no cross-chat pollution, focus stealing, or message hijacking occurs.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import pytest


def create_example_chats(brain_root: Path, chat_specs: dict[str, str]) -> dict[str, Path]:
    """Creates directory structures for realistic example chats."""
    created = {}
    for cid, description in chat_specs.items():
        cdir = brain_root / cid
        (cdir / ".system_generated" / "messages" / "undelivered").mkdir(parents=True, exist_ok=True)
        (cdir / ".system_generated" / "logs").mkdir(parents=True, exist_ok=True)
        (cdir / "walkthrough.md").write_text(f"# {description}\nConversation ID: {cid}\n", encoding="utf-8")
        created[cid] = cdir
    return created


def test_real_world_example_chats_simulation():
    """Simulates 5 distinct realistic Antigravity chat sessions simultaneously."""
    temp_dir = Path(tempfile.mkdtemp(prefix="antigravity_test_chats_"))
    app_data_dir = temp_dir / "antigravity"
    brain_root = app_data_dir / "brain"

    try:
        # 1. Setup 5 Realistic Example Chats
        chat_specs = {
            "chat-01-user-active-terminal": "Active chat where the human user is currently typing",
            "chat-02-background-worker-research": "Background agent researching doctor diagnostics",
            "chat-03-background-worker-refactor": "Background agent refactoring parser modules",
            "chat-04-subagent-worker-audit": "Child subagent executing security audits",
            "chat-05-idle-standby": "Idle session from 2 hours ago",
        }
        chat_dirs = create_example_chats(brain_root, chat_specs)

        # -------------------------------------------------------------
        # SCENARIO 1: The Exact Bug Scenario (Cross-Chat Hijacking Vector)
        # -------------------------------------------------------------
        # Background Agent in chat-02 finishes a step and naively invokes:
        # queue_paster "/g (Step 2/4) wire doctor forensics" --delivery-mode gui
        # VERIFY:
        # - Automatic promotion to targeted mailbox for chat-02.
        # - Chat-01 (Active User) receives ZERO messages.
        # - Idle chats receive ZERO messages.

        worker_env = dict(os.environ)
        worker_env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data_dir)
        worker_env["ANTIGRAVITY_CONVERSATION_ID"] = "chat-02-background-worker-research"
        worker_env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({
            "tool": {
                "conversationId": "chat-02-background-worker-research",
                "stepIndex": 512,
            }
        })

        t1_prompt = "/g (Step 2/4) wire doctor forensics into hud and menubar, build orphan reaper command, run tests"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "auto_reply_route.queue_paster",
                t1_prompt,
                "--delivery-mode",
                "gui",  # Agent naively asks for GUI mode
            ],
            capture_output=True,
            text=True,
            env=worker_env,
            timeout=10,
        )

        assert proc.returncode == 0, f"Process failed: {proc.stderr}"
        assert "Promoting from GUI paste to Targeted Mailbox Delivery" in proc.stdout

        # Check Chat 02 mailbox (must have exactly 1 message)
        chat02_msgs = list((chat_dirs["chat-02-background-worker-research"] / ".system_generated" / "messages").glob("*.json"))
        assert len(chat02_msgs) == 1
        with open(chat02_msgs[0]) as f:
            c02_payload = json.load(f)
            assert c02_payload["recipient"] == "chat-02-background-worker-research"
            assert c02_payload["content"] == t1_prompt

        # Check Chat 01 mailbox (Active User) -> MUST BE EMPTY
        chat01_msgs = list((chat_dirs["chat-01-user-active-terminal"] / ".system_generated" / "messages").glob("*.json"))
        assert len(chat01_msgs) == 0, f"CRITICAL FAILURE: active user chat polluted! Found {chat01_msgs}"

        # Check Idle chats -> MUST BE EMPTY
        for cid in ["chat-03-background-worker-refactor", "chat-04-subagent-worker-audit", "chat-05-idle-standby"]:
            msgs = list((chat_dirs[cid] / ".system_generated" / "messages").glob("*.json"))
            assert len(msgs) == 0, f"Pollution found in {cid}!"

        # -------------------------------------------------------------
        # SCENARIO 2: High Concurrency Blast Across Multiple Chats
        # -------------------------------------------------------------
        # Firing 20 concurrent background dispatches across chats 02, 03, 04 simultaneously.
        def dispatch_worker(index: int, target_chat: str):
            env = dict(os.environ)
            env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data_dir)
            env["ANTIGRAVITY_CONVERSATION_ID"] = target_chat
            env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"conversationId": target_chat, "workerId": index}})
            prompt = f"/g (Step {index}/5) concurrent worker step {index} for {target_chat}"
            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "auto_reply_route.queue_paster",
                    prompt,
                    "--delivery-mode",
                    "auto",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            return target_chat, index, res.returncode, res.stdout

        tasks = []
        for i in range(1, 21):
            target = f"chat-0{(i % 3) + 2}-background-worker-refactor" if (i % 3) == 1 else (
                "chat-04-subagent-worker-audit" if (i % 3) == 2 else "chat-02-background-worker-research"
            )
            tasks.append((i, target))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = [pool.submit(dispatch_worker, idx, tgt) for idx, tgt in tasks]
            for fut in concurrent.futures.as_completed(results):
                tgt, idx, code, out = fut.result()
                assert code == 0, f"Worker {idx} targeting {tgt} failed!"

        # Verify chat-01 (Active User) is STILL 100% clean
        chat01_msgs_after = list((chat_dirs["chat-01-user-active-terminal"] / ".system_generated" / "messages").glob("*.json"))
        assert len(chat01_msgs_after) == 0, "Chat 01 polluted during concurrent burst!"

        total_received = 0
        for cid in ["chat-02-background-worker-research", "chat-03-background-worker-refactor", "chat-04-subagent-worker-audit"]:
            msgs = list((chat_dirs[cid] / ".system_generated" / "messages").glob("*.json"))
            total_received += len(msgs)
            for m in msgs:
                with open(m) as f:
                    p = json.load(f)
                    assert p["recipient"] == cid, f"Wrong recipient {p['recipient']} found in {cid}!"
                    # Verify undelivered indicator file exists
                    indicator = chat_dirs[cid] / ".system_generated" / "messages" / "undelivered" / p["id"]
                    assert indicator.exists(), f"Indicator file missing for {p['id']}"

        assert total_received == 21, f"Expected 21 total messages, found {total_received}"

        # -------------------------------------------------------------
        # SCENARIO 3: External Terminal Execution (Zero-Guessing Invariant)
        # -------------------------------------------------------------
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "ANTIGRAVITY_APP_DATA_DIR": str(app_data_dir),
        }

        # Touch chat-01 to give it the freshest mtime
        (chat_dirs["chat-01-user-active-terminal"] / "walkthrough.md").touch()

        res_no_conv = subprocess.run(
            [
                sys.executable,
                "-m",
                "auto_reply_route.queue_paster",
                "/g test prompt from external terminal",
                "--delivery-mode",
                "targeted",
            ],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert res_no_conv.returncode != 0
        assert "no conversation ID could be resolved" in res_no_conv.stderr or "Targeted delivery requested but no conversation ID" in res_no_conv.stderr

        # -------------------------------------------------------------
        # SCENARIO 4: Security Hardening (Path Traversal Rejection)
        # -------------------------------------------------------------
        malicious_ids = ["../../etc", "chat/../../../etc/passwd", "..\\..\\windows\\system32"]
        for bad_id in malicious_ids:
            bad_env = dict(worker_env)
            bad_env["ANTIGRAVITY_CONVERSATION_ID"] = bad_id
            proc_bad = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "auto_reply_route.queue_paster",
                    "innocent prompt",
                    "-C",
                    bad_id,
                ],
                capture_output=True,
                text=True,
                env=bad_env,
            )
            assert proc_bad.returncode != 0
            assert "Invalid conversation ID" in proc_bad.stderr or "ValueError" in proc_bad.stderr

        # Test embedded null byte directly against validation
        from auto_reply_route.queue_paster import resolve_conversation_id
        with pytest.raises(ValueError):
            resolve_conversation_id(conversation_id="chat\x00evil")

        # -------------------------------------------------------------
        # SCENARIO 5: Schema Strictness and Message Deliverability
        # -------------------------------------------------------------
        sample_msg = next((chat_dirs["chat-02-background-worker-research"] / ".system_generated" / "messages").glob("*.json"))
        with open(sample_msg) as f:
            msg = json.load(f)
        required_keys = {"id", "recipient", "sender", "priority", "timestamp", "content", "deliveryStrategy"}
        missing = required_keys - set(msg.keys())
        assert not missing, f"Missing required keys in message schema: {missing}"
        assert msg["priority"] == "MESSAGE_PRIORITY_HIGH"
        assert msg["deliveryStrategy"] == "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE"
        assert msg["timestamp"].endswith("Z")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_real_wrapper_binary_execution(tmp_path):
    """Verifies that the actual installed /Users/qenglish/.local/bin/queue_paster
    wrapper correctly auto-promotes and isolates chats."""
    wrapper_bin = Path("/Users/qenglish/.local/bin/queue_paster")
    if not wrapper_bin.exists():
        pytest.skip("Local binary /Users/qenglish/.local/bin/queue_paster not present")

    app_data = tmp_path / "antigravity"
    chats = ["bin-chat-1", "bin-chat-2-user-active"]
    create_example_chats(app_data / "brain", {c: f"Chat {c}" for c in chats})

    env = dict(os.environ)
    env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data)
    env["ANTIGRAVITY_CONVERSATION_ID"] = "bin-chat-1"
    env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"conversationId": "bin-chat-1"}})

    prompt = "/g (Step 2/3) test real wrapper binary execution"
    res = subprocess.run(
        [str(wrapper_bin), prompt, "--delivery-mode", "gui"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert res.returncode == 0
    assert "Promoting from GUI paste to Targeted Mailbox Delivery" in res.stdout

    # Verify bin-chat-1 received message
    c1_msgs = list((app_data / "brain" / "bin-chat-1" / ".system_generated" / "messages").glob("*.json"))
    assert len(c1_msgs) == 1
    with open(c1_msgs[0]) as f:
        data = json.load(f)
        assert data["recipient"] == "bin-chat-1"
        assert data["content"] == prompt

    # Verify bin-chat-2 received ZERO messages
    c2_msgs = list((app_data / "brain" / "bin-chat-2-user-active" / ".system_generated" / "messages").glob("*.json"))
    assert len(c2_msgs) == 0


def test_multi_turn_adaptive_g_simulation(tmp_path):
    """Simulates multi-turn /g sequences occurring in two chats simultaneously
    while a third chat has the user actively working.
    Verifies that neither chat crosses boundaries across multiple sequential turns.
    """
    app_data = tmp_path / "antigravity"
    chats = {
        "user-active-chat": "Active human chat",
        "chat-feature-alpha": "Feature Alpha chat running 3-step loop",
        "chat-bugfix-beta": "Bugfix Beta chat running 2-step loop",
    }
    create_example_chats(app_data / "brain", chats)

    # Chat Alpha 3-step sequence
    alpha_steps = [
        "/g (Step 1/3) inspect error logs in auth module",
        "/g (Step 2/3) patch token refresh race condition and write test",
        "/g (Step 3/3) verify all 50 auth integration tests pass",
    ]

    # Chat Beta 2-step sequence
    beta_steps = [
        "/g (Step 1/2) add responsive padding to mobile navbar",
        "/g (Step 2/2) run visual regression check on mobile viewport",
    ]

    def run_turn(cid: str, step_text: str):
        env = dict(os.environ)
        env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data)
        env["ANTIGRAVITY_CONVERSATION_ID"] = cid
        env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"conversationId": cid}})
        return subprocess.run(
            [sys.executable, "-m", "auto_reply_route.queue_paster", step_text, "--delivery-mode", "gui"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

    # Interleave turns from Chat Alpha and Chat Beta concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = []
        for s in alpha_steps:
            futs.append(pool.submit(run_turn, "chat-feature-alpha", s))
        for s in beta_steps:
            futs.append(pool.submit(run_turn, "chat-bugfix-beta", s))
        for f in concurrent.futures.as_completed(futs):
            res = f.result()
            assert res.returncode == 0

    # Verify Chat Alpha has exactly 3 messages, all addressed to Alpha
    alpha_msgs = sorted(
        list((app_data / "brain" / "chat-feature-alpha" / ".system_generated" / "messages").glob("*.json")),
        key=lambda p: p.stat().st_mtime,
    )
    assert len(alpha_msgs) == 3
    for m in alpha_msgs:
        with open(m) as f:
            d = json.load(f)
            assert d["recipient"] == "chat-feature-alpha"
            assert any(s in d["content"] for s in alpha_steps)

    # Verify Chat Beta has exactly 2 messages, all addressed to Beta
    beta_msgs = sorted(
        list((app_data / "brain" / "chat-bugfix-beta" / ".system_generated" / "messages").glob("*.json")),
        key=lambda p: p.stat().st_mtime,
    )
    assert len(beta_msgs) == 2
    for m in beta_msgs:
        with open(m) as f:
            d = json.load(f)
            assert d["recipient"] == "chat-bugfix-beta"
            assert any(s in d["content"] for s in beta_steps)

    # Verify User Active Chat has ZERO messages
    user_msgs = list((app_data / "brain" / "user-active-chat" / ".system_generated" / "messages").glob("*.json"))
    assert len(user_msgs) == 0, f"User chat polluted! Found {user_msgs}"


def test_50_concurrent_burst_across_10_chats(tmp_path):
    """Massive concurrency burst: 50 requests across 10 chats simultaneously.
    Verifies atomic writing, zero file locking collisions, zero dropped messages,
    and 100% strict routing under load.
    """
    app_data = tmp_path / "antigravity"
    chats = {f"burst-chat-{i}": f"Concurrent Chat {i}" for i in range(10)}
    create_example_chats(app_data / "brain", chats)

    def dispatch_burst(req_id: int):
        target_chat = f"burst-chat-{req_id % 10}"
        env = dict(os.environ)
        env["ANTIGRAVITY_APP_DATA_DIR"] = str(app_data)
        env["ANTIGRAVITY_CONVERSATION_ID"] = target_chat
        env["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"conversationId": target_chat}})
        prompt = f"/g (Step 2/3) burst request {req_id} targeting {target_chat}"
        res = subprocess.run(
            [sys.executable, "-m", "auto_reply_route.queue_paster", prompt, "--delivery-mode", "auto"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        return req_id, target_chat, res.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(dispatch_burst, i) for i in range(50)]
        for fut in concurrent.futures.as_completed(futures):
            req_id, tgt, code = fut.result()
            assert code == 0, f"Request {req_id} failed with code {code}"

    # Verify that each of the 10 chats has exactly 5 messages
    for i in range(10):
        cid = f"burst-chat-{i}"
        msgs = list((app_data / "brain" / cid / ".system_generated" / "messages").glob("*.json"))
        assert len(msgs) == 5, f"Expected 5 messages in {cid}, found {len(msgs)}"
        for m in msgs:
            with open(m) as f:
                d = json.load(f)
                assert d["recipient"] == cid
                assert cid in d["content"]

