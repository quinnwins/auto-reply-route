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
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Optional, Union
import urllib.request

from auto_reply_route.builder import generate_followup_queue
from auto_reply_route.hook_driver import QueueDispatcher, _validate_conversation_id


def get_active_antigravity_conversation_id(
    app_data_dir: Optional[Union[str, Path]] = None,
    timeout: float = 0.5,
) -> Optional[str]:
    """Inspects Antigravity's live Chrome DevTools port to determine which conversation is currently active on screen.

    Returns the conversation ID string if Antigravity is running and has an active page open,
    or None if DevTools is unreachable or Antigravity is not running.
    """
    try:
        # 1. Locate DevTools active port file
        port_file = Path.home() / "Library/Application Support/Antigravity/DevToolsActivePort"
        if not port_file.exists():
            return None
        lines = port_file.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        port = lines[0].strip()
        if not port.isdigit():
            return None

        # 2. Query DevTools JSON targets
        url = f"http://127.0.0.1:{port}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "antigravity-monitor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pages = json.loads(resp.read().decode("utf-8"))

        # 3. Match active page URL /c/<conversation_id>
        for p in pages:
            if isinstance(p, dict) and p.get("type") == "page":
                p_url = p.get("url", "")
                m = re.search(r"/c/([a-zA-Z0-9_-]+)", p_url)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def send_message_via_agentapi(
    recipient_id: str,
    content: str,
    title: Optional[str] = None,
    agentapi_exe: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
    timeout: float = 5.0,
) -> bool:
    """Delivers a message natively through Antigravity's Language Server agentapi CLI.

    Guarantees:
    - Zero window switching or AppleScript keystrokes
    - Zero clipboard corruption or focus stealing
    - Direct Language Server queue delivery into the recipient conversation
    - Immunity to window focus, screen locks, and background tab state

    Returns True if successfully delivered, False otherwise.
    """
    env = os.environ if environ is None else environ
    try:
        safe_recipient = _validate_conversation_id(recipient_id)
    except Exception:
        return False

    exe = (
        agentapi_exe
        or env.get("ANTIGRAVITY_AGENTAPI_EXE")
        or "/Applications/Antigravity.app/Contents/Resources/bin/language_server"
    )
    if not Path(exe).exists():
        return False

    cmd = [exe, "agentapi", "send-message"]
    if title:
        cmd.append(f"--title={title}")
    cmd.extend([safe_recipient, content])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
        if proc.returncode == 0 and "error" not in proc.stdout.lower():
            return True
    except Exception:
        return False
    return False


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
    clean_app_name = re.sub(r"[^a-zA-Z0-9_\-\. ]", "", app_name).strip() or "Antigravity"
    script = f'''
    with timeout of 2 seconds
        tell application "{clean_app_name}" to activate
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


_PREFIX_RE = re.compile(
    r"^(?:/(?:queue-prompts|queue|q)\b|(?:queue-prompts|queue|q)\s+(?=\d+\b))\s*",
    re.IGNORECASE,
)
_G_PREFIX_RE = re.compile(r"^/g\b", re.IGNORECASE)
_ASK_G_RE = re.compile(r"\bask[\s\-_]*g\b", re.IGNORECASE)


def is_g_command(text: str) -> bool:
    """Checks if text begins with the '/g' adaptive guidance command."""
    return bool(_G_PREFIX_RE.search((text or "").strip()))
_LEAD_SUB_RE = re.compile(
    r"^(?:(?:with|\()\s*)?(?:up to\s+)?(\d+)\s*sub(?:agent)?s?\)?\s*(?:and\s*|,\s*|for\s*|:\s*|-\s*)?",
    re.IGNORECASE,
)
_LEAD_STEP_RE = re.compile(
    r"^(?:with\s+)?(\d+)\s+(?:follow\s*ups?|followups?|steps?|turns?)?\s*(?:and\s*|,\s*|for\s*|:\s*|-\s*)?",
    re.IGNORECASE,
)
_BARE_STEP_RE = re.compile(r"^(\d+)\s*(?::|-)\s*")
_TRAIL_SUB_RE = re.compile(r"[\s,\-\(]+(?:with\s+)?(\d+)\s*sub(?:agent)?s?\)?$", re.IGNORECASE)
_TRAIL_STEP_RE = re.compile(r"[\s,\-\(]+(\d+)\s*(?:steps?|turns?|follow\s*ups?|followups?)\)?$", re.IGNORECASE)
_TRAIL_CONJ_RE = re.compile(r"[\s,]+(?:and|with)\s*$", re.IGNORECASE)
_CLEAN_DELIM_RE = re.compile(r"^(?:for|:|-)\s*", re.IGNORECASE)
_TECH_PREFIX_GUARD_RE = re.compile(
    r"^(?:404|500|502|503|200|201|204|400|401|403|2fa|3d|4k|5g|100x|128-bit|256-bit|32-bit|64-bit)\b",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def is_ask_g_command(text: str) -> bool:
    """Checks if text contains the 'ask g' / 'ask-g' adaptive directive."""
    return bool(_ASK_G_RE.search(text))


def parse_queue_command(text: str, default_steps: int = 5, default_subagents: int = 0) -> tuple[str, int, int]:
    """Parses natural language and slash queue commands like:
    - '/q dental cavitation plaque removal device' -> ('dental cavitation plaque removal device', 5, 0)
    - '/q 5 dental device' -> ('dental device', 5, 0)
    - '/q 5 (3 subagents) dental device' -> ('dental device', 5, 3)
    - '/q look at this from multiple angles 5 sub' -> ('look at this from multiple angles', 5, 5)
    - 'Q 5 follow ups for making this ready for my daily use' -> ('making this ready for my daily use', 5, 0)
    - '/g (Step 2/4) wire forensics into hud' -> ('/g (Step 2/4) wire forensics into hud', 1, 0)
    """
    clean = text.strip()

    # If it is an adaptive guidance command (/g), enforce 1 step and preserve full command
    if is_g_command(clean):
        return clean, 1, default_subagents

    # 1. Strip leading command prefix: /q, /queue-prompts, /queue, Q, Queue
    m_prefix = _PREFIX_RE.match(clean)
    body = clean[m_prefix.end():].strip() if m_prefix else clean

    steps = default_steps
    subagents = default_subagents

    # 1.5 Strip 'ask g' if present anywhere in body so trailing steps/subagents can be matched
    if is_ask_g_command(body):
        body = _ASK_G_RE.sub("", body).strip()
        body = _WHITESPACE_RE.sub(" ", body).strip()

    # 2. Check for leading modifiers (steps, subagents, compound clauses)
    changed = True
    while changed:
        changed = False
        if _TECH_PREFIX_GUARD_RE.match(body):
            break

        m_lead_sub = _LEAD_SUB_RE.match(body)
        if m_lead_sub:
            subagents = int(m_lead_sub.group(1))
            body = body[m_lead_sub.end():].strip()
            changed = True
            continue

        m_lead_step = _LEAD_STEP_RE.match(body)
        if m_lead_step:
            num = int(m_lead_step.group(1))
            has_unit = any(u in m_lead_step.group(0).lower() for u in ("step", "turn", "follow", "for", ":", "-"))
            if num <= 12 or has_unit:
                steps = num
                body = body[m_lead_step.end():].strip()
                changed = True
                continue

        m_bare_step = _BARE_STEP_RE.match(body)
        if m_bare_step:
            steps = int(m_bare_step.group(1))
            body = body[m_bare_step.end():].strip()
            changed = True
            continue

    # 3. Loop for trailing modifiers (subagents, steps) in any order
    while True:
        body = _TRAIL_CONJ_RE.sub("", body).strip()
        m_sub = _TRAIL_SUB_RE.search(body)
        if m_sub:
            subagents = int(m_sub.group(1))
            body = body[:m_sub.start()].strip()
            continue
        m_step = _TRAIL_STEP_RE.search(body)
        if m_step:
            steps = int(m_step.group(1))
            body = body[:m_step.start()].strip()
            continue
        break

    # 4. Clean up any remaining trailing conjunctions or leading separators ("for", ":", "-")
    body = _TRAIL_CONJ_RE.sub("", body).strip()
    body = _CLEAN_DELIM_RE.sub("", body).strip()

    return body or clean, max(1, steps), max(0, subagents)


def parse_queue_command_v4(text: str, default_steps: int = 5, default_subagents: int = 0) -> tuple[str, int, int, bool]:
    """Extended parser returning (seed_prompt, steps, subagents, is_ask_g)."""
    ask_g = is_ask_g_command(text)
    prompt, steps, subagents = parse_queue_command(text, default_steps, default_subagents)
    return prompt, steps, subagents, ask_g


def resolve_conversation_id(
    conversation_id: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Resolves the verified Antigravity conversation ID from parameters or environment.

    Resolution hierarchy:
    1. Explicit conversation_id parameter (if provided and non-empty)
    2. Environment variable `ANTIGRAVITY_CONVERSATION_ID`
    3. JSON metadata in `ANTIGRAVITY_SOURCE_METADATA` (`tool.conversationId`)

    Returns validated, safe conversation ID string, or None if not determinable.
    Raises ValueError if an explicit or environment ID fails path traversal checks.
    NOTE: NEVER guesses or falls back to 'most recent directory' by mtime, as that
    risks cross-chat pollution if the user is working in another chat.
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
            tool_meta = parsed.get("tool", {}) if isinstance(parsed.get("tool"), dict) else {}
            meta_id = (
                tool_meta.get("conversationId")
                or parsed.get("conversationId")
                or parsed.get("conversation_id")
            )
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

    env = os.environ if environ is None else environ
    effective_app_data_dir = app_data_dir or env.get("ANTIGRAVITY_APP_DATA_DIR")
    dispatcher = QueueDispatcher(app_data_dir=effective_app_data_dir)

    # 1. Native AgentAPI Delivery (triggers Language Server reactive wakeup)
    send_message_via_agentapi(
        recipient_id=safe_conv_id,
        content=prompt,
        title="Targeted Prompt",
        environ=env,
    )

    # 2. Durable Mailbox Ledger
    return dispatcher.queue_user_message(
        conversation_id=safe_conv_id,
        content=prompt,
        priority=priority,
        sender="user",
        delivery_strategy=delivery_strategy,
    )


def extract_json_array(text: str) -> Optional[list[str]]:
    """Extracts a list of non-empty strings from raw JSON or markdown-fenced text."""
    if not text:
        return None
    # 1. Direct JSON parse
    try:
        data = json.loads(text.strip())
        if isinstance(data, list):
            cleaned = [str(x).strip() for x in data if str(x).strip()]
            if cleaned:
                return cleaned
    except Exception:
        pass

    # 2. Markdown code fence ```json [...] ```
    fence_m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text, re.IGNORECASE)
    if fence_m:
        try:
            data = json.loads(fence_m.group(1).strip())
            if isinstance(data, list):
                cleaned = [str(x).strip() for x in data if str(x).strip()]
                if cleaned:
                    return cleaned
        except Exception:
            pass

    # 3. Regex search for array brackets [ ... ]
    arr_m = re.search(r"\[[\s\S]*?\]", text)
    if arr_m:
        try:
            data = json.loads(arr_m.group(0).strip())
            if isinstance(data, list):
                cleaned = [str(x).strip() for x in data if str(x).strip()]
                if cleaned:
                    return cleaned
        except Exception:
            pass

    return None


def synthesize_bespoke_followups_via_flash(
    prompt: str,
    steps: int = 5,
    subagents: int = 0,
    timeout_s: float = 12.0,
    model: str = "gemini-3.8-flash-low",
) -> Optional[list[str]]:
    """Synthesizes high-signal follow-up prompts using Gemini Flash via `agy`.

    Enforces strict fail-open semantics: if `agy` is missing, times out, or
    returns invalid JSON, returns None so callers fall back to deterministic templates.
    """
    agy_bin = shutil.which("agy")
    if not agy_bin:
        local_agy = os.path.expanduser("~/.local/bin/agy")
        if os.path.exists(local_agy) and os.access(local_agy, os.X_OK):
            agy_bin = local_agy
    if not agy_bin:
        return None

    # Load core DNA guidelines if available
    dna_summary = (
        "Tone & Strategy: Terse, 10-25 words per prompt, founder pragmatism, zero fluff. "
        "Strictly actionable engineering steps: scaffold/prototype -> test/refactor -> production readiness."
    )
    for path_cand in [
        Path.home() / ".gemini" / "config" / "quinns_dna.md",
        Path(".agents/quinns_dna.md"),
    ]:
        if path_cand.exists():
            try:
                content = path_cand.read_text(encoding="utf-8")
                lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
                if lines:
                    dna_summary = " ".join(lines[:6])
                break
            except Exception:
                pass

    sub_directive = f" Each step must coordinate a team of up to {subagents} subagents." if subagents > 0 else ""
    flash_prompt = (
        f"You are formulating multi-step prompts for an autonomous agent.\n"
        f"Task: {prompt}\n"
        f"Step Count: {steps}\n"
        f"Guidelines: {dna_summary}{sub_directive}\n"
        f"Return ONLY a valid JSON array of exactly {steps} prompt strings. No markdown fences, no commentary."
    )

    try:
        proc = subprocess.run(
            [agy_bin, "-p", flash_prompt, "--model", model, "--disable-slash-commands"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            return None
        return extract_json_array(proc.stdout)
    except (subprocess.TimeoutExpired, Exception):
        return None


def queue_prompts_into_antigravity(
    prompt: str,
    steps: int = 5,
    subagents: int = 0,
    delay_between_steps: float = 0.35,
    countdown_seconds: float = 0.2,
    app_name: str = "Antigravity",
    custom_prompts: Optional[list[str]] = None,
    conversation_id: Optional[str] = None,
    app_data_dir: Optional[Union[str, Path]] = None,
    environ: Optional[dict[str, str]] = None,
    delivery_mode: str = "auto",
    dry_run: bool = False,
    as_json: bool = False,
    domain_override: Optional[str] = None,
    use_ai: bool = False,
    ai_timeout: float = 12.0,
    model: str = "gemini-3.8-flash-low",
    force_gui: bool = False,
) -> list[str]:
    """Generates the prompt sequence and stages them into Antigravity's native queue.

    Delivery modes:
    - "auto" (default): Uses targeted inbox delivery if explicit conversation_id is provided,
      if running inside an Antigravity agent process, or if handling a `/g` adaptive follow-up.
      Otherwise uses AppleScript GUI paster so upfront `/q` prompts appear visibly in the tray.
    - "targeted": Forces direct atomic mailbox delivery via QueueDispatcher (zero focus stealing).
    - "gui": Forces AppleScript GUI keystroke paste into the frontmost window. If running inside
      an Antigravity session, auto-promotes to targeted delivery unless force_gui=True to protect
      the user from cross-chat contamination.

    Returns the list of generated/staged prompt strings.
    """
    # Auto-parse natural language command if present
    parsed_prompt, parsed_steps, parsed_subagents = parse_queue_command(
        prompt, default_steps=steps, default_subagents=subagents
    )
    actual_prompt = parsed_prompt or prompt
    actual_steps = parsed_steps
    actual_subagents = parsed_subagents

    # If it is an adaptive guidance command (/g) and no custom prompts were given,
    # preserve the exact prompt as the single step.
    if is_g_command(actual_prompt) and not custom_prompts:
        prompts = [actual_prompt]
    elif custom_prompts:
        prompts = list(custom_prompts)[:actual_steps]
    elif use_ai:
        ai_prompts = synthesize_bespoke_followups_via_flash(
            actual_prompt, steps=actual_steps, subagents=actual_subagents, timeout_s=ai_timeout, model=model
        )
        if ai_prompts:
            prompts = ai_prompts[:actual_steps]
            if actual_subagents > 0:
                formatted_ai = []
                for p in prompts:
                    if "subagent" not in p.lower():
                        team_note = (
                            f" (with {actual_subagents} subagents)"
                            if actual_subagents > 1
                            else " (with 1 subagent)"
                        )
                        formatted_ai.append(f"{p.rstrip('.')}{team_note}")
                    else:
                        formatted_ai.append(p)
                prompts = formatted_ai
        else:
            if not as_json:
                print("⚠️ AI synthesis unavailable or timed out; falling back to deterministic template.")
            manifest = generate_followup_queue(
                actual_prompt, count=actual_steps, max_subagents=actual_subagents, domain_override=domain_override
            )
            prompts = [msg.prompt for msg in manifest.messages]
    else:
        manifest = generate_followup_queue(
            actual_prompt, count=actual_steps, max_subagents=actual_subagents, domain_override=domain_override
        )
        prompts = [msg.prompt for msg in manifest.messages]

    if not prompts:
        if as_json:
            print("[]")
        else:
            print("❌ No prompts generated.")
        return []

    if as_json:
        payload = [{"step": i + 1, "prompt": p} for i, p in enumerate(prompts)]
        print(json.dumps(payload, indent=2))
        return prompts

    print(f"\n📋 Generated {len(prompts)} Follow-Up Prompts for: \"{actual_prompt}\"")
    print(f"👥 Subagents per team: {actual_subagents if actual_subagents > 0 else 'None (Single Agent)'}\n")
    for i, p in enumerate(prompts):
        preview = p if len(p) <= 80 else p[:77] + "..."
        print(f"   [{i + 1}/{len(prompts)}] {preview}")

    if dry_run:
        print("\n🔍 Dry run active: Prompts previewed above. Zero clipboard or keystrokes sent.")
        return prompts

    # Determine delivery routing
    env = os.environ if environ is None else environ
    resolved_id = resolve_conversation_id(conversation_id=conversation_id, environ=env)
    is_inside_antigravity = bool(
        resolved_id and (
            env.get("ANTIGRAVITY_SOURCE_METADATA") or
            env.get("ANTIGRAVITY_CONVERSATION_ID") or
            conversation_id
        )
    )

    # Determine active tab in Antigravity UI to ensure zero cross-chat pollution
    active_chat_id = get_active_antigravity_conversation_id(app_data_dir=app_data_dir)
    user_is_in_target_chat = bool(active_chat_id and resolved_id and active_chat_id == resolved_id)

    target_conv_id: Optional[str] = None
    if delivery_mode == "targeted":
        target_conv_id = resolved_id
        if not target_conv_id:
            raise ValueError("Targeted delivery requested but no conversation ID could be resolved.")
    elif delivery_mode == "auto":
        if is_g_command(prompt) or not user_is_in_target_chat:
            target_conv_id = resolved_id
    elif delivery_mode == "gui":
        if is_inside_antigravity and not force_gui:
            if not user_is_in_target_chat:
                # User is NOT in this chat! Run 100% in the background!
                print(f"\n🛡️ Background Delivery Active: User is not currently focused on chat '{resolved_id}'.")
                print("   Promoting from GUI paste to Targeted Mailbox Delivery (Background Native AgentAPI) to prevent cross-chat pollution.")
                target_conv_id = resolved_id
            elif is_g_command(prompt):
                # /g adaptive commands run in the background to avoid stealing cursor/focus
                print(f"\n🎯 /g adaptive guidance loop active.")
                print("   Promoting from GUI paste to Targeted Mailbox Delivery (Background Native AgentAPI) to avoid focus stealing.")
                target_conv_id = resolved_id
            else:
                # User IS in this chat and requested GUI mode (/q): Safe to paste into visible Queued Messages!
                print(f"\n📺 User is currently active in chat '{resolved_id}'. Staging into visible Queued Messages card.")

    if target_conv_id:
        print(f"\n🎯 Background Delivery Active: Routing directly to conversation '{target_conv_id}'")
        print(f"   (Zero focus stealing, zero window switching, zero cross-chat pollution)\n")

        effective_app_data_dir = app_data_dir or env.get("ANTIGRAVITY_APP_DATA_DIR")
        dispatcher = QueueDispatcher(app_data_dir=effective_app_data_dir)
        for i, p in enumerate(prompts):
            # 1. Native AgentAPI Delivery (wakes up Language Server reactively)
            title = "/g Adaptive Guidance" if is_g_command(p) else f"Queued Follow-up [{i + 1}/{len(prompts)}]"
            native_delivered = send_message_via_agentapi(
                recipient_id=target_conv_id,
                content=p,
                title=title,
                environ=env,
            )

            # 2. Durable Mailbox Ledger
            receipt = dispatcher.queue_user_message(
                conversation_id=target_conv_id,
                content=p,
                priority="MESSAGE_PRIORITY_HIGH",
                sender="user",
                delivery_strategy="MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE",
            )
            msg_id = receipt["id"]
            delivery_status = "Native AgentAPI + Mailbox" if native_delivered else "Durable Mailbox Ledger"
            print(f"   ✔ [Step {i + 1}/{len(prompts)}] Enqueued to conversation {target_conv_id} ({delivery_status}, msg: {msg_id[:8]}...)")
            if delay_between_steps > 0 and i < len(prompts) - 1:
                time.sleep(min(delay_between_steps, 0.05))

        print(f"\n🎉 Done! All {len(prompts)} prompt(s) delivered in the background to conversation '{target_conv_id}'.")
        return prompts

    # Non-macOS safety check
    if sys.platform != "darwin":
        print(f"\nℹ️ Non-macOS platform ({sys.platform}) detected. Direct AppleScript GUI paste skipped.")
        print(f"   Prompts generated above can be piped or used in scripts.")
        return prompts

    # Fallback to AppleScript UI paster if outside Antigravity environment
    print("\n⚠️ Staging via AppleScript UI paste into visible Queued Messages tray.")
    original_clipboard = get_clipboard()
    gui_failed = False

    try:
        if countdown_seconds > 0:
            print(f"\n⏳ Switching to {app_name} in {countdown_seconds:.1f}s... (Keep cursor in chat input)")
            time.sleep(countdown_seconds)

        # Real-time safety check: did the user switch tabs during the countdown?
        active_now = get_active_antigravity_conversation_id(app_data_dir=app_data_dir)
        if resolved_id and active_now and active_now != resolved_id and not force_gui:
            print(f"\n🛡️ Active chat changed during countdown to '{active_now}'.")
            print(f"   Aborting GUI paste to avoid cross-chat pollution. Routing in background to '{resolved_id}'.")
            eff_dir = app_data_dir or env.get("ANTIGRAVITY_APP_DATA_DIR")
            disp = QueueDispatcher(app_data_dir=eff_dir)
            for i, p in enumerate(prompts):
                send_message_via_agentapi(recipient_id=resolved_id, content=p, environ=env)
                disp.queue_user_message(conversation_id=resolved_id, content=p)
            print(f"🎉 Delivered all {len(prompts)} prompt(s) in background to '{resolved_id}'.")
            return prompts

        print(f"\n🚀 Staging {len(prompts)} prompts into Antigravity's Queued Messages...")
        for i, p in enumerate(prompts):
            # Load into clipboard
            if not set_clipboard(p):
                print(f"   ❌ Failed to set clipboard for Step {i + 1}")
                gui_failed = True
                break

            success = send_keystroke_to_antigravity(app_name=app_name)
            if success:
                print(f"   ✔ [Step {i + 1}/{len(prompts)}] Sent to queue")
            else:
                print(f"   ⚠️ [Step {i + 1}/{len(prompts)}] Keystroke skipped or failed")
                gui_failed = True
                break

            time.sleep(delay_between_steps)

        if not gui_failed:
            print(f"\n🎉 Done! All {len(prompts)} prompts are sitting in your visible Queued Messages card.")
        else:
            scratch_dir = Path(app_data_dir or (Path.home() / ".gemini" / "antigravity")) / "scratch"
            scratch_dir.mkdir(parents=True, exist_ok=True)
            fallback_file = scratch_dir / "staged_prompts_fallback.json"
            fallback_file.write_text(json.dumps(prompts, indent=2), encoding="utf-8")
            print(f"\n⚠️ AppleScript GUI keystroke paste failed. Safely saved {len(prompts)} prompt(s) to fallback file: {fallback_file}")

    finally:
        # Restore user's original clipboard (even if originally empty)
        if original_clipboard is not None:
            set_clipboard(original_clipboard)

    return prompts


def main() -> int:
    parser = argparse.ArgumentParser(description="Pings prompts into Antigravity queue.")
    parser.add_argument("prompt", nargs="?", default="this project", help="Seed prompt")
    parser.add_argument("--steps", "-n", type=int, default=5, help="Number of follow-up steps")
    parser.add_argument("--subagents", "-s", type=int, default=0, help="Max subagents per step (default: 0 = none)")
    parser.add_argument("--delay", "-d", type=float, default=0.35, help="Delay between messages in seconds")
    parser.add_argument("--countdown", "-c", type=float, default=0.2, help="Countdown before dispatch")
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and preview prompts without clipboard or UI dispatch",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output generated prompts as JSON to stdout",
    )
    parser.add_argument(
        "--domain",
        type=str,
        choices=["code", "ux", "research"],
        default=None,
        help="Explicit domain override for generated prompts",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Use Gemini Flash via agy CLI to synthesize bespoke prompts (fails open to deterministic templates)",
    )
    parser.add_argument(
        "--ai-timeout",
        type=float,
        default=12.0,
        help="Timeout in seconds for AI prompt synthesis (default: 12.0s)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.8-flash-low",
        help="Model to use for AI synthesis (default: gemini-3.8-flash-low)",
    )
    parser.add_argument(
        "--grade",
        action="store_true",
        help="Evaluate and grade the generated prompts against Operator DNA quality pillars",
    )
    parser.add_argument(
        "--force-gui",
        action="store_true",
        help="Force AppleScript GUI paste even if inside an active Antigravity session",
    )

    args = parser.parse_args()

    if args.grade:
        from auto_reply_route.grader import PromptGrader, format_grade_card
        report = PromptGrader.grade(args.prompt, steps=args.steps, subagents=args.subagents)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(format_grade_card(report))
        return 0

    queue_prompts_into_antigravity(
        prompt=args.prompt,
        steps=args.steps,
        subagents=args.subagents,
        delay_between_steps=args.delay,
        countdown_seconds=args.countdown,
        conversation_id=args.conversation_id,
        delivery_mode=args.delivery_mode,
        dry_run=args.dry_run,
        as_json=args.json,
        domain_override=args.domain,
        use_ai=args.ai,
        ai_timeout=args.ai_timeout,
        model=args.model,
        force_gui=args.force_gui,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
