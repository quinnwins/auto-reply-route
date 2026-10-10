from __future__ import annotations

import collections
from dataclasses import dataclass, field
import enum
import json
from pathlib import Path
import re
from typing import Any, Optional

from auto_reply_route.sanitizer import SecretAndPIISanitizer


class IntentStratum(str, enum.Enum):
    ARCH_DESIGN = "ARCH_DESIGN"
    SCAFFOLD_BUILD = "SCAFFOLD_BUILD"
    DEBUG_REPAIR = "DEBUG_REPAIR"
    VERIFY_QA = "VERIFY_QA"
    RELEASE_OPS = "RELEASE_OPS"


@dataclass
class IntentCluster:
    cluster_id: str
    stratum: IntentStratum
    medoid: str
    raw_medoid: str
    prompts: list[str] = field(default_factory=list)
    raw_prompts: list[str] = field(default_factory=list)
    frequency: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "stratum": self.stratum.value if isinstance(self.stratum, IntentStratum) else str(self.stratum),
            "medoid": self.medoid,
            "raw_medoid": self.raw_medoid,
            "frequency": self.frequency,
            "prompt_count": len(self.prompts),
        }


@dataclass
class BranchCandidate:
    rank: int
    role: str  # "primary_forward", "qa_defensive", "alternative", "fallback"
    intent_id: str
    stratum: str
    medoid: str
    raw_prompt: str
    probability: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "role": self.role,
            "intent_id": self.intent_id,
            "stratum": self.stratum,
            "medoid": self.medoid,
            "raw_prompt": self.raw_prompt,
            "probability": round(self.probability, 4),
            "score": round(self.score, 4),
        }


class PromptNormalizer:
    """Normalizes raw transcript user prompts with XML tag extraction,

    slot masking, fluff stripping, and telegraphic intent act expansion.
    """

    USER_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL | re.IGNORECASE)
    METADATA_STRIP_RE = re.compile(
        r"<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_INSTRUCTION|system_reminder|RULE)[^>]*>.*?</(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_INSTRUCTION|system_reminder|RULE)>",
        re.DOTALL | re.IGNORECASE,
    )
    ALL_XML_TAGS_RE = re.compile(r"<[^>]+>")

    URL_RE = re.compile(
        r"https?://[^\s<>\"']+|\b(?:localhost|127\.0\.0\.1)(?::\d+)?(?:/[^\s<>\"']*)?\b",
        re.IGNORECASE,
    )
    UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    GIT_HASH_40_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
    GIT_HASH_SHORT_RE = re.compile(
        r"\b(?=[0-9a-fA-F]{7,12}\b)(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{7,12}\b"
    )
    GIT_COMMIT_PREFIX_RE = re.compile(r"(?<=\bcommit\s)[0-9a-fA-F]{7,12}\b", re.IGNORECASE)

    PATH_SLASHES_RE = re.compile(
        r"(?:(?:\/|[a-zA-Z]:\\|~|\.\.?\/|[a-zA-Z0-9_\-]+(?:\/|\\))[a-zA-Z0-9_\-\.\/\\]+)"
    )
    KNOWN_CODE_EXTS = (
        "py|js|ts|tsx|jsx|json|yaml|yml|md|html|css|toml|rs|go|c|cpp|h|sh|sql|rb|php|java|kt|swift"
    )
    BARE_CODE_FILE_RE = re.compile(
        rf"\b[a-zA-Z0-9_\-]+\.({KNOWN_CODE_EXTS})\b",
        re.IGNORECASE,
    )

    PORT_EXPLICIT_RE = re.compile(r"\bport\s+(\d{2,5})\b", re.IGNORECASE)
    PORT_COLON_RE = re.compile(r"(?<=[:])\d{2,5}\b")
    NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")

    FLUFF_PATTERNS = [
        re.compile(r"\b(?:could\s+you\s+please|would\s+you\s+please|can\s+you\s+please|please|plz)\b", re.IGNORECASE),
        re.compile(r"\b(?:could\s+you|would\s+you|can\s+you)\b", re.IGNORECASE),
        re.compile(r"\b(?:thank\s+you\s+very\s+much|thank\s+you|thanks\s+a\s+lot|thanks)\b", re.IGNORECASE),
        re.compile(r"\b(?:appreciate\s+it|if\s+possible|kindly|hello|hey|hi)\b", re.IGNORECASE),
        re.compile(r"\b(?:i\s+think|i\s+believe|just|simply)\b", re.IGNORECASE),
    ]

    _BUDGET_TECH_GUARD_1 = re.compile(r"^\d+(?:[a-zA-Z]{1,3}\b|_\w+)")
    _BUDGET_TECH_GUARD_2 = re.compile(r"^\d+-(?!steps?\b)[a-zA-Z]+")
    _BUDGET_HTTP_STATUS = re.compile(r"^(?:404|500|502|503|200|201|401|403)\b")
    _BUDGET_BRACKET = re.compile(r"^\[\s*([1-9]|1[0-2])\s*\]\s*(.*)$")
    _BUDGET_COLON = re.compile(r"^([1-9]|1[0-2])\s*(?:steps?)?\s*[:\-]\s*(.*)$")
    _BUDGET_LEAD_INT = re.compile(r"^([1-9]|1[0-2])\s+([a-zA-Z].*)$")
    _BUDGET_TRAILING_SEP = re.compile(r"^[:\-]\s*")
    _NON_ACTION_UNITS = frozenset({"fa", "d", "k", "g", "fps", "ms", "s", "min", "sec", "px", "rem", "em", "pt", "x"})

    @classmethod
    def extract_step_budget(cls, raw_prompt: str, default: int = 1) -> tuple[int, str]:
        """Extracts leading step budget (1-12) from prompt if present. Defaults to 1 step.
        
        Examples:
            "[4] Build real-time canvas" -> (4, "Build real-time canvas")
            "4: Build real-time canvas"  -> (4, "Build real-time canvas")
            "4 steps: Build canvas"      -> (4, "Build canvas")
            "4 Build real-time canvas"   -> (4, "Build real-time canvas")
            "404 error handler"          -> (1, "404 error handler")
            "2FA authentication flow"    -> (1, "2FA authentication flow")
            "3D rendering canvas"        -> (1, "3D rendering canvas")
            "Build real-time canvas"     -> (1, "Build real-time canvas")
        """
        clean = raw_prompt.strip()

        # Guard against technical false positives (e.g. 2FA, 3D, 4K, 5G, 404, 500, 8-bit, 4-bit, 3-tier)
        if (
            cls._BUDGET_TECH_GUARD_1.match(clean)
            or cls._BUDGET_TECH_GUARD_2.match(clean)
            or cls._BUDGET_HTTP_STATUS.match(clean)
        ):
            return default, clean

        # Pattern 1: Bracketed "[4] ...", "[12] ..."
        m_bracket = cls._BUDGET_BRACKET.match(clean)
        if m_bracket:
            remainder = m_bracket.group(2).strip()
            # Clean up optional trailing separator after bracket e.g. "[12]: foo" -> "foo"
            remainder = cls._BUDGET_TRAILING_SEP.sub("", remainder).strip()
            return int(m_bracket.group(1)), remainder

        # Pattern 2: Colon or 'steps:' prefix e.g. "4: ...", "4 steps: ..."
        m_colon = cls._BUDGET_COLON.match(clean)
        if m_colon:
            return int(m_colon.group(1)), m_colon.group(2).strip()

        # Pattern 3: Leading integer followed by an action verb e.g. "4 build ...", "12 implement ..."
        m_lead = cls._BUDGET_LEAD_INT.match(clean)
        if m_lead:
            first_word = m_lead.group(2).split()[0].lower() if m_lead.group(2) else ""
            if first_word not in cls._NON_ACTION_UNITS:
                return int(m_lead.group(1)), m_lead.group(2).strip()

        return default, clean

    TELEGRAPHIC_MAP = {
        "ok": "proceed with plan",
        "okay": "proceed with plan",
        "yes": "proceed with plan",
        "yep": "proceed with plan",
        "proceed": "proceed with plan",
        "continue": "proceed with plan",
        "go": "proceed with plan",
        "go ahead": "proceed with plan",
        "lgtm": "proceed with plan",
        "looks good": "proceed with plan",
        "sure": "proceed with plan",
        "commit": "commit and release changes",
        "push": "commit and release changes",
        "commit and push": "commit and release changes",
        "save": "commit and release changes",
        "why": "explain root cause",
        "why?": "explain root cause",
        "how come": "explain root cause",
        "how come?": "explain root cause",
        "what happened": "explain root cause",
        "what happened?": "explain root cause",
        "fix": "fix error and repair defect",
        "fix it": "fix error and repair defect",
        "repair": "fix error and repair defect",
        "test": "run tests and verify behavior",
        "test it": "run tests and verify behavior",
        "tests": "run tests and verify behavior",
        "verify": "run tests and verify behavior",
        "check": "run tests and verify behavior",
        "diff": "inspect diff and system status",
        "status": "inspect diff and system status",
        "rollback": "revert changes and rollback",
        "revert": "revert changes and rollback",
        "undo": "revert changes and rollback",
    }

    def extract_user_request(self, raw_input: str) -> str:
        """Extracts <USER_REQUEST> text from raw user input strings,

        stripping metadata tags like <ADDITIONAL_METADATA>, <USER_SETTINGS_CHANGE>, etc.
        """
        if not raw_input:
            return ""

        matches = self.USER_REQUEST_RE.findall(raw_input)
        if matches:
            cleaned = "\n".join(m.strip() for m in matches if m.strip())
            return cleaned.strip()

        # If no <USER_REQUEST> tag, strip known metadata blocks
        text = self.METADATA_STRIP_RE.sub("", raw_input)
        text = self.ALL_XML_TAGS_RE.sub("", text)
        return text.strip()

    def mask_slots(self, text: str) -> str:
        """Replaces file paths ([PATH:ext]), URLs ([URL]), git hashes ([GIT_HASH]),

        UUIDs ([UUID]), ports ([PORT]), and numbers ([NUM]).
        """
        if not text:
            return ""

        result = text

        # 1. URLs and Localhost
        result = self.URL_RE.sub("[URL]", result)

        # 2. UUIDs
        result = self.UUID_RE.sub("[UUID]", result)

        # 3. Git Hashes
        result = self.GIT_HASH_40_RE.sub("[GIT_HASH]", result)
        result = self.GIT_COMMIT_PREFIX_RE.sub("[GIT_HASH]", result)
        result = self.GIT_HASH_SHORT_RE.sub("[GIT_HASH]", result)

        # 4. File Paths
        def replace_path(match: re.Match[str]) -> str:
            path_str = match.group(0)
            ext_match = re.search(r"\.([a-zA-Z0-9]{1,8})$", path_str)
            if ext_match:
                ext = ext_match.group(1).lower()
                return f"[PATH:{ext}]"
            return "[PATH]"

        result = self.PATH_SLASHES_RE.sub(replace_path, result)
        result = self.BARE_CODE_FILE_RE.sub(lambda m: f"[PATH:{m.group(1).lower()}]", result)

        # 5. Ports
        result = self.PORT_EXPLICIT_RE.sub("port [PORT]", result)
        result = self.PORT_COLON_RE.sub("[PORT]", result)

        # 6. Numbers
        result = self.NUMBER_RE.sub("[NUM]", result)

        # Clean spacing
        result = re.sub(r"\s+", " ", result).strip()
        return result

    def strip_fluff(self, text: str) -> str:
        """Strips conversational fluff and polite boilerplate."""
        if not text:
            return ""

        result = text
        for pattern in self.FLUFF_PATTERNS:
            result = pattern.sub(" ", result)

        # Remove trailing excessive punctuation but preserve trailing question mark for short queries
        result = re.sub(r"[!]+", " ", result)
        result = re.sub(r"\s+", " ", result).strip()
        return result

    def expand_telegraphic(
        self,
        text: str,
        context_stratum: Optional[str | IntentStratum] = None,
    ) -> str:
        """Converts telegraphic prompts ('ok', 'commit', 'why?') into contextualized intent acts."""
        cleaned = text.strip().lower()
        core = cleaned.rstrip(".!").strip()
        has_question = cleaned.endswith("?") or core.endswith("?")

        lookup_key = core + ("?" if has_question else "")

        stratum_val = context_stratum.value if isinstance(context_stratum, IntentStratum) else context_stratum

        # Context-aware overrides
        if stratum_val == IntentStratum.ARCH_DESIGN.value and core in ("ok", "okay", "yes", "proceed", "go"):
            return "proceed with implementation plan"
        if stratum_val == IntentStratum.VERIFY_QA.value and core in ("commit", "push", "save", "ok"):
            return "commit and release verified changes"
        if stratum_val == IntentStratum.DEBUG_REPAIR.value and core in ("test", "verify", "check"):
            return "verify defect fix with automated tests"

        if lookup_key in self.TELEGRAPHIC_MAP:
            return self.TELEGRAPHIC_MAP[lookup_key]
        if core in self.TELEGRAPHIC_MAP:
            return self.TELEGRAPHIC_MAP[core]

        return text

    def normalize(
        self,
        raw_input: str,
        context_stratum: Optional[str | IntentStratum] = None,
    ) -> str:
        """Full normalization pipeline: extract request, expand telegraphic shorthand,

        strip fluff, and mask slots.
        """
        extracted = self.extract_user_request(raw_input)
        if not extracted:
            return ""

        # Check if extracted prompt is already telegraphic
        pre_telegraphic = self.expand_telegraphic(extracted, context_stratum=context_stratum)
        if pre_telegraphic != extracted:
            extracted = pre_telegraphic

        stripped = self.strip_fluff(extracted)

        # Check again in case stripping fluff revealed a telegraphic root (e.g. "please commit")
        post_telegraphic = self.expand_telegraphic(stripped, context_stratum=context_stratum)
        if post_telegraphic != stripped:
            stripped = post_telegraphic

        masked = self.mask_slots(stripped)
        return masked.strip()


class IntentClusterer:
    """Stratifies prompts into 5 core pragmatic grammar strata and clusters

    by token n-gram Jaccard similarity, extracting canonical cluster medoids.
    """

    STRATUM_PATTERNS = {
        IntentStratum.RELEASE_OPS: [
            r"\bcommit\b", r"\bgit\b", r"\bpush\b", r"\bdeploy\b", r"\brelease\b", r"\btag\b",
            r"\bpublish\b", r"\bmerge\b", r"\bci\b", r"\bcd\b", r"\bdocker\b", r"\bship\b",
            r"\bpr\b", r"\bpull\s+request\b", r"\bchangelog\b", r"\bversion\s+bump\b"
        ],
        IntentStratum.DEBUG_REPAIR: [
            r"\bfix\b", r"\berror\b", r"\bbug\b", r"\btrace\b", r"\btraceback\b", r"\bfailed\b",
            r"\bfailing\b", r"\bsyntax\b", r"\bbroken\b", r"\bexception\b", r"\bcrash\b",
            r"\brepair\b", r"\bresolve\b", r"\bpatch\b", r"\bregress\b", r"\bregression\b",
            r"\bdefect\b", r"\bdiagnose\b"
        ],
        IntentStratum.VERIFY_QA: [
            r"\btest\b", r"\btests\b", r"\btesting\b", r"\bpytest\b", r"\bverify\b", r"\bverification\b",
            r"\bcheck\b", r"\breview\b", r"\baudit\b", r"\bscreenshot\b", r"\blint\b", r"\blinter\b",
            r"\binspect\b", r"\bassert\b", r"\bcoverage\b", r"\bvalidate\b", r"\bvalidation\b",
            r"\bbenchmark\b", r"\ba11y\b", r"\beval\b", r"\bevaluate\b"
        ],
        IntentStratum.ARCH_DESIGN: [
            r"\barchitecture\b", r"\bplan\b", r"\bdesign\b", r"\btrade-?offs?\b", r"\brfc\b",
            r"\bspec\b", r"\bspecification\b", r"\bschema\b", r"\bblueprint\b", r"\bmodel\b",
            r"\brefactor\b", r"\bstrategy\b", r"\bapproach\b", r"\bstructure\b"
        ],
        IntentStratum.SCAFFOLD_BUILD: [
            r"\bcreate\b", r"\badd\b", r"\bbuild\b", r"\bimplement\b", r"\bcode\b", r"\bwrite\b",
            r"\bgenerate\b", r"\bscaffold\b", r"\bdevelop\b", r"\bwire\b", r"\bmake\b",
            r"\bsetup\b", r"\binit\b", r"\binitialize\b", r"\binstall\b", r"\bconstruct\b"
        ],
    }

    def __init__(self, normalizer: Optional[PromptNormalizer] = None):
        self.normalizer = normalizer or PromptNormalizer()

    def categorize_stratum(self, prompt: str) -> IntentStratum:
        """Categorizes a normalized prompt into one of the 5 Pragmatic Grammar Strata."""
        lower_prompt = prompt.lower()
        scores = {s: 0 for s in IntentStratum}

        for stratum, patterns in self.STRATUM_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, lower_prompt)
                if matches:
                    scores[stratum] += len(matches) * 2

        # Priority ordering for tie-breaking: DEBUG > RELEASE > VERIFY > ARCH > SCAFFOLD
        tie_breaker_order = [
            IntentStratum.DEBUG_REPAIR,
            IntentStratum.RELEASE_OPS,
            IntentStratum.VERIFY_QA,
            IntentStratum.ARCH_DESIGN,
            IntentStratum.SCAFFOLD_BUILD,
        ]

        ranked = sorted(
            scores.items(),
            key=lambda item: (item[1], -tie_breaker_order.index(item[0])),
            reverse=True,
        )

        if ranked[0][1] > 0:
            return ranked[0][0]

        return IntentStratum.SCAFFOLD_BUILD

    @staticmethod
    def extract_ngrams(text: str) -> set[str]:
        """Extracts word 1-grams and 2-grams for Jaccard similarity."""
        cleaned = re.sub(r"[^\w\s\[\]:]+", " ", text.lower())
        words = [w for w in cleaned.split() if w]
        if not words:
            return {text.lower()}

        ngrams = set(words)
        for i in range(len(words) - 1):
            ngrams.add(f"{words[i]} {words[i+1]}")
        return ngrams

    @classmethod
    def jaccard_similarity(cls, text_a: str, text_b: str) -> float:
        """Computes n-gram Jaccard similarity between two prompt texts."""
        set_a = cls.extract_ngrams(text_a)
        set_b = cls.extract_ngrams(text_b)
        if not set_a and not set_b:
            return 1.0
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)

    def cluster_prompts(
        self,
        prompts: list[dict[str, str] | str],
        distance_threshold: float = 0.65,
    ) -> list[IntentCluster]:
        """Clusters normalized prompts by token n-gram Jaccard similarity and stratum.

        Extracts the cluster medoid (the most representative real prompt).
        """
        if not prompts:
            return []

        # Standardize items to list of dicts with 'raw', 'norm', 'stratum'
        items: list[dict[str, Any]] = []
        for p in prompts:
            if isinstance(p, dict):
                raw = p.get("raw", "")
                norm = p.get("normalized") or self.normalizer.normalize(raw)
            else:
                raw = p
                norm = self.normalizer.normalize(p)

            if not norm:
                continue

            stratum = self.categorize_stratum(norm)
            ngrams = self.extract_ngrams(norm)
            items.append({
                "raw": raw,
                "norm": norm,
                "stratum": stratum,
                "ngrams": ngrams,
            })

        if not items:
            return []

        clusters: list[IntentCluster] = []
        cluster_counter = 0
        similarity_threshold = max(0.20, 1.0 - distance_threshold)

        # Cluster strictly within each stratum to avoid semantic bleeding
        for stratum in IntentStratum:
            stratum_items = [it for it in items if it["stratum"] == stratum]
            if not stratum_items:
                continue

            # Online Leader Clustering with pre-computed n-grams: O(N * K)
            stratum_clusters: list[dict[str, Any]] = []

            for item in stratum_items:
                item_ngrams = item["ngrams"]
                best_cluster = None
                best_sim = -1.0

                for sc in stratum_clusters:
                    leader_ngrams = sc["leader_ngrams"]
                    intersection_len = len(item_ngrams & leader_ngrams)
                    union_len = len(item_ngrams | leader_ngrams)
                    sim = intersection_len / union_len if union_len > 0 else 0.0

                    if sim > best_sim:
                        best_sim = sim
                        best_cluster = sc

                if best_cluster is not None and best_sim >= similarity_threshold:
                    best_cluster["items"].append(item)
                else:
                    stratum_clusters.append({
                        "leader_ngrams": item_ngrams,
                        "items": [item],
                    })

            # Medoid selection for each cluster
            for sc in stratum_clusters:
                group = sc["items"]
                if len(group) == 1:
                    best_cand = group[0]
                else:
                    best_cand = group[0]
                    best_avg_sim = -1.0
                    for cand in group:
                        c_ngrams = cand["ngrams"]
                        total_sim = 0.0
                        for other in group:
                            o_ngrams = other["ngrams"]
                            u_len = len(c_ngrams | o_ngrams)
                            if u_len > 0:
                                total_sim += len(c_ngrams & o_ngrams) / u_len
                        avg_sim = total_sim / len(group)
                        if avg_sim > best_avg_sim:
                            best_avg_sim = avg_sim
                            best_cand = cand

                cluster_id = f"intent_{stratum.value.lower()}_{cluster_counter}"
                cluster_counter += 1

                c_obj = IntentCluster(
                    cluster_id=cluster_id,
                    stratum=stratum,
                    medoid=best_cand["norm"],
                    raw_medoid=best_cand["raw"],
                    prompts=[it["norm"] for it in group],
                    raw_prompts=[it["raw"] for it in group],
                    frequency=len(group),
                )
                clusters.append(c_obj)

        return clusters

    def find_nearest_cluster(
        self,
        prompt: str,
        clusters: list[IntentCluster],
    ) -> Optional[IntentCluster]:
        """Maps a given prompt to its closest cluster by stratum and Jaccard similarity."""
        if not clusters:
            return None

        norm = self.normalizer.normalize(prompt)
        stratum = self.categorize_stratum(norm)

        same_stratum = [c for c in clusters if c.stratum == stratum]
        candidates = same_stratum if same_stratum else clusters

        best_cluster = candidates[0]
        best_sim = -1.0
        for c in candidates:
            sim = self.jaccard_similarity(norm, c.medoid)
            if sim > best_sim:
                best_sim = sim
                best_cluster = c

        return best_cluster


class SequenceMarkovModel:
    """Variable-Order Markov Model (orders 1 and 2 with backoff) for intent sequences.

    Generates 1st (Primary Forward), 2nd (QA/Defensive), 3rd (Alternative),
    and 4th (Fallback) branch candidates using MMR diversity scoring.
    """

    def __init__(
        self,
        lambda_2: float = 0.7,
        lambda_1: float = 0.8,
        mmr_lambda: float = 0.6,
    ):
        self.lambda_2 = lambda_2
        self.lambda_1 = lambda_1
        self.mmr_lambda = mmr_lambda

        self.unigram_counts: collections.Counter[str] = collections.Counter()
        self.order1_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        self.order2_counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)

        self.clusters: dict[str, IntentCluster] = {}
        self.vocabulary: set[str] = set()

    def fit(
        self,
        sequences: list[list[str]],
        clusters: dict[str, IntentCluster],
    ) -> None:
        """Trains the Variable-Order Markov model on sequences of intent cluster IDs."""
        self.clusters = dict(clusters)
        self.vocabulary = set(self.clusters.keys())

        self.unigram_counts.clear()
        self.order1_counts.clear()
        self.order2_counts.clear()

        for seq in sequences:
            if not seq:
                continue

            for item in seq:
                self.unigram_counts[item] += 1
                self.vocabulary.add(item)

            for i in range(len(seq) - 1):
                self.order1_counts[seq[i]][seq[i + 1]] += 1

            for i in range(len(seq) - 2):
                self.order2_counts[(seq[i], seq[i + 1])][seq[i + 2]] += 1

    def transition_probability(
        self,
        next_intent: str,
        history: tuple[str, ...] | list[str],
    ) -> float:
        """Calculates P(u | H) with variable-order backoff."""
        dist = self.get_transition_distribution(history)
        return dist.get(next_intent, 0.0)

    def get_transition_distribution(
        self,
        history: tuple[str, ...] | list[str],
    ) -> dict[str, float]:
        """Calculates probability distribution over next intents given history with backoff."""
        if not self.vocabulary:
            return {}

        hist = tuple(history)
        total_unigrams = sum(self.unigram_counts.values()) or len(self.vocabulary)
        p0 = {
            v: (self.unigram_counts[v] if total_unigrams > 0 else 1.0) / total_unigrams
            for v in self.vocabulary
        }

        # Order 1 base
        p1 = dict(p0)
        if hist and hist[-1] in self.order1_counts:
            prev = hist[-1]
            total_1 = sum(self.order1_counts[prev].values())
            if total_1 > 0:
                p1 = {
                    v: (self.order1_counts[prev][v] / total_1) * self.lambda_1 + p0[v] * (1.0 - self.lambda_1)
                    for v in self.vocabulary
                }

        # Order 2
        if len(hist) >= 2:
            context = (hist[-2], hist[-1])
            if context in self.order2_counts:
                total_2 = sum(self.order2_counts[context].values())
                if total_2 > 0:
                    dist = {
                        v: (self.order2_counts[context][v] / total_2) * self.lambda_2 + p1[v] * (1.0 - self.lambda_2)
                        for v in self.vocabulary
                    }
                    total_prob = sum(dist.values())
                    return {v: p / total_prob for v, p in dist.items()}

        # Backoff to Order 1 or Order 0
        total_prob = sum(p1.values())
        return {v: p / total_prob for v, p in p1.items()}

    def generate_branch_candidates(
        self,
        history: tuple[str, ...] | list[str],
        top_k: int = 4,
    ) -> list[BranchCandidate]:
        """Generates 1st (Primary Forward), 2nd (QA/Defensive), 3rd (Alternative),

        and 4th (Fallback) branch candidates using MMR diversity scoring.
        """
        dist = self.get_transition_distribution(history)
        max_prob = max(dist.values()) if dist else 1.0
        if max_prob <= 0:
            max_prob = 1.0

        roles = ["primary_forward", "qa_defensive", "alternative", "fallback"]
        selected: list[BranchCandidate] = []
        used_intent_ids: set[str] = set()

        for rank, role in enumerate(roles[:top_k], start=1):
            best_intent_id: Optional[str] = None
            best_score = -float("inf")

            for cid, prob in dist.items():
                if cid in used_intent_ids:
                    continue

                rel = prob / max_prob
                cluster = self.clusters.get(cid)
                stratum = cluster.stratum.value if cluster else IntentStratum.SCAFFOLD_BUILD.value

                # Max similarity to already selected branches
                max_sim = 0.0
                for s in selected:
                    sim = 0.0
                    if cluster:
                        sim = IntentClusterer.jaccard_similarity(cluster.medoid, s.medoid)
                    if stratum == s.stratum:
                        sim = max(sim, 0.5)
                    if sim > max_sim:
                        max_sim = sim

                # Role functional affinity
                role_bonus = 0.0
                if role == "primary_forward":
                    score = rel
                elif role == "qa_defensive":
                    if stratum in (IntentStratum.VERIFY_QA.value, IntentStratum.DEBUG_REPAIR.value):
                        role_bonus = 0.35
                    score = self.mmr_lambda * rel - (1.0 - self.mmr_lambda) * max_sim + role_bonus
                elif role == "alternative":
                    if stratum == IntentStratum.ARCH_DESIGN.value or (
                        selected and stratum != selected[0].stratum
                    ):
                        role_bonus = 0.30
                    score = self.mmr_lambda * rel - (1.0 - self.mmr_lambda) * max_sim + role_bonus
                else:  # fallback
                    if stratum == IntentStratum.RELEASE_OPS.value:
                        role_bonus = 0.35
                    score = self.mmr_lambda * rel - (1.0 - self.mmr_lambda) * max_sim + role_bonus

                if score > best_score:
                    best_score = score
                    best_intent_id = cid

            # Fallback if no unused intent exists in training data
            if best_intent_id is None:
                synthetic_cluster = self._synthesize_fallback_cluster(role, rank)
                best_intent_id = synthetic_cluster.cluster_id
                self.clusters[best_intent_id] = synthetic_cluster
                prob = 0.05
                best_score = 0.1

            c = self.clusters[best_intent_id]
            used_intent_ids.add(best_intent_id)

            cand = BranchCandidate(
                rank=rank,
                role=role,
                intent_id=best_intent_id,
                stratum=c.stratum.value if isinstance(c.stratum, IntentStratum) else str(c.stratum),
                medoid=c.medoid,
                raw_prompt=c.raw_medoid,
                probability=dist.get(best_intent_id, 0.05),
                score=best_score,
            )
            selected.append(cand)

        return selected

    def _synthesize_fallback_cluster(self, role: str, rank: int) -> IntentCluster:
        """Provides high-quality functional fallback intent if corpus has fewer than 4 intents."""
        if role == "qa_defensive":
            return IntentCluster(
                cluster_id=f"synth_qa_{rank}",
                stratum=IntentStratum.VERIFY_QA,
                medoid="run automated tests and verify code quality",
                raw_medoid="Run tests and verify everything is working",
                frequency=1,
            )
        elif role == "alternative":
            return IntentCluster(
                cluster_id=f"synth_arch_{rank}",
                stratum=IntentStratum.ARCH_DESIGN,
                medoid="review architectural design trade-offs",
                raw_medoid="Can we reconsider the architectural design?",
                frequency=1,
            )
        elif role == "fallback":
            return IntentCluster(
                cluster_id=f"synth_ops_{rank}",
                stratum=IntentStratum.RELEASE_OPS,
                medoid="commit changes and prepare release",
                raw_medoid="Commit all changes and tag release",
                frequency=1,
            )
        else:
            return IntentCluster(
                cluster_id=f"synth_build_{rank}",
                stratum=IntentStratum.SCAFFOLD_BUILD,
                medoid="implement next feature module",
                raw_medoid="Let's build the next feature module",
                frequency=1,
            )


class PromptRouteMiner:
    """Ingests transcript logs, clusters user prompts, models transition sequences,

    and discovers canonical routes with 4-way diverse branching options.
    """

    def __init__(
        self,
        normalizer: Optional[PromptNormalizer] = None,
        clusterer: Optional[IntentClusterer] = None,
        markov_model: Optional[SequenceMarkovModel] = None,
        sanitizer: Optional[SecretAndPIISanitizer] = None,
    ):
        self.normalizer = normalizer or PromptNormalizer()
        self.clusterer = clusterer or IntentClusterer(self.normalizer)
        self.markov_model = markov_model or SequenceMarkovModel()
        self.sanitizer = sanitizer or SecretAndPIISanitizer()

    def parse_transcript_file(self, file_path: Path | str) -> list[tuple[str, str]]:
        """Extracts (raw_prompt, normalized_prompt) tuples in chronological order from a JSONL file,

        ensuring secrets and PII are redacted before downstream route discovery.
        """
        path = Path(file_path)
        if not path.is_file():
            return []

        turns: list[tuple[str, str]] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    source = record.get("source", "")
                    step_type = record.get("type", "")

                    if source in ("USER_EXPLICIT", "USER") or step_type == "USER_INPUT":
                        raw_content = record.get("content", "")
                        if not raw_content and isinstance(record.get("args"), dict):
                            raw_content = record["args"].get("prompt", "")

                        if not raw_content:
                            continue

                        extracted = self.normalizer.extract_user_request(raw_content)
                        if not extracted:
                            continue

                        norm = self.normalizer.normalize(extracted)
                        if norm:
                            turns.append((extracted, norm))
        except Exception:
            return []

        if self.sanitizer and turns:
            turns = self.sanitizer.sanitize_transcript_turns(turns)

        return turns

    def collect_transcript_files(self, transcript_paths: list[str], max_files: int = 50) -> list[Path]:
        """Expands paths to files or recursively scans directories for JSONL logs."""
        seen: set[Path] = set()
        files: list[Path] = []
        for p_str in transcript_paths:
            p = Path(p_str)
            if p.is_file():
                if p.suffix in (".jsonl", ".json") and p not in seen:
                    files.append(p)
                    seen.add(p)
            elif p.is_dir():
                found = list(p.rglob("transcript.jsonl"))
                if not found:
                    found = [f for f in p.rglob("*.jsonl") if not f.name.endswith(".tmp")]
                # Sort by modification time descending so recent sessions take priority
                found.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
                for f in found[:max_files]:
                    if f not in seen:
                        files.append(f)
                        seen.add(f)
        files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
        return files[:max_files]

    def mine_transcripts(self, transcript_paths: list[str]) -> list[dict[str, Any]]:
        """Mines transcripts to discover canonical route paths and diverse 4-way branching options."""
        files = self.collect_transcript_files(transcript_paths)
        sessions: list[list[tuple[str, str]]] = []
        all_raw_and_norm: list[dict[str, str]] = []

        for f in files:
            turns = self.parse_transcript_file(f)
            if turns:
                sessions.append(turns)
                for raw, norm in turns:
                    all_raw_and_norm.append({"raw": raw, "normalized": norm})

        if not sessions or not all_raw_and_norm:
            return []

        # 1. Cluster all observed prompts
        clusters = self.clusterer.cluster_prompts(all_raw_and_norm)
        if not clusters:
            return []

        clusters_by_id = {c.cluster_id: c for c in clusters}

        # 2. Map sessions from turns to cluster ID sequences
        session_cluster_seqs: list[list[str]] = []
        for session in sessions:
            seq: list[str] = []
            for raw, norm in session:
                target_cluster = self.clusterer.find_nearest_cluster(norm, clusters)
                if target_cluster:
                    seq.append(target_cluster.cluster_id)
            if seq:
                session_cluster_seqs.append(seq)

        # 3. Fit Markov sequence transition model
        self.markov_model.fit(session_cluster_seqs, clusters_by_id)

        # 4. Canonical Route Generation
        start_counts: collections.Counter[str] = collections.Counter()
        for seq in session_cluster_seqs:
            start_counts[seq[0]] += 1

        if not start_counts:
            return []

        start_cluster_id = start_counts.most_common(1)[0][0]

        # Follow primary forward transitions to construct canonical route
        visited_nodes: list[str] = []
        current_id = start_cluster_id
        route_steps: list[dict[str, Any]] = []
        history: list[str] = []

        step_limit = min(8, len(clusters))
        for step_idx in range(1, step_limit + 1):
            if current_id in visited_nodes:
                break
            visited_nodes.append(current_id)
            history.append(current_id)

            cluster = clusters_by_id[current_id]
            branches = self.markov_model.generate_branch_candidates(tuple(history), top_k=4)

            step_data = {
                "step_index": step_idx,
                "intent_id": cluster.cluster_id,
                "stratum": cluster.stratum.value if isinstance(cluster.stratum, IntentStratum) else str(cluster.stratum),
                "medoid": cluster.medoid,
                "raw_medoid": cluster.raw_medoid,
                "frequency": cluster.frequency,
                "branches": [b.to_dict() for b in branches],
            }
            route_steps.append(step_data)

            # Advance to 1st place Primary Forward candidate
            primary_branch = branches[0]
            next_id = primary_branch.intent_id
            if next_id == current_id or next_id in visited_nodes:
                # Pick alternative unused branch if available
                found_next = False
                for b in branches[1:]:
                    if b.intent_id not in visited_nodes and b.intent_id in clusters_by_id:
                        next_id = b.intent_id
                        found_next = True
                        break
                if not found_next:
                    break

            if next_id not in clusters_by_id:
                break
            current_id = next_id

        total_transitions = sum(
            sum(c.values()) for c in self.markov_model.order1_counts.values()
        )

        route_record = {
            "route_id": f"route_{clusters_by_id[start_cluster_id].stratum.value.lower()}",
            "title": "Autonomous Engineering Canonical Route",
            "total_sessions": len(sessions),
            "total_transitions": total_transitions,
            "total_intents": len(clusters),
            "steps": route_steps,
        }

        return [route_record]

    def export_route_markdown(self, route_data: dict[str, Any]) -> str:
        """Exports discovered routes into clean .route.md format with Mermaid graph."""
        title = route_data.get("title", "Canonical Auto-Reply Route")
        total_sessions = route_data.get("total_sessions", 0)
        total_transitions = route_data.get("total_transitions", 0)
        steps = route_data.get("steps", [])

        lines: list[str] = [
            f"# Auto-Reply Route Map: {title}",
            "",
            f"- **Sessions Analyzed**: {total_sessions}",
            f"- **Canonical Steps**: {len(steps)}",
            f"- **Transitions Modeled**: {total_transitions}",
            "",
            "## State Transition Graph",
            "",
            "```mermaid",
            "flowchart TD",
        ]

        # Build Mermaid flowchart nodes and edges
        for i, step in enumerate(steps):
            s_idx = step["step_index"]
            node_id = f"Step{s_idx}"
            label = f"{s_idx}. [{step['stratum']}] {step['medoid']}".replace('"', "'")
            lines.append(f'    {node_id}["{label}"]')

            # Draw branch connections
            branches = step.get("branches", [])
            if branches:
                primary = branches[0]
                p_pct = int(primary["probability"] * 100)
                if i + 1 < len(steps):
                    next_node_id = f"Step{steps[i+1]['step_index']}"
                    lines.append(f'    {node_id} -->|Primary ({p_pct}%)| {next_node_id}')

                for b in branches[1:]:
                    b_rank = b["rank"]
                    b_pct = int(b["probability"] * 100)
                    b_node_id = f"{node_id}_B{b_rank}"
                    b_label = f"[{b['stratum']}] {b['medoid']}".replace('"', "'")
                    lines.append(f'    {b_node_id}["{b_label}"]')
                    lines.append(f'    {node_id} -.->|{b["role"]} ({b_pct}%)| {b_node_id}')

        lines.extend([
            "```",
            "",
            "## Canonical Route Sequence & Branching Map",
            "",
        ])

        role_emojis = {
            "primary_forward": "🟢 Primary Forward",
            "qa_defensive": "🛡️ QA / Defensive",
            "alternative": "🔀 Alternative",
            "fallback": "🚪 Fallback / Exit",
        }

        for step in steps:
            s_idx = step["step_index"]
            lines.extend([
                f"### Step {s_idx}: {step['medoid']}",
                f"- **Stratum**: `{step['stratum']}`",
                f"- **Canonical Representative Prompt**: \"{step['raw_medoid']}\"",
                f"- **Observation Frequency**: {step['frequency']} occurrences",
                "",
                "| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |",
                "|:---:|:---|:---|:---|:---:|",
            ])

            for b in step.get("branches", []):
                role_label = role_emojis.get(b["role"], b["role"])
                prob_str = f"{b['probability']:.1%}"
                lines.append(
                    f"| {b['rank']} | {role_label} | `{b['stratum']}` | {b['medoid']} | {prob_str} |"
                )

            lines.append("")

        return "\n".join(lines).strip() + "\n"


PromptMiner = PromptRouteMiner

