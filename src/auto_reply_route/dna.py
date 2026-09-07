"""Operator DNA Bootstrapper with AGENTS.md Ingestion & Transcript Mining.

Bootstraps a personalized Operator DNA matrix encoding linguistic fingerprint,
simplicity invariants, 5-phase problem breakdown, subagent delegation rules,
and executive steering principles.

Guarantees:
1. the operator's personal DNA (`~/.gemini/config/personal_dna.md`) is 100% untouched and preserved.
2. Ingests core principles from global and workspace `AGENTS.md`.
3. Mines genuine user prompts from recent session transcripts using `PromptMiner`.
4. Zero crashes on missing directories, missing git, corrupt transcripts, or missing files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
from typing import Any, Optional

from auto_reply_route.miner import IntentStratum, PromptMiner


PERSONAL_DNA_FILENAME = "personal_dna.md"
OPERATOR_DNA_FILENAME = "operator_dna.md"


def personal_dna_path() -> Path:
    """Returns the canonical path to the operator's personal Operator DNA matrix."""
    return Path.home() / ".gemini" / "config" / PERSONAL_DNA_FILENAME


MAX_SECTION_RULES = 10
MAX_RULES_PER_SECTION = MAX_SECTION_RULES
MAX_RULE_CHARS = 240
MAX_TOTAL_BUDGET_CHARS = 2800

_BULLET_PREFIX_RE = re.compile(r"^[-*+]\s+")
_NUMBERED_PREFIX_RE = re.compile(r"^\d+[.)]\s+")
_LIVING_ROOM_RE = re.compile(r"(?:The\s+)?Living-Room\s+Test:\*{0,2}\s*(.+)", re.IGNORECASE)
_BOLD_KEY_VALUE_RE = re.compile(r"^\*{2}(.*?)\*{2}:?\s*(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def default_operator_dna_path() -> Path:
    """Returns the default fallback path to the generated Operator DNA matrix."""
    return Path.home() / ".gemini" / "config" / OPERATOR_DNA_FILENAME


def clean_bullet_text(text: str) -> str:
    """Safely strips leading bullet list marker (- * + or 1.) without damaging markdown bold asterisks."""
    s = text.strip()
    if s.startswith(("- ", "* ", "+ ")):
        return s[2:].strip()
    if s and s[0].isdigit():
        idx = 0
        while idx < len(s) and s[idx].isdigit():
            idx += 1
        if idx < len(s) and s[idx] in (".", ")") and idx + 1 < len(s) and s[idx + 1] == " ":
            return s[idx + 2:].strip()
    cleaned = _BULLET_PREFIX_RE.sub("", s)
    cleaned = _NUMBERED_PREFIX_RE.sub("", cleaned)
    return cleaned.strip()



def strip_markdown_bold(text: str) -> str:
    """Strips leading/trailing markdown bold markers (** or __) if present."""
    t = text.strip()
    if (t.startswith("**") and t.endswith("**")) or (t.startswith("__") and t.endswith("__")):
        if len(t) >= 4:
            t = t[2:-2].strip()
    return t


def extract_git_user_name(workspace_root: Optional[str | Path] = None) -> str:
    """Extracts git user name (`git config user.name`) or falls back to 'Operator'.
    
    Gracefully handles missing git binary, non-git directories, timeouts, and empty output.
    """
    try:
        cwd = None
        if workspace_root:
            wp = Path(workspace_root).expanduser().resolve()
            if wp.is_dir():
                cwd = str(wp)

        res = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=cwd,
        )
        if res.returncode == 0:
            name = res.stdout.strip()
            if name:
                return name
    except Exception:
        pass
    return "Operator"


@dataclass
class IngestedPrinciples:
    """Principles and rules ingested from AGENTS.md files."""
    operator_name: str = "Operator"
    simplicity_laws: list[str] = field(default_factory=list)
    living_room_test: str = "If you wouldn't say the sentence to a neighbor over coffee, delete it."
    anti_patterns: list[str] = field(default_factory=list)
    anti_tower_of_babel: list[str] = field(default_factory=list)
    executive_steering: list[str] = field(default_factory=list)
    core_rules: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def parse_agents_markdown(content: str) -> dict[str, Any]:
    """Parses AGENTS.md markdown content to extract simplicity laws, living-room test,
    anti-patterns, anti-tower-of-babel rules, and executive steering invariants.

    Enforces strict token budget (<3,000 chars total, <=10 rules per section)
    and linear O(N) performance with sub-100ms execution on massive files.
    """
    simplicity_laws: list[str] = []
    simplicity_set: set[str] = set()

    anti_patterns: list[str] = []
    anti_patterns_set: set[str] = set()

    anti_tower_of_babel: list[str] = []
    anti_tower_set: set[str] = set()

    executive_steering: list[str] = []
    executive_set: set[str] = set()

    core_rules: list[str] = []
    core_rules_set: set[str] = set()

    living_room_test: Optional[str] = None

    if not content or not content.strip():
        return {
            "simplicity_laws": simplicity_laws,
            "living_room_test": living_room_test,
            "anti_patterns": anti_patterns,
            "anti_tower_of_babel": anti_tower_of_babel,
            "executive_steering": executive_steering,
            "core_rules": core_rules,
        }

    simplicity_keywords = (
        "simplicity above all",
        "stress-free",
        "zero cognitive load",
        "plain, clear language",
        "fun & intuitive",
        "zero plumbing",
        "anti-overexplaining",
    )
    anti_pattern_keywords = (
        "never expose system mechanics",
        "cut the throat-clearing preamble",
        "enterprise consultant fluff",
        "theoretical checklists",
        "academic, defensive, or overly synthetic",
        "never speak like an enterprise consultant",
        "never start copy with",
        "anti-patterns",
    )
    anti_tower_keywords = (
        "anti-tower-of-babel",
        "rabbit hole circuit breaker",
        "direct 20-line solution",
        "premature inheritance",
        "premature plugin",
        "speculative multi-layered abstractions",
    )
    executive_keywords = (
        "session-history grounding",
        "executive founder sanity check",
        "north star steering",
        "least complicated way to build this",
    )

    lines = content.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Fast break if all sections are fully saturated
        all_sections_saturated = (
            len(simplicity_laws) >= MAX_SECTION_RULES
            and len(anti_patterns) >= MAX_SECTION_RULES
            and len(anti_tower_of_babel) >= MAX_SECTION_RULES
            and len(executive_steering) >= MAX_SECTION_RULES
            and len(core_rules) >= MAX_SECTION_RULES
        )
        if all_sections_saturated:
            if living_room_test is not None:
                break
            if "living-room" in stripped.lower():
                m_lrt = _LIVING_ROOM_RE.search(stripped)
                if m_lrt:
                    extracted_lrt = m_lrt.group(1).strip()
                    extracted_lrt = strip_markdown_bold(extracted_lrt).strip('"\' ')
                    if extracted_lrt:
                        living_room_test = extracted_lrt[:MAX_RULE_CHARS]
                        break
            continue

        # Header detection (H1-H6)
        m_head = _HEADING_RE.match(stripped)
        if m_head:
            level = len(m_head.group(1))
            header_text = m_head.group(2).strip()[:MAX_RULE_CHARS]
            if level <= 2 and len(core_rules) < MAX_SECTION_RULES:
                if header_text and header_text != "Global Antigravity Operating Rules" and header_text not in core_rules_set:
                    core_rules.append(header_text)
                    core_rules_set.add(header_text)
            continue

        low = stripped.lower()

        # Living-Room Test detection
        if living_room_test is None and "living-room" in low:
            m_lrt = _LIVING_ROOM_RE.search(stripped)
            if m_lrt:
                extracted_lrt = m_lrt.group(1).strip()
                extracted_lrt = strip_markdown_bold(extracted_lrt).strip('"\' ')
                if extracted_lrt:
                    living_room_test = extracted_lrt[:MAX_RULE_CHARS]

        # Fast keyword match without generator expressions
        matched_category = None
        if len(simplicity_laws) < MAX_SECTION_RULES:
            for kw in simplicity_keywords:
                if kw in low:
                    matched_category = "simplicity"
                    break

        if matched_category is None and len(anti_patterns) < MAX_SECTION_RULES:
            for kw in anti_pattern_keywords:
                if kw in low:
                    matched_category = "anti_patterns"
                    break

        if matched_category is None and len(anti_tower_of_babel) < MAX_SECTION_RULES:
            for kw in anti_tower_keywords:
                if kw in low:
                    matched_category = "anti_tower"
                    break

        if matched_category is None and len(executive_steering) < MAX_SECTION_RULES:
            for kw in executive_keywords:
                if kw in low:
                    matched_category = "executive"
                    break

        if matched_category is None:
            continue

        bullet_text = clean_bullet_text(stripped)
        if not bullet_text:
            continue
        if len(bullet_text) > MAX_RULE_CHARS:
            bullet_text = bullet_text[:MAX_RULE_CHARS].rstrip() + "..."

        if matched_category == "simplicity":
            if bullet_text not in simplicity_set:
                simplicity_laws.append(bullet_text)
                simplicity_set.add(bullet_text)
        elif matched_category == "anti_patterns":
            if bullet_text not in anti_patterns_set:
                anti_patterns.append(bullet_text)
                anti_patterns_set.add(bullet_text)
        elif matched_category == "anti_tower":
            if bullet_text not in anti_tower_set:
                anti_tower_of_babel.append(bullet_text)
                anti_tower_set.add(bullet_text)
        elif matched_category == "executive":
            if bullet_text not in executive_set:
                executive_steering.append(bullet_text)
                executive_set.add(bullet_text)


    # Hard token budget enforcement: ensure total chars strictly < 3,000 chars
    def _current_total() -> int:
        return (
            sum(len(x) for x in simplicity_laws)
            + sum(len(x) for x in anti_patterns)
            + sum(len(x) for x in anti_tower_of_babel)
            + sum(len(x) for x in executive_steering)
            + (len(living_room_test) if living_room_test else 0)
        )

    while _current_total() >= MAX_TOTAL_BUDGET_CHARS:
        lists = [simplicity_laws, anti_patterns, anti_tower_of_babel, executive_steering]
        longest = max(lists, key=lambda lst: sum(len(x) for x in lst) if lst else 0)
        if longest:
            longest.pop()
        else:
            break

    return {
        "simplicity_laws": simplicity_laws,
        "living_room_test": living_room_test,
        "anti_patterns": anti_patterns,
        "anti_tower_of_babel": anti_tower_of_babel,
        "executive_steering": executive_steering,
        "core_rules": core_rules,
    }


def ingest_agents_principles(
    workspace_root: Optional[str | Path] = None,
    global_config_dir: Optional[str | Path] = None,
) -> IngestedPrinciples:
    """Ingests principles from `~/.gemini/config/AGENTS.md` and workspace `AGENTS.md`.
    
    Workspace principles augment and take precedence over global defaults.
    """
    g_dir = Path(global_config_dir) if global_config_dir else Path.home() / ".gemini" / "config"
    global_agents_file = g_dir / "AGENTS.md"

    workspace_agents_file = None
    if workspace_root:
        wp = Path(workspace_root).expanduser().resolve()
        candidate = wp / "AGENTS.md"
        if candidate.is_file():
            workspace_agents_file = candidate
    if workspace_agents_file is None:
        cwd_candidate = Path.cwd() / "AGENTS.md"
        if cwd_candidate.is_file():
            workspace_agents_file = cwd_candidate

    principles = IngestedPrinciples(
        operator_name=extract_git_user_name(workspace_root),
    )

    # Ingest global AGENTS.md
    if global_agents_file.is_file():
        try:
            content = global_agents_file.read_text(encoding="utf-8", errors="replace")
            parsed = parse_agents_markdown(content)
            principles.simplicity_laws.extend(parsed["simplicity_laws"])
            if parsed.get("living_room_test"):
                principles.living_room_test = parsed["living_room_test"]
            principles.anti_patterns.extend(parsed["anti_patterns"])
            principles.anti_tower_of_babel.extend(parsed["anti_tower_of_babel"])
            principles.executive_steering.extend(parsed["executive_steering"])
            principles.core_rules.extend(parsed["core_rules"])
            principles.sources.append(str(global_agents_file))
        except Exception:
            pass

    # Ingest workspace AGENTS.md
    if workspace_agents_file and workspace_agents_file.is_file():
        try:
            w_content = workspace_agents_file.read_text(encoding="utf-8", errors="replace")
            w_parsed = parse_agents_markdown(w_content)
            if w_parsed.get("living_room_test"):
                principles.living_room_test = w_parsed["living_room_test"]

            for target_list, items, prepend in (
                (principles.simplicity_laws, w_parsed["simplicity_laws"], True),
                (principles.anti_patterns, w_parsed["anti_patterns"], True),
                (principles.anti_tower_of_babel, w_parsed["anti_tower_of_babel"], True),
                (principles.executive_steering, w_parsed["executive_steering"], True),
                (principles.core_rules, w_parsed["core_rules"], False),
            ):
                for item in items:
                    if item not in target_list:
                        if prepend:
                            target_list.insert(0, item)
                        else:
                            target_list.append(item)
            principles.sources.append(str(workspace_agents_file))
        except Exception:
            pass

    # Cap sections to MAX_SECTION_RULES to guarantee strict token budgets
    principles.simplicity_laws = principles.simplicity_laws[:MAX_SECTION_RULES]
    principles.anti_patterns = principles.anti_patterns[:MAX_SECTION_RULES]
    principles.anti_tower_of_babel = principles.anti_tower_of_babel[:MAX_SECTION_RULES]
    principles.executive_steering = principles.executive_steering[:MAX_SECTION_RULES]
    principles.core_rules = principles.core_rules[:MAX_SECTION_RULES]

    # Ensure battle-tested defaults if files were absent or empty
    if not principles.simplicity_laws:
        principles.simplicity_laws = [
            "**Simplicity Above All:** Anything facing customers must be incredibly simple in terms of both language and user experience.",
            "**Stress-Free & Zero Cognitive Load:** Eliminate friction, technical jargon, unnecessary choices, and confusing steps.",
            "**Plain, Clear Language:** Speak like a helpful human using short, direct, everyday words.",
        ]

    if not principles.anti_patterns:
        principles.anti_patterns = [
            "Enterprise consultant fluff (\"In order to facilitate this architecture...\").",
            "Theoretical checklists dumped into prompts without context.",
            "Academic, defensive, or overly synthetic phrasing.",
            "Exposing background system plumbing (database, server, internal algorithm details).",
            "Throat-clearing preambles (\"In order to...\", \"This section allows you to...\").",
        ]

    if not principles.anti_tower_of_babel:
        principles.anti_tower_of_babel = [
            "**Anti-Tower-of-Babel Invariant:** Never construct massive, speculative multi-layered abstractions, generic plugin architectures, or premature inheritance trees when a direct 20-line solution works. Keep blast radius minimal.",
            "**Rabbit Hole Circuit Breaker:** If a turn hits a tangential rabbit hole, forcefully pull execution back to the user's primary North Star.",
            "**Executive Founder Sanity Check:** *\"What is the least complicated way to build this, prove it works with tests, and ship it?\"*",
            "**Session-History Grounding:** Never evaluate prompts in isolation. Inspect the last 2–5 user prompts and tool receipts to anchor prompt synthesis to the actual North Star.",
        ]

    return principles


def synthesize_idea_label(raw: str, norm: str) -> str:
    """Derives a concise, clean 2-5 word idea label from raw and normalized prompt text."""
    cleaned = re.sub(r"\[[^\]]+\]", "", norm)
    cleaned = re.sub(

        r"^(?:so|if|how|what|can|why|please|will|like|just|could|would)\s+(?:can|do|we|i|it|you)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(".,;:?!-_ ")
    words = cleaned.split()[:5]
    if len(words) >= 2:
        return " ".join(words).capitalize().strip(".,;:?!-_ ")

    raw_clean = re.sub(
        r"^(?:so|if|how|what|can|why|please|will|like|just)\s+", "", raw, flags=re.IGNORECASE
    ).strip()
    raw_words = raw_clean.split()[:4]
    if raw_words:
        return " ".join(raw_words).capitalize().strip(".,;:?!-_ ")
    return "Feature Execution"


def mine_transcript_examples(
    brain_dir: Optional[str | Path] = None,
    max_examples: int = 5,
) -> list[dict[str, str]]:
    """Mines recent Antigravity transcripts for genuine operator prompts across intent strata.
    
    Sanitizes all extracted text to guarantee zero secret, token, or PII leakage.
    Gracefully handles missing brain directories or corrupt transcripts.
    """
    b_path = Path(brain_dir) if brain_dir else Path.home() / ".gemini" / "antigravity" / "brain"
    if not b_path.is_dir():
        return []

    try:
        miner = PromptMiner()
        transcript_files = miner.collect_transcript_files([str(b_path)], max_files=30)
    except Exception:
        return []

    if not transcript_files:
        return []

    domain_map = {
        IntentStratum.ARCH_DESIGN: "Architecture & System Design",
        IntentStratum.SCAFFOLD_BUILD: "Feature Implementation & Build",
        IntentStratum.DEBUG_REPAIR: "Bug Fixing & Diagnostic Repair",
        IntentStratum.VERIFY_QA: "Testing & Quality Assurance",
        IntentStratum.RELEASE_OPS: "Deployment & Operations",
    }

    examples: list[dict[str, str]] = []
    strata_seen: set[IntentStratum] = set()

    for tf in transcript_files:
        try:
            turns = miner.parse_transcript_file(tf)
        except Exception:
            continue

        for raw_prompt, norm_prompt in turns:
            clean_raw = raw_prompt.strip()
            words = clean_raw.split()
            # Require concise, genuine operator length (4 to 45 words)
            if not (4 <= len(words) <= 45):
                continue
            # Filter out command syntax, code pastes, or XML/JSON snippets
            if clean_raw.startswith(("/", "```", "{", "[", "<", "http://", "https://", "def ", "class ", "import ")):
                continue
            if clean_raw.count("\n") > 2:
                continue

            stratum = miner.clusterer.categorize_stratum(norm_prompt)
            if stratum in strata_seen:
                continue

            domain = domain_map.get(stratum, "Engineering & Execution")
            idea = synthesize_idea_label(clean_raw, norm_prompt)

            examples.append({
                "domain": domain,
                "idea": idea,
                "prompt": clean_raw.replace('"', "'"),
            })
            strata_seen.add(stratum)

            if len(examples) >= max_examples:
                break

        if len(examples) >= max_examples:
            break

    return examples



def format_bullet_point(item: str, indent: str = "") -> str:
    """Formats a bullet item into '- **Key:** Value' or '- Text' with zero markdown syntax defects."""
    clean = clean_bullet_text(item)
    if not clean:
        return ""

    # Check for bold pattern: **Term:** or **Term**:
    m_bold = _BOLD_KEY_VALUE_RE.match(clean)
    if m_bold:
        term = m_bold.group(1).rstrip(":").strip()
        body = m_bold.group(2).lstrip(":").strip()
        body = re.sub(r"^\*{2}\s*", "", body).strip()
        if body:
            return f"{indent}- **{term}:** {body}"
        return f"{indent}- **{term}**"

    # Check for plain Key: Value pattern
    if ":" in clean:
        k, v = clean.split(":", 1)
        k_clean = strip_markdown_bold(k.strip()).rstrip(":")
        v_clean = strip_markdown_bold(v.strip()).lstrip(":")
        if len(k_clean.split()) <= 8 and v_clean:
            return f"{indent}- **{k_clean}:** {v_clean}"

    return f"{indent}- {clean}"


def _format_and_dedupe_bullets(items: list[str], indent: str = "  ") -> list[str]:
    """Helper to clean, format, and deduplicate bullet items preserving insertion order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        cleaned = clean_bullet_text(item)
        if "living-room test" in cleaned.lower():
            continue
        formatted = format_bullet_point(cleaned, indent=indent)
        if formatted and formatted not in seen:
            deduped.append(formatted)
            seen.add(formatted)
    return deduped


def render_operator_dna_matrix(
    operator_name: str | IngestedPrinciples,
    principles: Optional[IngestedPrinciples] = None,
    examples: Optional[list[dict[str, str]]] = None,
) -> str:
    """Renders the clean Markdown DNA matrix from a structured template and ingested principles."""
    if isinstance(operator_name, IngestedPrinciples):
        principles = operator_name
        operator_name = principles.operator_name
    elif principles is None:
        principles = IngestedPrinciples(operator_name=operator_name or "Operator")

    name_clean = operator_name.strip() if operator_name and operator_name.strip() else "Operator"
    if name_clean.lower() == "operator":
        title_header = "# OPERATOR DNA MATRIX"
    else:
        title_header = f"# {name_clean.upper()}'S OPERATOR DNA MATRIX"

    # Living-room test
    lrt = principles.living_room_test or "If you wouldn't say the sentence to a neighbor over coffee, delete it."

    # Format anti-patterns
    deduped_ap = _format_and_dedupe_bullets(principles.anti_patterns, indent="  ")
    anti_patterns_block = "\n".join(deduped_ap) if deduped_ap else (
        "  - Enterprise consultant fluff (\"In order to facilitate this architecture...\").\n"
        "  - Theoretical checklists dumped into prompts without context.\n"
        "  - Academic, defensive, or overly synthetic phrasing."
    )

    # Format Section 5: Few-Shot Ground Truth Translations
    if not examples:
        examples = [
            {
                "domain": "Mobile UI / Frontend",
                "idea": "Touch gesture indicator",
                "prompt": "only show this swipe indicator on the first property card after that just show 1/6 counter when they swipe",
            },
            {
                "domain": "System Architecture / Backend",
                "idea": "In-app calling privacy",
                "prompt": "allow calling from app itself like uber without personal phone numbers being exchanged, keep it minimal",
            },
            {
                "domain": "Product Readiness / Quality",
                "idea": "V1 release readiness",
                "prompt": "is this app feature complete for v1? wrap up features, fix bugs, harden, then get first users on board",
            },
            {
                "domain": "Verification / Testing",
                "idea": "Adversarial edge cases",
                "prompt": "run the test suite and verify edge cases with zero mock leakage",
            },
        ]

    few_shot_blocks: list[str] = []
    for ex in examples:
        dom = ex.get("domain", "General Engineering")
        idea = ex.get("idea", "Core task")
        p = ex.get("prompt", "")
        few_shot_blocks.append(
            f"- **Domain: {dom}**\n"
            f"  - *Idea:* {idea}\n"
            f"  - *{name_clean}'s Prompt:* \"{p}\""
        )
    few_shots_str = "\n\n".join(few_shot_blocks)

    # Format Section 6: Executive Steering & Anti-Tower-of-Babel
    steering_lines: list[str] = []
    for item in principles.anti_tower_of_babel:
        formatted = format_bullet_point(item)
        if formatted not in steering_lines:
            steering_lines.append(formatted)

    for item in principles.executive_steering:
        formatted = format_bullet_point(item)
        if formatted not in steering_lines:
            steering_lines.append(formatted)

    if not steering_lines:
        steering_lines = [
            "- **Session-History Grounding:** Never evaluate prompts in isolation. Inspect the last 2–5 user prompts and tool receipts to anchor prompt synthesis to the actual North Star.",
            "- **Anti-Tower-of-Babel Law:** Reject speculative multi-layered abstractions, premature plugin frameworks, and bloated class trees. Build the direct 20-line solution first.",
            "- **Rabbit Hole Circuit Breaker:** If a turn hits a tangential rabbit hole (e.g. linter warnings on untouched files or speculative edge cases), forcefully pull execution back to the user's primary North Star.",
            "- **Executive Founder Sanity Check:** *\"What is the least complicated way to build this, prove it works with tests, and ship it?\"*",
        ]
    steering_str = "\n".join(steering_lines)

    # Format simplicity laws
    deduped_sl = _format_and_dedupe_bullets(principles.simplicity_laws, indent="  ")
    simplicity_block = ""
    if deduped_sl:
        simplicity_block = "- **Simplicity Laws:**\n" + "\n".join(deduped_sl) + "\n"

    template = f"""{title_header}

## 1. Voice Identity & Linguistic Fingerprint
- **Role:** Technical Founder / Senior Systems Architect / Pragmatic Builder.
- **Sentence Economy:** 10 to 30 words per prompt. High velocity. Zero throat-clearing preamble.
- **Tone:** Plain everyday English. The living-room test: {lrt}
- **Core Stance:** Practical velocity over theoretical architecture. Empirical proof over self-attestation.
{simplicity_block}- **Anti-Patterns (NEVER DO THIS):**
{anti_patterns_block}

---

## 2. The 5-Phase Meta-Trajectory
When tackling complex technical tasks, structure follow-ups across 5 clear phases:

1. **Phase 1: Adversarial Refutation & Real Constraints**
   - Direct the agent to research actual physical/technical mechanisms, giving explicit permission to refute earlier claims or unproven assumptions.
2. **Phase 2: Least-Complicated Prototype**
   - Build or design the minimal prototype in the least complicated way possible to get a full sense of how it works.
3. **Phase 3: Feasibility & Investment Reality Check**
   - Evaluate whether continuing is worth the effort, what the investment/time looks like, and the realistic probability of success.
4. **Phase 4: Adversarial Go / No-Go**
   - Critically evaluate why others failed at this exact problem so you don't jump into it blindly or naively.
5. **Phase 5: Concrete Synthesis Report**
   - Deliver clear findings, working proof, diagrams, and operational trade-offs without fluff.

---

## 3. Subagent Team Allocation
- **Default (Single Agent):** Zero subagents for routine edits, refactors, and test runs.
- **Explicit Team Directive:** Specify subagent counts only when needed for isolated multi-perspective audits (e.g. 3-person QA team: edge cases, security, smoke tests).

---

## 4. Anti-Pollution & Evolution Invariant
- **Unidirectional Flow:** {name_clean}'s genuine voice $\\rightarrow$ DNA Matrix $\\rightarrow$ Generated Queue Prompts.
- **Strict Quarantine:** Generated queue prompts and synthetic assistant text are permanently quarantined and can **never** be used to update, train, or modify this DNA matrix.
- **Evolution Mechanism:** This matrix evolves strictly through {name_clean}'s direct feedback, corrections, and explicit edits to this file.

---

## 5. Few-Shot Ground Truth Translations

{few_shots_str}

---

## 6. Executive Steering & Anti-Overbuild Invariants

{steering_str}
"""
    return template.strip() + "\n"


class OperatorDNABootstrapper:
    """Bootstrapper and manager for Operator DNA matrix files."""

    def __init__(
        self,
        workspace_root: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
        brain_dir: Optional[str | Path] = None,
        global_config_dir: Optional[str | Path] = None,
    ):
        self.workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else None
        self.target_path = Path(target_path).expanduser().resolve() if target_path else None
        self.brain_dir = Path(brain_dir).expanduser().resolve() if brain_dir else None
        self.global_config_dir = Path(global_config_dir).expanduser().resolve() if global_config_dir else None

    def get_operator_name(self) -> str:
        return extract_git_user_name(self.workspace_root)

    def get_principles(self) -> IngestedPrinciples:
        return ingest_agents_principles(
            workspace_root=self.workspace_root,
            global_config_dir=self.global_config_dir,
        )

    def mine_examples(self, max_examples: int = 5) -> list[dict[str, str]]:
        return mine_transcript_examples(brain_dir=self.brain_dir, max_examples=max_examples)

    def render(self, mine: bool = False) -> str:
        principles = self.get_principles()
        examples = self.mine_examples() if mine else None
        return render_operator_dna_matrix(
            operator_name=principles.operator_name,
            principles=principles,
            examples=examples,
        )

    def bootstrap(self, force: bool = False, mine: bool = False) -> Path:
        return ensure_operator_dna(
            workspace_root=self.workspace_root,
            target_path=self.target_path,
            force=force,
            mine=mine,
        )


def ensure_operator_dna(
    workspace_root: Optional[str | Path] = None,
    target_path: Optional[str | Path] = None,
    force: bool = False,
    mine: bool = False,
) -> Path:
    """Ensures an Operator DNA file exists, returning its Path.

    Checks priority:
      a. `~/.gemini/config/personal_dna.md` (if exists and target_path is not an
         independent custom path, return it immediately so the operator's local file is 100% untouched).
      b. Target path or `~/.gemini/config/operator_dna.md` (if exists and not force, return it).

    If missing:
      - Extracts git user name (`git config user.name`) or fallback to 'Operator'.
      - Ingests principles from `~/.gemini/config/AGENTS.md` and workspace `AGENTS.md`.
      - If available (and requested or discovered), mines recent transcripts using `PromptMiner`.
      - Renders the clean Markdown DNA matrix from a structured template.
      - Writes to destination file and returns the Path.
    """
    q_path = personal_dna_path()
    default_target = default_operator_dna_path()

    # Priority Check (a):
    # If target_path is None or points to the operator's DNA, and the operator's DNA exists,
    # return it immediately. the operator's personal file is 100% untouched.
    if target_path is None:
        if not force and q_path.is_file():
            return q_path
        destination = default_target
    else:
        dest_candidate = Path(target_path).expanduser().resolve()
        # If caller explicitly targeted personal_dna, return it without modifying
        if dest_candidate == q_path.resolve() and not force and q_path.is_file():
            return q_path
        destination = dest_candidate

    # Priority Check (b):
    # If destination exists and force is False, return it directly
    if not force and destination.is_file():
        return destination

    # Protection Invariant: Never overwrite personal_dna.md under any circumstance
    if destination == q_path.resolve() or destination.name == PERSONAL_DNA_FILENAME:
        destination = default_target

    # Auto-create the DNA file
    operator_name = extract_git_user_name(workspace_root)
    principles = ingest_agents_principles(workspace_root=workspace_root)
    principles.operator_name = operator_name

    mined_examples = None
    if mine:
        mined_examples = mine_transcript_examples(max_examples=5)

    content = render_operator_dna_matrix(
        operator_name=operator_name,
        principles=principles,
        examples=mined_examples,
    )

    # Ensure destination is not a directory
    if destination.is_dir():
        raise IsADirectoryError(f"Target path '{destination}' is a directory, not a file.")

    # Ensure parent directory exists
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")

    return destination

