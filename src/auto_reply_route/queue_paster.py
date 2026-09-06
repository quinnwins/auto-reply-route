"""Native Antigravity Queue Paster & Visual Queue Stager.

Generates structured, multi-turn follow-up prompts tailored to a seed idea
and stages them directly into Antigravity's native `Queued Messages (N)` box.

Preserves the user's existing clipboard contents and enforces strict 2-second
AppleScript timeouts to guarantee zero system freezes or lockups.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional, Union

# Ensure package root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_reply_route.builder import generate_followup_queue
from auto_reply_route.hook_driver import QueueDispatcher, _validate_conversation_id


def get_clipboard() -> str:
    """Safely retrieves the current clipboard contents."""
    try:
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return res.stdout
    except Exception:
        return ""


def set_clipboard(text: str) -> bool:
    """Safely sets the clipboard contents via pbcopy."""
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-8"), timeout=2)
        return p.returncode == 0
    except Exception:
        return False


def send_keystroke_to_antigravity(app_name: str = "Antigravity") -> bool:
    """Focuses Antigravity, pastes current clipboard, and presses Return.
    
    Enforces a strict 2-second timeout to prevent any macOS TCC hangs.
    """
    script = f'''
    with timeout of 2 seconds
        tell application "{app_name}" to activate
        delay 0.15
        tell application "System Events"
            keystroke "v" using {{command down}}
            delay 0.12
            key code 36
        end tell
    end timeout
    '''
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        print("⚠️ Warning: AppleScript timed out after 3 seconds.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"⚠️ Warning: AppleScript error: {e}", file=sys.stderr)
        return False


import re


def parse_queue_command(text: str, default_steps: int = 5, default_subagents: int = 0) -> tuple[str, int, int]:
    """Parses natural language and slash queue commands like:
    - '/q dental cavitation plaque removal device' -> ('dental cavitation plaque removal device', 5, 0)
    - '/q 5 dental device' -> ('dental device', 5, 0)
    - '/q 5 (3 subagents) dental device' -> ('dental device', 5, 3)
    - '/q look at this from multiple angles 5 sub' -> ('look at this from multiple angles', 5, 5)
    - 'Q 5 follow ups for making this ready for my daily use' -> ('making this ready for my daily use', 5, 0)
    """
    clean = text.strip()

    # 1. Strip leading command prefix: /q, /queue-prompts, /queue, Q, Queue
    prefix_pattern = re.compile(r"^(?:/?queue-prompts\b|/?queue\b|/?q\b)\s*", re.IGNORECASE)
    m_prefix = prefix_pattern.match(clean)
    if m_prefix:
        body = clean[m_prefix.end():].strip()
    else:
        body = clean

    steps = default_steps
    subagents = default_subagents

    # 1.5 Strip 'ask g' if present anywhere in body so trailing steps/subagents can be matched
    if is_ask_g_command(body):
        body = re.sub(r"\bask[\s\-_]*g\b", "", body, flags=re.IGNORECASE).strip()
        body = re.sub(r"\s+", " ", body).strip()

    # 2. Check for leading step count (e.g. "5 ...", "5 follow ups ...", "3 steps ...")
    leading_steps = re.match(r"^(\d+)\s*(?:follow\s*ups?|followups?|steps?|turns?)?\s*(?:for|:|-)?\s*", body, re.IGNORECASE)
    if leading_steps:
        steps = int(leading_steps.group(1))
        body = body[leading_steps.end():].strip()

    # 3. Check for leading subagent specification (e.g. "(3 subagents)", "with 3 subagents")
    sub_prefix = re.match(
        r"^(?:\((?:up to )?(\d+)\s*sub(?:agent)?s?\)|with (\d+)\s*sub(?:agent)?s?|(\d+)\s*sub(?:agent)?s?)\s*(?:for|:|-)?\s*",
        body,
        re.IGNORECASE,
    )
    if sub_prefix:
        for g in sub_prefix.groups():
            if g:
                subagents = int(g)
                break
        body = body[sub_prefix.end():].strip()

    # 4. Loop for trailing modifiers (subagents, steps) in any order
    while True:
        m_sub = re.search(r"[\s,\-\(]+(?:with\s+)?(\d+)\s*sub(?:agent)?s?\)?$", body, re.IGNORECASE)
        if m_sub:
            subagents = int(m_sub.group(1))
            body = body[:m_sub.start()].strip()
            continue
        m_step = re.search(r"[\s,\-\(]+(\d+)\s*(?:steps?|turns?|follow\s*ups?|followups?)\)?$", body, re.IGNORECASE)
        if m_step:
            steps = int(m_step.group(1))
            body = body[:m_step.start()].strip()
            continue
        break

    # 5. Clean up any remaining leading separators ("for", ":", "-")
    body = re.sub(r"^(?:for|:|-)\s*", "", body, flags=re.IGNORECASE).strip()

    return body or clean, steps, subagents



def is_ask_g_command(text: str) -> bool:
    """Checks if text contains the 'ask g' / 'ask-g' adaptive directive."""
    return bool(re.search(r"\bask[\s\-_]*g\b", text, re.IGNORECASE))


def parse_queue_command_v4(text: str, default_steps: int = 5, default_subagents: int = 0) -> tuple[str, int, int, bool]:
    """Extended parser returning (seed_prompt, steps, subagents, is_ask_g)."""
    ask_g = is_ask_g_command(text)
    prompt, steps, subagents = parse_queue_command(text, default_steps, default_subagents)
    return prompt, steps, subagents, ask_g


def resolve_conversation_id(
    conversation_id: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Resolves the active Antigravity conversation ID from parameters or environment.

    Resolution hierarchy:
    1. Explicit conversation_id parameter (if provided and non-empty)
    2. Environment variable `ANTIGRAVITY_CONVERSATION_ID`
    3. JSON metadata in `ANTIGRAVITY_SOURCE_METADATA` (`tool.conversationId`)

    Returns validated, safe conversation ID string, or None if not determinable.
    Raises ValueError if an explicit or environment ID fails path traversal checks.
    """
    env = os.environ if environ is None else environ

    # 1. Explicit argument
    if conversation_id is not None:
        clean = conversation_id.strip()
        if clean:
            return _validate_conversation_id(clean)

    # 2. Environment variable ANTIGRAVITY_CONVERSATION_ID
    env_id = env.get("ANTIGRAVITY_CONVERSATION_ID")
    if env_id is not None:
        clean = env_id.strip()
        if clean:
            return _validate_conversation_id(clean)

    # 3. ANTIGRAVITY_SOURCE_METADATA JSON
    source_meta = env.get("ANTIGRAVITY_SOURCE_METADATA")
    if source_meta and source_meta.strip():
        try:
            parsed = json.loads(source_meta)
            tool_meta = parsed.get("tool", {})
            meta_id = tool_meta.get("conversationId")
            if meta_id and isinstance(meta_id, str):
                clean = meta_id.strip()
                if clean:
                    return _validate_conversation_id(clean)
        except Exception:
            pass

    return None


def dispatch_prompt_to_conversation(
    prompt: str,
    conversation_id: Optional[str] = None,
    app_data_dir: Optional[Union[str, Path]] = None,
    priority: str = "MESSAGE_PRIORITY_HIGH",
    delivery_strategy: str = "MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE",
    environ: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Atomically dispatches a prompt directly to the targeted conversation inbox.

    Guarantees:
    - Zero window switching or OS focus changes (no AppleScript)
    - Zero cross-chat pollution (strictly scoped to conversation brain dir)
    - Zero clipboard modification

    Returns the message payload receipt dict.
    Raises ValueError if no conversation ID could be resolved or if validation fails.
    """
    safe_conv_id = resolve_conversation_id(conversation_id=conversation_id, environ=environ)
    if not safe_conv_id:
        raise ValueError(
            "Cannot dispatch targeted prompt: no conversation ID provided and none detected in environment."
        )

    dispatcher = QueueDispatcher(app_data_dir=app_data_dir)
    return dispatcher.queue_user_message(
        conversation_id=safe_conv_id,
        content=prompt,
        priority=priority,
        sender="user",
        delivery_strategy=delivery_strategy,
    )


def queue_prompts_into_antigravity(
    prompt: str,
    steps: int = 5,
    subagents: int = 0,
    delay_between_steps: float = 0.35,
    countdown_seconds: float = 1.5,
    app_name: str = "Antigravity",
    custom_prompts: Optional[list[str]] = None,
    conversation_id: Optional[str] = None,
    app_data_dir: Optional[Union[str, Path]] = None,
    environ: Optional[dict[str, str]] = None,
    delivery_mode: str = "auto",
) -> list[str]:
    """Generates the prompt sequence and stages them into Antigravity's native queue.

    Delivery modes:
    - "auto" (default): Uses targeted inbox delivery if explicit conversation_id is provided,
      or if custom_prompts has a single `/g` adaptive follow-up. Otherwise uses AppleScript
      GUI paster so upfront `/q` prompts appear visibly in the GUI 'Queued Messages' tray.
    - "targeted": Forces direct atomic mailbox delivery via QueueDispatcher (zero focus stealing).
    - "gui": Forces AppleScript GUI keystroke paste into the frontmost window.

    Returns the list of generated/staged prompt strings.
    """
    # Auto-parse natural language command if present
    parsed_prompt, parsed_steps, parsed_subagents = parse_queue_command(
        prompt, default_steps=steps, default_subagents=subagents
    )
    actual_prompt = parsed_prompt or prompt
    actual_steps = parsed_steps if parsed_steps != 5 or steps == 5 else steps
    actual_subagents = parsed_subagents if parsed_subagents > 0 else subagents

    if custom_prompts:
        prompts = list(custom_prompts)[:actual_steps]
    else:
        manifest = generate_followup_queue(actual_prompt, count=actual_steps, max_subagents=actual_subagents)
        prompts = [msg.prompt for msg in manifest.messages]

    if not prompts:
        print("❌ No prompts generated.")
        return []

    print(f"\n📋 Generated {len(prompts)} Follow-Up Prompts for: \"{actual_prompt}\"")
    print(f"👥 Subagents per team: {actual_subagents if actual_subagents > 0 else 'None (Single Agent)'}\n")
    for i, p in enumerate(prompts):
        preview = p if len(p) <= 80 else p[:77] + "..."
        print(f"   [{i + 1}/{len(prompts)}] {preview}")

    # Determine delivery routing
    target_conv_id: Optional[str] = None
    should_use_targeted = False

    if delivery_mode == "targeted":
        target_conv_id = resolve_conversation_id(conversation_id=conversation_id, environ=environ)
        if not target_conv_id:
            raise ValueError("Targeted delivery requested but no conversation ID could be resolved.")
        should_use_targeted = True
    elif delivery_mode == "gui":
        should_use_targeted = False
    elif delivery_mode == "auto":
        if conversation_id is not None and bool(str(conversation_id).strip()):
            target_conv_id = resolve_conversation_id(conversation_id=conversation_id, environ=environ)
            should_use_targeted = bool(target_conv_id)
        elif custom_prompts and len(custom_prompts) == 1 and str(custom_prompts[0]).strip().startswith("/g"):
            target_conv_id = resolve_conversation_id(conversation_id=None, environ=environ)
            should_use_targeted = bool(target_conv_id)
        else:
            should_use_targeted = False

    if should_use_targeted and target_conv_id:
        print(f"\n🎯 Targeted Delivery Active: Routing directly to conversation '{target_conv_id}'")
        print(f"   (Zero focus stealing, zero window switching, zero cross-chat pollution)\n")

        dispatcher = QueueDispatcher(app_data_dir=app_data_dir)
        for i, p in enumerate(prompts):
            receipt = dispatcher.queue_user_message(
                conversation_id=target_conv_id,
                content=p,
                priority="MESSAGE_PRIORITY_HIGH",
                sender="user",
                delivery_strategy="MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE",
            )
            msg_id = receipt["id"]
            print(f"   ✔ [Step {i + 1}/{len(prompts)}] Enqueued to conversation {target_conv_id} (msg: {msg_id[:8]}...)")
            if delay_between_steps > 0 and i < len(prompts) - 1:
                time.sleep(min(delay_between_steps, 0.05))

        print(f"\n🎉 Done! All {len(prompts)} prompts are delivered to conversation '{target_conv_id}'.")
        return prompts

    # Fallback to AppleScript UI paster if outside Antigravity environment
    print("\n⚠️ Staging via AppleScript UI paste into visible Queued Messages tray.")
    original_clipboard = get_clipboard()

    try:
        if countdown_seconds > 0:
            print(f"\n⏳ Switching to {app_name} in {countdown_seconds:.1f}s... (Keep cursor in chat input)")
            time.sleep(countdown_seconds)

        print(f"\n🚀 Staging {len(prompts)} prompts into Antigravity's Queued Messages...")
        for i, p in enumerate(prompts):
            # Load into clipboard
            if not set_clipboard(p):
                print(f"   ❌ Failed to set clipboard for Step {i + 1}")
                continue

            success = send_keystroke_to_antigravity(app_name=app_name)
            if success:
                print(f"   ✔ [Step {i + 1}/{len(prompts)}] Sent to queue")
            else:
                print(f"   ⚠️ [Step {i + 1}/{len(prompts)}] Keystroke skipped")

            time.sleep(delay_between_steps)

        print(f"\n🎉 Done! All {len(prompts)} prompts are sitting in your visible Queued Messages card.")

    finally:
        # Restore user's original clipboard
        if original_clipboard:
            set_clipboard(original_clipboard)

    return prompts


def main() -> int:
    parser = argparse.ArgumentParser(description="Pings prompts into Antigravity queue.")
    parser.add_argument("prompt", nargs="?", default="this project", help="Seed prompt")
    parser.add_argument("--steps", "-n", type=int, default=5, help="Number of follow-up steps")
    parser.add_argument("--subagents", "-s", type=int, default=0, help="Max subagents per step (default: 0 = none)")
    parser.add_argument("--delay", "-d", type=float, default=0.35, help="Delay between messages in seconds")
    parser.add_argument("--countdown", "-c", type=float, default=1.5, help="Countdown before dispatch")
    parser.add_argument(
        "--conversation-id", "-C",
        type=str,
        default=None,
        help="Target Antigravity conversation ID for direct, focus-free delivery",
    )
    parser.add_argument(
        "--delivery-mode", "-m",
        choices=["auto", "targeted", "gui"],
        default="auto",
        help="Delivery mode: 'auto' (targeted if conv ID or /g, else gui), 'targeted', or 'gui'",
    )

    args = parser.parse_args()

    queue_prompts_into_antigravity(
        prompt=args.prompt,
        steps=args.steps,
        subagents=args.subagents,
        delay_between_steps=args.delay,
        countdown_seconds=args.countdown,
        conversation_id=args.conversation_id,
        delivery_mode=args.delivery_mode,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
