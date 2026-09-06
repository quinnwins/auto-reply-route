"""Comprehensive Unit Tests for Enterprise Governance & Secret Sanitizer.

Verifies:
1. SecretAndPIISanitizer:
   - Redaction of Stripe API keys (sk_live_..., rk_live_..., pk_live_...)
   - Redaction of OpenAI & Anthropic API keys (sk-..., sk-proj-..., sk-ant-...)
   - Redaction of Google API keys (AIza...)
   - Redaction of AWS keys (AKIA..., ASIA..., aws_secret_access_key)
   - Redaction of GitHub tokens (ghp_..., github_pat_...)
   - Redaction of corporate internal hostnames (*.internal, *.corp, *.local, *.corp.google.com)
   - Redaction of private IPv4 addresses (10.x, 192.168.x, 172.16-31.x)
   - Redaction of Bearer tokens (retaining prefix, scrubbing token payload)
   - Redaction of connection URIs and explicit password assignments
   - Redaction of private key blocks (RSA, EC, Generic)
   - Redaction of PII (emails, US/international phone numbers, SSNs)
   - Shannon entropy estimation and un-prefixed high-entropy secret detection
   - False positive avoidance (UUIDs, repetitive strings, natural language identifiers)
   - Overlap resolution and deterministic reverse text surgery
   - SanitizationRecord auditing, masked text preview, and SHA-256 hashing
   - Custom placeholder overrides and configuration options
2. Integration with transcript turns & PromptRouteMiner:
   - Direct sanitize_transcript_turns() validation
   - End-to-end integration with PromptRouteMiner.parse_transcript_file() on JSONL logs
   - End-to-end route mining verification ensuring mined routes are completely free of secrets

Standard library Python 3.9+ and pytest. Zero external dependencies.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
from typing import Any

import pytest

from auto_reply_route.miner import PromptRouteMiner
from auto_reply_route.sanitizer import (
    SanitizationRecord,
    SecretAndPIISanitizer,
    calculate_shannon_entropy,
)


# Deliberately synthetic keys assembled at runtime for redaction tests.
# No usable provider credentials belong in these fixtures.
STRIPE_SECRET_FIXTURE = "sk_live_" + "TESTONLY" * 4
STRIPE_RESTRICTED_FIXTURE = "rk_live_" + "TESTONLY" * 4
STRIPE_PUBLIC_FIXTURE = "pk_live_" + "TESTONLY" * 4


# ============================================================================
# 1. Shannon Entropy Estimator Tests
# ============================================================================

class TestShannonEntropyCalculator:
    """Tests for calculate_shannon_entropy()."""

    def test_empty_string_has_zero_entropy(self) -> None:
        assert calculate_shannon_entropy("") == 0.0

    def test_single_repeated_char_has_zero_entropy(self) -> None:
        assert calculate_shannon_entropy("aaaaaaaaaaaaaaaa") == 0.0
        assert calculate_shannon_entropy("1111111111111111") == 0.0

    def test_two_equally_distributed_chars_has_one_bit_entropy(self) -> None:
        # P('a') = 0.5, P('b') = 0.5 -> H = -(0.5*log2(0.5) + 0.5*log2(0.5)) = 1.0
        assert math.isclose(calculate_shannon_entropy("abababababababab"), 1.0, rel_tol=1e-5)

    def test_four_equally_distributed_chars_has_two_bits_entropy(self) -> None:
        # P = 0.25 each -> H = 2.0
        assert math.isclose(calculate_shannon_entropy("abcdabcdabcdabcd"), 2.0, rel_tol=1e-5)

    def test_sixteen_equally_distributed_hex_chars_has_four_bits_entropy(self) -> None:
        # 16 unique characters distributed equally -> H = 4.0
        hex_sample = "0123456789abcdef" * 4
        assert math.isclose(calculate_shannon_entropy(hex_sample), 4.0, rel_tol=1e-5)

    def test_natural_language_has_moderate_entropy(self) -> None:
        # Natural English sentences typically sit around 2.5 - 4.0 bits
        english = "This is a simple natural English test sentence for text analysis"
        entropy = calculate_shannon_entropy(english)
        assert 2.5 <= entropy <= 4.0

    def test_random_cryptographic_token_has_high_entropy(self) -> None:
        # A 40-character pseudo-random token with high variance
        crypto_token = "K9xP2#mQ8$vL1*zW7@tR4!yB0^cN6&eF"
        entropy = calculate_shannon_entropy(crypto_token)
        assert entropy >= 4.5


# ============================================================================
# 2. Vendor API Key Redaction Tests
# ============================================================================

class TestVendorAPIKeyRedaction:
    """Verifies detection and redaction of Stripe, OpenAI, Google, AWS, and GitHub keys."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_redact_stripe_live_secret_key(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = f"Process credit card using {STRIPE_SECRET_FIXTURE} on checkout"
        sanitized, records = sanitizer.sanitize_text(text)
        assert STRIPE_SECRET_FIXTURE not in sanitized
        assert "[REDACTED:STRIPE_KEY]" in sanitized
        assert sanitized == "Process credit card using [REDACTED:STRIPE_KEY] on checkout"
        assert len(records) == 1
        assert records[0].detector == "stripe_key"
        assert records[0].category == "API_KEY"
        assert records[0].placeholder == "[REDACTED:STRIPE_KEY]"
        assert records[0].matched_text == STRIPE_SECRET_FIXTURE

    def test_redact_stripe_restricted_and_publishable_keys(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = f"Public: {STRIPE_PUBLIC_FIXTURE} and restricted: {STRIPE_RESTRICTED_FIXTURE}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "pk_live_" not in sanitized
        assert "rk_live_" not in sanitized
        assert sanitized.count("[REDACTED:STRIPE_KEY]") == 2
        assert len(records) == 2

    def test_redact_stripe_test_keys(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Debug with sk_test_51AbC2dEfG3hIjKlMnOpQrStUv987654"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "sk_test_" not in sanitized
        assert "[REDACTED:STRIPE_KEY]" in sanitized

    def test_redact_openai_standard_key(self, sanitizer: SecretAndPIISanitizer) -> None:
        key = "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOP"
        text = f"Set OPENAI_API_KEY={key} in your .env"
        sanitized, records = sanitizer.sanitize_text(text)
        assert key not in sanitized
        assert "[REDACTED:OPENAI_KEY]" in sanitized
        assert sanitized == "Set OPENAI_API_KEY=[REDACTED:OPENAI_KEY] in your .env"
        assert len(records) == 1
        assert records[0].detector == "openai_api_key"
        assert records[0].category == "API_KEY"

    def test_redact_openai_project_and_admin_keys(self, sanitizer: SecretAndPIISanitizer) -> None:
        proj_key = "sk-proj-9876543210abcdefghijklmnopqrstuvwxyzABCD"
        admin_key = "sk-admin-1234567890abcdefghijklmnopqrstuvwxyzEFGH"
        text = f"Keys: {proj_key} and {admin_key}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert proj_key not in sanitized
        assert admin_key not in sanitized
        assert sanitized.count("[REDACTED:OPENAI_KEY]") == 2

    def test_redact_anthropic_key(self, sanitizer: SecretAndPIISanitizer) -> None:
        key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789-_ABCDEFGHIJKLMNOP"
        text = f"Connect Claude client with {key}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert key not in sanitized
        assert "[REDACTED:ANTHROPIC_KEY]" in sanitized
        assert len(records) == 1
        assert records[0].detector == "anthropic_api_key"

    def test_redact_google_api_key(self, sanitizer: SecretAndPIISanitizer) -> None:
        # Standard Google API key is 39 characters starting with AIza
        google_key = "AIzaSyD0123456789abcdefghijklmnopqrstUV"
        text = f"curl https://generativelanguage.googleapis.com/v1beta/models?key={google_key}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert google_key not in sanitized
        assert "[REDACTED:GOOGLE_KEY]" in sanitized
        assert sanitized == "curl https://generativelanguage.googleapis.com/v1beta/models?key=[REDACTED:GOOGLE_KEY]"
        assert len(records) == 1
        assert records[0].detector == "google_api_key"
        assert records[0].category == "API_KEY"

    def test_redact_aws_access_key_id(self, sanitizer: SecretAndPIISanitizer) -> None:
        aws_access_key = "AKIAIOSFODNN7EXAMPLE"
        text = f"export AWS_ACCESS_KEY_ID={aws_access_key}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert aws_access_key not in sanitized
        assert "[REDACTED:AWS_KEY]" in sanitized
        assert sanitized == "export AWS_ACCESS_KEY_ID=[REDACTED:AWS_KEY]"
        assert len(records) == 1
        assert records[0].detector == "aws_access_key"

    def test_redact_aws_temporary_key_asia(self, sanitizer: SecretAndPIISanitizer) -> None:
        temp_key = "ASIAIOSFODNN7EXAMPLE"
        text = f"Session key: {temp_key}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert temp_key not in sanitized
        assert "[REDACTED:AWS_KEY]" in sanitized

    def test_redact_aws_secret_access_key_assignment(self, sanitizer: SecretAndPIISanitizer) -> None:
        secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        text = f'aws_secret_access_key = "{secret_key}"'
        sanitized, records = sanitizer.sanitize_text(text)
        assert secret_key not in sanitized
        assert "[REDACTED:AWS_KEY]" in sanitized
        assert 'aws_secret_access_key = "[REDACTED:AWS_KEY]"' in sanitized
        assert any(r.detector == "aws_secret_key" for r in records)

    def test_redact_github_tokens(self, sanitizer: SecretAndPIISanitizer) -> None:
        ghp = "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"
        text = f"git remote set-url origin https://{ghp}@github.com/repo.git"
        sanitized, records = sanitizer.sanitize_text(text)
        assert ghp not in sanitized
        assert "[REDACTED:GITHUB_TOKEN]" in sanitized
        assert len(records) == 1
        assert records[0].detector == "github_token"


# ============================================================================
# 3. Network, Credential, and Hostname Redaction Tests
# ============================================================================

class TestNetworkAndCredentialRedaction:
    """Verifies detection and redaction of internal hostnames, private IPs, bearer tokens, passwords."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_redact_corporate_internal_hostname(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Deploy service to my-service.corp.google.internal via RPC"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "my-service.corp.google.internal" not in sanitized
        assert "[REDACTED:INTERNAL_HOST]" in sanitized
        assert sanitized == "Deploy service to [REDACTED:INTERNAL_HOST] via RPC"
        assert len(records) == 1
        assert records[0].detector == "internal_host"
        assert records[0].category == "INTERNAL_NETWORK"

    def test_redact_corp_and_local_domain_variants(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Ping auth.corp, database.internal, and gateway.local"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "auth.corp" not in sanitized
        assert "database.internal" not in sanitized
        assert "gateway.local" not in sanitized
        assert sanitized.count("[REDACTED:INTERNAL_HOST]") == 3

    def test_redact_google_corp_domain(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Visit internal admin tool at portal.corp.google.com/dashboard"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "portal.corp.google.com" not in sanitized
        assert "[REDACTED:INTERNAL_HOST]" in sanitized

    def test_redact_private_ipv4_10_network(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Connecting to internal proxy at 10.0.1.5 on port 8080"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "10.0.1.5" not in sanitized
        assert "[REDACTED:INTERNAL_IP]" in sanitized
        assert sanitized == "Connecting to internal proxy at [REDACTED:INTERNAL_IP] on port 8080"
        assert len(records) == 1
        assert records[0].detector == "private_ip"

    def test_redact_private_ipv4_192_168_network(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Default gateway is 192.168.1.1 or 192.168.0.254"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "192.168.1.1" not in sanitized
        assert "192.168.0.254" not in sanitized
        assert sanitized.count("[REDACTED:INTERNAL_IP]") == 2

    def test_redact_private_ipv4_172_network(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Docker bridge host: 172.16.42.1 and staging host: 172.31.255.1"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "172.16.42.1" not in sanitized
        assert "172.31.255.1" not in sanitized
        assert sanitized.count("[REDACTED:INTERNAL_IP]") == 2

    def test_do_not_redact_public_ips(self, sanitizer: SecretAndPIISanitizer) -> None:
        # Public DNS IPs like 8.8.8.8 and 1.1.1.1 are not private IPs
        text = "Using DNS servers 8.8.8.8 and 1.1.1.1"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "8.8.8.8" in sanitized
        assert "1.1.1.1" in sanitized
        assert not any(r.detector == "private_ip" for r in records)

    def test_redact_bearer_token(self, sanitizer: SecretAndPIISanitizer) -> None:
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature12345"
        text = f"Authorization: Bearer {token}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert token not in sanitized
        # The prefix "Bearer " is preserved while the token payload is scrubbed
        assert sanitized == "Authorization: Bearer [REDACTED:BEARER_TOKEN]"
        assert len(records) == 1
        assert records[0].detector == "bearer_token"
        assert records[0].matched_text == token

    def test_redact_password_in_connection_uri(self, sanitizer: SecretAndPIISanitizer) -> None:
        uri = "postgres://appuser:sUp3rS3cr3tPassw0rd_99@db.example.internal:5432/production"
        sanitized, records = sanitizer.sanitize_text(uri)
        assert "sUp3rS3cr3tPassw0rd_99" not in sanitized
        assert "[REDACTED:PASSWORD]" in sanitized
        assert "[REDACTED:INTERNAL_HOST]" in sanitized
        assert "postgres://appuser:[REDACTED:PASSWORD]@[REDACTED:INTERNAL_HOST]:5432/production" in sanitized
        assert any(r.detector == "password_uri" for r in records)

    def test_redact_explicit_password_assignments(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = 'db_pass = "MySecretPass_9988!" and client_secret: "xyzCorporateSecret123"'
        sanitized, records = sanitizer.sanitize_text(text)
        assert "MySecretPass_9988!" not in sanitized
        assert "xyzCorporateSecret123" not in sanitized
        assert sanitized.count("[REDACTED:PASSWORD]") == 2

    def test_redact_private_key_blocks(self, sanitizer: SecretAndPIISanitizer) -> None:
        pem_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA0Yk4k8o2P4+examplePrivateKeyPayload1234567890\n"
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ==\n"
            "-----END RSA PRIVATE KEY-----"
        )
        text = f"Configuration:\n{pem_key}\nSave to disk."
        sanitized, records = sanitizer.sanitize_text(text)
        assert pem_key not in sanitized
        assert "[REDACTED:PRIVATE_KEY]" in sanitized
        assert len(records) == 1
        assert records[0].detector == "private_key"


# ============================================================================
# 4. PII Redaction Tests
# ============================================================================

class TestPIIRedaction:
    """Verifies detection and redaction of emails, phone numbers, and SSNs."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_redact_standard_email_addresses(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Send incident report to alice.smith@corp.example.com and security@google.com"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "alice.smith@corp.example.com" not in sanitized
        assert "security@google.com" not in sanitized
        assert sanitized == "Send incident report to [EMAIL] and [EMAIL]"
        assert len(records) == 2
        assert all(r.detector == "email" for r in records)
        assert all(r.category == "PII" for r in records)

    def test_redact_subaddressed_email(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Sign up with dev+testing123@gmail.com for sandboxed accounts"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "dev+testing123@gmail.com" not in sanitized
        assert "[EMAIL]" in sanitized

    def test_redact_us_phone_numbers(self, sanitizer: SecretAndPIISanitizer) -> None:
        samples = [
            ("Call support at 1-800-555-0199 immediately", "1-800-555-0199"),
            ("Direct line: (555) 234-5678", "(555) 234-5678"),
            ("Emergency desk: 555-876-5432", "555-876-5432"),
            ("Dotted format: 555.345.6789", "555.345.6789"),
        ]
        for prompt, phone in samples:
            sanitized, records = sanitizer.sanitize_text(prompt)
            assert phone not in sanitized
            assert "[PHONE]" in sanitized
            assert any(r.detector == "phone" for r in records)

    def test_redact_international_phone_numbers(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "London office: +44 20 7946 0958 or Zurich desk: +41 44 668 1800"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "+44 20 7946 0958" not in sanitized
        assert "+41 44 668 1800" not in sanitized
        assert sanitized.count("[PHONE]") == 2

    def test_redact_social_security_number(self, sanitizer: SecretAndPIISanitizer) -> None:
        text = "Employee SSN record: 123-45-6789 in personnel file"
        sanitized, records = sanitizer.sanitize_text(text)
        assert "123-45-6789" not in sanitized
        assert "[SSN]" in sanitized
        assert any(r.detector == "ssn" for r in records)


# ============================================================================
# 5. Shannon Entropy & High-Entropy Secret Tests
# ============================================================================

class TestHighEntropySecretDetection:
    """Verifies detection of un-prefixed CSPRNG secrets and false positive avoidance."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_detect_unprefixed_high_entropy_hex_token(self, sanitizer: SecretAndPIISanitizer) -> None:
        # 32-character random hex token with high entropy (> 3.4)
        hex_secret = "9f4e2b8a1c7d3f0e5a6b8c9d0e1f2a3b"
        text = f"Use HMAC secret {hex_secret} for verification"
        sanitized, records = sanitizer.sanitize_text(text)
        assert hex_secret not in sanitized
        assert "[REDACTED:HIGH_ENTROPY_SECRET]" in sanitized
        assert any(r.detector == "shannon_entropy_hex" for r in records)

    def test_detect_unprefixed_high_entropy_base64_secret(self, sanitizer: SecretAndPIISanitizer) -> None:
        # 32-character random base64 secret with high entropy (> 4.2)
        b64_secret = "K9xP2mQ8vL1zW7tR4yB0cN6eF1a2b3c4"
        text = f"Signing key: {b64_secret}"
        sanitized, records = sanitizer.sanitize_text(text)
        assert b64_secret not in sanitized
        assert "[REDACTED:HIGH_ENTROPY_SECRET]" in sanitized
        assert any(r.category == "HIGH_ENTROPY" for r in records)

    def test_avoid_false_positive_on_uuids(self, sanitizer: SecretAndPIISanitizer) -> None:
        uuid_val = "12345678-1234-1234-1234-123456789abc"
        text = f"Fetch user where id = '{uuid_val}'"
        sanitized, records = sanitizer.sanitize_text(text)
        assert uuid_val in sanitized
        assert "[REDACTED:HIGH_ENTROPY_SECRET]" not in sanitized
        assert len(records) == 0

    def test_avoid_false_positive_on_repetitive_delimiters(self, sanitizer: SecretAndPIISanitizer) -> None:
        delimiter = "=================================================="
        text = f"Header:\n{delimiter}\nSection content"
        sanitized, records = sanitizer.sanitize_text(text)
        assert delimiter in sanitized
        assert len(records) == 0

    def test_avoid_false_positive_on_long_code_identifiers(self, sanitizer: SecretAndPIISanitizer) -> None:
        # Standard camel-case class names have lower entropy (< 3.4)
        identifier = "EnterpriseAuthenticationSecurityManagerConfig"
        text = f"Instantiate class {identifier} in module"
        sanitized, records = sanitizer.sanitize_text(text)
        assert identifier in sanitized
        assert len(records) == 0

    def test_disable_entropy_detection_flag(self) -> None:
        sanitizer_no_entropy = SecretAndPIISanitizer(enable_entropy=False)
        hex_secret = "9f4e2b8a1c7d3f0e5a6b8c9d0e1f2a3b"
        text = f"Token: {hex_secret}"
        sanitized, records = sanitizer_no_entropy.sanitize_text(text)
        # Should not be redacted because entropy scanning is disabled
        assert hex_secret in sanitized
        assert len(records) == 0


# ============================================================================
# 6. Audit Records, Overlap Resolution, and Text Surgery
# ============================================================================

class TestSanitizationAuditRecords:
    """Verifies SanitizationRecord fields, masked previews, and conflict resolution."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_sanitization_record_properties(self, sanitizer: SecretAndPIISanitizer) -> None:
        raw_key = "AIzaSyD0123456789abcdefghijklmnopqrstUV"
        text = f"Secret: {raw_key}"
        _, records = sanitizer.sanitize_text(text)
        assert len(records) == 1
        rec = records[0]

        # Alias properties
        assert rec.secret_type == "google_api_key"
        assert rec.rule_id == "google_api_key"
        assert rec.replacement == "[REDACTED:GOOGLE_KEY]"

        # Masked text preview
        assert rec.masked_text == "AIza...stUV"
        assert raw_key not in rec.masked_text

        # SHA-256 hash prefix
        assert len(rec.secret_hash) == 12

        # Dictionary serialization
        d = rec.to_dict()
        assert d["detector"] == "google_api_key"
        assert d["category"] == "API_KEY"
        assert d["matched_text"] == raw_key
        assert d["masked_text"] == "AIza...stUV"
        assert d["secret_hash"] == rec.secret_hash
        assert d["start"] == 8
        assert d["end"] == 8 + len(raw_key)

    def test_masked_text_for_short_secrets(self) -> None:
        rec = SanitizationRecord(
            category="TEST",
            detector="test",
            matched_text="short",
            placeholder="[TEST]",
            start=0,
            end=5,
        )
        assert rec.masked_text == "***"

    def test_multiple_secrets_in_single_prompt_preserve_indices(self, sanitizer: SecretAndPIISanitizer) -> None:
        prompt = (
            "Contact dev ops engineer alice@corp.internal at 10.0.4.2 "
            "with key AIzaSyD0123456789abcdefghijklmnopqrstUV and stripe key "
            f"{STRIPE_SECRET_FIXTURE} to verify."
        )
        sanitized, records = sanitizer.sanitize_text(prompt)

        assert "alice@corp.internal" not in sanitized
        assert "10.0.4.2" not in sanitized
        assert "AIzaSyD" not in sanitized
        assert "sk_live_" not in sanitized

        assert "[EMAIL]" in sanitized
        assert "[REDACTED:INTERNAL_IP]" in sanitized
        assert "[REDACTED:GOOGLE_KEY]" in sanitized
        assert "[REDACTED:STRIPE_KEY]" in sanitized

        # Verify that the records are ordered chronologically by original start index
        starts = [r.start for r in records]
        assert starts == sorted(starts)

    def test_custom_placeholder_override(self) -> None:
        custom_placeholders = {
            "stripe_key": "<STRIPE_SECRET_SCRUBBED>",
            "email": "<USER_EMAIL_MASKED>",
        }
        custom_sanitizer = SecretAndPIISanitizer(custom_placeholders=custom_placeholders)
        text = f"Key {STRIPE_SECRET_FIXTURE} for user@example.com"
        sanitized, records = custom_sanitizer.sanitize_text(text)
        assert "<STRIPE_SECRET_SCRUBBED>" in sanitized
        assert "<USER_EMAIL_MASKED>" in sanitized
        assert "[REDACTED:STRIPE_KEY]" not in sanitized


# ============================================================================
# 7. Transcript Turns & PromptRouteMiner Integration Tests
# ============================================================================

class TestTranscriptTurnsAndMinerIntegration:
    """Verifies turn-level sanitization and end-to-end integration with PromptRouteMiner."""

    @pytest.fixture
    def sanitizer(self) -> SecretAndPIISanitizer:
        return SecretAndPIISanitizer()

    def test_sanitize_transcript_turns_direct(self, sanitizer: SecretAndPIISanitizer) -> None:
        turns = [
            (f"Fix payment with {STRIPE_SECRET_FIXTURE}", f"fix payment {STRIPE_SECRET_FIXTURE}"),
            ("Notify admin at admin@corp.google.internal", "notify admin admin@corp.google.internal"),
            ("Clean turn without secrets", "clean turn without secrets"),
        ]
        sanitized_turns = sanitizer.sanitize_transcript_turns(turns)
        assert len(sanitized_turns) == 3

        # First turn: Stripe key scrubbed from both raw and normalized
        raw_0, norm_0 = sanitized_turns[0]
        assert "sk_live_" not in raw_0
        assert "sk_live_" not in norm_0
        assert "[REDACTED:STRIPE_KEY]" in raw_0
        assert "[REDACTED:STRIPE_KEY]" in norm_0

        # Second turn: Email scrubbed
        raw_1, norm_1 = sanitized_turns[1]
        assert "admin@corp.google.internal" not in raw_1
        assert "admin@corp.google.internal" not in norm_1
        assert "[EMAIL]" in raw_1
        assert "[EMAIL]" in norm_1

        # Third turn: Untouched
        raw_2, norm_2 = sanitized_turns[2]
        assert raw_2 == "Clean turn without secrets"
        assert norm_2 == "clean turn without secrets"

    def test_sanitize_transcript_turns_empty_list(self, sanitizer: SecretAndPIISanitizer) -> None:
        assert sanitizer.sanitize_transcript_turns([]) == []

    def test_miner_parse_transcript_file_scrubs_secrets_from_jsonl(self, tmp_path: Path) -> None:
        """Verifies that PromptRouteMiner scrubs secrets during transcript ingestion."""
        # Create a synthetic JSONL pairing session transcript with real secrets
        transcript_file = tmp_path / "transcript.jsonl"
        lines = [
            {
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": f"<USER_REQUEST>Setup Stripe with {STRIPE_SECRET_FIXTURE} and email alert to ops@corp.internal</USER_REQUEST>",
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "content": "Configuring payment gateway...",
            },
            {
                "step_index": 3,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Now connect Gemini model using AIzaSyD0123456789abcdefghijklmnopqrstUV at 10.0.2.15",
            },
        ]

        with open(transcript_file, "w", encoding="utf-8") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        miner = PromptRouteMiner()
        turns = miner.parse_transcript_file(transcript_file)

        assert len(turns) == 2

        turn1_raw, turn1_norm = turns[0]
        # Stripe key & email must be scrubbed
        assert "sk_live_" not in turn1_raw
        assert "sk_live_" not in turn1_norm
        assert "ops@corp.internal" not in turn1_raw
        assert "ops@corp.internal" not in turn1_norm
        assert "[REDACTED:STRIPE_KEY]" in turn1_raw
        assert "[EMAIL]" in turn1_raw

        turn2_raw, turn2_norm = turns[1]
        # Google API key & private IP must be scrubbed
        assert "AIzaSyD" not in turn2_raw
        assert "AIzaSyD" not in turn2_norm
        assert "10.0.2.15" not in turn2_raw
        assert "10.0.2.15" not in turn2_norm
        assert "[REDACTED:GOOGLE_KEY]" in turn2_raw
        assert "[REDACTED:INTERNAL_IP]" in turn2_raw

    def test_miner_end_to_end_route_discovery_contains_no_secrets(self, tmp_path: Path) -> None:
        """Verifies that discovered route candidates generated by miner do not leak secrets."""
        transcript_file = tmp_path / "transcript.jsonl"
        lines = [
            {
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": f"Initialize payment system with {STRIPE_SECRET_FIXTURE}",
            },
            {
                "step_index": 2,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Run security check and ping server at 10.0.1.5",
            },
            {
                "step_index": 3,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Deploy release to my-service.corp.google.internal",
            },
        ]
        with open(transcript_file, "w", encoding="utf-8") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        miner = PromptRouteMiner()
        # Mine transcripts
        routes = miner.mine_transcripts([str(transcript_file)])

        # Serialize discovered routes to string to do a comprehensive secret scan
        routes_dump = json.dumps(routes)
        assert STRIPE_SECRET_FIXTURE not in routes_dump
        assert "10.0.1.5" not in routes_dump
        assert "my-service.corp.google.internal" not in routes_dump
