from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Optional

from auto_reply_route.miner import PromptNormalizer


class PromptIntentTier(str, Enum):
    """The 3 operational intent tiers for human prompts."""
    DIRECT_ANSWER = "direct_answer"   # Tier 0: Strategic, advisory, questions, GTM, roadmap (Zero route)
    UX_CRAFT_AUDIT = "ux_craft_audit" # Tier 1: Design critiques, anti-slop, UI/UX polish (3-step audit deck)
    CODE_BUILD = "code_build"         # Tier 2: Feature engineering, bug fixes, refactoring (1-12 step matrix)


@dataclass(frozen=True)
class IntentClassification:
    tier: PromptIntentTier
    confidence: float
    reason: str
    suggested_steps: int
    extracted_subject: str
    bypass_route_generation: bool
    explicit_prefix_override: bool = False
    cleaned_prompt: str = ""


class HumanIntentClassifier:
    """Classifies natural, conversational human prompts into appropriate execution tiers.
    
    Prevents conversational questions and design critiques from being awkwardly routed 
    as code compilation plans with git assertions.
    """

    # Tier 1: Design & UX Critique Patterns
    UX_CRITIQUE_PATTERNS = [
        r"\b(?:ai\s*slop|slop\s*design|ugl(?:y|ier|iest)|unattractive|clunk(?:y|ier|iest)|amateur(?:ish)?|looks?\s*terrible|looks?\s*bad|looks?\s*amateur)\b",
        r"\b(?:hate\s*this\s*(?:design|ui|ux|theme|styling|look))\b",
        r"\b(?:improve\s*the\s*(?:ux|ui|user\s*experience|design|look|feel))\b",
        r"\b(?:make\s*(?:this|it)\s*(?:look\s*better|feel\s*(?:more\s*)?human|cleaner|modern|professional)|less\s*robotic|feel\s*human|more\s*human)\b",
        r"\b(?:clean\s*up\s*(?:the\s*)?(?:ui|ux|interface|screen|layout|design|styling))\b",
        r"\b(?:ux\s*audit|design\s*critique|visual\s*polish|micro\-?craft)\b",
        r"\b(?:fix\s*this\s*(?:design|styling|clutter|mess))\b",
    ]

    # Tier 0: Strategic, Advisory, Roadmap, GTM & Business Consultation Patterns
    STRATEGIC_ADVISORY_PATTERNS = [
        r"\b(?:go\s*to\s*market|gtm|marketing\s*strategy|distribution\s*strategy)\b",
        r"\b(?:heading\s*in\s*the\s*right\s*direction|right\s*direction|good\s*idea|bad\s*idea)\b",
        r"\b(?:what\s*features?\s*(?:are\s*we\s*missing|should\s*we\s*add|am\s*i\s*missing|do\s*people\s*want))\b",
        r"\b(?:what\s*kind\s*of\s*(?:strategy|pricing|market|niche|audience))\b",
        r"\b(?:what\s*do\s*you\s*think\s*(?:about|of)?)\b",
        r"\b(?:do\s*you\s*think\s*(?:this|we|it|our))\b",
        r"\b(?:pros\s*and\s*cons|trade\-?offs|compare|opinion|advice|feedback)\b",
        r"\b(?:roadmap|future\s*plan|next\s*steps\s*for\s*the\s*business)\b",
        r"\b(?:angel\s*investors?|venture\s*capital|vcs?|fundrais\w*|pitch\s*deck|pre\-?seed|seed\s*round|series\s*[a-d]|cap\s*table|term\s*sheet|safe\s*agreement|valuation)\b",
        r"\b(?:product\s*hunt|launch\s*strategy|waitlist|beta\s*(?:testers?|users?))\b",
        r"\b(?:competitors?|competitive\s*(?:landscape|analysis|advantage|moat)|market\s*share)\b",
        r"\b(?:pricing\s*(?:model|strategy|structure|tiers?)|price\s*this\s*for|business\s*model|monetiz\w*)\b",
        r"\b(?:churn(?:\s*rate)?|retention(?:\s*rate)?|mrr|arr|cac|ltv|burn\s*rate|runway|unit\s*economics)\b",
        r"\b(?:biggest\s*risks?|key\s*risks?|main\s*risks?)\b",
        r"\b(?:ready\s*to\s*(?:show|pitch|demo|launch|present)|is\s*this\s*ready)\b",
        r"\b(?:metrics?\s*should\s*we\s*track|north\s*star\s*metric|kpis?\b)\b",
        r"\b(?:marketing\s*budget|ad\s*spend|customer\s*acquisition)\b",
    ]

    # Direct Question Starters
    QUESTION_STARTERS = [
        r"^(?:what|why|how|when|where|who|which)\b",
        r"^(?:do\s*you|is\s*(?:this|it|that)|are\s*(?:we|you|they)|can\s*(?:we|you|i)|should\s*(?:we|you|i)|could\s*(?:we|you|this)|would\s*(?:you|we))\b",
    ]

    # Meta-commands that should be answered directly rather than building code
    META_COMMANDS = {
        "help", "status", "info", "version", "pricing", "roadmap", "faq"
    }

    # Concrete Code Build Action Verbs (counter-indicators for pure questions)
    CODE_ACTION_VERBS = [
        r"\b(?:build|implement|code|create|add|scaffold|write|wire\s*up|hook\s*up|set\s*up|setup|integrate|connect|fix|patch|refactor|delete|remove|compile|test|deploy|migrate|make|send|export|generate|install|sync|let)\b",
    ]

    @classmethod
    def classify(cls, raw_prompt: str) -> IntentClassification:
        """Classifies a human prompt into Tier 0, Tier 1, or Tier 2."""
        stripped = raw_prompt.strip()
        if not stripped:
            return IntentClassification(
                tier=PromptIntentTier.DIRECT_ANSWER,
                confidence=1.0,
                reason="Empty prompt defaults to direct response",
                suggested_steps=0,
                extracted_subject="",
                bypass_route_generation=True,
                explicit_prefix_override=False,
                cleaned_prompt="",
            )

        # 1. Check for explicit step prefix: e.g. "[4] Build...", "4: ...", "[3] what feature are we missing?"
        budget, cleaned_prompt = PromptNormalizer.extract_step_budget(stripped, default=1)
        has_bracket_prefix = bool(re.match(r"^\s*\[\s*\d{1,2}\s*\]", stripped))
        has_colon_prefix = bool(re.match(r"^\s*\d{1,2}\s*:\s+", stripped))
        has_words_prefix = bool(re.match(r"^\s*\d{1,2}\s+steps?:\s+", stripped, re.IGNORECASE))
        is_explicit_prefix = has_bracket_prefix or has_colon_prefix or has_words_prefix

        # If the user explicitly prefixed a step count, honor their explicit command
        if is_explicit_prefix:
            return IntentClassification(
                tier=PromptIntentTier.CODE_BUILD,
                confidence=0.99,
                reason=f"User explicitly requested {budget}-step route via prefix",
                suggested_steps=budget,
                extracted_subject=cleaned_prompt,
                bypass_route_generation=False,
                explicit_prefix_override=True,
                cleaned_prompt=cleaned_prompt,
            )

        p_lower = cleaned_prompt.lower()

        # 2. Check for Single-Word Meta-Commands
        cleaned_word = re.sub(r"[^\w\s]", "", p_lower).strip()
        if cleaned_word in cls.META_COMMANDS:
            return IntentClassification(
                tier=PromptIntentTier.DIRECT_ANSWER,
                confidence=0.98,
                reason=f"Detected single-word informational command '{cleaned_word}'",
                suggested_steps=0,
                extracted_subject=cleaned_prompt,
                bypass_route_generation=True,
                explicit_prefix_override=False,
                cleaned_prompt=cleaned_prompt,
            )

        # 3. Check for Tier 1: Design & UX Critique
        for pattern in cls.UX_CRITIQUE_PATTERNS:
            if re.search(pattern, p_lower):
                return IntentClassification(
                    tier=PromptIntentTier.UX_CRAFT_AUDIT,
                    confidence=0.95,
                    reason="Detected design critique or anti-slop overhaul intent",
                    suggested_steps=3,
                    extracted_subject=cleaned_prompt,
                    bypass_route_generation=False,
                    explicit_prefix_override=False,
                    cleaned_prompt=cleaned_prompt,
                )

        # 4. Check for Tier 0: Strategic Advisory, GTM, or Open Questions
        for pattern in cls.STRATEGIC_ADVISORY_PATTERNS:
            if re.search(pattern, p_lower):
                return IntentClassification(
                    tier=PromptIntentTier.DIRECT_ANSWER,
                    confidence=0.95,
                    reason="Detected strategic, business, or open advisory consultation",
                    suggested_steps=0,
                    extracted_subject=cleaned_prompt,
                    bypass_route_generation=True,
                    explicit_prefix_override=False,
                    cleaned_prompt=cleaned_prompt,
                )

        # 5. Check for general questions without code actions
        is_question_structure = any(re.search(pat, p_lower) for pat in cls.QUESTION_STARTERS) or p_lower.endswith("?")
        has_code_action = any(re.search(pat, p_lower) for pat in cls.CODE_ACTION_VERBS)

        if is_question_structure and not has_code_action:
            return IntentClassification(
                tier=PromptIntentTier.DIRECT_ANSWER,
                confidence=0.90,
                reason="Detected informational or conceptual inquiry without code implementation directives",
                suggested_steps=0,
                extracted_subject=cleaned_prompt,
                bypass_route_generation=True,
                explicit_prefix_override=False,
                cleaned_prompt=cleaned_prompt,
            )

        # 6. Otherwise Tier 2: Code Build & Implementation Task
        return IntentClassification(
            tier=PromptIntentTier.CODE_BUILD,
            confidence=0.92,
            reason="Detected concrete engineering feature, maintenance, or bugfix build",
            suggested_steps=1,
            extracted_subject=cleaned_prompt,
            bypass_route_generation=False,
            explicit_prefix_override=False,
            cleaned_prompt=cleaned_prompt,
        )
