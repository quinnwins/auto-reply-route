from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional, Sequence, Union

from auto_reply_route.miner import IntentClusterer, IntentStratum, PromptNormalizer
from auto_reply_route.models import RouteManifest, RouteStep, StepStatus
from auto_reply_route.parser import RouteParser


# ============================================================================
# Expert Decision Rubric: Ambient Ghost Route Chips vs. Modal Popups
# ============================================================================
# Why the world's best UX engineer rejects modal popups in favor of ambient chips:
#
# 1. Zero Flow Interruption (Modal Tax vs. Ambient Serendipity):
#    - Modals steal application focus, lock the screen behind a backdrop scrim,
#      demand explicit dismissal (Escape / Cancel), and break the engineer's deep flow.
#    - When an engineer starts typing a prompt, an unsolicited modal induces immediate
#      irritation ("modal blindness" and reflexive Escape hammering).
#    - In contrast, ambient ghost chips rest gently below or beside the input box
#      (like fish-shell autosuggestions or Copilot ghost text). They provide immediate
#      one-click acceleration with ZERO obligation. If ignored, the user simply presses
#      Enter and proceeds normally.
#
# 2. Near-Zero Cognitive Load (The Living-Room Test):
#    - Modals obscure the context (the code diff, terminal logs, or prompt text).
#      The engineer must hold all state in working memory while reading modal copy.
#    - Ambient chips reside directly at the visual locus of attention (saccade distance
#      < 20px vs. 400px jump to a center-screen dialog).
#
# 3. Explicit Trade-offs Stated (Never Absorbed):
#    - Real Estate Truncation: Ambient chips can only fit 2-3 options with concise titles
#      and step counts on a single line. Deep multi-step configurations cannot be displayed
#      without expanding into an optional preview card.
#    - Discoverability of Rare Playbooks: Less frequent, niche playbooks will not appear
#      in the top 3 ambient slots unless the user types specific matching keywords.
#    - Standard Library ANSI Rendering: Standard library terminal rendering requires
#      careful escape code hygiene across varying terminal emulators (xterm, VT100,
#      dumb terminals) without external dependencies like Rich.
# ============================================================================


@dataclass
class RouteSuggestion:
    """Predictive Ghost Route suggestion chip matching developer seed prompts."""

    route_id: str
    title: str
    description: str
    step_count: int
    confidence: float
    preview_steps: list[str] = field(default_factory=list)
    preset_slug: Optional[str] = None
    emoji: str = "🚀"

    def to_dict(self) -> dict[str, Any]:
        """Serialize suggestion to JSON-compatible dictionary."""
        return {
            "route_id": self.route_id,
            "title": self.title,
            "description": self.description,
            "step_count": self.step_count,
            "confidence": round(float(self.confidence), 4),
            "preview_steps": list(self.preview_steps),
            "preset_slug": self.preset_slug,
            "emoji": self.emoji,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteSuggestion:
        """Hydrate suggestion from dictionary."""
        return cls(
            route_id=str(data.get("route_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            step_count=int(data.get("step_count", 0)),
            confidence=float(data.get("confidence", 0.0)),
            preview_steps=list(data.get("preview_steps", [])),
            preset_slug=data.get("preset_slug"),
            emoji=str(data.get("emoji", "🚀")),
        )


@dataclass
class CanonicalPlaybookDefinition:
    """Internal definition for canonical built-in and discovered route playbooks."""

    route_id: str
    title: str
    emoji: str
    description: str
    step_count: int
    preset_slug: str
    preview_steps: list[str]
    primary_strata: list[IntentStratum]
    intent_keywords: set[str]
    archetype: str  # "ship", "spike", "audit", "custom"
    is_canonical: bool = True
    raw_playbook_path: Optional[Path] = None


# Built-in canonical playbooks available out-of-the-box with zero filesystem dependencies
CANONICAL_BUILTINS: list[CanonicalPlaybookDefinition] = [
    CanonicalPlaybookDefinition(
        route_id="ship-feature",
        title="Ship Feature",
        emoji="🚀",
        description="End-to-end production workflow: implementation, QA review, debt audit, e2e proof, and visual polish.",
        step_count=5,
        preset_slug="ship-feature",
        preview_steps=[
            "Build the requested feature cleanly with minimal blast radius",
            "Review implementation with 3-agent QA team and fix defects",
            "Review for executive-level compromises, architectural shortcuts, or hidden debt",
            "Verify end-to-end functionality and capture screenshot proof in browser",
            "Review visual walkthrough evidence and fix remaining rough edges",
        ],
        primary_strata=[IntentStratum.SCAFFOLD_BUILD, IntentStratum.ARCH_DESIGN, IntentStratum.RELEASE_OPS],
        intent_keywords={
            "build", "implement", "feature", "ship", "create", "endpoint", "webhook", "controller",
            "service", "api", "integration", "stripe", "auth", "prod", "production", "full",
            "complete", "develop", "system", "component", "module", "handler", "scaffold", "add",
            "refactor", "rearchitect", "design",
        },
        archetype="ship",
        is_canonical=True,
    ),
    CanonicalPlaybookDefinition(
        route_id="quick-spike",
        title="Fast Spike",
        emoji="⚡",
        description="Rapid feasibility prototype: lightweight zero-dependency implementation and quick execution smoke test.",
        step_count=2,
        preset_slug="quick-spike",
        preview_steps=[
            "Create a rapid working prototype spike",
            "Verify basic end-to-end execution",
        ],
        primary_strata=[IntentStratum.SCAFFOLD_BUILD, IntentStratum.DEBUG_REPAIR],
        intent_keywords={
            "spike", "quick", "fast", "prototype", "experiment", "poc", "mvp", "mock", "draft",
            "simple", "lightweight", "minimal", "smoke", "speed", "explore", "try", "scratch",
            "test", "hack", "script", "instant", "temp", "temporary", "rapid", "toy", "fix",
        },
        archetype="spike",
        is_canonical=True,
    ),
    CanonicalPlaybookDefinition(
        route_id="audit-only",
        title="Full Audit",
        emoji="🛡️",
        description="Deep codebase inspection: static security analysis, dependency vulnerability check, and test coverage verification.",
        step_count=2,
        preset_slug="audit-only",
        preview_steps=[
            "Run comprehensive static analysis and security audit",
            "Verify test coverage and check for brittle mocks",
        ],
        primary_strata=[IntentStratum.VERIFY_QA, IntentStratum.DEBUG_REPAIR],
        intent_keywords={
            "audit", "security", "review", "vulnerability", "vulnerabilities", "leak", "leaks",
            "check", "inspect", "coverage", "lint", "linter", "static", "analysis", "performance",
            "benchmark", "eval", "evaluate", "verify", "verification", "defensive", "sanitize",
            "hardening", "hardened", "flaw", "flaws", "invariant", "invariants", "cleanliness",
        },
        archetype="audit",
        is_canonical=True,
    ),
    CanonicalPlaybookDefinition(
        route_id="feature_build",
        title="Feature Build",
        emoji="🏗️",
        description="Structured 3-step feature pipeline: domain models, route parser, and state machine persistence.",
        step_count=3,
        preset_slug="feature_build",
        preview_steps=[
            "Scaffold Feature Data Models and Core Types",
            "Implement Route Playbook Markdown Parser",
            "Build Route State Machine and Atomic Persistence",
        ],
        primary_strata=[IntentStratum.SCAFFOLD_BUILD, IntentStratum.ARCH_DESIGN],
        intent_keywords={
            "model", "schema", "parser", "state", "machine", "persistence", "pipeline",
            "types", "dataclass", "storage", "checkpoint", "engine", "core",
        },
        archetype="ship",
        is_canonical=False,
    ),
]


class RouteSuggester:
    """Predictive Ghost Route Suggester for instantaneous 1-click ambient route selection.

    Analyzes developer seed prompts, classifies intent stratum and semantic keywords,
    and ranks matching canonical and user-mined playbooks with calibrated confidence.
    """

    def __init__(
        self,
        playbooks_dir: Optional[Union[str, Path, Sequence[Union[str, Path]]]] = None,
        normalizer: Optional[PromptNormalizer] = None,
        clusterer: Optional[IntentClusterer] = None,
    ) -> None:
        self.normalizer = normalizer or PromptNormalizer()
        self.clusterer = clusterer or IntentClusterer(self.normalizer)
        self.playbooks: list[CanonicalPlaybookDefinition] = []

        # 1. Initialize with built-in playbooks
        self._load_builtins()

        # 2. Discover local filesystem playbooks
        self._discover_playbooks(playbooks_dir)

    def _load_builtins(self) -> None:
        """Loads canonical built-in playbooks into library."""
        for pb in CANONICAL_BUILTINS:
            self.playbooks.append(pb)

    def _clean_title(self, raw_title: str) -> str:
        """Cleans titles of verbose boilerplate to preserve concise optical width."""
        cleaned = re.sub(
            r"^(?:Auto-Reply\s+Route\s+Map:\s*|Canonical\s+Route:\s*)",
            "",
            raw_title.strip(),
            flags=re.IGNORECASE,
        )
        if len(cleaned) > 24:
            cleaned = cleaned.replace(" Autonomous Engineering", "")
            cleaned = cleaned.replace(" Canonical Route", "")
        if len(cleaned) > 24:
            cleaned = cleaned[:21].rstrip() + "..."
        return cleaned.strip()

    def _discover_playbooks(
        self,
        playbooks_dir: Optional[Union[str, Path, Sequence[Union[str, Path]]]] = None,
    ) -> None:
        """Discovers and parses .route.md playbooks from workspace and user directories."""
        candidate_dirs: list[Path] = []

        if playbooks_dir is not None:
            if isinstance(playbooks_dir, (str, Path)):
                candidate_dirs.append(Path(playbooks_dir).resolve())
            else:
                for d in playbooks_dir:
                    candidate_dirs.append(Path(d).resolve())
        else:
            cwd = Path.cwd()
            candidate_dirs.extend([
                cwd / "playbooks",
                cwd / "auto_reply_route" / "playbooks",
                Path(__file__).resolve().parent.parent.parent / "playbooks",
                Path.home() / ".gemini" / "antigravity" / "playbooks",
            ])

        for directory in candidate_dirs:
            if not directory.is_dir():
                continue
            for file_path in sorted(directory.glob("*.route.md")):
                try:
                    manifest = RouteParser.parse_file(str(file_path))
                    route_id = manifest.route_id
                    if not route_id:
                        route_id = file_path.stem.replace(".route", "")

                    matching_existing = next((p for p in self.playbooks if p.route_id == route_id), None)
                    if matching_existing:
                        matching_existing.raw_playbook_path = file_path
                        matching_existing.step_count = len(manifest.steps)
                        if manifest.steps:
                            matching_existing.preview_steps = [s.title for s in manifest.steps]
                        continue

                    desc = f"Custom playbook with {len(manifest.steps)} automated steps."
                    if manifest.steps and manifest.steps[0].primary_prompt:
                        first_prompt = manifest.steps[0].primary_prompt.splitlines()[0].strip()
                        if len(first_prompt) > 80:
                            first_prompt = first_prompt[:77] + "..."
                        desc = first_prompt

                    title_text = " ".join([manifest.title] + [s.title for s in manifest.steps])
                    stratum = self.clusterer.categorize_stratum(title_text)

                    emoji = "📋"
                    archetype = "custom"
                    if stratum == IntentStratum.VERIFY_QA:
                        emoji = "🛡️"
                        archetype = "audit"
                    elif stratum == IntentStratum.DEBUG_REPAIR:
                        emoji = "🔧"
                    elif stratum == IntentStratum.RELEASE_OPS:
                        emoji = "🚀"
                        archetype = "ship"
                    elif stratum == IntentStratum.ARCH_DESIGN:
                        emoji = "📐"
                    elif "spike" in route_id.lower() or "fast" in route_id.lower():
                        emoji = "⚡"
                        archetype = "spike"

                    clean_t = self._clean_title(manifest.title)
                    keywords = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", title_text.lower()))

                    new_pb = CanonicalPlaybookDefinition(
                        route_id=route_id,
                        title=clean_t,
                        emoji=emoji,
                        description=desc,
                        step_count=len(manifest.steps),
                        preset_slug=route_id,
                        preview_steps=[s.title for s in manifest.steps],
                        primary_strata=[stratum],
                        intent_keywords=keywords,
                        archetype=archetype,
                        is_canonical=False,
                        raw_playbook_path=file_path,
                    )
                    self.playbooks.append(new_pb)
                except Exception:
                    continue

    def suggest_routes(
        self,
        seed_prompt: str,
        top_k: int = 3,
    ) -> list[RouteSuggestion]:
        """Predicts and ranks the top-k ghost routes for a given seed prompt.

        Args:
            seed_prompt: The developer's initial prompt (e.g. 'Build a Stripe webhook')
            top_k: Maximum number of suggested routes to return (default: 3)

        Returns:
            List of RouteSuggestion instances ranked by calibrated confidence.
        """
        raw_prompt = seed_prompt.strip() if seed_prompt else ""
        if not raw_prompt:
            return self._default_canonical_suggestions(top_k)

        normalized = self.normalizer.normalize(raw_prompt)
        prompt_stratum = self.clusterer.categorize_stratum(normalized or raw_prompt)

        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", (normalized or raw_prompt).lower()))

        # Intent signals
        has_speed_intent = bool(tokens & {
            "spike", "fast", "quick", "prototype", "poc", "mvp", "experiment", "scratch", "draft", "try", "toy"
        })
        has_audit_intent = bool(tokens & {
            "audit", "security", "vulnerability", "vulnerabilities", "leak", "check", "inspect",
            "coverage", "lint", "benchmark", "verify", "flaw", "invariants", "hardening", "performance"
        })
        has_build_intent = bool(tokens & {
            "build", "implement", "feature", "ship", "create", "endpoint", "webhook", "controller",
            "service", "api", "integration", "add", "develop", "system"
        })
        has_refactor_intent = bool(tokens & {
            "refactor", "rearchitect", "design", "clean", "split", "migrate", "architecture", "decouple"
        })
        has_debug_intent = bool(tokens & {
            "fix", "error", "bug", "crash", "traceback", "failing", "broken", "repair", "defect"
        })

        relevance_scores: dict[str, float] = {}

        for pb in self.playbooks:
            # 1. Stratum Alignment
            if prompt_stratum in pb.primary_strata:
                stratum_idx = pb.primary_strata.index(prompt_stratum)
                stratum_score = 1.0 - (stratum_idx * 0.15)
            else:
                stratum_score = 0.35

            # 2. Keyword Jaccard / Overlap
            common_keywords = tokens & pb.intent_keywords
            keyword_overlap = len(common_keywords) / max(1, len(tokens))

            # 3. Title & Steps Jaccard
            all_pb_text = f"{pb.title} {' '.join(pb.preview_steps)} {pb.description}"
            jaccard_sim = IntentClusterer.jaccard_similarity(raw_prompt, all_pb_text)

            # 4. Trigger Bonuses
            trigger_bonus = 0.0
            if pb.archetype == "spike" or pb.route_id == "quick-spike":
                if has_speed_intent:
                    trigger_bonus += 0.80
                elif has_build_intent and not has_audit_intent:
                    trigger_bonus += 0.25
                elif has_debug_intent:
                    trigger_bonus += 0.30
            elif pb.archetype == "audit" or pb.route_id == "audit-only":
                if has_audit_intent:
                    trigger_bonus += 0.85
                elif prompt_stratum == IntentStratum.VERIFY_QA:
                    trigger_bonus += 0.50
                elif has_refactor_intent:
                    trigger_bonus += 0.35
            elif pb.archetype == "ship" or pb.route_id in ("ship-feature", "feature_build"):
                if has_build_intent and not has_speed_intent:
                    trigger_bonus += 0.70
                elif has_refactor_intent:
                    trigger_bonus += 0.50
                elif prompt_stratum in (IntentStratum.SCAFFOLD_BUILD, IntentStratum.ARCH_DESIGN):
                    trigger_bonus += 0.40

            # Curated canonical prior
            if pb.route_id == "ship-feature":
                base_prior = 0.40
            elif pb.route_id == "quick-spike":
                base_prior = 0.35
            elif pb.route_id == "audit-only":
                base_prior = 0.30
            elif pb.is_canonical:
                base_prior = 0.20
            else:
                base_prior = 0.05

            total = (
                0.35 * stratum_score
                + 0.30 * min(1.0, keyword_overlap * 2.5)
                + 0.15 * jaccard_sim
                + trigger_bonus
                + base_prior
            )
            relevance_scores[pb.route_id] = total

        # Archetype-priority selection: ensures 1-click diversity across Ship, Spike, and Audit
        selected_pbs: list[CanonicalPlaybookDefinition] = []
        selected_archetypes: set[str] = set()
        pb_map = {p.route_id: p for p in self.playbooks}

        while len(selected_pbs) < min(top_k, len(self.playbooks)):
            best_id: Optional[str] = None
            best_score = -float("inf")

            # Check if there are unrepresented archetypes
            unrepresented = [
                p_id for p_id, p in pb_map.items()
                if p_id not in [s.route_id for s in selected_pbs] and p.archetype not in selected_archetypes
            ]

            candidates_pool = unrepresented if unrepresented else [
                p_id for p_id in pb_map.keys()
                if p_id not in [s.route_id for s in selected_pbs]
            ]

            for pb_id in candidates_pool:
                score = relevance_scores[pb_id]
                if score > best_score:
                    best_score = score
                    best_id = pb_id

            if best_id is None:
                break

            chosen = pb_map[best_id]
            selected_pbs.append(chosen)
            selected_archetypes.add(chosen.archetype)

        # Calibrate confidences
        results: list[RouteSuggestion] = []
        top_score = relevance_scores.get(selected_pbs[0].route_id, 1.0) if selected_pbs else 1.0

        for idx, pb in enumerate(selected_pbs):
            raw = relevance_scores.get(pb.route_id, 0.5)
            rel = min(1.0, max(0.1, raw / max(0.1, top_score)))

            if idx == 0:
                confidence = 0.92 + 0.06 * rel
            elif idx == 1:
                confidence = 0.80 + 0.06 * rel
            elif idx == 2:
                confidence = 0.65 + 0.06 * rel
            else:
                confidence = max(0.40, 0.50 * rel)

            confidence = round(min(0.98, max(0.45, confidence)), 4)

            suggestion = RouteSuggestion(
                route_id=pb.route_id,
                title=pb.title,
                description=pb.description,
                step_count=pb.step_count,
                confidence=confidence,
                preview_steps=list(pb.preview_steps),
                preset_slug=pb.preset_slug,
                emoji=pb.emoji,
            )
            results.append(suggestion)

        return results

    def _default_canonical_suggestions(self, top_k: int = 3) -> list[RouteSuggestion]:
        """Provides default canonical suggestions when prompt is blank."""
        defaults = [
            RouteSuggestion(
                route_id="ship-feature",
                title="Ship Feature",
                description="End-to-end production workflow: implementation, QA review, debt audit, e2e proof, and visual polish.",
                step_count=5,
                confidence=0.95,
                preview_steps=[
                    "Build the requested feature cleanly with minimal blast radius",
                    "Review implementation with 3-agent QA team and fix defects",
                    "Review for executive-level compromises, architectural shortcuts, or hidden debt",
                    "Verify end-to-end functionality and capture screenshot proof in browser",
                    "Review visual walkthrough evidence and fix remaining rough edges",
                ],
                preset_slug="ship-feature",
                emoji="🚀",
            ),
            RouteSuggestion(
                route_id="quick-spike",
                title="Fast Spike",
                description="Rapid feasibility prototype: lightweight zero-dependency implementation and quick execution smoke test.",
                step_count=2,
                confidence=0.82,
                preview_steps=[
                    "Create a rapid working prototype spike",
                    "Verify basic end-to-end execution",
                ],
                preset_slug="quick-spike",
                emoji="⚡",
            ),
            RouteSuggestion(
                route_id="audit-only",
                title="Full Audit",
                description="Deep codebase inspection: static security analysis, dependency vulnerability check, and test coverage verification.",
                step_count=2,
                confidence=0.68,
                preview_steps=[
                    "Run comprehensive static analysis and security audit",
                    "Verify test coverage and check for brittle mocks",
                ],
                preset_slug="audit-only",
                emoji="🛡️",
            ),
        ]
        return defaults[:top_k]

    def format_suggestion_chips(
        self,
        suggestions: list[RouteSuggestion],
        format_type: str = "terminal",
    ) -> str:
        """Formats route suggestions into selectable chips or representations.

        Args:
            suggestions: List of RouteSuggestion objects
            format_type: Output format - 'terminal', 'plain', 'json', or 'markdown'

        Returns:
            Formatted chip representation string.
        """
        if not suggestions:
            return ""

        if format_type == "json":
            return json.dumps([s.to_dict() for s in suggestions], indent=2)

        if format_type == "markdown":
            chips: list[str] = []
            for idx, s in enumerate(suggestions, start=1):
                chip_text = f"**[{idx}] {s.emoji} {s.title}** *({s.step_count} steps)*"
                chips.append(chip_text)
            return " &nbsp; ".join(chips)

        if format_type == "plain":
            chips = []
            for idx, s in enumerate(suggestions, start=1):
                chips.append(f"[{idx}] {s.emoji} {s.title} ({s.step_count} steps)")
            return "  ".join(chips)

        # Default: 'terminal' with high-intent ANSI styling
        chips = []
        for idx, s in enumerate(suggestions, start=1):
            badge = f"\033[1;36m[{idx}]\033[0m"
            title_part = f"\033[1m{s.emoji} {s.title}\033[0m"
            step_part = f"\033[90m({s.step_count} steps)\033[0m"
            chips.append(f"{badge} {title_part} {step_part}")

        return "  ".join(chips)

    def format_detailed_cards(
        self,
        suggestions: list[RouteSuggestion],
        plain: bool = False,
    ) -> str:
        """Formats detailed preview cards showing step-by-step breakdown."""
        lines: list[str] = []
        width = 72

        for idx, s in enumerate(suggestions, start=1):
            conf_pct = int(s.confidence * 100)
            header_title = f" [{idx}] {s.emoji} {s.title} ({s.step_count} steps) · {conf_pct}% match "
            padding = max(0, width - len(header_title) - 3)

            top_border = f"╭─{header_title}{'─' * padding}╮"
            bottom_border = f"╰{'─' * (width - 1)}╯"

            if not plain:
                top_border = f"\033[1;36m{top_border}\033[0m"
                bottom_border = f"\033[90m{bottom_border}\033[0m"

            lines.append(top_border)

            desc = s.description
            if len(desc) > width - 6:
                desc = desc[:width - 9] + "..."
            desc_line = f"│  \033[3m{desc}\033[0m" if not plain else f"│  {desc}"
            desc_pad = max(0, width - len(desc) - 5)
            lines.append(f"{desc_line}{' ' * desc_pad}│")

            lines.append(f"│{' ' * (width - 2)}│")

            for step_num, step_title in enumerate(s.preview_steps, start=1):
                clean_title = step_title.strip()
                if len(clean_title) > width - 10:
                    clean_title = clean_title[:width - 13] + "..."
                step_str = f"│   {step_num}. {clean_title}"
                step_pad = max(0, width - len(step_str) - 1)
                lines.append(f"{step_str}{' ' * step_pad}│")

            lines.append(bottom_border)
            lines.append("")

        return "\n".join(lines).strip()

    def resolve_manifest(
        self,
        suggestion: RouteSuggestion,
        playbooks_dir: Optional[Union[str, Path]] = None,
    ) -> RouteManifest:
        """Resolves a RouteSuggestion into a concrete runnable RouteManifest."""
        search_dirs: list[Path] = []
        if playbooks_dir:
            search_dirs.append(Path(playbooks_dir).resolve())
        cwd = Path.cwd()
        search_dirs.extend([
            cwd / "playbooks",
            cwd / "auto_reply_route" / "playbooks",
            Path(__file__).resolve().parent.parent.parent / "playbooks",
        ])

        target_slug = suggestion.preset_slug or suggestion.route_id
        for d in search_dirs:
            if not d.is_dir():
                continue
            for ext in [".route.md", ".md"]:
                candidate = d / f"{target_slug}{ext}"
                if candidate.is_file():
                    return RouteParser.parse_file(str(candidate))

        steps = []
        for i, st in enumerate(suggestion.preview_steps):
            steps.append(
                RouteStep(
                    index=i,
                    title=st,
                    primary_prompt=f"{st}.\nEnsure high code quality and zero regressions.",
                    status=StepStatus.PENDING,
                )
            )

        return RouteManifest(
            route_id=suggestion.route_id,
            title=suggestion.title,
            steps=steps,
            current_step_idx=0,
            state=StepStatus.PENDING,
            metadata={"source": "ghost_route_suggestion", "confidence": suggestion.confidence},
        )


# ============================================================================
# Standalone CLI / Composer Helpers
# ============================================================================

def auto_suggest_chips(
    seed_prompt: str,
    top_k: int = 3,
    format_type: str = "terminal",
    playbooks_dir: Optional[Union[str, Path]] = None,
) -> str:
    """Instant 1-line helper for obtaining ghost route chips in any composer or CLI."""
    suggester = RouteSuggester(playbooks_dir=playbooks_dir)
    suggestions = suggester.suggest_routes(seed_prompt, top_k=top_k)
    return suggester.format_suggestion_chips(suggestions, format_type=format_type)


def interactive_route_picker(
    seed_prompt: str,
    top_k: int = 3,
    playbooks_dir: Optional[Union[str, Path]] = None,
    stream: Any = sys.stdout,
) -> Optional[RouteManifest]:
    """Displays ambient ghost chips and prompts developer for 1-click selection."""
    suggester = RouteSuggester(playbooks_dir=playbooks_dir)
    suggestions = suggester.suggest_routes(seed_prompt, top_k=top_k)
    if not suggestions:
        return None

    chips_line = suggester.format_suggestion_chips(suggestions, format_type="terminal")
    stream.write(f"\n\033[90mSuggested Routes:\033[0m {chips_line}\n")
    stream.write("\033[90mSelect [1-3] to execute route, or Enter to skip: \033[0m")
    stream.flush()

    try:
        choice = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not choice:
        return None

    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(suggestions):
            selected = suggestions[idx - 1]
            return suggester.resolve_manifest(selected, playbooks_dir=playbooks_dir)

    return None
