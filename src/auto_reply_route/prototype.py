"""Auto-Reply Route Prototype & End-to-End Simulation.

Demonstrates Operator DNA 5-phase trajectory generation, upfront queue staging,
status card rendering, turn quality gates, human preemption, and context hygiene.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Optional, Union
import uuid

from auto_reply_route.context_hygiene import calculate_token_reduction, prune_turn_transcript
from auto_reply_route.models import MessageQueueManifest
from auto_reply_route.queue_watcher import QueueWatcher, _bold, _cyan, _dim, _green, _magenta, _yellow

DEFAULT_PROMPT = "Build an autonomous auto-reply route engine for Antigravity"

PHASE_TEMPLATES = [
    ("Phase 1: Adversarial Refutation & Constraints", "architecture", "Phase 1: Refutation — Investigate actual Antigravity hook mechanics, verify constraints, and refute assumptions for: {p}"),
    ("Phase 2: Least-Complicated Prototype", "core", "Phase 2: Minimal Prototype — Build least-complicated working prototype with zero speculative abstractions for: {p}"),
    ("Phase 3: Feasibility & Investment Reality Check", "product", "Phase 3: Feasibility Check — Evaluate investment, complexity, and probability of success for: {p}"),
    ("Phase 4: Adversarial Go / No-Go", "qa", "Phase 4: Go/No-Go Audit — Audit failure modes, edge cases, and regression risks for: {p}"),
    ("Phase 5: Concrete Synthesis Report", "executive", "Phase 5: Synthesis Report — Deliver clean verification proof, diffs, and operational trade-offs for: {p}"),
]


def generate_5phase_prompts(initial_prompt: str) -> list[dict[str, str]]:
    """Generate 5-phase trajectory prompts conforming to Operator DNA."""
    cleaned = initial_prompt.strip() or DEFAULT_PROMPT
    return [
        {"phase": title, "domain": domain, "prompt": template.format(p=cleaned)}
        for title, domain, template in PHASE_TEMPLATES
    ]


def simulate_turn_execution(turn_num: int, phase_info: dict[str, str]) -> dict[str, Any]:
    """Simulate single turn execution lifecycle: agent work -> stop hook -> quality gates."""
    return {
        "turn": turn_num,
        "phase": phase_info["phase"],
        "tools_executed": ["find_by_name", "view_file", "write_to_file", "run_command (pytest)"],
        "stop_hook": {"triggered": True, "event": "on_turn_end", "quarantine_retries": 0},
        "quality_gates": {
            "concentric_radii": "PASS",
            "strict_8pt_rhythm": "PASS",
            "state_completeness": "PASS",
            "touch_ergonomics": "PASS",
            "high_intent_action_copy": "PASS",
            "anti_overexplaining_law": "PASS",
            "overall": "PASSED",
        },
    }


def simulate_context_hygiene() -> dict[str, Any]:
    """Demonstrate context hygiene pruning and token reduction on verbose tool outputs."""
    raw_steps = [
        {"turn": 0, "type": "USER_INPUT", "role": "user", "content": "Execute Phase 1 audit."},
        {"turn": 0, "type": "TOOL_EXECUTION", "role": "tool", "tool_name": "run_command",
         "args": {"CommandLine": "pytest -vv tests/"},
         "content": "\n".join(f"test_case_{i:03d} PASSED [100%] detail logs trace stack dump..." for i in range(45))},
        {"turn": 0, "type": "TOOL_EXECUTION", "role": "tool", "tool_name": "view_file",
         "args": {"AbsolutePath": "/workspace/src/auto_reply_route/models.py"},
         "content": "\n".join(f"class ModelLine{i}: pass  # verbose context line" for i in range(60))},
        {"turn": 0, "type": "MILESTONE_MANIFEST", "role": "assistant",
         "content": "## 📍 Milestone 1: Refutation complete. Zero blocking architectural hazards detected."},
        {"turn": 1, "type": "USER_INPUT", "role": "user", "content": "Proceed to Phase 2."},
    ]
    pruned = prune_turn_transcript(raw_steps, completed_turn_cutoff=1, max_preview_lines=2)
    stats = calculate_token_reduction(raw_steps, pruned)
    sample_receipt = pruned[1]["content"] if len(pruned) > 1 and "content" in pruned[1] else ""
    return {
        "original_steps": len(raw_steps),
        "pruned_steps": len(pruned),
        "sample_receipt": sample_receipt,
        "stats": stats,
    }


def run_prototype(
    prompt: Optional[str] = None,
    mode: str = "auto",
    output_json: bool = False,
    conv_id: Optional[str] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    delay: float = 0.2,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Execute end-to-end prototype simulation showcasing all core capabilities."""
    initial_prompt = (prompt or DEFAULT_PROMPT).strip()
    target_dir = Path(workspace_dir or ".").resolve()
    conv_id = conv_id or f"demo-{uuid.uuid4().hex[:6]}"
    queue_path = target_dir / f".queued_messages_{conv_id}.json"

    def _ui(msg: str) -> None:
        if not output_json:
            print(msg)
            if delay > 0:
                time.sleep(delay)

    def _step(prompt_text: str) -> None:
        if mode == "interactive" and not output_json:
            input(_dim(f"Press Enter to {prompt_text}..."))

    # 1. Intake & 5-Phase Plan
    _ui(_bold(_cyan("\n🚀 [Auto-Reply Route] Goal Intake & 5-Phase Plan")))
    _ui(f"  {_bold('Goal:')} {initial_prompt}")
    phases = generate_5phase_prompts(initial_prompt)
    for idx, p in enumerate(phases, start=1):
        phase_label = p["phase"].removeprefix(f"Phase {idx}: ")
        _ui(f"  {_dim(f'Phase {idx}:')} {_magenta(phase_label)}")

    # 2. Upfront Queue Staging
    _step("stage 5 follow-up prompts into queue manifest")
    manifest = MessageQueueManifest(conversation_id=conv_id)
    for p in phases:
        manifest.add_message(prompt=p["prompt"], domain=p["domain"])
    manifest.save_to_file(queue_path)
    _ui(_green(f"\n✔ 5 planned turns staged into queue ({queue_path.name})"))

    # 3. Terminal Status Card Rendering (Active State)
    watcher = QueueWatcher(target_dir=target_dir, conversation_id=conv_id)
    _ui(f"\n{watcher.format_status_card(manifest)}")

    # 4. Turn 1 Execution Simulation
    _step("simulate Agent Turn 1 execution and Quality Gate check")
    turn1_result = simulate_turn_execution(1, phases[0])
    popped = manifest.pop_next_message()
    manifest.save_to_file(queue_path)
    _ui(_cyan("\n✔ Turn 1 Complete — Automated Quality Checks Passed"))
    _ui(f"{watcher.format_status_card(manifest)}")

    # 5. Human Preemption Handling (Paused & Resumed States)
    _step("simulate Human Preemption (pause -> inspect -> resume)")
    manifest.pause(reason="Human override: verify test coverage")
    manifest.save_to_file(queue_path)
    _ui(_yellow("\n⏸ Operator Intervened: Paused auto-reply queue"))
    _ui(f"{watcher.format_status_card(manifest)}")

    _step("resume queue execution")
    manifest.resume()
    manifest.save_to_file(queue_path)
    _ui(_green("\n▶ Operator Resumed: Resuming auto-reply queue"))
    _ui(f"{watcher.format_status_card(manifest)}")

    # 6. Complete Remaining Turns -> Completed State
    _step("advance remaining turns to complete the route")
    while not manifest.is_completed:
        manifest.pop_next_message()
    manifest.save_to_file(queue_path)
    _ui(_green("\n✔ All 5 turns completed successfully"))
    _ui(f"{watcher.format_status_card(manifest)}")

    # 7. Context Hygiene Demonstration
    _step("demonstrate Context Hygiene pruning & token savings")
    hygiene = simulate_context_hygiene()
    pct = hygiene["stats"]["reduction_percent"]
    saved = hygiene["stats"]["saved_tokens"]
    _ui(_bold(_magenta("\n🧹 Smart Context Pruning & History Receipts:")))
    _ui(f"  Token Savings: {_bold(_green(f'{pct}%'))} ({saved} tokens saved post-turn)")
    if hygiene.get("sample_receipt"):
        _ui(_dim("  Sample Receipt:\n" + "\n".join(f"    {line}" for line in hygiene["sample_receipt"].splitlines())))

    # Teardown / Cleanup
    if cleanup and queue_path.exists():
        try:
            queue_path.unlink()
        except OSError:
            pass

    summary = {
        "status": "success",
        "conversation_id": conv_id,
        "initial_prompt": initial_prompt,
        "phases": phases,
        "state_transitions": ["staged", "active", "paused", "resumed", "completed"],
        "turn_execution": turn1_result,
        "dispatched_turn_1": popped.to_dict() if popped else None,
        "preemption_handled": True,
        "is_completed": manifest.is_completed,
        "total_turns": manifest.total_count,
        "completed_turns": manifest.active_index,
        "context_hygiene": hygiene["stats"],
    }
    if output_json:
        print(json.dumps(summary, indent=2))
    else:
        _ui(_bold(_green("\n✨ Prototype demonstration completed successfully.\n")))
    return summary


def run_demo(
    prompt: Optional[str] = None,
    auto: bool = True,
    interactive: bool = False,
    output_json: bool = False,
    conv_id: Optional[str] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    delay: float = 0.0,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Run prototype demonstration in automated or interactive mode."""
    mode = "interactive" if interactive or not auto else "auto"
    return run_prototype(
        prompt=prompt,
        mode=mode,
        output_json=output_json,
        conv_id=conv_id,
        workspace_dir=workspace_dir,
        delay=delay,
        cleanup=cleanup,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for standalone execution."""
    parser = argparse.ArgumentParser(prog="auto_reply_route.prototype", description="Auto-Reply Route Prototype")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive step-by-step mode")
    parser.add_argument("--auto", "-a", action="store_true", help="Automated demonstration pacing")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON simulation trace")
    parser.add_argument("--prompt", "-p", type=str, default=None, help="Initial prompt to seed trajectory")
    parser.add_argument("--dir", "-d", type=str, default=".", help="Target workspace directory")
    parser.add_argument("--delay", type=float, default=0.2, help="Pacing delay in seconds")
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false", default=True, help="Retain manifest")
    args = parser.parse_args(argv)

    mode = "interactive" if args.interactive else "auto"
    run_prototype(
        prompt=args.prompt,
        mode=mode,
        output_json=args.json,
        workspace_dir=args.dir,
        delay=0.0 if args.json else args.delay,
        cleanup=args.cleanup,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
