from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from auto_reply_route.queue_paster import (
    get_clipboard,
    set_clipboard,
    send_keystroke_to_antigravity,
    queue_prompts_into_antigravity,
)


def test_clipboard_helpers():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="test clipboard text")
        assert get_clipboard() == "test clipboard text"

    with patch("subprocess.Popen") as mock_popen:
        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        mock_popen.return_value = proc
        assert set_clipboard("hello") is True


def test_send_keystroke_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert send_keystroke_to_antigravity() is True


def test_send_keystroke_timeout_handled():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=3)):
        # Must gracefully return False without raising
        assert send_keystroke_to_antigravity() is False


def test_queue_prompts_preserves_clipboard():
    """Verifies that in standard queue staging (no conversation ID), clipboard is preserved."""
    with patch("auto_reply_route.queue_paster.get_clipboard", return_value="original text"), \
         patch("auto_reply_route.queue_paster.set_clipboard") as mock_set_clip, \
         patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity", return_value=True):

        prompts = queue_prompts_into_antigravity(
            prompt="dental cavitation device",
            steps=5,
            subagents=3,
            delay_between_steps=0.01,
            countdown_seconds=0.0,
        )

        assert len(prompts) == 5
        # Verify first prompt matches expected format
        assert "subagent team" in prompts[0]
        # Verify original clipboard was restored at the end
        mock_set_clip.assert_called_with("original text")


def test_queue_prompts_defaults_to_no_subagents():
    from auto_reply_route.queue_paster import parse_queue_command
    with patch("auto_reply_route.queue_paster.get_clipboard", return_value=""), \
         patch("auto_reply_route.queue_paster.set_clipboard"), \
         patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity", return_value=True):

        # When subagents not specified in command, subagents is 0
        prompts = queue_prompts_into_antigravity(
            prompt="Q 5 follow ups for making this ready for daily use",
            steps=5,
            delay_between_steps=0.01,
            countdown_seconds=0.0,
        )

        assert len(prompts) == 5
        for p in prompts:
            assert "subagent" not in p.lower()


def test_queue_prompts_targeted_delivery_bypasses_applescript(tmp_path):
    """Verifies that targeted conversation delivery writes directly to inbox with zero AppleScript."""
    app_data = tmp_path / "antigravity"
    conv_id = "test-conv-targeted-paster"

    with patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity") as mock_keystroke, \
         patch("auto_reply_route.queue_paster.set_clipboard") as mock_set_clip:

        prompts = queue_prompts_into_antigravity(
            prompt="Q 3 follow ups for database sharding",
            steps=3,
            delay_between_steps=0.001,
            countdown_seconds=0.0,
            conversation_id=conv_id,
            app_data_dir=app_data,
        )

        assert len(prompts) == 3
        # AppleScript and clipboard must NEVER be touched in targeted mode
        mock_keystroke.assert_not_called()
        mock_set_clip.assert_not_called()

        # Messages must exist on disk in the targeted conversation directory
        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        msg_files = list(messages_dir.glob("*.json"))
        assert len(msg_files) == 3

        # Undelivered indicators must exist
        undelivered_files = list((messages_dir / "undelivered").glob("*"))
        assert len(undelivered_files) == 3


def test_queue_prompts_auto_routes_single_g_prompt(tmp_path):
    """Verifies that a single /g custom prompt automatically activates targeted delivery when in Antigravity."""
    app_data = tmp_path / "antigravity"
    conv_id = "conv-auto-g-route"

    with patch("auto_reply_route.queue_paster.send_keystroke_to_antigravity") as mock_keystroke, \
         patch("auto_reply_route.queue_paster.set_clipboard") as mock_set_clip:

        environ = {"ANTIGRAVITY_CONVERSATION_ID": conv_id}
        prompts = queue_prompts_into_antigravity(
            prompt="/g (Step 2/5) follow up task",
            custom_prompts=["/g (Step 2/5) follow up task"],
            countdown_seconds=0.0,
            app_data_dir=app_data,
            environ=environ,
        )

        assert len(prompts) == 1
        mock_keystroke.assert_not_called()
        mock_set_clip.assert_not_called()

        messages_dir = app_data / "brain" / conv_id / ".system_generated" / "messages"
        msg_files = list(messages_dir.glob("*.json"))
        assert len(msg_files) == 1


def test_parse_queue_command_variations():
    from auto_reply_route.queue_paster import parse_queue_command

    # Without subagents
    p, n, s = parse_queue_command("Q 5 follow ups for making this ready for my daily use")
    assert p == "making this ready for my daily use"
    assert n == 5
    assert s == 0

    # With subagents in parentheses
    p, n, s = parse_queue_command("Q 5 follow ups (3 subagents) for dental cavitation device")
    assert p == "dental cavitation device"
    assert n == 5
    assert s == 3

    # With 'with 2 subagents'
    p, n, s = parse_queue_command("Queue 4 followups with 2 subagents for ecommerce checkout")
    assert p == "ecommerce checkout"
    assert n == 4
    assert s == 2

    # Plain text without command prefix
    p, n, s = parse_queue_command("dental cavitation device")
    assert p == "dental cavitation device"
    assert n == 5
    assert s == 0

    # With ask g modifier
    p, n, s = parse_queue_command("/q Build Stripe webhook endpoint ask g")
    assert p == "Build Stripe webhook endpoint"
    assert n == 5
    assert s == 0


def test_is_ask_g_and_v4_parser():
    from auto_reply_route.queue_paster import is_ask_g_command, parse_queue_command_v4

    assert is_ask_g_command("ask g") is True
    assert is_ask_g_command("ask-g") is True
    assert is_ask_g_command("Ask G") is True
    assert is_ask_g_command("/q build webhook ask g 3 sub") is True
    assert is_ask_g_command("basket of apples") is False

    p, n, s, ask_g = parse_queue_command_v4("/q 4 followups (2 subagents) for ecommerce checkout ask g")
    assert p == "ecommerce checkout"
    assert n == 4
    assert s == 2
    assert ask_g is True

    p2, n2, s2, ask_g2 = parse_queue_command_v4("dental device")
    assert p2 == "dental device"
    assert n2 == 5
    assert s2 == 0
    assert ask_g2 is False


def test_trailing_step_configuration():
    from auto_reply_route.queue_paster import parse_queue_command, parse_queue_command_v4

    # Trailing steps
    p, n, s = parse_queue_command("/q build stripe webhook 3 steps")
    assert p == "build stripe webhook"
    assert n == 3
    assert s == 0

    # Trailing steps + subagents
    p, n, s = parse_queue_command("/q build stripe webhook 3 steps 2 sub")
    assert p == "build stripe webhook"
    assert n == 3
    assert s == 2

    # Reverse order: subagents then steps
    p, n, s = parse_queue_command("/q build stripe webhook 2 sub 4 steps")
    assert p == "build stripe webhook"
    assert n == 4
    assert s == 2

    # Trailing turns / followups
    p, n, s = parse_queue_command("/q review architecture 2 turns")
    assert p == "review architecture"
    assert n == 2

    # With ask g and trailing steps
    p, n, s, ask_g = parse_queue_command_v4("/q build auth 3 steps ask g")
    assert p == "build auth"
    assert n == 3
    assert ask_g is True


def test_technical_prefixes_and_command_words_preserved():
    from auto_reply_route.queue_paster import parse_queue_command

    # Technical numbers must not be stripped as steps
    p, n, s = parse_queue_command("/q 404 error handler")
    assert p == "404 error handler"
    assert n == 5

    p, n, s = parse_queue_command("/q 2fa login flow")
    assert p == "2fa login flow"
    assert n == 5

    p, n, s = parse_queue_command("/q 500 server crash recovery")
    assert p == "500 server crash recovery"
    assert n == 5

    # Domain prompts with 'queue' or 'q' must not be stripped unless followed by numbers or with slash
    p, n, s = parse_queue_command("queue implementation in C")
    assert p == "queue implementation in C"
    assert n == 5

    p, n, s = parse_queue_command("q learning agent in pytorch")
    assert p == "q learning agent in pytorch"
    assert n == 5


def test_extract_json_array():
    from auto_reply_route.queue_paster import extract_json_array

    # 1. Direct JSON array
    assert extract_json_array('["prompt 1", "prompt 2"]') == ["prompt 1", "prompt 2"]

    # 2. Markdown fenced code block
    fenced = '```json\n["step a", "step b"]\n```'
    assert extract_json_array(fenced) == ["step a", "step b"]

    # 3. Trailing commentary or prompt reminder hooks
    with_hook = (
        '["investigate canvas", "build prototype"]\n\n'
        'For every decision, ask what the best expert in that field would do...'
    )
    assert extract_json_array(with_hook) == ["investigate canvas", "build prototype"]

    # 4. Invalid or empty
    assert extract_json_array("") is None
    assert extract_json_array("not json at all") is None
    assert extract_json_array('{"key": "val"}') is None


def test_synthesize_bespoke_followups_via_flash_success():
    from auto_reply_route.queue_paster import synthesize_bespoke_followups_via_flash
    from unittest.mock import patch, MagicMock

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '["Task 1: Scaffold routing", "Task 2: Implement crew UI", "Task 3: Integration tests"]'

    with patch("shutil.which", return_value="/mock/bin/agy"), \
         patch("subprocess.run", return_value=mock_proc):
        prompts = synthesize_bespoke_followups_via_flash("canvassing route optimizer", steps=3)
        assert prompts == [
            "Task 1: Scaffold routing",
            "Task 2: Implement crew UI",
            "Task 3: Integration tests",
        ]


def test_synthesize_bespoke_followups_via_flash_fail_open():
    import subprocess
    from unittest.mock import patch, MagicMock
    from auto_reply_route.queue_paster import synthesize_bespoke_followups_via_flash

    # 1. Missing executable
    with patch("shutil.which", return_value=None), \
         patch("os.path.exists", return_value=False):
        assert synthesize_bespoke_followups_via_flash("test prompt") is None

    # 2. Timeout
    with patch("shutil.which", return_value="/mock/bin/agy"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=12.0)):
        assert synthesize_bespoke_followups_via_flash("test prompt") is None

    # 3. Non-zero exit code
    mock_err = MagicMock(returncode=1, stdout="Error")
    with patch("shutil.which", return_value="/mock/bin/agy"), \
         patch("subprocess.run", return_value=mock_err):
        assert synthesize_bespoke_followups_via_flash("test prompt") is None

    # 4. Malformed output
    mock_bad = MagicMock(returncode=0, stdout="Random non-json chatter")
    with patch("shutil.which", return_value="/mock/bin/agy"), \
         patch("subprocess.run", return_value=mock_bad):
        assert synthesize_bespoke_followups_via_flash("test prompt") is None


def test_queue_prompts_with_ai_flag_and_fallback():
    from unittest.mock import patch
    from auto_reply_route.queue_paster import queue_prompts_into_antigravity

    # Succeeded AI synthesis with subagents formatting
    with patch("auto_reply_route.queue_paster.synthesize_bespoke_followups_via_flash", return_value=["Do step 1", "Do step 2"]):
        prompts = queue_prompts_into_antigravity(
            prompt="implement offline sync",
            steps=2,
            subagents=3,
            use_ai=True,
            dry_run=True,
        )
        assert len(prompts) == 2
        assert "with 3 subagents" in prompts[0]
        assert "with 3 subagents" in prompts[1]

    # Failed AI synthesis falls open to deterministic template
    with patch("auto_reply_route.queue_paster.synthesize_bespoke_followups_via_flash", return_value=None):
        prompts = queue_prompts_into_antigravity(
            prompt="implement offline sync",
            steps=3,
            subagents=0,
            use_ai=True,
            dry_run=True,
        )
        assert len(prompts) == 3
        # Should be the engineering deterministic prompts
        assert any("sync" in p.lower() or "offline" in p.lower() for p in prompts)


