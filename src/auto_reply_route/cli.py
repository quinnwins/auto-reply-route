from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sys
import textwrap
from typing import Any, Optional, Union

from auto_reply_route.miner import PromptRouteMiner
from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.parser import RouteParser
from auto_reply_route.state_machine import RouteStateMachine


# ============================================================================
# Playbook Linter & Validator
# ============================================================================

@dataclass
class ValidationIssue:
    severity: str  # "ERROR" or "WARNING"
    line_number: Optional[int]
    message: str

    def __str__(self) -> str:
        loc = f"Line {self.line_number}: " if self.line_number is not None else ""
        return f"[{self.severity}] {loc}{self.message}"


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    manifest: Optional[RouteManifest] = None
    stats: dict[str, int] = field(default_factory=dict)


class RouteValidator:
    """Lints and validates .route.md playbooks for headers, numbering, formats, and assertions."""

    @classmethod
    def validate_content(
        cls,
        content: str,
        filepath: Optional[str] = None,
        route_id: Optional[str] = None,
    ) -> ValidationResult:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        lines = content.splitlines()

        if not content.strip():
            errors.append(ValidationIssue("ERROR", None, "Playbook file is empty."))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 1. Header validation
        header_found = False
        header_line = 0
        header_title = ""
        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if not s:
                continue
            if s.startswith("# "):
                header_found = True
                header_line = idx
                header_title = s[2:].strip()
                break
            else:
                # First non-empty line is not a top-level header
                break

        if not header_found or not header_title:
            errors.append(
                ValidationIssue(
                    "ERROR",
                    header_line if header_found else 1,
                    "Missing top-level route title header (e.g. '# Route Title').",
                )
            )

        # 2. Numbered steps and bullets analysis
        step_pattern = re.compile(r"^\s{0,2}(\d+)[.)]\s*(.*)$")
        bullet_pattern = re.compile(r"^(\s{2,}|\t+)[-*+]\s+(.*)$")
        unindented_bullet_pattern = re.compile(r"^[-*+]\s+(.*)$")

        step_indices_found: list[tuple[int, int]] = []  # (step_number, line_num)
        current_step_num: Optional[int] = None
        current_step_line: Optional[int] = None
        current_step_has_body = False
        step_alt_count = 0
        step_assert_count = 0
        total_alts = 0
        total_asserts = 0

        for line_num, line in enumerate(lines, start=1):
            # Skip top-level header line
            if header_found and line_num == header_line:
                continue

            step_match = step_pattern.match(line)
            if step_match:
                # Check previous step body
                if current_step_num is not None and not current_step_has_body:
                    errors.append(
                        ValidationIssue(
                            "ERROR",
                            current_step_line,
                            f"Step {current_step_num} has an empty primary prompt.",
                        )
                    )

                step_num = int(step_match.group(1))
                step_indices_found.append((step_num, line_num))
                current_step_num = step_num
                current_step_line = line_num
                step_body = step_match.group(2).strip()
                current_step_has_body = bool(step_body)
                continue

            # Unindented bullet check (outside numbered step)
            if current_step_num is None:
                if unindented_bullet_pattern.match(line) or bullet_pattern.match(line):
                    warnings.append(
                        ValidationIssue(
                            "WARNING",
                            line_num,
                            "Bullet found outside any numbered step.",
                        )
                    )
                continue

            # Check unindented bullet inside step
            if unindented_bullet_pattern.match(line):
                warnings.append(
                    ValidationIssue(
                        "WARNING",
                        line_num,
                        "Bullet is not indented under the step (use 2+ spaces or a tab).",
                    )
                )

            # Check indented bullet
            bullet_match = bullet_pattern.match(line)
            if bullet_match:
                bullet_body = bullet_match.group(2).strip()
                lower_bullet = bullet_body.lower()

                # Check assertion
                if lower_bullet.startswith("assert:") or lower_bullet.startswith("assertion:"):
                    total_asserts += 1
                    step_assert_count += 1
                    assertion_val = bullet_body.split(":", 1)[1].strip()
                    if not assertion_val:
                        errors.append(
                            ValidationIssue(
                                "ERROR",
                                line_num,
                                f"Step {current_step_num} has an empty assertion condition.",
                            )
                        )
                    continue

                # Check manifest ref
                if lower_bullet.startswith("manifest:") or lower_bullet.startswith("manifest_ref:"):
                    ref_val = bullet_body.split(":", 1)[1].strip()
                    if not ref_val:
                        errors.append(
                            ValidationIssue(
                                "ERROR",
                                line_num,
                                f"Step {current_step_num} has an empty manifest reference.",
                            )
                        )
                    continue

                # Alternative branch bullet format check
                total_alts += 1
                step_alt_count += 1

                # Recognized bullet patterns
                is_bold_or_italic = bool(re.match(r"^\*{1,2}(.*?)\*{1,2}:\s*(.*)$", bullet_body))
                is_bracketed = bool(re.match(r"^\[(.*?)\]:?\s*(.*)$", bullet_body))
                is_plain_colon = ":" in bullet_body and len(bullet_body.split(":", 1)[0].split()) <= 6

                if not (is_bold_or_italic or is_bracketed or is_plain_colon):
                    warnings.append(
                        ValidationIssue(
                            "WARNING",
                            line_num,
                            f"Alternative bullet '{bullet_body[:35]}...' does not match standard label format "
                            f"'- *Label*: Prompt' or '- [Label]: Prompt'.",
                        )
                    )
                continue

            # Non-bullet non-empty text contributes to step body
            if line.strip():
                current_step_has_body = True

        # Check final step body
        if current_step_num is not None and not current_step_has_body:
            errors.append(
                ValidationIssue(
                    "ERROR",
                    current_step_line,
                    f"Step {current_step_num} has an empty primary prompt.",
                )
            )

        # 3. Check step presence and sequential numbering
        if not step_indices_found:
            errors.append(
                ValidationIssue(
                    "ERROR",
                    None,
                    "Playbook contains no numbered steps (e.g. '1. Step title...').",
                )
            )
        else:
            seen_numbers: set[int] = set()
            for idx, (num, line_num) in enumerate(step_indices_found):
                expected_num = idx + 1
                if num in seen_numbers:
                    errors.append(
                        ValidationIssue(
                            "ERROR",
                            line_num,
                            f"Duplicate step number {num} detected.",
                        )
                    )
                seen_numbers.add(num)

                if num != expected_num:
                    errors.append(
                        ValidationIssue(
                            "ERROR",
                            line_num,
                            f"Non-sequential step numbering: expected step {expected_num}, but found {num}.",
                        )
                    )

        # 4. Parse manifest if basic syntax is sound
        manifest: Optional[RouteManifest] = None
        if not errors:
            try:
                manifest = RouteParser.parse_string(content, route_id=route_id or "")
            except Exception as e:
                errors.append(ValidationIssue("ERROR", None, f"Parser exception: {e}"))

        is_valid = len(errors) == 0
        stats = {
            "steps": len(step_indices_found),
            "alternatives": total_alts,
            "assertions": total_asserts,
        }

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            manifest=manifest,
            stats=stats,
        )

    @classmethod
    def validate_file(cls, filepath: str | Path) -> ValidationResult:
        if "\0" in str(filepath):
            return ValidationResult(
                is_valid=False,
                errors=[ValidationIssue("ERROR", None, "NUL byte in playbook filepath")],
            )

        path = Path(filepath).resolve()
        forbidden_roots = ("/etc", "/var", "/private/etc", "/dev", "/proc", "/sys")
        if any(str(path).startswith(fb) for fb in forbidden_roots):
            return ValidationResult(
                is_valid=False,
                errors=[ValidationIssue("ERROR", None, f"Access denied to system directory path: {filepath}")],
            )

        if not path.is_file():
            return ValidationResult(
                is_valid=False,
                errors=[ValidationIssue("ERROR", None, f"Playbook file not found: {filepath}")],
            )
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[ValidationIssue("ERROR", None, f"Could not read playbook file: {e}")],
            )

        stem = path.name
        for suffix in [".route.md", ".route", ".md"]:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break

        return cls.validate_content(content, filepath=str(path), route_id=stem)


# ============================================================================
# Pinned "Stepping Deck" Terminal HUD
# ============================================================================

class SteppingDeckHUD:
    """Renders a polished, pinned Stepping Deck HUD displaying active step,

    completed steps, upcoming steps, and 4-way alternative branch proposals.
    """

    WIDTH = 80

    @classmethod
    def _pad_line(cls, text: str, width: int = WIDTH) -> str:
        """Pads text to fit inside box borders: │ <text> │."""
        cleaned = text.rstrip()
        inner_width = width - 4  # Account for '│ ' and ' │'
        if len(cleaned) > inner_width:
            cleaned = cleaned[: inner_width - 3] + "..."
        padding = " " * (inner_width - len(cleaned))
        return f"│ {cleaned}{padding} │"

    @classmethod
    def _wrap_lines(cls, text: str, width: int = WIDTH, indent: str = "  ") -> list[str]:
        """Wraps text cleanly within box borders."""
        inner_width = width - 4 - len(indent)
        wrapped_lines: list[str] = []
        for paragraph in text.splitlines():
            stripped = paragraph.strip()
            if not stripped:
                wrapped_lines.append(cls._pad_line("", width))
                continue
            for line in textwrap.wrap(stripped, width=inner_width):
                wrapped_lines.append(cls._pad_line(f"{indent}{line}", width))
        return wrapped_lines

    @classmethod
    def render(
        cls,
        sm: RouteStateMachine,
        mode_label: str = "LIVE",
        checkpoint_path: Optional[str] = None,
    ) -> str:
        manifest = sm.manifest
        total_steps = len(manifest.steps)
        current_idx = manifest.current_step_idx
        current_step = sm.get_current_step()
        w = cls.WIDTH

        output: list[str] = []

        # Top border
        output.append("┌" + "─" * (w - 2) + "┐")

        # Header Title
        title_str = f"🚀 AUTO-REPLY ROUTE: {manifest.title}"
        output.append(cls._pad_line(title_str, w))

        # Status subheaders (unclipped, clean 2-line metadata)
        status_val = manifest.state.value if isinstance(manifest.state, StepStatus) else str(manifest.state)
        step_pos = min(current_idx + 1, total_steps) if total_steps > 0 else 0
        pct = int((step_pos / total_steps) * 100) if total_steps > 0 else 100
        meta_line = f"State: {status_val}  │  Progress: [{step_pos}/{total_steps}] ({pct}%)  │  Mode: {mode_label}"
        output.append(cls._pad_line(meta_line, w))

        if checkpoint_path:
            ckpt_line = f"Checkpoint: {checkpoint_path}"
            output.append(cls._pad_line(ckpt_line, w))

        # Divider
        output.append("├" + "─" * (w - 2) + "┤")

        # Step Deck Progress Track
        output.append(cls._pad_line("DECK PROGRESSION:", w))
        track_tokens: list[str] = []
        for i, step in enumerate(manifest.steps):
            s_num = i + 1
            if step.status == StepStatus.COMPLETED:
                track_tokens.append(f"[✔ {s_num}]")
            elif i == current_idx and sm.is_running:
                track_tokens.append(f"[▶ {s_num}]")
            elif step.status in (StepStatus.PAUSED, getattr(StepStatus, "PAUSED_BY_USER", StepStatus.PAUSED)):
                track_tokens.append(f"[⏸ {s_num}]")
            elif step.status == StepStatus.FAILED:
                track_tokens.append(f"[✖ {s_num}]")
            else:
                track_tokens.append(f"[⏳ {s_num}]")

        track_str = " ──> ".join(track_tokens) if track_tokens else "(no steps)"
        for line in textwrap.wrap(track_str, width=w - 6):
            output.append(cls._pad_line(f"  {line}", w))

        output.append("├" + "─" * (w - 2) + "┤")

        # Active Step Deck Card
        if current_step is not None and not sm.is_completed:
            active_num = current_step.index + 1
            active_header = f"▶ ACTIVE STEP {active_num}: {current_step.title}"
            output.append(cls._pad_line(active_header, w))
            output.append(cls._pad_line("", w))

            # Primary prompt
            output.append(cls._pad_line("  Primary Instruction Prompt:", w))
            for line in cls._wrap_lines(current_step.primary_prompt, width=w, indent="    "):
                output.append(line)

            # Assertions
            if current_step.assertions:
                output.append(cls._pad_line("", w))
                output.append(cls._pad_line(f"  Assertions ({len(current_step.assertions)}):", w))
                for assertion in current_step.assertions:
                    output.append(cls._pad_line(f"    ✔ {assertion}", w))

            # Alternative branches
            if current_step.alternatives:
                output.append(cls._pad_line("", w))
                output.append(
                    cls._pad_line(
                        f"  Alternative Branch Options ({len(current_step.alternatives)}):",
                        w,
                    )
                )
                for alt in current_step.alternatives:
                    alt_hdr = f"    [Rank {alt.rank}] *{alt.label}*"
                    output.append(cls._pad_line(alt_hdr, w))
                    preview = alt.prompt_template.splitlines()[0] if alt.prompt_template else ""
                    if preview:
                        for line in textwrap.wrap(preview, width=w - 18):
                            output.append(cls._pad_line(f"             {line}", w))
        elif sm.is_completed:
            output.append(cls._pad_line("🎉 ROUTE EXECUTION COMPLETE: All steps verified and finished.", w))
        else:
            output.append(cls._pad_line("Active Step: None (Route pending or stopped)", w))

        output.append("├" + "─" * (w - 2) + "┤")

        # Completed steps summary
        completed_steps = [s for s in manifest.steps if s.status == StepStatus.COMPLETED]
        if completed_steps:
            output.append(cls._pad_line(f"COMPLETED STEPS ({len(completed_steps)}):", w))
            for cs in completed_steps:
                output.append(cls._pad_line(f"  ✔ Step {cs.index + 1}: {cs.title}", w))
        else:
            output.append(cls._pad_line("COMPLETED STEPS: (none)", w))

        output.append("├" + "─" * (w - 2) + "┤")

        # Upcoming steps summary
        upcoming_steps = [
            s for i, s in enumerate(manifest.steps)
            if i > current_idx and s.status != StepStatus.COMPLETED
        ]
        if upcoming_steps:
            output.append(cls._pad_line(f"UPCOMING STEPS ({len(upcoming_steps)}):", w))
            for us in upcoming_steps:
                output.append(cls._pad_line(f"  ⏳ Step {us.index + 1}: {us.title}", w))
        else:
            output.append(cls._pad_line("UPCOMING STEPS: (none)", w))

        # Bottom Border
        output.append("└" + "─" * (w - 2) + "┘")

        return "\n".join(output)


# ============================================================================
# Subcommand Handlers
# ============================================================================

def cmd_validate(args: argparse.Namespace) -> int:
    """Lints and validates a .route.md playbook file."""
    filepath = args.playbook
    res = RouteValidator.validate_file(filepath)

    print(f"\nAuditing Route Playbook: {filepath}")
    print("─" * 60)

    if res.warnings:
        for w in res.warnings:
            print(f"⚠️  {w}")

    if not res.is_valid:
        for e in res.errors:
            print(f"❌ {e}")
        print("─" * 60)
        print(f"❌ Validation FAILED: Found {len(res.errors)} error(s).")
        return 1

    print("─" * 60)
    print(f"✅ Validation PASSED:")
    print(f"   • Route Title:         {res.manifest.title if res.manifest else 'N/A'}")
    print(f"   • Steps Verified:      {res.stats.get('steps', 0)}")
    print(f"   • Branch Alternatives: {res.stats.get('alternatives', 0)}")
    print(f"   • Assertions Checked:  {res.stats.get('assertions', 0)}")
    return 0


def _resolve_step_index(manifest: RouteManifest, step_spec: str) -> int:
    """Resolve a step index string (e.g. '0' or '1') to a valid 0-based index."""
    val = int(step_spec.strip())
    total = len(manifest.steps)
    if 0 <= val < total:
        return val
    if 1 <= val <= total:
        return val - 1
    raise IndexError(f"Step index '{step_spec}' is out of bounds (total steps: {total})")


def cmd_run(args: argparse.Namespace) -> int:
    """Runs a playbook route, displaying the Pinned Stepping Deck HUD."""
    playbook_path = args.playbook
    val_res = RouteValidator.validate_file(playbook_path)

    if not val_res.is_valid:
        print(f"❌ Cannot run playbook '{playbook_path}': Validation failed.", file=sys.stderr)
        for e in val_res.errors:
            print(f"   {e}", file=sys.stderr)
        return 1

    manifest = val_res.manifest
    if manifest is None:
        print("❌ Could not generate RouteManifest from playbook.", file=sys.stderr)
        return 1

    checkpoint_path = args.checkpoint or f".{manifest.route_id}.checkpoint.json"

    # Load from checkpoint if available and not dry-run
    if not args.dry_run and args.checkpoint and Path(args.checkpoint).is_file():
        try:
            sm = RouteStateMachine.load_checkpoint(args.checkpoint)
            manifest = sm.manifest
        except Exception as e:
            print(f"⚠️  Could not load checkpoint '{args.checkpoint}': {e}. Initializing fresh.", file=sys.stderr)
            sm = RouteStateMachine(manifest)
    else:
        sm = RouteStateMachine(manifest)

    # Apply branch swaps if requested: --swap <step_idx>:<rank>
    if args.swap:
        for swap_item in args.swap:
            if ":" not in swap_item:
                print(f"❌ Invalid --swap format '{swap_item}'. Expected '<step_idx>:<rank>'.", file=sys.stderr)
                return 1
            step_str, rank_str = swap_item.split(":", 1)
            try:
                target_idx = _resolve_step_index(manifest, step_str)
                target_rank = int(rank_str.strip())
                swapped_branch = sm.swap_branch(target_idx, target_rank)
                print(f"🔀 Swapped Step {target_idx + 1} with branch Rank {target_rank}: '{swapped_branch.label}'")
            except Exception as e:
                print(f"❌ Failed to swap branch '{swap_item}': {e}", file=sys.stderr)
                return 1

    # Dry-Run Mode
    if args.dry_run:
        print("\n" + "=" * SteppingDeckHUD.WIDTH)
        print("  DRY-RUN SIMULATION: Stepping Deck HUD & Transitions")
        print("=" * SteppingDeckHUD.WIDTH + "\n")

        sm.start()
        hud_output = SteppingDeckHUD.render(sm, mode_label="DRY-RUN", checkpoint_path=checkpoint_path)
        print(hud_output)
        print()

        # Step through simulated transitions
        step_idx = 0
        total_steps = len(manifest.steps)
        while sm.is_running and not sm.is_completed:
            step = sm.get_current_step()
            if step is None:
                break
            print(f"👉 [DRY-RUN] Advancing Step {step_idx + 1}/{total_steps}: {step.title}")
            if step.assertions:
                for a in step.assertions:
                    print(f"   ✔ [DRY-RUN] Assertion verified: {a}")

            next_step = sm.advance_step()
            step_idx += 1
            if next_step is None:
                break

        print("\n" + "=" * SteppingDeckHUD.WIDTH)
        print("  FINAL STATE: Stepping Deck HUD")
        print("=" * SteppingDeckHUD.WIDTH + "\n")
        final_hud = SteppingDeckHUD.render(sm, mode_label="DRY-RUN", checkpoint_path=checkpoint_path)
        print(final_hud)
        print(f"\n✨ [DRY-RUN COMPLETE] Successfully simulated all {total_steps} steps with 0 errors.\n")
        return 0

    # Live Run Mode: start if PENDING, or resume if PAUSED
    if sm.manifest.state == StepStatus.PENDING:
        sm.start()
    elif sm.is_paused:
        sm.resume()

    try:
        sm.save_checkpoint(checkpoint_path)
    except Exception:
        pass

    hud_output = SteppingDeckHUD.render(sm, mode_label="LIVE", checkpoint_path=checkpoint_path)
    print("\n" + hud_output + "\n")

    # Non-interactive live run: advance through all steps cleanly
    if args.non_interactive or not sys.stdin.isatty():
        total_steps = len(manifest.steps)
        while not sm.is_completed and not sm.is_failed:
            current = sm.get_current_step()
            if current:
                print(f"👉 Step {current.index + 1}/{total_steps} Active: {current.title}")
            sm.advance_step()
            try:
                sm.save_checkpoint(checkpoint_path)
            except Exception:
                pass

        final_hud = SteppingDeckHUD.render(sm, mode_label="LIVE", checkpoint_path=checkpoint_path)
        print("\n" + final_hud + "\n")
        print("✨ [ROUTE COMPLETED] Execution finished successfully.")
        return 0

    # Interactive live run with pause/step controls
    while not sm.is_completed and not sm.is_failed:
        curr = sm.get_current_step()
        step_str = f"Step {curr.index + 1}" if curr else "End"
        try:
            prompt_msg = (
                f"\n[Deck Controls ({step_str})]: "
                f"[Enter] Advance Step | [s] Swap Branch | [p] Pause/Resume | [q] Quit > "
            )
            choice = input(prompt_msg).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborting route execution.")
            sm.abort("User interrupted")
            try:
                sm.save_checkpoint(checkpoint_path)
            except Exception:
                pass
            return 1

        if choice in ("", "enter", "next", "n", "advance"):
            sm.advance_step()
            try:
                sm.save_checkpoint(checkpoint_path)
            except Exception:
                pass
            print("\n" + SteppingDeckHUD.render(sm, mode_label="LIVE", checkpoint_path=checkpoint_path) + "\n")

        elif choice in ("s", "swap"):
            curr_idx = sm.manifest.current_step_idx
            try:
                swap_in = input(f"Enter swap as '<step_idx>:<rank>' (or rank for current step {curr_idx + 1}): ").strip()
                if ":" in swap_in:
                    s_idx_str, s_rank_str = swap_in.split(":", 1)
                    t_idx = _resolve_step_index(manifest, s_idx_str)
                    t_rank = int(s_rank_str)
                else:
                    t_idx = curr_idx
                    t_rank = int(swap_in)
                branch = sm.swap_branch(t_idx, t_rank)
                print(f"🔀 Swapped Step {t_idx + 1} with branch Rank {t_rank}: '{branch.label}'")
                try:
                    sm.save_checkpoint(checkpoint_path)
                except Exception:
                    pass
                print("\n" + SteppingDeckHUD.render(sm, mode_label="LIVE", checkpoint_path=checkpoint_path) + "\n")
            except Exception as e:
                print(f"❌ Swap failed: {e}")

        elif choice in ("p", "pause", "resume"):
            if sm.is_paused:
                sm.resume()
                print("▶ Route resumed.")
            else:
                if hasattr(sm, "pause_by_user"):
                    sm.pause_by_user("User requested pause")
                else:
                    sm.pause("User paused")
                print("⏸ Route paused.")
            try:
                sm.save_checkpoint(checkpoint_path)
            except Exception:
                pass
            print("\n" + SteppingDeckHUD.render(sm, mode_label="LIVE", checkpoint_path=checkpoint_path) + "\n")

        elif choice in ("q", "quit", "exit"):
            sm.abort("User quit")
            try:
                sm.save_checkpoint(checkpoint_path)
            except Exception:
                pass
            print("Route execution aborted.")
            return 0

    if sm.is_completed:
        print("🎉 Route completed successfully.")
        return 0
    return 1


def cmd_mine(args: argparse.Namespace) -> int:
    """Ingests transcript files and outputs a mined route map playbook."""
    transcript_paths = args.transcripts
    if not transcript_paths:
        default_brain = Path.home() / ".gemini" / "antigravity" / "brain"
        if default_brain.exists():
            transcript_paths = [str(default_brain)]
        else:
            print("No transcript paths provided and default brain directory not found.", file=sys.stderr)
            return 1

    miner = PromptRouteMiner()
    routes = miner.mine_transcripts(transcript_paths)

    if not routes:
        print("No routes mined from the provided transcripts.", file=sys.stderr)
        return 1

    if args.format == "json":
        output_content = json.dumps(routes, indent=2)
    else:
        output_content = "\n\n---\n\n".join(miner.export_route_markdown(r) for r in routes)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_content, encoding="utf-8")
        print(f"Discovered {len(routes)} route(s) exported to {out_path}")
    else:
        print(output_content)

    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    """Handles Antigravity's Stop hook via stdin/stdout JSON."""
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except Exception:
        payload = {}

    termination_reason = payload.get("terminationReason", "model_stop")
    if termination_reason != "model_stop":
        sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
        sys.stdout.flush()
        return 0

    workspace_paths = payload.get("workspacePaths", [])
    cwd = Path(workspace_paths[0]) if workspace_paths else Path.cwd()

    # Delegate to hook_driver if present
    try:
        from auto_reply_route import hook_driver
        if hasattr(hook_driver, "AntigravityHookDriver"):
            driver = hook_driver.AntigravityHookDriver(base_dir=cwd)
            resp = driver.handle_stop_hook(payload)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            return 0
        elif hasattr(hook_driver, "handle_stop_hook"):
            resp = hook_driver.handle_stop_hook(payload)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            return 0
    except ImportError:
        pass

    # Check for active route checkpoint in workspace
    checkpoint_file = cwd / ".agy-route-state.json"

    if checkpoint_file.is_file():
        try:
            sm = RouteStateMachine.load_checkpoint(str(checkpoint_file))
            if sm.is_running:
                step = sm.get_current_step()
                if step:
                    # Advance to next step for subsequent turn
                    next_step = sm.advance_step()
                    sm.save_checkpoint(str(checkpoint_file))
                    target = next_step or step
                    reason = f"[Route Step {target.index + 1}: {target.title}]\n\n{target.primary_prompt}"
                    sys.stdout.write(json.dumps({"decision": "continue", "reason": reason}) + "\n")
                    sys.stdout.flush()
                    return 0
        except Exception:
            pass

    # Default fallback: allow stop
    sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
    sys.stdout.flush()
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    """Predicts and formats ambient ghost route suggestions."""
    from auto_reply_route.suggester import RouteSuggester

    seed_prompt = args.prompt or ""
    if not seed_prompt and not sys.stdin.isatty():
        try:
            import select
            # Check if stdin has data ready without blocking
            rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
            if rlist:
                seed_prompt = sys.stdin.read().strip()
        except Exception:
            seed_prompt = ""

    suggester = RouteSuggester(playbooks_dir=args.playbooks_dir)
    suggestions = suggester.suggest_routes(seed_prompt, top_k=args.top_k)

    if not suggestions:
        print("No route suggestions found.", file=sys.stderr)
        return 1

    if args.cards:
        plain = (args.format == "plain")
        output = suggester.format_detailed_cards(suggestions, plain=plain)
        print(output)
    else:
        output = suggester.format_suggestion_chips(suggestions, format_type=args.format)
        print(output)

    if args.interactive:
        if not sys.stdin.isatty():
            return 0
        try:
            choice = input("\nSelect [1-3] to execute route, or Enter to skip: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if not choice:
            return 0

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(suggestions):
                selected = suggestions[idx - 1]
                playbook_file = None
                if selected.preset_slug:
                    for d in [
                        Path("playbooks"),
                        Path("auto_reply_route/playbooks"),
                        Path(__file__).resolve().parent.parent.parent / "playbooks",
                    ]:
                        cand = d / f"{selected.preset_slug}.route.md"
                        if cand.is_file():
                            playbook_file = str(cand)
                            break
                if playbook_file:
                    run_args = argparse.Namespace(
                        playbook=playbook_file,
                        dry_run=False,
                        checkpoint=None,
                        non_interactive=False,
                        swap=[],
                    )
                    return cmd_run(run_args)
                else:
                    manifest = suggester.resolve_manifest(selected, playbooks_dir=args.playbooks_dir)
                    sm = RouteStateMachine(manifest)
                    sm.start()
                    print(f"\n🚀 Started route: {manifest.title}")
                    print(SteppingDeckHUD.render(sm, mode_label="LIVE"))
                    return 0

    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Build a dynamic multi-branch route from a seed prompt."""
    from auto_reply_route.builder import RouteBuilder
    from auto_reply_route.miner import PromptNormalizer

    # Extract step budget prefix if present (e.g. "[4] ...", "4: ..."), default to 1!
    configured_steps = getattr(args, "steps", None)
    if configured_steps is None:
        steps, clean_prompt = PromptNormalizer.extract_step_budget(args.prompt, default=1)
    else:
        steps = configured_steps
        _, clean_prompt = PromptNormalizer.extract_step_budget(args.prompt, default=steps)

    if not clean_prompt.strip():
        print("❌ Error: prompt cannot be empty or whitespace.", file=sys.stderr)
        return 2

    if steps < 1 or steps > 12:
        print(f"❌ Error: --steps must be between 1 and 12 (got {steps}).", file=sys.stderr)
        return 2

    args.prompt = clean_prompt
    max_subagents = getattr(args, "max_subagents", 3)
    if getattr(args, "interactive", False):
        builder = RouteBuilder()
        manifest = builder.interactive_build(clean_prompt)
    elif getattr(args, "matrix", True):
        from auto_reply_route.prompt_matrix import MatrixBeamRouter
        router = MatrixBeamRouter()
        manifest = router.map_route_from_matrix(
            clean_prompt,
            num_steps=steps,
            alternatives_per_step=4,
            max_subagents=max_subagents,
        )
        builder = RouteBuilder()
    else:
        builder = RouteBuilder()
        manifest = builder.build_route_from_prompt(clean_prompt, num_steps=steps)

    if getattr(args, "fast_review", False):
        from auto_reply_route.refiner import GeminiRouteRefiner
        refiner = GeminiRouteRefiner()
        manifest = refiner.refine_manifest(
            clean_prompt,
            manifest,
            timeout_s=getattr(args, "review_timeout", 1.5),
        )

    markdown = builder.export_to_playbook(manifest, filepath=args.output)
    if args.output:
        print(f"\n✔ Route successfully exported to {args.output}")
    else:
        print(markdown)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initializes Antigravity Stop hook and Route Runner skill in workspace."""
    target_dir = Path(getattr(args, "dir", ".")).resolve()
    agents_dir = target_dir / ".agents"
    hooks_file = agents_dir / "hooks.json"
    skill_dir = agents_dir / "skills" / "route-runner"
    skill_file = skill_dir / "SKILL.md"

    if hooks_file.exists() and not getattr(args, "force", False):
        print(f"ℹ Configuration already exists at {hooks_file}. Use --force to overwrite.")
        return 0

    agents_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)

    hook_config = {
        "hooks": {
            "Stop": [
                {
                    "type": "command",
                    "command": "agy-route hook",
                    "timeout": 30,
                }
            ]
        }
    }
    hooks_file.write_text(json.dumps(hook_config, indent=2) + "\n", encoding="utf-8")

    # Install skills: route-runner, q, g, queue-prompts
    skills_to_install = ["route-runner", "q", "g", "queue-prompts"]
    repo_skills_root = Path(__file__).resolve().parent.parent.parent / "skills"
    installed_skills: list[Path] = []

    for skill_name in skills_to_install:
        s_target_dir = agents_dir / "skills" / skill_name
        s_target_dir.mkdir(parents=True, exist_ok=True)
        s_target_file = s_target_dir / "SKILL.md"

        s_source_file = repo_skills_root / skill_name / "SKILL.md"
        if not s_source_file.is_file():
            s_source_file = Path.cwd() / ".agents" / "skills" / skill_name / "SKILL.md"

        if s_source_file.is_file() and s_source_file != s_target_file:
            s_target_file.write_text(s_source_file.read_text(encoding="utf-8"), encoding="utf-8")
            installed_skills.append(s_target_file)
        elif not s_target_file.is_file():
            s_target_file.write_text(f"---\nname: {skill_name}\n---\n", encoding="utf-8")
            installed_skills.append(s_target_file)

    print(f"✨ [INITIALIZED] Auto-Reply Route Stop Hook & Skills configured in {agents_dir}")
    print(f"   • Hook: {hooks_file}")
    for sk in installed_skills:
        print(f"   • Skill: {sk}")
    return 0


def cmd_init_dna(args: argparse.Namespace) -> int:
    """Bootstraps Operator DNA matrix from AGENTS.md and user transcripts."""
    from auto_reply_route.dna import ensure_operator_dna, personal_dna_path

    target_dir = getattr(args, "dir", ".")
    target_path = getattr(args, "output", None)
    force = getattr(args, "force", False)
    mine = getattr(args, "mine", False)

    try:
        q_path = personal_dna_path()
        dest_path = ensure_operator_dna(
            workspace_root=target_dir,
            target_path=target_path,
            force=force,
            mine=mine,
        )

        if not target_path and dest_path.resolve() == q_path.resolve():
            print(f"✨ [PRESERVED] the operator's Operator DNA matrix active at: {dest_path}")
            print("   the operator's personal DNA file is 100% untouched.")
            print("   Tip: Use --output <path> to generate an independent copy.")
        else:
            print(f"🧬 [INITIALIZED] Operator DNA Matrix ready at: {dest_path}")
            print(f"   • File: {dest_path}")
            print(f"   • Mining enabled: {mine}")
            print(f"   • Force overwrite: {force}")
        return 0
    except Exception as e:
        print(f"❌ Failed to bootstrap Operator DNA: {e}", file=sys.stderr)
        return 1


def cmd_watch(args: argparse.Namespace) -> int:
    """Live-tails active queued messages and prints terminal status cards."""
    from auto_reply_route.queue_watcher import QueueWatcher

    target_dir = Path(getattr(args, "dir", ".")).resolve()
    conv_id = getattr(args, "conversation_id", "default")
    interval = getattr(args, "interval", 0.5)
    once = getattr(args, "once", False)
    as_json = getattr(args, "json", False)

    watcher = QueueWatcher(target_dir=target_dir, conversation_id=conv_id, poll_interval=interval)

    if as_json:
        snapshot = watcher.snapshot()
        print(json.dumps(snapshot, indent=2))
        return 0

    watcher.watch(once=once)
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    """Manages active Queued Messages for the current workspace session."""
    from auto_reply_route.builder import generate_followup_queue
    from auto_reply_route.models import MessageQueueManifest, QueuedMessageStatus
    from auto_reply_route.queue_watcher import (
        QueueWatcher,
        _bold,
        _cyan,
        _dim,
        _green,
        _magenta,
        _red,
        _yellow,
    )

    target_dir = Path(getattr(args, "dir", ".")).resolve()
    conv_id = getattr(args, "conversation_id", "default")
    safe_conv = re.sub(r"[^a-zA-Z0-9_\-]", "_", conv_id)
    queue_file = target_dir / f".queued_messages_{safe_conv}.json"

    as_json = getattr(args, "json", False)
    action = getattr(args, "queue_action", "list")
    auto_gen_count = getattr(args, "auto_generate", None)

    # If --auto-generate flag is provided, override action to generate
    if auto_gen_count is not None:
        action = "generate"
        setattr(args, "count", auto_gen_count)

    if action == "status":
        watcher = QueueWatcher(target_dir=target_dir, conversation_id=conv_id)
        if as_json:
            print(json.dumps(watcher.snapshot(), indent=2))
            return 0
        card = watcher.format_status_card()
        print(card)
        return 0

    elif action == "generate":
        prompt = getattr(args, "prompt", "")
        count = getattr(args, "count", 1)
        if not prompt:
            if as_json:
                print(json.dumps({"error": "Prompt is required for queue generation."}, indent=2))
            else:
                print(_red("Error: Prompt is required for queue generation."), file=sys.stderr)
            return 1
        queue = generate_followup_queue(prompt, count=count, conversation_id=conv_id)
        if getattr(args, "save", True):
            queue.save_to_file(queue_file)
            if as_json:
                print(json.dumps(queue.to_dict(), indent=2))
            else:
                print(f"✨ {_bold(_green('[QUEUE GENERATED & SAVED]'))} {len(queue.messages)} follow-up message(s) queued to {_cyan(queue_file.name)}")
        else:
            print(json.dumps(queue.to_dict(), indent=2))
        return 0

    elif action == "list":
        if not queue_file.is_file():
            if as_json:
                print(json.dumps({"exists": False, "messages": []}, indent=2))
            else:
                print(f"No active queue found at {queue_file.name}")
            return 0
        queue = MessageQueueManifest.load_from_file(queue_file)
        if not queue or queue.is_empty:
            if as_json:
                print(json.dumps(queue.to_dict() if queue else {"exists": True, "messages": []}, indent=2))
            else:
                print("Queue is empty.")
            return 0

        if as_json:
            print(json.dumps(queue.to_dict(), indent=2))
            return 0

        paused_str = f" {_yellow('[PAUSED]')}" if queue.is_paused else ""
        print(f"\n📋 {_bold('Queued Messages')} ({len(queue.messages)}) [Active: {queue.active_index}]{paused_str}:")
        for idx, m in enumerate(queue.messages):
            if m.status == QueuedMessageStatus.COMPLETED:
                status_icon = _green("✔")
            elif idx == queue.active_index and not queue.is_paused:
                status_icon = _cyan("▶")
            elif queue.is_paused and idx == queue.active_index:
                status_icon = _yellow("⏸")
            else:
                status_icon = _dim("⏳")
            domain_badge = _magenta(f"({m.domain})")
            print(f"  {status_icon} [{idx + 1}] {domain_badge}: {m.prompt}")
        print()
        return 0

    elif action == "clear":
        if queue_file.is_file():
            queue_file.unlink()
            if as_json:
                print(json.dumps({"cleared": True, "file": queue_file.name}, indent=2))
            else:
                print(f"{_green('✔')} Cleared queue file {_cyan(queue_file.name)}")
        else:
            if as_json:
                print(json.dumps({"cleared": False, "file": queue_file.name, "message": "No active queue file to clear."}, indent=2))
            else:
                print("No active queue file to clear.")
        return 0

    elif action == "add":
        prompt = getattr(args, "prompt", "")
        if not prompt:
            if as_json:
                print(json.dumps({"error": "prompt is required"}, indent=2))
            else:
                print("Error: prompt is required", file=sys.stderr)
            return 1
        queue = MessageQueueManifest.load_from_file(queue_file) if queue_file.is_file() else MessageQueueManifest(conversation_id=conv_id)
        if queue is None:
            queue = MessageQueueManifest(conversation_id=conv_id)
        domain = getattr(args, "domain", "general")
        msg = queue.add_message(prompt, domain=domain)
        queue.save_to_file(queue_file)
        if as_json:
            print(json.dumps(msg.to_dict(), indent=2))
        else:
            print(f"{_green('✔')} Added message [{msg.index + 1}] to queue: '{prompt[:60]}...'")
        return 0

    elif action == "pop":
        if not queue_file.is_file():
            if as_json:
                print(json.dumps({"popped": None, "error": "No queue file found."}, indent=2))
            else:
                print("No active queue file found.")
            return 1
        queue = MessageQueueManifest.load_from_file(queue_file)
        if not queue or queue.is_empty:
            if as_json:
                print(json.dumps({"popped": None, "error": "Queue is empty."}, indent=2))
            else:
                print("Queue is empty.")
            return 0

        popped = queue.pop_next_message()
        if popped:
            queue.save_to_file(queue_file)
            if as_json:
                print(json.dumps({"popped": popped.to_dict(), "remaining": queue.pending_count}, indent=2))
            else:
                print(f"🚀 {_bold(_green('[POPPED MESSAGE]'))} [{popped.index + 1}/{queue.total_count}] ({popped.domain}): {popped.prompt}")
        else:
            if as_json:
                print(json.dumps({"popped": None, "is_paused": queue.is_paused, "is_completed": queue.is_completed}, indent=2))
            else:
                if queue.is_paused:
                    print(f"{_yellow('⏸ Queue is paused')}: {queue.metadata.get('pause_reason', 'Human preemption')}")
                else:
                    print(_green("✨ Queue is already completed (no pending messages)."))
        return 0

    elif action == "pause":
        if not queue_file.is_file():
            if as_json:
                print(json.dumps({"error": "No active queue file found."}, indent=2))
            else:
                print("No active queue file found.")
            return 1
        queue = MessageQueueManifest.load_from_file(queue_file)
        if not queue:
            return 1
        reason = getattr(args, "prompt", "") or getattr(args, "reason", "Manual CLI pause")
        queue.pause(reason=reason)
        queue.save_to_file(queue_file)
        if as_json:
            print(json.dumps(queue.to_dict(), indent=2))
        else:
            print(f"⏸ {_bold(_yellow('[QUEUE PAUSED]'))} Reason: {reason}")
        return 0

    elif action == "resume":
        if not queue_file.is_file():
            if as_json:
                print(json.dumps({"error": "No active queue file found."}, indent=2))
            else:
                print("No active queue file found.")
            return 1
        queue = MessageQueueManifest.load_from_file(queue_file)
        if not queue:
            return 1
        queue.resume()
        queue.save_to_file(queue_file)
        if as_json:
            print(json.dumps(queue.to_dict(), indent=2))
        else:
            print(f"▶ {_bold(_green('[QUEUE RESUMED]'))} Ready for stop hook auto-dispatch.")
        return 0

    return 0


# ============================================================================
# Argument Parser & CLI Entry Point
# ============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-route",
        description="Auto-Reply Map & Route Engine for Antigravity",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. run
    run_parser = subparsers.add_parser("run", help="Run a route playbook with the Stepping Deck HUD")
    run_parser.add_argument("playbook", type=str, help="Path to .route.md playbook file")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate execution without side effects")
    run_parser.add_argument("--checkpoint", type=str, default=None, help="Path to checkpoint state file")
    run_parser.add_argument("--non-interactive", action="store_true", help="Run without interactive pause/step prompts")
    run_parser.add_argument(
        "--swap",
        action="append",
        default=[],
        help="Swap branch before execution: <step_idx>:<rank> (e.g. 0:2)",
    )
    run_parser.add_argument(
        "--watchdog",
        action="store_true",
        help="Enable tool usage watchdog to monitor step execution activity",
    )
    run_parser.add_argument(
        "--watchdog-timeout",
        type=float,
        default=45.0,
        help="Inactivity timeout in seconds for watchdog (default: 45.0)",
    )

    # 2. validate
    val_parser = subparsers.add_parser("validate", help="Lint and validate a .route.md playbook")
    val_parser.add_argument("playbook", type=str, help="Path to .route.md playbook file")

    # 3. mine
    mine_parser = subparsers.add_parser("mine", help="Mine canonical prompt routes from transcript logs")
    mine_parser.add_argument(
        "--transcripts",
        "-t",
        nargs="+",
        default=[],
        help="Path(s) to transcript .jsonl files or directories.",
    )
    mine_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path to output .route.md or .json file.",
    )
    mine_parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown).",
    )

    # 4. hook
    subparsers.add_parser("hook", help="Antigravity Stop hook entry point (stdin/stdout JSON)")

    # 6. suggest
    suggest_parser = subparsers.add_parser(
        "suggest", help="Predict and suggest ghost routes for an initial prompt"
    )
    suggest_parser.add_argument(
        "prompt",
        type=str,
        nargs="?",
        default="",
        help="Initial seed prompt (e.g. 'Build a Stripe webhook')",
    )
    suggest_parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=3,
        help="Number of suggested routes (default: 3)",
    )
    suggest_parser.add_argument(
        "--format",
        "-f",
        choices=["terminal", "plain", "json", "markdown"],
        default="terminal",
        help="Output format (default: terminal)",
    )
    suggest_parser.add_argument(
        "--playbooks-dir",
        "-p",
        type=str,
        default=None,
        help="Path to directory containing .route.md playbooks",
    )
    suggest_parser.add_argument(
        "--cards",
        action="store_true",
        help="Display detailed preview cards showing step breakdown",
    )
    suggest_parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactively select a route and execute it",
    )

    # 7. build
    build_parser = subparsers.add_parser(
        "build", help="Generate a dynamic multi-branch route from a seed prompt"
    )
    build_parser.add_argument(
        "prompt",
        type=str,
        help="Seed prompt describing the feature or task",
    )
    build_parser.add_argument(
        "--steps",
        "-s",
        type=int,
        default=None,
        help="Number of steps in route trajectory (1-12, default: 1 if omitted)",
    )
    build_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path to save generated .route.md file",
    )
    build_parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive builder mode to customize branches",
    )
    build_parser.add_argument(
        "--matrix",
        "-m",
        action="store_true",
        default=True,
        help="Map route using the 1,008-prompt canonical matrix (default: True)",
    )
    build_parser.add_argument(
        "--max-subagents",
        "-k",
        type=int,
        default=3,
        help="Maximum number of subagents allowed per turn (default: 3)",
    )
    build_parser.add_argument(
        "--fast-review",
        "-r",
        action="store_true",
        default=False,
        help="Enable fast 300 TPS Gemini Flash speculative review and surgical polish pass",
    )
    build_parser.add_argument(
        "--review-timeout",
        type=float,
        default=1.5,
        help="Timeout in seconds for fast review pass (default: 1.5s)",
    )

    # 8. init
    init_parser = subparsers.add_parser(
        "init", help="Initialize Antigravity Stop hook and Route Runner skill in workspace"
    )
    init_parser.add_argument(
        "--dir", "-d", type=str, default=".", help="Target workspace directory (default: current directory)"
    )
    init_parser.add_argument(
        "--force", "-f", action="store_true", help="Overwrite existing configuration if present"
    )

    # 9. queue
    queue_parser = subparsers.add_parser(
        "queue", help="Manage or inspect active Queued Messages"
    )
    queue_parser.add_argument(
        "queue_action",
        nargs="?",
        choices=["list", "status", "generate", "clear", "add", "pop", "pause", "resume"],
        default="list",
        help="Action to perform on the message queue (default: list)",
    )
    queue_parser.add_argument(
        "prompt",
        nargs="?",
        default="",
        help="Prompt text for generate, add, or pause actions",
    )
    queue_parser.add_argument(
        "--auto-generate",
        "-a",
        type=int,
        default=None,
        choices=[1, 2, 3, 4, 5],
        help="Automatically generate 1-5 follow-up prompts from prompt and save",
    )
    queue_parser.add_argument(
        "--count", "-n", type=int, default=1, help="Number of follow-up messages to generate (default: 1)"
    )
    queue_parser.add_argument(
        "--domain", type=str, default="general", help="Domain category for added message"
    )
    queue_parser.add_argument(
        "--reason", type=str, default="Manual CLI pause", help="Pause reason for pause action"
    )
    queue_parser.add_argument(
        "--json", action="store_true", default=False, help="Output response in machine-readable JSON format"
    )
    queue_parser.add_argument(
        "--conversation-id", "-c", type=str, default="default", help="Conversation ID scope"
    )
    queue_parser.add_argument(
        "--dir", "-d", type=str, default=".", help="Target workspace directory"
    )
    queue_parser.add_argument(
        "--no-save", dest="save", action="store_false", default=True, help="Do not save generated queue to disk"
    )

    # 10. watch
    watch_parser = subparsers.add_parser(
        "watch", help="Live-tail active queued messages and print status cards"
    )
    watch_parser.add_argument(
        "--dir", "-d", type=str, default=".", help="Target workspace directory"
    )
    watch_parser.add_argument(
        "--conversation-id", "-c", type=str, default="default", help="Conversation ID scope"
    )
    watch_parser.add_argument(
        "--interval", "-i", type=float, default=0.5, help="Polling interval in seconds"
    )
    watch_parser.add_argument(
        "--once", action="store_true", default=False, help="Render single status card snapshot and exit"
    )
    watch_parser.add_argument(
        "--json", action="store_true", default=False, help="Output JSON snapshot instead of visual card"
    )

    # 11. init-dna
    init_dna_parser = subparsers.add_parser(
        "init-dna", help="Bootstrap Operator DNA matrix from AGENTS.md and user transcripts"
    )
    init_dna_parser.add_argument(
        "--mine",
        "-m",
        action="store_true",
        default=False,
        help="Mine recent user transcripts for genuine prompt examples",
    )
    init_dna_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        default=False,
        help="Force regeneration of Operator DNA file even if destination exists",
    )
    init_dna_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Target output path for the generated Operator DNA file",
    )
    init_dna_parser.add_argument(
        "--dir",
        "-d",
        type=str,
        default=".",
        help="Target workspace directory for workspace AGENTS.md ingestion",
    )

    return parser



def main(args: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if args is None else args)

    # Backward compatibility: if first arg is not a subcommand and looks like miner flags, route to mine
    subcommands = {
        "run",
        "validate",
        "mine",
        "hook",
        "suggest",
        "build",
        "init",
        "init-dna",
        "queue",
        "watch",
        "-h",
        "--help",
    }

    if raw_args and raw_args[0] not in subcommands and any(a in ("--transcripts", "-t", "--format", "-f") for a in raw_args):
        raw_args.insert(0, "mine")

    if raw_args and raw_args[0] == "queue":
        valid_actions = {"list", "status", "generate", "clear", "add", "pop", "pause", "resume"}
        has_auto_gen = any(a in ("--auto-generate", "-a") for a in raw_args)
        flags: list[str] = []
        positionals: list[str] = []
        options_with_arg = {
            "--auto-generate",
            "-a",
            "--count",
            "-n",
            "--domain",
            "--reason",
            "--conversation-id",
            "-c",
            "--dir",
            "-d",
        }
        skip_next = False
        for item in raw_args[1:]:
            if skip_next:
                flags.append(item)
                skip_next = False
                continue
            if item in options_with_arg:
                flags.append(item)
                skip_next = True
                continue
            if item.startswith("-"):
                flags.append(item)
                continue
            positionals.append(item)

        if has_auto_gen:
            if not positionals or positionals[0] not in valid_actions:
                positionals.insert(0, "generate")
        elif positionals and positionals[0] not in valid_actions:
            positionals.insert(0, "add")

        raw_args = ["queue"] + flags + positionals

    parser = build_parser()
    parsed = parser.parse_args(raw_args)

    if not parsed.command:
        parser.print_help()
        return 0

    if parsed.command == "run":
        return cmd_run(parsed)
    elif parsed.command == "validate":
        return cmd_validate(parsed)
    elif parsed.command == "mine":
        return cmd_mine(parsed)
    elif parsed.command == "hook":
        return cmd_hook(parsed)
    elif parsed.command == "suggest":
        return cmd_suggest(parsed)
    elif parsed.command == "build":
        return cmd_build(parsed)
    elif parsed.command == "init":
        return cmd_init(parsed)
    elif parsed.command == "init-dna":
        return cmd_init_dna(parsed)
    elif parsed.command == "queue":
        return cmd_queue(parsed)
    elif parsed.command == "watch":
        return cmd_watch(parsed)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
