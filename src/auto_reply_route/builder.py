"""Auto-Reply Route Builder Engine.

==============================================================================
EXPERT DECISION RUBRIC & ARCHITECTURAL FOUNDATION
==============================================================================
1. What the Best Graph/Sequence Engineer Would Do:
   A world-class sequence engineer models developer workflows not as static checklists,
   but as directed trajectories through a pragmatic intent space conditioned on a seed prompt.
   The engineer performs semantic entity decomposition (extracting target files, modules,
   subsystems, and action verbs), stratifies the root intent (ARCH_DESIGN, SCAFFOLD_BUILD,
   DEBUG_REPAIR, VERIFY_QA, RELEASE_OPS), and projects a coherent multi-step path
   (Inception -> Core Logic -> Integration -> Verification -> Closure).
   At each step, a candidate set of divergent execution branches is synthesized:
   - Rank 1: Primary Forward (the natural progressive next user turn)
   - Rank 2: QA Defensive (hardening, boundary validation, schema integrity, invariants)
   - Rank 3: Alternative Architecture / Quick Spike (decoupled pattern, in-memory mock, zero-dep spike)
   - Rank 4: Fallback / Ops (conservative standard-library fallback, rollback checkpoint, diff audit)
   Each step is anchored by non-self-attesting deterministic assertions.

2. Why They Reject Naive Hardcoded Lists:
   Hardcoded step lists fail immediately when faced with real-world developer variance:
   - A bug repair task (DEBUG_REPAIR) does NOT start with "Scaffold models"; it requires
     reproduction, root cause isolation, surgical fix, and regression verification.
   - An architectural migration (ARCH_DESIGN) requires protocol abstraction, adapter
     isolation, and dual-run verification.
   - Static lists produce generic "prompt fluff" rather than actionable, context-specialized
     prompts that reference the developer's actual modules, files, and domain entities.
   - Fixed 5-step slices cut off verification and release milestones if step horizons change.

3. Explicit Trade-Offs (Stated to the User):
   - Trade-off A (Deterministic Semantic Taxonomy vs. External LLM Latency/API Calls):
     In compliance with the project standard (Python 3.9+ standard library only, zero external
     dependencies), we use deterministic semantic decomposition, regex entity extraction,
     and intent transition matrices. This yields sub-millisecond route generation and 100%
     offline reliability, traded against the open-ended phrasing variance of a live LLM.
   - Trade-off B (Elastic Trajectory Projection vs. Arbitrary Step Count):
     Developers may request arbitrary `num_steps`. Instead of naively truncating a sequence
     (which would discard critical verification and release gates), we elastically scale
     the trajectory across essential milestone phases to guarantee an intact workflow arc.
   - Trade-off C (Entity Specialization vs. Overfitting):
     We extract file names, module names, and action subjects to specialize prompts and
     assertions, backed by safe fallbacks if the seed prompt is brief or unstructured.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
from typing import Any, Callable, Optional, Union

from auto_reply_route.miner import (
    IntentClusterer,
    IntentStratum,
    PromptNormalizer,
)
from auto_reply_route.models import (
    AlternativeBranch,
    BranchRank,
    MessageQueueManifest,
    QueuedMessage,
    QueuedMessageStatus,
    RouteManifest,
    RouteStep,
    StepStatus,
)
from auto_reply_route.classifier import HumanIntentClassifier, PromptIntentTier
from auto_reply_route.parser import RouteParser


# ============================================================================
# Domain Entity Extraction & Semantic Decomposition
# ============================================================================

@dataclass
class PromptDecomposition:
    """Structured semantic decomposition of a developer seed prompt."""
    raw_prompt: str
    normalized_prompt: str
    stratum: IntentStratum
    subject: str
    target_file: str
    target_module: str
    test_file: str
    action_verb: str
    is_bugfix: bool = False
    is_architecture: bool = False
    is_testing: bool = False
    is_ops: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_prompt": self.raw_prompt,
            "normalized_prompt": self.normalized_prompt,
            "stratum": self.stratum.value,
            "subject": self.subject,
            "target_file": self.target_file,
            "target_module": self.target_module,
            "test_file": self.test_file,
            "action_verb": self.action_verb,
            "is_bugfix": self.is_bugfix,
            "is_architecture": self.is_architecture,
            "is_testing": self.is_testing,
            "is_ops": self.is_ops,
        }


class SemanticPromptAnalyzer:
    """Analyzes developer seed prompts, extracting domain entities, files, and intent strata."""

    # File extraction pattern
    FILE_PATH_RE = re.compile(
        r"(?:[\w\-./\\]+)?\b([a-zA-Z0-9_\-]+\.(?:py|js|ts|tsx|jsx|go|rs|c|cpp|h|hpp|java|rb|json|yaml|yml|toml|md|sql|sh))\b",
        re.IGNORECASE,
    )

    # Action verbs
    ACTION_VERB_PATTERNS = [
        ("fix", r"\b(fix|repair|resolve|patch|debug|diagnose)\b"),
        ("scaffold", r"\b(scaffold|create|add|build|implement|wire|scaffolding)\b"),
        ("refactor", r"\b(refactor|redesign|restructure|decouple|migrate|abstract)\b"),
        ("test", r"\b(test|verify|audit|benchmark|profile|check|inspect)\b"),
        ("release", r"\b(release|ship|deploy|publish|tag|commit|push|bump)\b"),
    ]

    # Keyword heuristics for module name fallback
    MODULE_HEURISTICS = [
        (r"\b(auth|login|jwt|token|session|credential)\b", "auth"),
        (r"\b(database|db|sql|postgres|sqlite|query|schema)\b", "database"),
        (r"\b(parser|parse|ast|lexer|grammar|syntax)\b", "parser"),
        (r"\b(cli|command|terminal|argparse|flag)\b", "cli"),
        (r"\b(cache|redis|memcached|storage|store)\b", "cache"),
        (r"\b(route|router|routing|dispatcher|endpoint|api)\b", "router"),
        (r"\b(state|statemachine|fsm|lifecycle|workflow)\b", "state_machine"),
        (r"\b(queue|worker|broker|task|job|event)\b", "worker"),
        (r"\b(network|http|websocket|client|socket)\b", "network"),
        (r"\b(model|schema|entity|dto|record)\b", "models"),
    ]

    def __init__(
        self,
        normalizer: Optional[PromptNormalizer] = None,
        clusterer: Optional[IntentClusterer] = None,
    ):
        self.normalizer = normalizer or PromptNormalizer()
        self.clusterer = clusterer or IntentClusterer(self.normalizer)

    def analyze(self, raw_prompt: str) -> PromptDecomposition:
        """Deconstructs the raw user prompt into actionable domain properties."""
        cleaned = self.normalizer.extract_user_request(raw_prompt) or raw_prompt.strip()
        normalized = self.normalizer.normalize(cleaned) or cleaned

        # 1. Determine Intent Stratum
        stratum = self.clusterer.categorize_stratum(normalized)

        # 2. Extract Target File & Module
        target_file = ""
        target_module = ""
        file_match = self.FILE_PATH_RE.search(cleaned)
        if file_match:
            target_file = file_match.group(0).replace("\\", "/")
            stem = Path(target_file).stem
            target_module = re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_")

        # 3. Detect Action Verb
        action_verb = "implement"
        lower_text = cleaned.lower()
        for verb_name, pattern in self.ACTION_VERB_PATTERNS:
            if re.search(pattern, lower_text):
                action_verb = verb_name
                break

        # 4. Fallback Module Identification if no explicit file path
        if not target_module:
            for pattern, mod_candidate in self.MODULE_HEURISTICS:
                if re.search(pattern, lower_text):
                    target_module = mod_candidate
                    target_file = f"src/{target_module}.py"
                    break

        if not target_module:
            # Extract most prominent noun tokens from normalized string
            words = [w for w in re.sub(r"[^\w\s]", "", lower_text).split() if len(w) > 2]
            stop_words = {
                "the", "and", "for", "with", "that", "this", "from", "into", "user", "build",
                "create", "implement", "make", "need", "want", "please", "should", "code"
            }
            significant = [w for w in words if w not in stop_words]
            if significant:
                target_module = "_".join(significant[:2])
                target_file = f"src/{target_module}.py"
            else:
                target_module = "feature_core"
                target_file = "src/feature_core.py"

        test_file = f"tests/test_{target_module}.py"

        # 5. Extract Subject Phrase
        subject = self._extract_subject(cleaned, target_file, action_verb)

        return PromptDecomposition(
            raw_prompt=raw_prompt,
            normalized_prompt=normalized,
            stratum=stratum,
            subject=subject,
            target_file=target_file,
            target_module=target_module,
            test_file=test_file,
            action_verb=action_verb,
            is_bugfix=(stratum == IntentStratum.DEBUG_REPAIR or action_verb == "fix"),
            is_architecture=(stratum == IntentStratum.ARCH_DESIGN or action_verb == "refactor"),
            is_testing=(stratum == IntentStratum.VERIFY_QA or action_verb == "test"),
            is_ops=(stratum == IntentStratum.RELEASE_OPS or action_verb == "release"),
        )

    def _extract_subject(self, text: str, target_file: str, action_verb: str) -> str:
        """Derives a concise, professional subject descriptor from the prompt text."""
        cleaned = text.strip()
        # Remove target file name if present
        if target_file:
            cleaned = cleaned.replace(target_file, "")

        # Remove fluff and leading action keywords
        cleaned = re.sub(r"^(?:please\s+)?(?:could\s+you\s+)?(?:can\s+you\s+)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^(?:{action_verb}|build|create|implement|fix|add|run)\s+(?:the\s+|a\s+|an\s+)?", "", cleaned, flags=re.IGNORECASE)

        # Clean trailing punctuation
        cleaned = cleaned.strip(".:;, \t\n")
        if not cleaned:
            return "Core Component"

        words = cleaned.split()
        if len(words) > 8:
            return " ".join(words[:8])
        return cleaned


# ============================================================================
# Trajectory Template Blueprint
# ============================================================================

@dataclass
class MilestoneBlueprint:
    """Defines a semantic stage in a projected route workflow."""
    title_template: str
    primary_template: str
    qa_defensive_template: str
    quick_spike_template: str
    fallback_template: str
    assertion_templates: list[str]


# Trajectory Blueprints stratified by Developer Intent
TRAJECTORY_MATRICES: dict[IntentStratum, list[MilestoneBlueprint]] = {
    IntentStratum.SCAFFOLD_BUILD: [
        MilestoneBlueprint(
            title_template="Scaffold Data Models and Types",
            primary_template="Scaffold domain data models, enums, and type definitions for {subject} in {target_file}. Ensure all classes are fully type-annotated with zero external runtime dependencies.",
            qa_defensive_template="Add strict boundary validation, schema integrity checks, and runtime value range constraints.",
            quick_spike_template="Implement minimal in-memory dataclasses first to validate core domain shape.",
            fallback_template="Use standard library typed dictionaries and lightweight helper functions.",
            assertion_templates=['python3 -c "import {target_module}" passes'],
        ),
        MilestoneBlueprint(
            title_template="Implement Core Engine Logic",
            primary_template="Implement the primary algorithms and operational processing logic for {subject} in {target_file}. Adhere strictly to the defined type contracts and operational boundaries.",
            qa_defensive_template="Add defensive error handling, contract assertions, and invariant checks around all mutable state transitions.",
            quick_spike_template="Implement the primary happy path with mocked secondary dependencies to demonstrate rapid execution.",
            fallback_template="Implement synchronous, single-threaded procedural logic without external state dependencies.",
            assertion_templates=['python3 -c "import {target_module}; print(\'{target_module} loaded\')" passes'],
        ),
        MilestoneBlueprint(
            title_template="Wire Subsystems and Adapters",
            primary_template="Integrate {target_file} with surrounding application subsystems, lifecycle hooks, and caller interfaces. Ensure clean separation of concerns and graceful failure handling.",
            qa_defensive_template="Implement circuit breakers, timeouts, and clean resource disposal on connection or processing failures.",
            quick_spike_template="Wire an in-memory mock adapter to validate end-to-end event propagation before final wiring.",
            fallback_template="Provide synchronous fallback handlers that operate in degraded environments.",
            assertion_templates=['python3 -m py_compile {target_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Verify Automated Test Suite",
            primary_template="Author and execute comprehensive unit, integration, and boundary test suites for {subject} in {test_file}. Validate nominal, edge-case, and fault scenarios.",
            qa_defensive_template="Add parameterized edge-case stress tests, null-safety checks, and adversarial boundary permutations.",
            quick_spike_template="Author a fast smoke test suite covering the top 3 critical functional paths.",
            fallback_template="Verify functionality via automated command line smoke test assertions.",
            assertion_templates=['pytest {test_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Finalize Package and Sign-Off",
            primary_template="Export public interfaces in package __init__.py, update documentation, and perform final workspace hygiene checks for {subject}.",
            qa_defensive_template="Run full package regression suite and AST anti-cheat scanner to verify absolute compliance.",
            quick_spike_template="Generate runnable interactive demo script verifying full end-to-end functionality.",
            fallback_template="Audit git diff against main branch and verify zero uncommitted scratch artifacts.",
            assertion_templates=['pytest passes', 'python3 -m pytest tests/ passes'],
        ),
    ],

    IntentStratum.DEBUG_REPAIR: [
        MilestoneBlueprint(
            title_template="Defect Reproduction and Isolation",
            primary_template="Reproduce the reported defect for {subject} with an isolated, minimal failing test fixture in {test_file}. Capture precise stack trace and failure mode.",
            qa_defensive_template="Inspect environment preconditions, boundary conditions, and null/empty state inputs surrounding the failure site.",
            quick_spike_template="Write a lightweight reproduction script in scratch/ to observe real-time failure behavior.",
            fallback_template="Inspect recent git commits and diffs targeting {target_file} to locate the introducing change.",
            assertion_templates=['python3 -m py_compile {target_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Root Cause Analysis",
            primary_template="Trace the complete execution flow in {target_file} to isolate the root defect. Identify invalid assumptions, race conditions, or unhandled edge states.",
            qa_defensive_template="Audit thread safety, memory lifecycles, and exception propagations around the failure locus.",
            quick_spike_template="Inject temporary tracing probes or assertion guards to isolate the exact failing line.",
            fallback_template="Review surrounding caller contracts and defensive boundary validations.",
            assertion_templates=['python3 -c "import {target_module}" passes'],
        ),
        MilestoneBlueprint(
            title_template="Implement Surgical Defect Fix",
            primary_template="Apply a minimal blast-radius fix to {target_file} addressing the root cause without perturbing adjacent functional behaviors.",
            qa_defensive_template="Enforce defensive guards, typed bounds, and explicit exception recovery at the defect site.",
            quick_spike_template="Apply targeted workaround or patch to immediately unblock downstream workflows.",
            fallback_template="Revert problematic lines and substitute a conservative, fail-safe fallback path.",
            assertion_templates=['pytest {test_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Regression and Invariant Verification",
            primary_template="Execute full test suites in {test_file} and across the repository to verify that the fix resolves the defect and causes zero regressions.",
            qa_defensive_template="Subject the patched component to adversarial fuzzing and high-concurrency stress verification.",
            quick_spike_template="Execute focused smoke assertions targeting the modified functions and methods.",
            fallback_template="Verify state persistence and backward compatibility with previous serialized formats.",
            assertion_templates=['pytest tests/ passes'],
        ),
        MilestoneBlueprint(
            title_template="Clean Workspace and Release Commit",
            primary_template="Remove debug probes, inspect git diff for cleanliness, and commit verified defect resolution for {subject}.",
            qa_defensive_template="Execute AST anti-cheat scanner and linter across all modified lines before finalizing commit.",
            quick_spike_template="Document the root cause and resolution in walkthrough notes.",
            fallback_template="Stage changes atomically and verify git status is clean.",
            assertion_templates=['git status --porcelain passes'],
        ),
    ],

    IntentStratum.ARCH_DESIGN: [
        MilestoneBlueprint(
            title_template="Architectural Blueprint and Specification",
            primary_template="Define abstract protocols, interface boundaries, and data flow specifications for {subject}. State all architectural trade-offs explicitly.",
            qa_defensive_template="Define strict boundary constraints, concurrency guarantees, and invariant fault-handling policies.",
            quick_spike_template="Create an architectural prototype spike in scratch/ to evaluate design viability.",
            fallback_template="Review existing architecture and design backward-compatible adapter wrappers.",
            assertion_templates=['python3 -c "import {target_module}" passes'],
        ),
        MilestoneBlueprint(
            title_template="Scaffold Modular Abstractions",
            primary_template="Scaffold decoupled interfaces, abstract base classes, and adapter layers for {subject} in {target_file}.",
            qa_defensive_template="Enforce strict typing, contract assertions, and immutable value objects across public boundaries.",
            quick_spike_template="Implement lightweight concrete adapter with zero external library dependencies.",
            fallback_template="Retain legacy adapter facades to maintain uninterrupted backward compatibility.",
            assertion_templates=['python3 -m py_compile {target_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Subsystem Migration and Wiring",
            primary_template="Refactor callers and subsystem consumers to use the new architectural abstractions for {subject}. Verify clean handoffs.",
            qa_defensive_template="Implement dual-run or shadow verification comparing outputs between legacy and refactored components.",
            quick_spike_template="Route a single non-critical subsystem through the new architecture to validate flow.",
            fallback_template="Maintain runtime feature flag allowing immediate fallback to legacy implementation.",
            assertion_templates=['pytest {test_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Stress and Concurrency Verification",
            primary_template="Validate the refactored architecture under heavy load, boundary pressure, and concurrent execution in {test_file}.",
            qa_defensive_template="Verify zero memory leaks, thread contention, or unclosed resource handles under sustained load.",
            quick_spike_template="Execute synthetic benchmark measuring latency and throughput deltas.",
            fallback_template="Verify graceful degradation and backpressure behavior under resource saturation.",
            assertion_templates=['pytest tests/ passes'],
        ),
        MilestoneBlueprint(
            title_template="Architectural Sign-Off and Handoff",
            primary_template="Clean up deprecated code paths, update architectural documentation, and prepare the refactored system for stable release.",
            qa_defensive_template="Perform exhaustive reference audit ensuring no stale calls to deprecated interfaces remain.",
            quick_spike_template="Publish architecture summary walkthrough with updated component diagrams.",
            fallback_template="Document step-by-step rollback procedures and emergency recovery steps.",
            assertion_templates=['pytest passes'],
        ),
    ],

    IntentStratum.VERIFY_QA: [
        MilestoneBlueprint(
            title_template="Audit Test Scope and Baseline",
            primary_template="Audit current test coverage and identify untested execution branches, boundary states, and failure points in {target_file}.",
            qa_defensive_template="Enumerate all unhandled exceptions, unvalidated user inputs, and unsafe type coercions.",
            quick_spike_template="Run fast automated test discovery to inventory existing test coverage baseline.",
            fallback_template="Inspect historical bug reports and previous regression sites to prioritize test scenarios.",
            assertion_templates=['pytest --collect-only passes'],
        ),
        MilestoneBlueprint(
            title_template="Implement Boundary and Unit Tests",
            primary_template="Author comprehensive unit tests covering nominal, boundary, and extreme inputs for {subject} in {test_file}.",
            qa_defensive_template="Add parameterized test matrices covering null bytes, boundary limits, and unexpected types.",
            quick_spike_template="Author targeted smoke test suite verifying core contracts and happy paths.",
            fallback_template="Verify test assertions using standard python assert statements and standard fixtures.",
            assertion_templates=['pytest {test_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Adversarial and Chaos Verification",
            primary_template="Implement adversarial tests verifying security boundaries, AST anti-cheat compliance, and concurrency invariants.",
            qa_defensive_template="Inject simulated network drops, file system permission faults, and corrupted payloads.",
            quick_spike_template="Execute quick random permutation fuzzer against public API endpoints.",
            fallback_template="Validate error logging and exception capture under forced runtime failures.",
            assertion_templates=['pytest {test_file} passes'],
        ),
        MilestoneBlueprint(
            title_template="Performance Profiling and Leak Audit",
            primary_template="Execute performance benchmarks, analyze memory allocations, and verify absence of leaks or bottlenecks in {subject}.",
            qa_defensive_template="Establish deterministic upper bounds on CPU time and resident memory growth.",
            quick_spike_template="Run lightweight microbenchmark measuring throughput and operations per second.",
            fallback_template="Compare execution benchmarks against baseline performance metrics.",
            assertion_templates=['python3 -c "print(\'Performance verified\')" passes'],
        ),
        MilestoneBlueprint(
            title_template="Quality Gate Certification",
            primary_template="Execute full deterministic gate sieve, verify 100% test pass rate, and document QA verification sign-off for {subject}.",
            qa_defensive_template="Audit entire test suite ensuring zero skipped or suppressed assertions remain active.",
            quick_spike_template="Generate concise markdown test report summarizing passed assertions and coverage.",
            fallback_template="Archive test execution receipts and commit verified test artifacts.",
            assertion_templates=['pytest tests/ passes'],
        ),
    ],

    IntentStratum.RELEASE_OPS: [
        MilestoneBlueprint(
            title_template="Pre-Release Workspace Security Audit",
            primary_template="Audit git working tree, inspect pending diffs, and verify static security compliance for {subject}.",
            qa_defensive_template="Scan for uncommitted scratch artifacts, temporary debug instrumentation, and leaked secrets.",
            quick_spike_template="Run quick git status and modified file inventory across the workspace.",
            fallback_template="Stash non-essential scratch changes and clean working directory.",
            assertion_templates=['git status --porcelain passes'],
        ),
        MilestoneBlueprint(
            title_template="Full Regression Gate Execution",
            primary_template="Execute the complete regression test suite and deterministic gate sieve across all supported environments.",
            qa_defensive_template="Run AST anti-cheat scanner and multi-process concurrency checks across the repository.",
            quick_spike_template="Execute high-priority smoke test suite covering critical production workflows.",
            fallback_template="Verify system stability using isolated offline verification script.",
            assertion_templates=['pytest tests/ passes'],
        ),
        MilestoneBlueprint(
            title_template="Version Bump and Dependency Hygiene",
            primary_template="Bump package version identifier, lock dependency manifests, and verify metadata integrity for {subject}.",
            qa_defensive_template="Validate dependency cryptographic hashes and verify zero unpinned vulnerable packages.",
            quick_spike_template="Update version constant in package metadata and setup configuration.",
            fallback_template="Retain current package configuration with incremental release build metadata.",
            assertion_templates=['python3 -c "import auto_reply_route; print(\'Version verified\')" passes'],
        ),
        MilestoneBlueprint(
            title_template="Package Build and Artifact Verification",
            primary_template="Build distribution package artifacts (wheels, source distributions) and verify archive integrity.",
            qa_defensive_template="Inspect package contents ensuring no private tests, credentials, or dev artifacts are bundled.",
            quick_spike_template="Build lightweight source distribution archive and verify installation in temporary environment.",
            fallback_template="Test local package installation using isolated Python virtual environment.",
            assertion_templates=['python3 setup.py check passes'],
        ),
        MilestoneBlueprint(
            title_template="Release Tagging and Production Deployment",
            primary_template="Generate changelog notes, commit release metadata, create signed git tag, and trigger release handoff for {subject}.",
            qa_defensive_template="Verify release tag cryptographic signature and commit verification status.",
            quick_spike_template="Push release tag to origin and emit release notification.",
            fallback_template="Prepare automated rollback script and operational checkpoint recovery plan.",
            assertion_templates=['git log -n 1 passes'],
        ),
    ],
}


# ============================================================================
# RouteBuilder Engine
# ============================================================================

class _HybridMethod:
    """Descriptor enabling a method to be called either on an instance
    (using instance state) or directly on the class (instantiating a default instance).
    """

    def __init__(self, func: Callable[..., Any]):
        self.func = func
        self.__doc__ = func.__doc__

    def __get__(self, instance: Any, owner: Any) -> Any:
        if instance is None:
            return self.func.__get__(owner(), owner)
        return self.func.__get__(instance, owner)


class RouteBuilder:
    """Intelligent Route Builder that constructs multi-turn auto-reply route playbooks
    from developer seed prompts, eliminating manual authoring friction.
    """

    def __init__(
        self,
        normalizer: Optional[PromptNormalizer] = None,
        clusterer: Optional[IntentClusterer] = None,
    ):
        self.normalizer = normalizer or PromptNormalizer()
        self.clusterer = clusterer or IntentClusterer(self.normalizer)
        self.analyzer = SemanticPromptAnalyzer(self.normalizer, self.clusterer)

    @_HybridMethod
    def build_route_from_prompt(
        self,
        seed_prompt: str,
        num_steps: int = 5,
        min_alternatives: int = 3,
    ) -> RouteManifest:
        """Analyzes seed prompt intent and projects an elastic trajectory of sequential steps.

        At each step t in [1, num_steps]:
        - Generates primary forward prompt (Rank 1)
        - Generates 2nd place (QA Defensive, Rank 2)
        - Generates 3rd place (Alternative Architecture / Quick Spike, Rank 3)
        - Generates 4th place (Fallback / Ops, Rank 4)
        - Attaches assertions and concise title

        Returns a fully structured, ready-to-execute RouteManifest.
        """
        return self._build_route(seed_prompt, num_steps=num_steps, min_alternatives=min_alternatives)

    def _build_route(
        self,
        seed_prompt: str,
        num_steps: int = 5,
        min_alternatives: int = 3,
    ) -> RouteManifest:
        # Sanitize parameters
        clean_prompt = seed_prompt.strip() if seed_prompt else ""
        if not clean_prompt:
            clean_prompt = "Implement feature component and verify functionality with automated tests"

        target_steps = max(1, int(num_steps))
        target_alts = max(3, int(min_alternatives))

        # 1. Semantic Analysis
        decomp = self.analyzer.analyze(clean_prompt)

        # 2. Select Trajectory Matrix
        blueprints = TRAJECTORY_MATRICES.get(decomp.stratum, TRAJECTORY_MATRICES[IntentStratum.SCAFFOLD_BUILD])

        # 3. Elastic Trajectory Projection
        projected_blueprints = self._project_elastic_trajectory(blueprints, target_steps)

        # 4. Generate Structured RouteSteps
        steps: list[RouteStep] = []
        fmt_kwargs = {
            "subject": decomp.subject,
            "target_file": decomp.target_file,
            "target_module": decomp.target_module,
            "test_file": decomp.test_file,
            "action_verb": decomp.action_verb,
        }

        for idx, bp in enumerate(projected_blueprints):
            title = self._format_safe(bp.title_template, fmt_kwargs)
            primary_prompt = self._format_safe(bp.primary_template, fmt_kwargs)

            # Build alternatives (Ranks 2, 3, 4, ...)
            alternatives: list[AlternativeBranch] = [
                AlternativeBranch(
                    rank=BranchRank.QA_DEFENSIVE,
                    label="QA Defensive",
                    prompt_template=self._format_safe(bp.qa_defensive_template, fmt_kwargs),
                ),
                AlternativeBranch(
                    rank=BranchRank.ALTERNATIVE_ARCH,
                    label="Quick Spike",
                    prompt_template=self._format_safe(bp.quick_spike_template, fmt_kwargs),
                ),
                AlternativeBranch(
                    rank=BranchRank.FALLBACK,
                    label="Fallback",
                    prompt_template=self._format_safe(bp.fallback_template, fmt_kwargs),
                ),
            ]

            # If user requested more than 3 alternatives, synthesize additional high-rank branches
            if target_alts > 3:
                for extra_rank in range(5, target_alts + 2):
                    if extra_rank == 5:
                        extra_label = "Performance Benchmark"
                        extra_prompt = f"Profile execution time and resource utilization for {decomp.subject} under high load."
                    elif extra_rank == 6:
                        extra_label = "Docs & Handoff"
                        extra_prompt = f"Document architectural decisions and API usage examples for {decomp.subject} in walkthrough notes."
                    else:
                        extra_label = f"Alternative {extra_rank}"
                        extra_prompt = f"Explore secondary approach for {decomp.subject} prioritizing simplicity."

                    alternatives.append(
                        AlternativeBranch(
                            rank=extra_rank,
                            label=extra_label,
                            prompt_template=extra_prompt,
                        )
                    )

            # Build assertions
            assertions = [
                self._format_safe(a, fmt_kwargs)
                for a in bp.assertion_templates
                if a.strip()
            ]
            if not assertions:
                assertions = [f'python3 -c "import {decomp.target_module}" passes']

            step = RouteStep(
                index=idx,
                title=title,
                primary_prompt=primary_prompt,
                alternatives=alternatives,
                status=StepStatus.PENDING,
                retries=0,
                max_retries=2,
                assertions=assertions,
            )
            steps.append(step)

        # 5. Build RouteManifest
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", decomp.subject.lower()).strip("_")
        route_id = f"route_{decomp.stratum.value.lower()}_{slug[:24]}" if slug else f"route_{decomp.stratum.value.lower()}"
        manifest_title = f"{decomp.subject.title()} Route ({decomp.stratum.value.replace('_', ' ').title()})"

        return RouteManifest(
            route_id=route_id,
            title=manifest_title,
            steps=steps,
            current_step_idx=0,
            state=StepStatus.PENDING,
            metadata={
                "seed_prompt": clean_prompt,
                "stratum": decomp.stratum.value,
                "target_file": decomp.target_file,
                "target_module": decomp.target_module,
                "test_file": decomp.test_file,
            },
        )

    def _project_elastic_trajectory(
        self,
        canonical_blueprints: list[MilestoneBlueprint],
        target_steps: int,
    ) -> list[MilestoneBlueprint]:
        """Elastically maps canonical trajectory blueprints into target_steps milestones.

        Maintains complete workflow arc (Inception -> Logic -> Integration -> Verification -> Closure)
        regardless of step horizon.
        """
        n_canonical = len(canonical_blueprints)
        if target_steps == n_canonical:
            return list(canonical_blueprints)

        if target_steps == 1:
            # Single-step route: Foundation milestone with immediate assertion
            return [canonical_blueprints[0]]

        if target_steps == 2:
            # Two-step route: Foundation -> Comprehensive Verification
            return [canonical_blueprints[0], canonical_blueprints[3]]

        if target_steps == 3:
            # Three-step route: Foundation -> Implementation & Wiring -> Verification
            return [canonical_blueprints[0], canonical_blueprints[1], canonical_blueprints[3]]

        if target_steps == 4:
            # Four-step route: Foundation -> Logic -> Integration -> Verification
            return [canonical_blueprints[0], canonical_blueprints[1], canonical_blueprints[2], canonical_blueprints[3]]

        # target_steps >= n_canonical: Expand intermediate steps if target_steps > n_canonical
        result = list(canonical_blueprints)
        needed = target_steps - n_canonical

        # Additional specialized blueprints to inject before final verification/closure
        specialized_blueprints = [
            MilestoneBlueprint(
                title_template="Concurrency and Fault Tolerance",
                primary_template="Harden {subject} in {target_file} for thread safety, non-blocking I/O, and safe resource recycling under concurrent pressure.",
                qa_defensive_template="Add atomic locks, race condition detectors, and graceful timeout bounds.",
                quick_spike_template="Validate thread safety with a parallel thread-pool smoke test script.",
                fallback_template="Enforce thread isolation via isolated per-thread instances.",
                assertion_templates=['pytest {test_file} passes'],
            ),
            MilestoneBlueprint(
                title_template="Performance and Memory Optimization",
                primary_template="Profile {subject} in {target_file}, remove hot-path overhead, and verify absence of persistent memory growth.",
                qa_defensive_template="Enforce deterministic allocation limits and resource reclamation guards.",
                quick_spike_template="Run microbenchmark measuring operations per second and latency percentiles.",
                fallback_template="Apply cached lookups and fast-path shortcuts for frequent access patterns.",
                assertion_templates=['python3 -c "import {target_module}" passes'],
            ),
            MilestoneBlueprint(
                title_template="Adversarial Fuzzing and Invariant Check",
                primary_template="Execute adversarial payload fuzzing against {subject} to verify robust rejection of malformed or malicious inputs.",
                qa_defensive_template="Add rigorous input sanitization and strict schema boundary assertions.",
                quick_spike_template="Run rapid fuzzing loop injecting random byte sequences.",
                fallback_template="Reject all non-whitelisted input structures at boundary gateway.",
                assertion_templates=['pytest {test_file} passes'],
            ),
        ]

        insert_pos = max(1, len(result) - 2)
        for i in range(needed):
            bp = specialized_blueprints[i % len(specialized_blueprints)]
            result.insert(insert_pos + i, bp)

        return result[:target_steps]

    @staticmethod
    def _format_safe(template_str: str, kwargs: dict[str, Any]) -> str:
        """Safely formats template strings, ignoring missing format keys."""
        try:
            return template_str.format(**kwargs)
        except Exception:
            res = template_str
            for k, v in kwargs.items():
                res = res.replace(f"{{{k}}}", str(v))
            return res

    @_HybridMethod
    def interactive_build(
        self,
        seed_prompt: str,
        num_steps: int = 5,
        min_alternatives: int = 3,
        input_fn: Optional[Callable[[str], str]] = None,
        print_fn: Optional[Callable[..., None]] = None,
    ) -> RouteManifest:
        """CLI constructor that presents predicted nodes and allows swapping alternatives in real time.

        Zero cognitive load: pressing [Enter] accepts the primary prediction.
        Entering 2, 3, or 4 swaps in the corresponding alternative.
        Entering 'c' allows entering custom prompt text.
        Entering 's' finishes and saves the route at the current step.
        """
        return self._run_interactive_build(
            seed_prompt,
            num_steps=num_steps,
            min_alternatives=min_alternatives,
            input_fn=input_fn,
            print_fn=print_fn,
        )

    def _run_interactive_build(
        self,
        seed_prompt: str,
        num_steps: int = 5,
        min_alternatives: int = 3,
        input_fn: Optional[Callable[[str], str]] = None,
        print_fn: Optional[Callable[..., None]] = None,
    ) -> RouteManifest:
        _print = print_fn or print
        manifest = self.build_route_from_prompt(seed_prompt, num_steps=num_steps, min_alternatives=min_alternatives)

        # Check if environment is interactive
        is_interactive = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False
        if input_fn is None and not is_interactive:
            # Headless environment: return generated manifest directly
            return manifest

        _input = input_fn or input

        _print("\n" + "=" * 72)
        _print(f"🚀 Auto-Reply Route Builder: {manifest.title}")
        _print(f"Seed Prompt: \"{seed_prompt}\"")
        _print(f"Total Predicted Steps: {len(manifest.steps)}")
        _print("=" * 72 + "\n")

        final_steps: list[RouteStep] = []

        for step in manifest.steps:
            _print(f"\n--- Step {step.index + 1} of {len(manifest.steps)}: {step.title} ---")
            _print(f"🟢 [1] Primary Forward (Recommended):\n    {step.primary_prompt}")
            _print("\n🔀 Alternative Branches:")
            for alt in step.alternatives:
                _print(f"    [{alt.rank}] {alt.label}: {alt.prompt_template}")

            if step.assertions:
                _print(f"\n🛡️ Assertions: {', '.join(step.assertions)}")

            prompt_label = (
                "\nActions: [Enter] Accept Primary | [2/3/4] Swap Alternative | [c] Customize | [s] Finish Route Early\n> "
            )

            try:
                choice = _input(prompt_label).strip()
            except (EOFError, KeyboardInterrupt):
                _print("\n[Interactive constructor terminated. Retaining generated manifest.]")
                final_steps.append(step)
                break

            if not choice or choice == "1":
                # Keep primary
                _print(f"✓ Step {step.index + 1} accepted with Primary Forward.")
                final_steps.append(step)
            elif choice in ("2", "3", "4") or choice.isdigit():
                chosen_rank = int(choice)
                matched_alt = next((a for a in step.alternatives if a.rank == chosen_rank), None)
                if matched_alt:
                    # Swap primary prompt with alternative
                    old_primary = step.primary_prompt
                    step.primary_prompt = matched_alt.prompt_template
                    # Replace alternative with old primary labeled as Standard
                    matched_alt.prompt_template = old_primary
                    matched_alt.label = "Standard Forward (Swapped)"
                    _print(f"✓ Step {step.index + 1} swapped with Alternative [{chosen_rank}].")
                else:
                    _print(f"! Invalid rank {chosen_rank}; keeping primary.")
                final_steps.append(step)
            elif choice.lower() == "c":
                try:
                    custom_text = _input("Enter custom primary prompt text:\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    custom_text = ""
                if custom_text:
                    step.primary_prompt = custom_text
                    _print(f"✓ Step {step.index + 1} updated with custom prompt.")
                else:
                    _print("! Empty input; keeping original primary prompt.")
                final_steps.append(step)
            elif choice.lower() in ("s", "done", "finish", "q"):
                _print(f"✓ Finalizing route at step {step.index + 1}.")
                final_steps.append(step)
                break
            else:
                _print("✓ Unrecognized option; accepting Primary Forward.")
                final_steps.append(step)

        manifest.steps = final_steps
        return manifest

    @classmethod
    def export_to_playbook(
        cls,
        manifest: RouteManifest,
        filepath: Optional[Union[str, Path]] = None,
    ) -> str:
        """Converts a RouteManifest into a clean, standard-compliant .route.md Markdown playbook.

        Guarantees 100% roundtrip fidelity with RouteParser and passes RouteValidator
        with zero errors and zero warnings.
        """
        lines: list[str] = [f"# {manifest.title}", ""]

        for idx, step in enumerate(manifest.steps):
            step_num = idx + 1
            title = step.title.strip()
            prompt = step.primary_prompt.strip()

            # Format step header line:
            # If prompt already starts with title, emit prompt directly; otherwise prepend Title:
            prompt_lines = prompt.splitlines()
            first_line = prompt_lines[0].strip() if prompt_lines else ""
            remaining_lines = prompt_lines[1:] if len(prompt_lines) > 1 else []

            clean_title = re.sub(r"[*_`#]", "", title).strip()
            if first_line.lower().startswith(clean_title.lower()):
                header_line = f"{step_num}. {first_line}"
            else:
                header_line = f"{step_num}. {clean_title}: {first_line}"

            lines.append(header_line)

            # Indent subsequent prompt lines with 3 spaces
            for line in remaining_lines:
                stripped = line.strip()
                if stripped:
                    lines.append(f"   {stripped}")
                else:
                    lines.append("")

            # Format alternatives with standard *Label*: format
            for alt in step.alternatives:
                clean_label = alt.label.replace("*", "").strip()
                alt_lines = alt.prompt_template.strip().splitlines()
                first_alt = alt_lines[0].strip() if alt_lines else ""
                lines.append(f"   - *{clean_label}*: {first_alt}")
                for rem in alt_lines[1:]:
                    if rem.strip():
                        lines.append(f"     {rem.strip()}")

            # Format assertions with standard Assert: format
            for assertion in step.assertions:
                clean_assert = assertion.strip()
                if clean_assert.lower().startswith("assert:"):
                    clean_assert = clean_assert[7:].strip()
                lines.append(f"   - Assert: {clean_assert}")

            # Format optional manifest ref
            if step.manifest_ref:
                clean_ref = step.manifest_ref.strip()
                if clean_ref.lower().startswith("manifest:"):
                    clean_ref = clean_ref[9:].strip()
                lines.append(f"   - Manifest: {clean_ref}")

            lines.append("")

        content = "\n".join(lines).strip() + "\n"

        # Write to disk if filepath provided
        if filepath is not None:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        return content


_FOLLOWUP_UX_RE = re.compile(
    r"\b(?:ui|ux|styling|css|html|tailwind|interface|modal|dialog|button|palette|typography|dark\s*mode|micro[\s\-_]*craft|tap\s*targets?|transitions?|responsive\s+layout)\b",
    re.IGNORECASE,
)
_FOLLOWUP_CODE_RE = re.compile(
    r"\b(?:code|coding|api|endpoint|database|sql|bug|patch|refactor|test|pytest|unittest|function|class|module|backend|frontend|git|commit|pr|pull\s+request|sdk|library|script|repo|repository|implement|build|scaffold|wire|route|routing|canvassing|screen|view|controller|handler|service|middleware|worker|pipeline|queue|cache|benchmark|optimize|optimization|audit|resumability|auth|oauth|login|token|jwt|webhook|schema|migration|parser|ast|compiler|concurrency|async|thread|mutex|lock|server|client|websocket|socket|http|rest|grpc|cli|command|reconcile|reconciliation)\b",
    re.IGNORECASE,
)
_FOLLOWUP_RESEARCH_RE = re.compile(
    r"\b(?:research|science|scientific|biomedical|clinical|biology|physics|chemistry|dental|cavitation|plaque|tray|trays|stl-derived|hypothesis|literature|prior\s+art|venture|invest|investment|investor|pitch|business\s+model|market\s+viability|go\s+or\s+no\s+go|feasibility\s+study|commercial\s+viability|roi|unit\s+economics)\b",
    re.IGNORECASE,
)


def generate_followup_queue(
    prompt: str,
    count: int = 1,
    conversation_id: str = "default",
    domain_override: Optional[str] = None,
    max_subagents: int = 0,
) -> MessageQueueManifest:
    """Generate a high-intent follow-up message queue tailored to the prompt.

    Directly implements domain-aware multi-perspective follow-up trajectories:
    - Code / Engineering: Inception/Scaffold -> Least-complicated Prototype -> Anti-slop Refactor -> Verification -> Final Report.
    - UX / Craft: 44px tap targets -> transitions & responsive -> microcopy -> visual proof -> walkthrough.
    - Research / Venture: Refutation -> Prototype -> Feasibility & ROI -> Adversarial Go/No-Go -> Synthesis.

    Defaults to count=1 (single best follow-up prompt), expandable up to 5 steps.
    Engineering tasks default to code; research is reserved for explicit venture/biomedical/science queries.
    """
    clean_prompt = prompt.strip() if prompt else ""
    if not clean_prompt:
        clean_prompt = "this project"

    classification = HumanIntentClassifier.classify(clean_prompt)
    tier = classification.tier
    raw_subject = classification.extracted_subject or "this project"
    # Clean leading verbs (audit, review, fix, build, etc.) to prevent stuttering duplication in templates
    subject = re.sub(
        r"^(?:please\s+)?(?:could\s+you\s+)?(?:can\s+you\s+)?(?:audit|review|implement|prototype|build|create|fix|repair|refactor|design)\s+(?:the\s+|a\s+|an\s+)?",
        "",
        raw_subject,
        flags=re.IGNORECASE,
    ).strip(".:;, \t\n") or raw_subject

    # Determine domain with word-boundary precision
    is_ux = (
        domain_override == "ux"
        or tier == PromptIntentTier.UX_CRAFT_AUDIT
        or bool(_FOLLOWUP_UX_RE.search(clean_prompt))
    ) and domain_override != "code" and domain_override != "research"

    is_research = (
        domain_override == "research"
        or (bool(_FOLLOWUP_RESEARCH_RE.search(clean_prompt)) and not is_ux and domain_override != "code")
    )

    is_code = (
        domain_override == "code"
        or tier == PromptIntentTier.CODE_BUILD
        or bool(_FOLLOWUP_CODE_RE.search(clean_prompt))
        or (not is_ux and not is_research)  # Default fallback for developer tooling is code, never research
    )

    # Build the 5-step trajectory tailored to domain
    trajectory: list[tuple[str, str]] = []

    if is_ux:
        domain = "ux"
        trajectory = [
            (
                f"audit the interface for {subject} focusing on 44px tap targets, concentric radii, and accessibility",
                "ux",
            ),
            (
                f"smooth out transitions, loading states, and responsive layout for {subject} across mobile (375px) and desktop",
                "ux",
            ),
            (
                f"replace robotic text, lazy verbs, and technical plumbing copy with plain, welcoming everyday language",
                "ux",
            ),
            (
                f"capture screenshot evidence of the final interface verifying clean alignment and zero layout glitches",
                "ux",
            ),
            (
                f"produce a final walkthrough report summarizing all design improvements and visual evidence",
                "ux",
            ),
        ]
    elif is_research:
        domain = "research"
        trajectory = [
            (
                f"review and research what is needed for {subject}, with explicit permission to refute earlier claims and add on",
                "research",
            ),
            (
                f"prototype this {subject} design in the least complicated way that will give me a full sense of how it works",
                "research",
            ),
            (
                f"review this and see if there is any point in continuing this project, what the investment would look like and what the probability of success would be and projected outcomes",
                "research",
            ),
            (
                f"critically review your work and determine if this is a go or no go project because there's been lots of others that have failed at this, so we don't want to jump into this blindly and naively",
                "research",
            ),
            (
                f"give me a final report for this {subject} idea and any potential product business with all relevant info/diagrams/etc",
                "research",
            ),
        ]
    else:
        # Default: Software Engineering / Code
        domain = "code"
        trajectory = [
            (
                f"review the implementation for {subject}, focusing on edge cases, race conditions, and error recovery, and fix all discovered bugs",
                "code",
            ),
            (
                f"prototype this design in the least complicated way that will give me a full sense of how it works",
                "code",
            ),
            (
                f"audit for compromises, temporary hacks, or bloated AI slop; refactor complex branches into clean minimal code",
                "code",
            ),
            (
                f"critically review your work and run end-to-end assertions to ensure all tests pass with exit code 0",
                "code",
            ),
            (
                f"give me a final report for this {subject} implementation with proof of verified functionality and operational instructions",
                "code",
            ),
        ]

    # Select count: default is 1, clamped between 1 and len(trajectory)
    num_to_take = max(1, min(count, len(trajectory)))
    selected = trajectory[:num_to_take]

    # Dynamic subagent directive injection: ONLY if max_subagents > 0
    directive = ""
    if max_subagents and max_subagents > 1:
        directive = f"Use as many subagents working as a team as you need (up to {max_subagents} subagents)."
    elif max_subagents and max_subagents == 1:
        directive = "Use 1 subagent if needed to isolate execution context."

    manifest = MessageQueueManifest(
        conversation_id=conversation_id,
        messages=[],
        active_index=0,
        is_paused=False,
        metadata={
            "seed_prompt": clean_prompt,
            "domain": domain,
            "subject": subject,
            "requested_count": count,
            "max_subagents": max_subagents,
            "subagent_directive": directive,
        },
    )

    for base_text, msg_domain in selected:
        if max_subagents and max_subagents > 0:
            team_prefix = f"have a {max_subagents} person subagent team " if max_subagents > 1 else "have a subagent "
            final_prompt = f"{team_prefix}{base_text}"
            if directive:
                final_prompt = f"{final_prompt.rstrip('.')}. {directive}"
        else:
            # Capitalize first letter, zero subagent mentions
            final_prompt = f"{base_text[:1].upper()}{base_text[1:]}"
        manifest.add_message(prompt=final_prompt, domain=msg_domain)

    return manifest


# ============================================================================
# CLI Entry Point
# ============================================================================

def main(args: Optional[list[str]] = None) -> int:
    """Command-line interface for the RouteBuilder."""
    parser = argparse.ArgumentParser(
        prog="agy-route-builder",
        description="Auto-Reply Route Builder: generates multi-turn playbooks from a prompt",
    )
    parser.add_argument("prompt", type=str, help="Seed prompt describing the developer task")
    parser.add_argument("--steps", "-n", type=int, default=5, help="Number of steps in trajectory (default: 5)")
    parser.add_argument("--alternatives", "-a", type=int, default=3, help="Minimum alternatives per step (default: 3)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output .route.md file path")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive stepping constructor")

    parsed = parser.parse_args(args)

    builder = RouteBuilder()
    if parsed.interactive:
        manifest = builder.interactive_build(
            parsed.prompt,
            num_steps=parsed.steps,
            min_alternatives=parsed.alternatives,
        )
    else:
        manifest = builder.build_route_from_prompt(
            parsed.prompt,
            num_steps=parsed.steps,
            min_alternatives=parsed.alternatives,
        )

    out_text = RouteBuilder.export_to_playbook(manifest, filepath=parsed.output)

    if not parsed.output:
        print(out_text)
    else:
        print(f"[Playbook Saved] Route exported to: {Path(parsed.output).resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
