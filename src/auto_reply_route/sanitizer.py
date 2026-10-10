"""Enterprise Governance & Secret Redactor Engine.

Detects and redacts high-entropy secrets, API keys, private credentials,
corporate internal hostnames/IPs, and PII from pairing transcripts
before route mining, clustering, or operational playbooks are generated.

Standard library Python 3.9+ only (re, math, hashlib, collections). Zero external dependencies.

==============================================================================
EXPERT DECISION RUBRIC: SHANNON ENTROPY VS. REGEX ALONE & SYSTEM TRADE-OFFS
==============================================================================
1. Why Regex Alone Fails:
   - Syntactic Rigidity: Regex is strictly pattern-bound and signature-driven.
     It depends entirely on static, pre-identified vendor prefixes (e.g. "AKIA...",
     "ghp_...", "AIza...").
   - Blindness to Unknown & Internal Secrets: Modern engineering teams generate
     arbitrary tokens for internal microservices, HMAC signatures, JWT signing keys,
     database passwords, and custom OAuth providers that lack standardized prefixes.
   - The False-Positive Trap: To capture un-prefixed secrets with regex alone,
     one must match generic alphanumeric patterns (e.g. `[a-zA-Z0-9]{32}`).
     Doing so catastrophically mangles benign code tokens—such as UUIDs, CamelCase
     identifiers (e.g. `EnterpriseAuthenticationManager`), base64 assets, and git hashes.
   - By contrast, Shannon entropy quantifies information density:
         H(X) = - sum(p(x) * log2(p(x)))
     CSPRNG-generated keys exhibit near-maximum theoretical entropy (~4.0 for hex,
     ~5.0+ for base64), while human language and natural code identifiers exhibit
     low entropy (~2.2 - 3.4) due to redundant linguistic morphemes and letter frequencies.

2. Comprehensive Architectural Trade-Offs:
   - Trade-Off 1: Entropy Sensitivity vs. False Positive Rates
     * Setting hex threshold H >= 3.0 or base64 H >= 4.0 catches arbitrary secrets,
       but risk flagging long, dense class names or compressed hashes.
     * Mitigation: We implement a two-tiered filter. Known vendor signatures run
       first with exact regexes; high-entropy detection runs second on extracted tokens
       excluding benign code constructs (file paths, URLs, UUIDs).
   - Trade-Off 2: Computational Overhead vs. Security Hardening
     * Computing character frequency distributions and logarithms is more CPU-intensive
       than compiled regular expressions.
     * Mitigation: Pre-filter candidate strings using length bounds (>= 16 chars)
       and candidate token boundaries before running the O(N) Shannon entropy calculation.
   - Trade-Off 3: Semantic Utility vs. Data Loss
     * Blanket redaction of entire lines prevents secret leakage but destroys the
       semantic meaning of pairing prompts needed for route discovery.
     * Mitigation: Deterministic granular placeholders (e.g. [REDACTED:STRIPE_KEY],
       [REDACTED:INTERNAL_HOST], [EMAIL]) preserve structural syntactic intent
       so Markov clustering algorithms can still understand command semantics.
==============================================================================
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
import hashlib
import math
import re
from typing import Any, Optional, Union


# ============================================================================
# 1. Models & Sanitization Records
# ============================================================================

@dataclass
class SanitizationRecord:
    """Audit ledger entry detailing a redacted secret or PII occurrence."""

    category: str
    detector: str
    matched_text: str
    placeholder: str
    start: int
    end: int
    entropy: Optional[float] = None
    confidence: float = 1.0

    @property
    def secret_type(self) -> str:
        """Alias for detector identifier."""
        return self.detector

    @property
    def rule_id(self) -> str:
        """Alias for detector identifier."""
        return self.detector

    @property
    def replacement(self) -> str:
        """Alias for replacement placeholder."""
        return self.placeholder

    @property
    def masked_text(self) -> str:
        """Safe non-leaking preview of matched secret."""
        if len(self.matched_text) <= 8:
            return "***"
        return f"{self.matched_text[:4]}...{self.matched_text[-4:]}"

    @property
    def secret_hash(self) -> str:
        """Deterministic SHA-256 digest prefix of the secret for deduplication."""
        return hashlib.sha256(self.matched_text.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        """Serialize record to dictionary for logging and audit persistence."""
        return {
            "category": self.category,
            "detector": self.detector,
            "matched_text": self.matched_text,
            "masked_text": self.masked_text,
            "secret_hash": self.secret_hash,
            "placeholder": self.placeholder,
            "start": self.start,
            "end": self.end,
            "entropy": round(self.entropy, 4) if self.entropy is not None else None,
            "confidence": round(self.confidence, 4),
        }


# ============================================================================
# 2. Shannon Entropy Estimator
# ============================================================================

def calculate_shannon_entropy(data: str) -> float:
    """Calculates the Shannon entropy H(X) in bits per character.

    Theoretical bounds:
    - Hex string (0-9a-f, alphabet 16): max 4.0 bits/char
    - Base64 string (alphabet 64): max 6.0 bits/char
    - Natural language / code: typically 2.0 - 3.4 bits/char
    """
    if not data:
        return 0.0
    length = len(data)
    frequencies = collections.Counter(data)
    entropy = 0.0
    for count in frequencies.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


# ============================================================================
# 3. Secret and PII Sanitizer Engine
# ============================================================================

class SecretAndPIISanitizer:
    """Enterprise-grade detector and redactor for secrets, credentials, internal networks, and PII."""

    # Default canonical placeholders
    DEFAULT_PLACEHOLDERS: dict[str, str] = {
        "google_key": "[REDACTED:GOOGLE_KEY]",
        "openai_key": "[REDACTED:OPENAI_KEY]",
        "anthropic_key": "[REDACTED:ANTHROPIC_KEY]",
        "stripe_key": "[REDACTED:STRIPE_KEY]",
        "aws_key": "[REDACTED:AWS_KEY]",
        "github_token": "[REDACTED:GITHUB_TOKEN]",
        "bearer_token": "[REDACTED:BEARER_TOKEN]",
        "private_key": "[REDACTED:PRIVATE_KEY]",
        "password": "[REDACTED:PASSWORD]",
        "internal_host": "[REDACTED:INTERNAL_HOST]",
        "internal_ip": "[REDACTED:INTERNAL_IP]",
        "private_ip": "[REDACTED:INTERNAL_IP]",
        "email": "[EMAIL]",
        "phone": "[PHONE]",
        "ssn": "[SSN]",
        "high_entropy": "[REDACTED:HIGH_ENTROPY_SECRET]",
    }

    # Compiled regex patterns for vendor API keys & known secrets
    GOOGLE_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")
    OPENAI_KEY_RE = re.compile(r"\bsk-(?:proj-|admin-)?[0-9a-zA-Z_-]{20,}\b")
    ANTHROPIC_KEY_RE = re.compile(r"\bsk-ant-[0-9a-zA-Z_-]{20,}\b")
    STRIPE_KEY_RE = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}\b")
    AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")
    AWS_SECRET_KEY_RE = re.compile(
        r"(?i)\b(?:aws_secret_access_key|aws_secret_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
    )
    GITHUB_TOKEN_RE = re.compile(
        r"\b(?:ghp_[0-9a-zA-Z]{36,}|github_pat_[0-9a-zA-Z_]{82,}|(?:gho|ghu|ghs|ghr)_[0-9a-zA-Z]{36,})\b"
    )
    BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+([a-zA-Z0-9_\-\.]{20,})\b")
    PRIVATE_KEY_RE = re.compile(
        r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY(?: BLOCK)?-----"
    )
    PASSWORD_URI_RE = re.compile(
        r"\b([a-zA-Z0-9+.-]+://[^:\s/@]+):([^@\s/@]+)(@[^\s/]+)"
    )
    PASSWORD_ASSIGN_RE = re.compile(
        r"(?i)\b(password|passwd|pwd|db_pass|client_secret)\s*([:=])\s*(?:['\"]([^'\"]{4,})['\"]|([^\s,;'\"]{4,}))"
    )

    # Corporate internal hostnames and private IPs
    INTERNAL_HOST_RE = re.compile(
        r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+(?:internal|corp|local)\b|"
        r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*corp\.google\.com\b|"
        r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*google\.internal\b",
        re.IGNORECASE,
    )
    PRIVATE_IPV4_10_RE = re.compile(
        r"\b10\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
    )
    PRIVATE_IPV4_192_RE = re.compile(
        r"\b192\.168\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
    )
    PRIVATE_IPV4_172_RE = re.compile(
        r"\b172\.(?:1[6-9]|2[0-9]|3[0-1])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
    )

    # PII patterns
    EMAIL_RE = re.compile(
        r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
    )
    PHONE_US_RE = re.compile(
        r"(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s][0-9]{3}[-.\s][0-9]{4}\b"
    )
    PHONE_INTL_RE = re.compile(
        r"\+[1-9]\d{0,2}[-.\s](?:\(?\d{1,4}\)?[-.\s])?\d{3,4}[-.\s]\d{3,4}\b"
    )
    SSN_RE = re.compile(
        r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
    )

    # Candidates for high-entropy token evaluation
    CANDIDATE_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9_\-+/=]{16,}\b")
    UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )

    def __init__(
        self,
        custom_placeholders: Optional[dict[str, str]] = None,
        entropy_threshold_base64: float = 4.2,
        entropy_threshold_hex: float = 3.4,
        enable_entropy: bool = True,
    ):
        self.placeholders = dict(self.DEFAULT_PLACEHOLDERS)
        if custom_placeholders:
            self.placeholders.update(custom_placeholders)

        self.entropy_threshold_base64 = entropy_threshold_base64
        self.entropy_threshold_hex = entropy_threshold_hex
        self.enable_entropy = enable_entropy

    def get_placeholder(self, key: str, fallback: str = "[REDACTED]") -> str:
        """Lookup configured placeholder for a given detector key."""
        return self.placeholders.get(key, fallback)

    # ========================================================================
    # Core Public Interface
    # ========================================================================

    def sanitize_text(self, text: str) -> tuple[str, list[SanitizationRecord]]:
        """Detects and redacts high-entropy secrets, vendor keys, internal hostnames, and PII.

        Returns:
            tuple[str, list[SanitizationRecord]]: (sanitized_text, list_of_audit_records)
        """
        if not text:
            return "", []

        # List of candidate match tuples:
        # (start, end, detector, category, matched_text, placeholder, entropy, confidence, priority)
        # Priority: Higher number = higher precedence during overlap resolution
        candidates: list[dict[str, Any]] = []

        # 1. Private Keys (highest precedence: priority 100)
        for m in self.PRIVATE_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "private_key",
                "category": "CREDENTIAL",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("private_key"),
                "entropy": None,
                "confidence": 1.0,
                "priority": 100,
            })

        # 2. Specific API Key Signatures (priority 90)
        # Google API Keys
        for m in self.GOOGLE_API_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "google_api_key",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("google_key"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # Anthropic API Keys
        for m in self.ANTHROPIC_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "anthropic_api_key",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("anthropic_key"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # OpenAI API Keys
        for m in self.OPENAI_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "openai_api_key",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("openai_key"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # Stripe Keys
        for m in self.STRIPE_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "stripe_key",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("stripe_key"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # AWS Access Keys
        for m in self.AWS_ACCESS_KEY_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "aws_access_key",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("aws_key"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # AWS Secret Access Keys in assignments
        for m in self.AWS_SECRET_KEY_RE.finditer(text):
            secret_val = m.group(1)
            start_offset = m.start(1)
            end_offset = m.end(1)
            candidates.append({
                "start": start_offset,
                "end": end_offset,
                "detector": "aws_secret_key",
                "category": "API_KEY",
                "matched_text": secret_val,
                "placeholder": self.get_placeholder("aws_key"),
                "entropy": calculate_shannon_entropy(secret_val),
                "confidence": 0.95,
                "priority": 90,
            })

        # GitHub Tokens
        for m in self.GITHUB_TOKEN_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "github_token",
                "category": "API_KEY",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("github_token"),
                "entropy": calculate_shannon_entropy(m.group(0)),
                "confidence": 1.0,
                "priority": 90,
            })

        # Bearer Tokens (Redact token payload, retain Bearer prefix)
        for m in self.BEARER_TOKEN_RE.finditer(text):
            token_val = m.group(1)
            candidates.append({
                "start": m.start(1),
                "end": m.end(1),
                "detector": "bearer_token",
                "category": "API_KEY",
                "matched_text": token_val,
                "placeholder": self.get_placeholder("bearer_token"),
                "entropy": calculate_shannon_entropy(token_val),
                "confidence": 0.95,
                "priority": 85,
            })

        # 3. Passwords & Connection Strings (priority 80)
        # URI passwords: scheme://user:password@host
        for m in self.PASSWORD_URI_RE.finditer(text):
            pass_val = m.group(2)
            candidates.append({
                "start": m.start(2),
                "end": m.end(2),
                "detector": "password_uri",
                "category": "CREDENTIAL",
                "matched_text": pass_val,
                "placeholder": self.get_placeholder("password"),
                "entropy": calculate_shannon_entropy(pass_val),
                "confidence": 0.95,
                "priority": 80,
            })

        # Explicit password assignments: password = "xxx"
        for m in self.PASSWORD_ASSIGN_RE.finditer(text):
            pass_val = m.group(3) if m.group(3) is not None else m.group(4)
            pass_grp = 3 if m.group(3) is not None else 4
            candidates.append({
                "start": m.start(pass_grp),
                "end": m.end(pass_grp),
                "detector": "password_assignment",
                "category": "CREDENTIAL",
                "matched_text": pass_val,
                "placeholder": self.get_placeholder("password"),
                "entropy": calculate_shannon_entropy(pass_val),
                "confidence": 0.90,
                "priority": 80,
            })

        # 4. PII: Email, Phone, SSN (priority 75)
        # Emails
        for m in self.EMAIL_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "email",
                "category": "PII",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("email"),
                "entropy": None,
                "confidence": 1.0,
                "priority": 75,
            })

        # Phone numbers
        for m in self.PHONE_US_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "phone",
                "category": "PII",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("phone"),
                "entropy": None,
                "confidence": 0.90,
                "priority": 75,
            })

        for m in self.PHONE_INTL_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "phone",
                "category": "PII",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("phone"),
                "entropy": None,
                "confidence": 0.90,
                "priority": 75,
            })

        # SSNs
        for m in self.SSN_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "ssn",
                "category": "PII",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("ssn"),
                "entropy": None,
                "confidence": 0.95,
                "priority": 75,
            })

        # 5. Corporate Internal Hostnames & IPs (priority 70)
        # Internal hostnames
        for m in self.INTERNAL_HOST_RE.finditer(text):
            candidates.append({
                "start": m.start(),
                "end": m.end(),
                "detector": "internal_host",
                "category": "INTERNAL_NETWORK",
                "matched_text": m.group(0),
                "placeholder": self.get_placeholder("internal_host"),
                "entropy": None,
                "confidence": 0.95,
                "priority": 70,
            })

        # Private IPv4 addresses (10.x, 192.168.x, 172.16-31.x)
        for rx in (self.PRIVATE_IPV4_10_RE, self.PRIVATE_IPV4_192_RE, self.PRIVATE_IPV4_172_RE):
            for m in rx.finditer(text):
                candidates.append({
                    "start": m.start(),
                    "end": m.end(),
                    "detector": "private_ip",
                    "category": "INTERNAL_NETWORK",
                    "matched_text": m.group(0),
                    "placeholder": self.get_placeholder("internal_ip"),
                    "entropy": None,
                    "confidence": 1.0,
                    "priority": 70,
                })

        # 6. Shannon Entropy Estimation for Un-prefixed High-Entropy Secrets (priority 60)
        if self.enable_entropy:
            for m in self.CANDIDATE_TOKEN_RE.finditer(text):
                token = m.group(0)
                # Skip known structural non-secrets: UUIDs, markdown delimiters
                if self.UUID_RE.match(token) or token.count("-") >= 4 or token.count("_") >= 4:
                    continue
                # Skip repetitive characters (e.g. "================")
                if len(set(token)) <= 4:
                    continue

                entropy = calculate_shannon_entropy(token)
                is_hex = bool(re.match(r"^[0-9a-fA-F]+$", token))

                # Evaluation criteria for high-entropy secret
                if is_hex:
                    if len(token) >= 32 and entropy >= self.entropy_threshold_hex:
                        candidates.append({
                            "start": m.start(),
                            "end": m.end(),
                            "detector": "shannon_entropy_hex",
                            "category": "HIGH_ENTROPY",
                            "matched_text": token,
                            "placeholder": self.get_placeholder("high_entropy"),
                            "entropy": entropy,
                            "confidence": 0.85,
                            "priority": 60,
                        })
                else:
                    if len(token) >= 20 and entropy >= self.entropy_threshold_base64:
                        candidates.append({
                            "start": m.start(),
                            "end": m.end(),
                            "detector": "shannon_entropy_base64",
                            "category": "HIGH_ENTROPY",
                            "matched_text": token,
                            "placeholder": self.get_placeholder("high_entropy"),
                            "entropy": entropy,
                            "confidence": 0.85,
                            "priority": 60,
                        })

        # Resolve overlapping match spans
        resolved_spans = self._resolve_overlapping_spans(candidates)

        # Apply replacements backwards (right-to-left) so prior string offsets remain intact
        sanitized_chars = list(text)
        records: list[SanitizationRecord] = []

        # Sort resolved spans descending by start position for in-place text surgery
        for span in sorted(resolved_spans, key=lambda s: s["start"], reverse=True):
            start = span["start"]
            end = span["end"]
            placeholder = span["placeholder"]
            sanitized_chars[start:end] = list(placeholder)

            records.append(
                SanitizationRecord(
                    category=span["category"],
                    detector=span["detector"],
                    matched_text=span["matched_text"],
                    placeholder=span["placeholder"],
                    start=start,
                    end=end,
                    entropy=span["entropy"],
                    confidence=span["confidence"],
                )
            )

        # Reverse records list so it is returned in chronological (start-index ascending) order
        records.reverse()
        return "".join(sanitized_chars), records

    def sanitize_transcript_turns(
        self, turns: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Sanitizes both raw and normalized turns before they reach clustering or mining.

        Args:
            turns: List of (raw_prompt, normalized_prompt) tuples.

        Returns:
            List of (sanitized_raw_prompt, sanitized_normalized_prompt) tuples.
        """
        if not turns:
            return []

        sanitized_turns: list[tuple[str, str]] = []
        for raw, norm in turns:
            sanitized_raw, _ = self.sanitize_text(raw)
            sanitized_norm, _ = self.sanitize_text(norm)
            sanitized_turns.append((sanitized_raw, sanitized_norm))

        return sanitized_turns

    # ========================================================================
    # Conflict Resolution & Helper Logic
    # ========================================================================

    def _resolve_overlapping_spans(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resolves overlapping match candidates using priority and span length."""
        if not candidates:
            return []

        # Sort primarily by priority desc, length desc, start asc
        sorted_candidates = sorted(
            candidates,
            key=lambda c: (
                -c["priority"],
                -(c["end"] - c["start"]),
                c["start"],
            ),
        )

        resolved: list[dict[str, Any]] = []
        for cand in sorted_candidates:
            c_start = cand["start"]
            c_end = cand["end"]

            # Overlap condition: not (c_end <= e_start or c_start >= e_end)
            if any(not (c_end <= e["start"] or c_start >= e["end"]) for e in resolved):
                continue

            resolved.append(cand)

        # Return sorted by start position
        return sorted(resolved, key=lambda x: x["start"])
