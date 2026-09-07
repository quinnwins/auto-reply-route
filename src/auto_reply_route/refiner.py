"""Gemini Route Refiner: Fast 300 TPS Speculative Review & Surgical Patch Engine.

==============================================================================
Architectural Invariant & Coworker Design Standard:
==============================================================================
1. The Two-Pass Hybrid Model:
   - Pass 1 (Deterministic Matrix): Generates a mathematically sound 6-phase
     engineering backbone in 1.01ms with zero network calls and strict schema validity.
   - Pass 2 (Gemini 3.8 Flash Refiner): Performs a sub-second alignment review
     at ~300 TPS to catch domain-specific jargon or cross-domain nuances (e.g.
     Solana + Discord bot) that a pure BM25 index might generalize.

2. Strict Fail-Open Safety:
   - If the refiner times out (> 1.5s), receives invalid JSON, or runs offline,
     it immediately returns the Pass 1 manifest completely unharmed.
   - Route generation NEVER crashes and NEVER blocks the developer.

3. Zero Network API Calls in Testing:
   - All tests run against offline mock/stub backends with deterministic sub-millisecond execution.
==============================================================================
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Optional, Protocol

from auto_reply_route.models import RouteManifest, RouteStep, StepStatus

logger = logging.getLogger(__name__)


class GeminiBackendProtocol(Protocol):
    """Protocol for Gemini Flash review backend (production agy CLI or offline mock)."""

    def generate_review(
        self,
        prompt: str,
        route_summary: str,
        timeout_s: float = 1.5,
    ) -> Optional[str]:
        ...


class MockGeminiBackend:
    """Deterministic offline backend for testing with ZERO external network API calls."""

    def __init__(
        self,
        canned_response: Optional[str] = None,
        simulate_timeout: bool = False,
        simulate_malformed: bool = False,
    ):
        self.canned_response = canned_response
        self.simulate_timeout = simulate_timeout
        self.simulate_malformed = simulate_malformed
        self.calls_count = 0

    def generate_review(
        self,
        prompt: str,
        route_summary: str,
        timeout_s: float = 1.5,
    ) -> Optional[str]:
        self.calls_count += 1
        if self.simulate_timeout:
            time.sleep(min(timeout_s + 0.1, 0.05))
            return None

        if self.simulate_malformed:
            return "NOT_JSON: Sorry, as an AI model I cannot do that."

        if self.canned_response is not None:
            return self.canned_response

        # Default intelligent mock behavior:
        # If prompt contains "solana" or "discord", patch step 1
        p_lower = prompt.lower()
        if "solana" in p_lower or "discord" in p_lower:
            return json.dumps({
                "status": "PATCH",
                "reason": "Tailored generic webhook to Solana RPC monitor and Discord bot integration",
                "patches": [
                    {
                        "step_index": 1,
                        "field": "title",
                        "replacement": "Principal Architect Build: Solana RPC & Discord Bot",
                    },
                    {
                        "step_index": 1,
                        "field": "primary_prompt",
                        "replacement": (
                            "Implement Solana RPC block validator monitor and Discord webhook notifier in validator_monitor.go. "
                            "Ensure fail-closed RPC reconnection and strict typing."
                        ),
                    }
                ]
            })

        # Otherwise PASS
        return json.dumps({"status": "PASS", "reason": "Route trajectory perfectly matches prompt requirements."})


class AgyCliBackend:
    """Production backend that leverages the user's active Gemini subscription via the agy CLI."""

    def __init__(self, agy_binary: Optional[str] = None):
        self.agy_path = agy_binary or shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")

    def is_available(self) -> bool:
        return Path(self.agy_path).exists() and os.access(self.agy_path, os.X_OK)

    def generate_review(
        self,
        prompt: str,
        route_summary: str,
        timeout_s: float = 1.5,
    ) -> Optional[str]:
        if not self.is_available():
            return None

        system_instruction = (
            "You are Gemini 3.8 Flash performing a fast, 1-second route alignment check.\n"
            "Analyze if the 6-step route matches the user's prompt.\n"
            "If it matches, return JSON: {\"status\": \"PASS\"}\n"
            "If there is domain mismatch or missing specific technology (e.g. Solana, Discord), return JSON:\n"
            "{\"status\": \"PATCH\", \"patches\": [{\"step_index\": 1, \"field\": \"primary_prompt\", \"replacement\": \"...\"}]}\n"
            "Return valid JSON only. No markdown fences."
        )

        full_prompt = (
            f"{system_instruction}\n\n"
            f"User Request: {prompt}\n\n"
            f"Proposed Route Summary:\n{route_summary}\n\n"
            "Respond strictly with valid JSON only."
        )

        try:
            cmd = [
                self.agy_path,
                "-p", full_prompt,
                "--model", "gemini-3.8-flash-low",
                "--effort", "low",
                "--disable-slash-commands",
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception) as exc:
            logger.debug("AgyCliBackend review timed out or failed: %s", exc)

        return None


class GeminiRouteRefiner:
    """Fast speculative route refiner running with strict 1.5s fail-open safety."""

    def __init__(self, backend: Optional[GeminiBackendProtocol] = None):
        self.backend = backend or AgyCliBackend()

    def refine_manifest(
        self,
        seed_prompt: str,
        manifest: RouteManifest,
        timeout_s: float = 1.5,
    ) -> RouteManifest:
        """Evaluates candidate manifest against seed prompt and applies surgical patches if needed."""
        t0 = time.perf_counter()
        max_subagents = manifest.metadata.get("max_subagents", 3)
        from auto_reply_route.prompt_matrix import MatrixBeamRouter
        team_directive = MatrixBeamRouter.format_subagent_directive(max_subagents)

        # 1. Build concise route summary (minimal tokens to keep Flash latency under 500ms)
        summary_lines = []
        for idx, step in enumerate(manifest.steps, start=1):
            summary_lines.append(f"Step {idx}: {step.title} | {step.primary_prompt[:120]}")
        route_summary = "\n".join(summary_lines)

        # 2. Query backend
        raw_response = None
        try:
            raw_response = self.backend.generate_review(
                prompt=seed_prompt,
                route_summary=route_summary,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            logger.debug("Refiner backend error: %s", exc)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        manifest.metadata["refiner_latency_ms"] = round(elapsed_ms, 2)

        # 3. Fail-Open Check: if no response or timeout, return unmodified manifest
        if not raw_response:
            manifest.metadata["refiner_verdict"] = "FAIL_OPEN_UNMODIFIED"
            return manifest

        # 4. Parse JSON using raw_decode to ignore any environment hook reminders or trailing output
        try:
            start_idx = raw_response.find("{")
            if start_idx == -1:
                manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
                return manifest
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(raw_response[start_idx:])
            if not isinstance(data, dict):
                manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
                return manifest
        except Exception:
            manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
            return manifest

        raw_status = data.get("status", "PASS")
        if not isinstance(raw_status, str):
            manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
            return manifest

        verdict = raw_status.upper()

        if verdict != "PATCH":
            manifest.metadata["refiner_verdict"] = "PASS_APPROVED"
            return manifest

        # 5. Apply Surgical Patches
        raw_patches = data.get("patches", [])
        if not isinstance(raw_patches, list) or not all(isinstance(p, dict) for p in raw_patches):
            manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
            return manifest

        # Snapshot steps to guarantee zero corruption if an unexpected error occurs during patching
        steps_snapshot = copy.deepcopy(manifest.steps)

        try:
            applied_count = 0
            for patch in raw_patches:
                raw_step_idx = patch.get("step_index")
                try:
                    step_idx = int(raw_step_idx) if raw_step_idx is not None else None
                except (ValueError, TypeError):
                    continue

                field = patch.get("field")
                replacement = str(patch.get("replacement", "")).strip()

                if not step_idx or not replacement:
                    continue

                if 1 <= step_idx <= len(manifest.steps):
                    target_step = manifest.steps[step_idx - 1]

                    if field == "title":
                        target_step.title = replacement
                        applied_count += 1
                    elif field == "primary_prompt":
                        if team_directive and team_directive not in replacement:
                            replacement = f"{replacement.rstrip('.')}. {team_directive}"
                        target_step.primary_prompt = replacement
                        if target_step.alternatives and int(target_step.alternatives[0].rank) == 1:
                            target_step.alternatives[0].prompt_template = replacement
                        applied_count += 1

            manifest.metadata["refiner_verdict"] = f"PATCHED_{applied_count}_CHANGES"
            manifest.metadata["refiner_reason"] = str(data.get("reason", "") or "")
            return manifest
        except Exception as exc:
            logger.debug("Refiner patching failed, reverting to unmodified manifest: %s", exc)
            manifest.steps = steps_snapshot
            manifest.metadata["refiner_verdict"] = "FAIL_OPEN_INVALID_JSON"
            return manifest
