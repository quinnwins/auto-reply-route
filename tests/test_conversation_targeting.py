"""Comprehensive Verification Tests for Targeted Conversation Delivery.

Verifies:
1. Multi-Conversation Isolation & Zero Cross-Chat Pollution:
   Messages destined for Conversation A physically exist ONLY in Conversation A's directory,
   and never leak to or affect Conversation B or Conversation C.
2. Zero Window Switching & Zero AppleScript:
   Targeted dispatch never calls osascript, never activates Antigravity, and never touches clipboard.
3. Resolution Priority Hierarchy:
   Explicit argument > ANTIGRAVITY_CONVERSATION_ID > ANTIGRAVITY_SOURCE_METADATA JSON > None.
4. Security & Path Traversal Resistance:
   Directory traversal sequences (../, slashes, null bytes, shell metachars) are rejected with ValueError.
5. Adaptive Guidance Integration:
   AdaptiveGuidanceController end-of-turn automatically delivers to the targeted conversation inbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from auto_reply_route.guidance import (
    AdaptiveGuidanceController,
    GuidanceStepState,
    GuidanceMode,
)
from auto_reply_route.queue_paster import (
    dispatch_prompt_to_conversation,
    queue_prompts_into_antigravity,
    resolve_conversation_id,
    main as queue_paster_main,
)


class TestConversationResolutionHierarchy:
    """Tests the resolution hierarchy for conversation ID discovery."""

    def test_explicit_argument_takes_highest_priority(self) -> None:
        environ = {
            "ANTIGRAVITY_CONVERSATION_ID": "env-conv-id",
            "ANTIGRAVITY_SOURCE_METADATA": json.dumps({"tool": {"conversationId": "meta-conv-id"}}),
        }
        res = resolve_conversation_id(conversation_id="explicit-conv-id", environ=environ)
        assert res == "explicit-conv-id"

    def test_environment_variable_takes_second_priority(self) -> None:
        environ = {
            "ANTIGRAVITY_CONVERSATION_ID": "env-conv-id",
            "ANTIGRAVITY_SOURCE_METADATA": json.dumps({"tool": {"conversationId": "meta-conv-id"}}),
        }
        res = resolve_conversation_id(conversation_id=None, environ=environ)
        assert res == "env-conv-id"

    def test_source_metadata_json_takes_third_priority(self) -> None:
        environ = {
            "ANTIGRAVITY_SOURCE_METADATA": json.dumps({"tool": {"conversationId": "meta-conv-id"}}),
        }
        res = resolve_conversation_id(conversation_id=None, environ=environ)
        assert res == "meta-conv-id"

    def test_missing_returns_none(self) -> None:
        res = resolve_conversation_id(conversation_id=None, environ={})
        assert res is None

    def test_empty_string_falls_back_to_environment(self) -> None:
        environ = {"ANTIGRAVITY_CONVERSATION_ID": "env-conv-id"}
        res = resolve_conversation_id(conversation_id="   ", environ=environ)
        assert res == "env-conv-id"


class TestSecurityAndPathTraversal:
    """Verifies that malicious or malformed conversation IDs cannot escape the brain root."""

    @pytest.mark.parametrize("malicious_id", [
        "../../etc/cron.d",
        "../traversal",
        "/absolute/root",
        "nested/path/to/file",
        "id_with\0null_byte",
        "id with spaces",
        "id;rm -rf /",
        "id`calc`",
        "id$(whoami)",
        "id&evil",
    ])
    def test_rejects_path_traversal_and_special_characters(self, malicious_id: str) -> None:
        with pytest.raises(ValueError):
            resolve_conversation_id(conversation_id=malicious_id)

    def test_dispatch_fails_with_helpful_error_when_no_id_found(self) -> None:
        with pytest.raises(ValueError, match="no conversation ID provided and none detected"):
            dispatch_prompt_to_conversation(
                prompt="test prompt",
                conversation_id=None,
                environ={},
            )


class TestMultiConversationIsolationAndZeroCrossTalk:
    """Verifies zero cross-chat pollution across concurrent conversation threads."""

    def test_isolated_dispatch_to_multiple_conversations(self, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        conv_alpha = "conv-alpha-session-1"
        conv_beta = "conv-beta-session-2"
        conv_gamma = "conv-gamma-session-3"  # Remains idle/empty

        # Dispatch 2 messages to Alpha
        receipt_a1 = dispatch_prompt_to_conversation(
            prompt="/g (Step 2/5) alpha step 2",
            conversation_id=conv_alpha,
            app_data_dir=app_data,
        )
        receipt_a2 = dispatch_prompt_to_conversation(
            prompt="/g (Step 3/5) alpha step 3",
            conversation_id=conv_alpha,
            app_data_dir=app_data,
        )

        # Dispatch 1 message to Beta
        receipt_b1 = dispatch_prompt_to_conversation(
            prompt="/g (Step 2/3) beta step 2",
            conversation_id=conv_beta,
            app_data_dir=app_data,
        )

        # 1. Verify Alpha inbox
        alpha_dir = app_data / "brain" / conv_alpha / ".system_generated" / "messages"
        alpha_files = sorted(alpha_dir.glob("*.json"))
        assert len(alpha_files) == 2

        with open(alpha_dir / f"{receipt_a1['id']}.json", "r", encoding="utf-8") as f:
            a1_data = json.load(f)
        assert a1_data["recipient"] == conv_alpha
        assert "/g (Step 2/5) alpha step 2" in a1_data["content"]

        with open(alpha_dir / f"{receipt_a2['id']}.json", "r", encoding="utf-8") as f:
            a2_data = json.load(f)
        assert a2_data["recipient"] == conv_alpha
        assert "/g (Step 3/5) alpha step 3" in a2_data["content"]

        # 2. Verify Beta inbox
        beta_dir = app_data / "brain" / conv_beta / ".system_generated" / "messages"
        beta_files = list(beta_dir.glob("*.json"))
        assert len(beta_files) == 1

        with open(beta_files[0], "r", encoding="utf-8") as f:
            b1_data = json.load(f)
        assert b1_data["recipient"] == conv_beta
        assert "/g (Step 2/3) beta step 2" in b1_data["content"]

        # 3. Verify Gamma inbox was NEVER created or touched
        gamma_dir = app_data / "brain" / conv_gamma
        assert not gamma_dir.exists(), "Gamma directory must never be created or touched"

        # 4. Zero Cross-Chat Pollution Invariant:
        # Alpha's messages must never appear in Beta's directory and vice-versa
        assert receipt_a1["id"] not in [f.stem for f in beta_files]
        assert receipt_a2["id"] not in [f.stem for f in beta_files]
        assert receipt_b1["id"] not in [f.stem for f in alpha_files]


class TestZeroWindowSwitchingAndZeroAppleScript:
    """Verifies that targeted delivery operates purely via filesystem without macOS UI side-effects."""

    @patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity")
    @patch("auto_reply_route.queue_paster.set_clipboard")
    def test_zero_applescript_when_targeted(
        self,
        mock_clipboard: MagicMock,
        mock_keystroke: MagicMock,
        tmp_path: Path,
    ) -> None:
        app_data = tmp_path / "antigravity"
        conv_id = "test-conv-no-ui"

        prompts = queue_prompts_into_antigravity(
            prompt="/q Build auth module 3 steps",
            steps=3,
            conversation_id=conv_id,
            app_data_dir=app_data,
            countdown_seconds=0.0,
            delay_between_steps=0.001,
        )

        assert len(prompts) == 3

        # UI actions must be completely bypassed
        mock_keystroke.assert_not_called()
        mock_clipboard.assert_not_called()

        # Files must exist in target inbox
        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        assert len(list(messages_dir.glob("*.json"))) == 3


class TestAdaptiveGuidanceTargetedIntegration:
    """Verifies that AdaptiveGuidanceController delivers end-of-turn follow-ups targeted to originating chat."""

    def test_adaptive_guidance_automatic_targeted_dispatch(self, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        conv_id = "conv-guidance-live-test"

        controller = AdaptiveGuidanceController(
            default_budget=5,
            conversation_id=conv_id,
            app_data_dir=app_data,
        )

        state, can_dispatch_upfront = controller.start_turn("/g (Step 1/5) run initial tests")
        assert can_dispatch_upfront is False

        task_result = controller.execute_task(
            lambda: {"success": False, "error": "AssertionError in payment_flow"},
            state,
        )

        next_prompt, should_dispatch = controller.evaluate_and_steer(state, task_result)
        assert should_dispatch is True
        assert "AssertionError in payment_flow" in next_prompt

        dispatched = controller.end_turn(state, should_dispatch)
        assert dispatched == next_prompt

        # Verify disk write to targeted inbox
        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        msg_files = list(messages_dir.glob("*.json"))
        assert len(msg_files) == 1

        with open(msg_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["recipient"] == conv_id
        assert data["content"] == next_prompt
        assert data["deliveryStrategy"] == "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE"

        # Verify undelivered indicator touched
        undelivered = messages_dir / "undelivered" / data["id"]
        assert undelivered.is_file()


class TestQueuePasterCLIIntegration:
    """Verifies CLI argument handling with --conversation-id."""

    @patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity")
    def test_cli_conversation_id_flag(self, mock_keystroke: MagicMock, tmp_path: Path) -> None:
        app_data = tmp_path / "antigravity"
        conv_id = "cli-target-conv"

        with patch("sys.argv", ["queue-paster", "refactor parser", "--steps", "2", "-C", conv_id]):
            with patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA_DIR": str(app_data)}):
                ret = queue_paster_main()
                assert ret == 0

        mock_keystroke.assert_not_called()
        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        assert len(list(messages_dir.glob("*.json"))) == 2
