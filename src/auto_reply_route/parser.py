from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    RouteManifest,
    RouteStep,
    StepStatus,
)


class RouteParser:
    """Parser for Markdown-based route playbooks (.route.md)."""

    @classmethod
    def _extract_title(cls, text: str) -> str:
        """Extract a concise step title (typically 3-6 words) from step text."""
        # Use first non-empty line
        first_line = ""
        for line in text.splitlines():
            s = line.strip()
            if s:
                first_line = s
                break

        clean = re.sub(r"[*_`#]", "", first_line).strip()
        if not clean:
            return ""

        # Check for explicit colon delimiter e.g. "Title: Description"
        if ":" in clean:
            prefix = clean.split(":", 1)[0].strip()
            prefix_words = prefix.split()
            if 1 <= len(prefix_words) <= 6:
                return " ".join(prefix_words).strip()

        # Check for dash delimiter e.g. "Title - Description"
        if " - " in clean:
            prefix = clean.split(" - ", 1)[0].strip()
            prefix_words = prefix.split()
            if 1 <= len(prefix_words) <= 6:
                return " ".join(prefix_words).strip()

        words = clean.split()
        if len(words) <= 6:
            return " ".join(words).rstrip(".:;,")

        # For longer text, check for punctuation breakpoint between word 3 and 6
        for idx in range(2, min(len(words), 6)):
            if words[idx].endswith((".", ",", ";", ":", "-")):
                return " ".join(words[: idx + 1]).rstrip(".:;,- ")

        # Lookahead: if 4th word is a preposition or article, grab 5 words to avoid dangling particle
        prepositions = {
            "in", "on", "at", "to", "for", "with", "by", "from", "of", "the", "a", "an", "and", "or"
        }
        if len(words) > 4 and words[3].lower().rstrip(".,") in prepositions:
            return " ".join(words[:5]).rstrip(".:;,")
        return " ".join(words[:4]).rstrip(".:;,")

    @classmethod
    def _parse_alternative_bullet(cls, raw_bullet: str, default_rank: int) -> tuple[str, str, int]:
        """Parse bullet text into label, prompt template, and rank."""
        text = raw_bullet.strip()
        assigned_rank = default_rank

        # Check if rank is explicitly tagged like [Rank 3] or [rank=2]
        explicit_rank_match = re.search(r"\[(?:rank[=:]?\s*)(\d+)\]", text, re.IGNORECASE)
        if explicit_rank_match:
            assigned_rank = int(explicit_rank_match.group(1))
            text = re.sub(r"\[(?:rank[=:]?\s*)\d+\]", "", text, flags=re.IGNORECASE).strip()

        # Pattern 1: *Label*: Prompt or **Label**: Prompt
        m = re.match(r"^\*{1,2}(.*?)\*{1,2}:\s*(.*)$", text)
        if m:
            return m.group(1).strip(), m.group(2).strip(), assigned_rank

        # Pattern 2: [Label]: Prompt or [Label] Prompt
        m = re.match(r"^\[(.*?)\]:?\s*(.*)$", text)
        if m:
            return m.group(1).strip(), m.group(2).strip(), assigned_rank

        # Pattern 3: Label: Prompt
        if ":" in text:
            parts = text.split(":", 1)
            candidate_label = parts[0].strip("*_ ")
            if len(candidate_label.split()) <= 5 and len(candidate_label) <= 35:
                return candidate_label, parts[1].strip(), assigned_rank

        # Fallback: generic label with full text
        return f"Alternative {assigned_rank}", text, assigned_rank

    @classmethod
    def parse_string(cls, content: str, route_id: str = "") -> RouteManifest:
        """Parse raw markdown content into a RouteManifest."""
        lines = content.splitlines()

        # 1. Extract Route Title from `# Route Title`
        title = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break

        if not title:
            if route_id:
                title = route_id.replace("_", " ").replace("-", " ").title()
            else:
                title = "Untitled Route"

        if not route_id:
            slug = re.sub(r"[^a-zA-Z0-9_]+", "_", title.lower()).strip("_")
            route_id = slug or "route_manifest"

        manifest = RouteManifest(
            route_id=route_id,
            title=title,
            steps=[],
            current_step_idx=0,
            state=StepStatus.PENDING,
        )

        steps: list[RouteStep] = []
        current_step: Optional[RouteStep] = None
        current_prompt_lines: list[str] = []
        current_alt: Optional[AlternativeBranch] = None
        current_alt_lines: list[str] = []
        base_alt_indent: Optional[int] = None

        def finalize_step() -> None:
            nonlocal current_step, current_prompt_lines, current_alt, current_alt_lines, base_alt_indent
            if current_step is None:
                return

            if current_alt and current_alt_lines:
                current_alt.prompt_template = "\n".join(current_alt_lines).strip()
                current_alt = None
                current_alt_lines = []

            full_prompt = "\n".join(current_prompt_lines).strip()
            current_step.primary_prompt = full_prompt
            if not current_step.title:
                extracted = cls._extract_title(full_prompt)
                current_step.title = extracted or f"Step {current_step.index + 1}"

            steps.append(current_step)
            current_step = None
            current_prompt_lines = []
            base_alt_indent = None

        # Numbered step pattern at margin: e.g. "1. " or "2. "
        step_pattern = re.compile(r"^\s{0,2}(\d+)[.)]\s*(.*)$")
        # Indented bullet pattern: e.g. "   - ..." or "\t- ..."
        bullet_pattern = re.compile(r"^(\s{2,}|\t+)[-*+]\s+(.*)$")

        for line in lines:
            # Skip Markdown top-level header
            if line.strip().startswith("# "):
                continue

            # Check for top-level numbered step
            step_match = step_pattern.match(line)
            if step_match:
                finalize_step()
                step_body = step_match.group(2).strip()
                new_idx = len(steps)
                current_step = RouteStep(
                    index=new_idx,
                    title="",
                    primary_prompt="",
                    alternatives=[],
                    status=StepStatus.PENDING,
                )
                if step_body:
                    current_prompt_lines.append(step_body)
                continue

            if current_step is None:
                continue

            # Check for indented bullet (alternative branch, assertion, or manifest)
            bullet_match = bullet_pattern.match(line)
            if bullet_match:
                indent_str = bullet_match.group(1)
                indent_len = len(indent_str.expandtabs(4))
                bullet_body = bullet_match.group(2).strip()

                # Check if bullet is an assertion
                lower_bullet = bullet_body.lower()
                if lower_bullet.startswith("assert:") or lower_bullet.startswith("assertion:"):
                    assertion_val = bullet_body.split(":", 1)[1].strip()
                    if assertion_val:
                        current_step.assertions.append(assertion_val)
                    continue

                # Check if bullet is a manifest ref
                if lower_bullet.startswith("manifest:") or lower_bullet.startswith("manifest_ref:"):
                    ref_val = bullet_body.split(":", 1)[1].strip()
                    if ref_val:
                        current_step.manifest_ref = ref_val
                    continue

                # If this bullet is indented deeper than the base alternative bullet, treat as nested sub-bullet
                if current_alt is not None and base_alt_indent is not None and indent_len > base_alt_indent:
                    current_alt_lines.append(line.strip())
                    continue

                # Finalize previous alternative if one was in progress
                if current_alt and current_alt_lines:
                    current_alt.prompt_template = "\n".join(current_alt_lines).strip()
                    current_alt_lines = []

                if base_alt_indent is None:
                    base_alt_indent = indent_len

                # Sequential rank assignment: 1st alt -> 2 (QA_DEFENSIVE), 2nd -> 3 (ALTERNATIVE_ARCH), 3rd -> 4 (FALLBACK)
                default_rank = len(current_step.alternatives) + 2
                label, prompt, alt_rank = cls._parse_alternative_bullet(bullet_body, default_rank)

                alt = AlternativeBranch(
                    rank=alt_rank,
                    label=label,
                    prompt_template=prompt,
                )
                current_step.alternatives.append(alt)
                current_alt = alt
                current_alt_lines = [prompt] if prompt else []
                continue

            # Non-bullet line
            stripped_line = line.strip()
            if not stripped_line:
                # Blank lines inside step prompt or alternative
                if current_alt and current_alt_lines:
                    current_alt_lines.append("")
                elif current_prompt_lines:
                    current_prompt_lines.append("")
                continue

            # Check for inline manifest_ref
            if stripped_line.lower().startswith("manifest:") or stripped_line.lower().startswith("manifest_ref:"):
                current_step.manifest_ref = stripped_line.split(":", 1)[1].strip()
                continue

            # Indented continuation line under an alternative
            if current_alt is not None:
                current_alt_lines.append(stripped_line)
            else:
                current_prompt_lines.append(stripped_line)

        # Finalize the last step
        finalize_step()

        manifest.steps = steps
        return manifest

    @classmethod
    def parse_file(cls, filepath: str) -> RouteManifest:
        """Read and parse a Markdown playbook file into a RouteManifest with directory traversal protection."""
        if "\0" in str(filepath):
            raise ValueError("NUL byte in filepath")

        path = Path(filepath).resolve()
        forbidden_roots = ("/etc", "/var", "/private/etc", "/dev", "/proc", "/sys")
        if any(str(path).startswith(fb) for fb in forbidden_roots):
            raise PermissionError(f"Access denied to system directory path: {filepath}")

        if not path.is_file():
            raise FileNotFoundError(f"Route playbook file not found: {filepath}")
        content = path.read_text(encoding="utf-8")

        stem = path.name
        for suffix in [".route.md", ".route", ".md"]:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break

        return cls.parse_string(content, route_id=stem)
