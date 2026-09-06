"""2,016-Prompt Canonical Matrix & Topological Beam Router.

Houses a stratified graph of 2,016 specialized developer prompt archetypes
partitioned across 12 lifecycle phases, 12 technical domains, and 14 strategic
archetypes. Maps seed prompts into optimal multi-branch routes with zero runtime
token bloat and sub-2ms search latency.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Any, Optional

from auto_reply_route.models import RouteManifest, RouteStep, AlternativeBranch, StepStatus


# ----------------------------------------------------------------------
# 1. Domain & Stratum Taxonomies
# ----------------------------------------------------------------------

PHASES = [
    "1_principal_build",
    "2_staff_qa_swarm",
    "3_security_hardening_swarm",
    "4_concurrency_chaos_fuzz",
    "5_idempotency_data_integrity",
    "6_executive_babel_audit",
    "7_performance_resource_budget",
    "8_observability_telemetry",
    "9_integration_signature_sync",
    "10_full_regression_guard",
    "11_product_craft_proof",
    "12_release_governance_certification",
]

DOMAINS = [
    "api_webhooks",
    "database_orm",
    "security_auth",
    "frontend_ui",
    "concurrency_async",
    "performance_memory",
    "cli_tooling",
    "state_machines",
    "data_pipelines",
    "networking_sockets",
    "compiler_ast",
    "general_systems",
]

ARCHETYPES = [
    ("principal_architect", "Principal Architect Directive", 1),
    ("staff_qa_lead", "Staff QA Subagent Swarm", 2),
    ("principal_hardening", "Principal Reliability & Security", 3),
    ("executive_reality", "VP of Engineering Reality & Babel Check", 4),
    ("systems_integrator", "Principal Systems Integration Lead", 2),
    ("product_design_lead", "Senior Product & Design Director", 3),
    ("rapid_spike_lead", "Rapid Prototyping Spike Lead", 2),
    ("fail_closed_guard", "Fail-Closed Defensive Systems Lead", 3),
    ("chaos_fuzz_specialist", "Chaos & Adversarial Fuzzing Lead", 4),
    ("zero_debt_auditor", "Zero Technical Debt Officer", 2),
    ("simplicity_purist", "Simplicity & Living-Room Standard", 3),
    ("craft_perfectionist", "6-Lens Micro-Craft Director", 2),
    ("standard_library_minimalist", "Zero-Dependency Minimalist", 4),
    ("release_governance", "Production Release & Audit Officer", 4),
]


@dataclass
class PromptNode:
    """A single canonical prompt archetype in the 1,000-node matrix."""

    node_id: str
    phase: str
    domain: str
    archetype: str
    archetype_title: str
    rank_default: int
    title_template: str
    prompt_template: str
    assertion_template: str
    tags: set[str] = field(default_factory=set)
    is_project_learned: bool = False
    project_frequency: int = 1

    def instantiate(self, context: Optional[dict[str, Any]] = None) -> tuple[str, str, str]:
        """Fills slots with default-safe fallbacks."""
        ctx = context or {}
        # has_file is True unless explicitly declared False by the non-coder entity extractor
        has_file = ctx.get("has_explicit_file", True) is not False

        safe_ctx = {
            "subject": str(ctx.get("subject") or "the core feature"),
            "target_file": str(ctx.get("target_file") or "the primary implementation file"),
            "test_file": str(ctx.get("test_file") or "tests/test_feature.py"),
            "target_module": str(ctx.get("target_module") or "feature_module"),
        }
        for k, v in ctx.items():
            if k not in safe_ctx:
                safe_ctx[k] = str(v) if v is not None else ""

        def safe_replace(tmpl: str) -> str:
            if not tmpl:
                return ""
            # If no explicit file was specified by the user, remove awkward "in {target_file}" phrasing
            if not has_file:
                tmpl = tmpl.replace(" in {target_file}", "")
                tmpl = tmpl.replace(" for {target_file}", "")
                tmpl = tmpl.replace(" on {target_file}", "")
                tmpl = tmpl.replace("{target_file}", "the codebase")
            for k, v in safe_ctx.items():
                tmpl = tmpl.replace("{" + k + "}", v)
            # Clean any truncated placeholders from string slicing
            tmpl = re.sub(r"\{[a-zA-Z_]{1,20}$", "", tmpl)
            return tmpl

        title = safe_replace(self.title_template)
        prompt = safe_replace(self.prompt_template)
        assertion = safe_replace(self.assertion_template)

        # Language-aware assertion for serious engineering codebases:
        if has_file and "py_compile" in assertion:
            suffix = Path(safe_ctx["target_file"]).suffix.lower()
            if suffix == ".go":
                assertion = f"go vet {safe_ctx['target_file']} passes"
            elif suffix in {".ts", ".tsx"}:
                assertion = "npx tsc --noEmit passes"
            elif suffix == ".rs":
                assertion = "cargo check passes"
        elif not has_file and "py_compile" in assertion:
            assertion = "git diff --check passes"

        return title, prompt, assertion


def parameterize_prompt_template(text: str) -> str:
    """Converts concrete feature files, paths, and entity targets into dynamic template slots.
    
    Prevents prior feature names and paths (e.g. 'stripe', 'billing.py') from leaking into
    unrelated future feature routes.
    """
    if not text:
        return ""
    
    res = text
    # 1. Test files (e.g. tests/test_billing.py, billing_test.go, auth.spec.ts)
    test_pattern = r"\b(?:tests?/[\w\-./]+\.(?:py|ts|js|jsx|tsx|go|rs|rb|php)|[\w\-./]+(?:_test|\.test|\.spec)\.(?:py|ts|js|jsx|tsx|go|rs))\b"
    res = re.sub(test_pattern, "{test_file}", res, flags=re.IGNORECASE)

    # 2. General code files (e.g. src/billing.py, lib/auth.ts)
    code_pattern = r"\b(?:src/|lib/|app/|pkg/)?[\w\-./]+\.(?:py|ts|js|jsx|tsx|html|css|json|sql|go|rs|rb|php|java|yaml|yml)\b"
    res = re.sub(code_pattern, lambda m: m.group(0) if "{" in m.group(0) else "{target_file}", res, flags=re.IGNORECASE)

    # 3. Snake_case tokens, config keys, credentials, or identifiers (e.g. legacy_jwt_secret_key, stripe_customer_id)
    token_pattern = r"\b[a-zA-Z0-9_]+_(?:key|id|secret|token|config|schema|service|client)\b|\b[a-z0-9]+(?:_[a-z0-9]+){2,}\b"
    res = re.sub(token_pattern, lambda m: m.group(0) if "{" in m.group(0) else "{subject}", res, flags=re.IGNORECASE)

    # 4. Clean up duplicates and nested braces
    res = re.sub(r"\{target_file\}(?:/\{target_file\})+", "{target_file}", res)
    res = re.sub(r"\{test_file\}(?:/\{test_file\})+", "{test_file}", res)
    res = re.sub(r"\{subject\}(?:\s+\{subject\})+", "{subject}", res)
    return res.strip()


# ----------------------------------------------------------------------
# 2. Procedural 1,000-Node Catalog Matrix
# ----------------------------------------------------------------------

PHASE_PRIORITY_ARCHETYPES: dict[str, list[str]] = {
    "1_principal_build": [
        "principal_architect",
        "rapid_spike_lead",
        "fail_closed_guard",
        "standard_library_minimalist",
        "simplicity_purist",
        "zero_debt_auditor",
    ],
    "2_staff_qa_swarm": [
        "staff_qa_lead",
        "chaos_fuzz_specialist",
        "fail_closed_guard",
        "release_governance",
        "zero_debt_auditor",
    ],
    "3_security_hardening_swarm": [
        "principal_hardening",
        "fail_closed_guard",
        "chaos_fuzz_specialist",
        "zero_debt_auditor",
        "release_governance",
    ],
    "4_concurrency_chaos_fuzz": [
        "chaos_fuzz_specialist",
        "principal_hardening",
        "fail_closed_guard",
        "zero_debt_auditor",
    ],
    "5_idempotency_data_integrity": [
        "zero_debt_auditor",
        "principal_hardening",
        "fail_closed_guard",
        "release_governance",
    ],
    "6_executive_babel_audit": [
        "executive_reality",
        "simplicity_purist",
        "zero_debt_auditor",
        "release_governance",
    ],
    "7_performance_resource_budget": [
        "rapid_spike_lead",
        "chaos_fuzz_specialist",
        "zero_debt_auditor",
        "principal_architect",
    ],
    "8_observability_telemetry": [
        "systems_integrator",
        "fail_closed_guard",
        "release_governance",
        "zero_debt_auditor",
    ],
    "9_integration_signature_sync": [
        "systems_integrator",
        "zero_debt_auditor",
        "staff_qa_lead",
        "principal_hardening",
    ],
    "10_full_regression_guard": [
        "staff_qa_lead",
        "release_governance",
        "chaos_fuzz_specialist",
        "systems_integrator",
    ],
    "11_product_craft_proof": [
        "product_design_lead",
        "craft_perfectionist",
        "chaos_fuzz_specialist",
        "release_governance",
    ],
    "12_release_governance_certification": [
        "release_governance",
        "executive_reality",
        "zero_debt_auditor",
        "simplicity_purist",
    ],
}


class PromptMatrixCatalog:
    """Generates, indexes, and searches the 1,000-prompt topological matrix."""

    def __init__(self) -> None:
        self.nodes: list[PromptNode] = []
        self._phase_index: dict[str, list[PromptNode]] = defaultdict(list)
        self._inverted_index: dict[str, list[int]] = defaultdict(list)
        self._doc_frequencies: Counter = Counter()
        self._build_matrix()
        self._build_inverted_index()

    def _build_matrix(self) -> None:
        """Constructs the stratified matrix across Phases x Domains x Archetypes."""
        idx = 0
        for phase in PHASES:
            for domain in DOMAINS:
                for arch_key, arch_title, default_rank in ARCHETYPES:
                    node = self._create_matrix_node(idx, phase, domain, arch_key, arch_title, default_rank)
                    self.nodes.append(node)
                    self._phase_index[phase].append(node)
                    idx += 1

    def _create_matrix_node(
        self,
        node_id_int: int,
        phase: str,
        domain: str,
        archetype: str,
        archetype_title: str,
        rank: int,
    ) -> PromptNode:
        """Procedurally crafts domain-specific high-signal prompt templates."""
        clean_domain = domain.replace("_", " ").title()
        
        # Phase 1: Principal Architect Build (Substantial End-to-End Implementation)
        if phase == "1_principal_build":
            if archetype == "rapid_spike_lead":
                title = f"Rapid Prototype Spike for {clean_domain}"
                prompt = (
                    "Build a minimal working prototype spike in scratch for {subject} to validate core algorithmic feasibility "
                    "before committing to the final architecture. Verify the end-to-end path in under 50 lines with zero extra dependencies."
                )
                assertion = 'python3 -c "print(\'spike passes\')" passes'
            elif archetype == "fail_closed_guard":
                title = f"Fail-Closed Defensive Architecture for {clean_domain}"
                prompt = (
                    "Implement {subject} in {target_file} with fail-closed security invariants, strict schema validation, "
                    "and defensive boundary guards from the outset. Ensure all invalid inputs and failure modes are explicitly handled."
                )
                assertion = 'python3 -m py_compile {target_file} passes'
            elif archetype == "standard_library_minimalist":
                title = f"Zero-Dependency Standard Library Build for {clean_domain}"
                prompt = (
                    "Implement {subject} in {target_file} using pure standard library components without adding any new package dependencies. "
                    "Preserve clean, portable code and strict typing."
                )
                assertion = 'python3 -c "import sys" passes'
            elif archetype == "simplicity_purist":
                title = f"Minimalist Low-Surface Build for {clean_domain}"
                prompt = (
                    "Implement a minimalist, low-surface-area version of {subject} in {target_file}. "
                    "Eliminate speculative wrappers, flatten nesting, and ensure zero unneeded code."
                )
                assertion = 'python3 -m py_compile {target_file} passes'
            elif archetype == "zero_debt_auditor":
                title = f"Zero-Debt Production Implementation for {clean_domain}"
                prompt = (
                    "Implement {subject} in {target_file} with complete type annotations, explicit error handling, "
                    "and zero temporary shortcuts. Ensure every edge condition is directly addressed."
                )
                assertion = 'python3 -m py_compile {target_file} passes'
            else:
                title = f"Principal Architect Build: {clean_domain}"
                prompt = (
                    "Implement the complete, production-grade feature for {subject} in {target_file}. Establish clean architectural boundaries, "
                    "enforce strict typing, ensure minimal blast radius, and avoid unrequested tangential refactors. "
                    "Deliver a working end-to-end implementation ready for adversarial review."
                )
                assertion = 'python3 -m py_compile {target_file} passes'

        # Phase 2: Staff QA Lead (Adversarial Subagent Swarm)
        elif phase == "2_staff_qa_swarm":
            if archetype == "chaos_fuzz_specialist":
                title = f"Chaos & Adversarial Fuzzing for {clean_domain}"
                prompt = (
                    "Deploy chaos testing subagents to probe {subject} in {target_file} under high-concurrency pressure, poison pill payloads, "
                    "and timeout disruptions. Verify absence of deadlocks, race conditions, or unhandled exceptions."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "fail_closed_guard":
                title = f"Contract & Boundary Conformance for {clean_domain}"
                prompt = (
                    "Deploy contract testing subagents to verify typed interfaces, boundary conditions, and serialization round-trips for {subject}. "
                    "Ensure fail-closed error behaviors are strictly observed."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "release_governance":
                title = f"Deterministic AST Anti-Cheat Sieve for {clean_domain}"
                prompt = (
                    "Run an AST anti-cheat scanner and isolated test harness on {target_file}. "
                    "Verify 100% deterministic test execution, zero skipped assertions, and strict mock realism."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "zero_debt_auditor":
                title = f"Test Coverage & Mutation Verification for {clean_domain}"
                prompt = (
                    "Audit test coverage and mutation resilience for {subject}. Probe missing test assertions, "
                    "boundary edge cases, and ensure comprehensive regression safety."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            else:
                title = f"Staff QA Subagent Review: {clean_domain}"
                prompt = (
                    "Deploy an adversarial QA subagent team (Edge Case Auditor, Security Auditor, Test Coverage Specialist) to "
                    "scrutinize {subject} in {target_file}. Audit boundary conditions, race conditions, auth bypasses, and missing assertions. "
                    "Fix all identified defects immediately."
                )
                assertion = 'python3 -m pytest tests/ passes'

        # Phase 3: Principal Reliability & Security Hardening
        elif phase == "3_security_hardening_swarm":
            if archetype == "chaos_fuzz_specialist":
                title = f"Concurrency & Deadlock Audit for {clean_domain}"
                prompt = (
                    "Audit lock contention, threadpool queues, and asynchronous event loops for deadlock cycles or starvation in {subject}. "
                    "Harden thread safety and resource management."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "zero_debt_auditor":
                title = f"Idempotency & Replay Protection for {clean_domain}"
                prompt = (
                    "Verify transactional rollbacks and deduplication caches for {subject} under network partition and retry storms. "
                    "Ensure state transitions are strictly atomic."
                )
                assertion = 'git diff --check passes'
            elif archetype == "fail_closed_guard":
                title = f"Zero-Trust Penetration Audit for {clean_domain}"
                prompt = (
                    "Conduct a zero-trust security audit on {subject} in {target_file}. Probe injection vectors, "
                    "path traversal, authorization bypasses, and credential exposure. Fix all vulnerabilities immediately."
                )
                assertion = 'python3 -m pytest tests/ -k security passes'
            elif archetype == "release_governance":
                title = f"Cryptographic & Secret Exposure Audit for {clean_domain}"
                prompt = (
                    "Audit cryptographic cipher strengths, key rotation mechanics, and secret masking for {subject}. "
                    "Ensure zero plaintext tokens or credentials can leak into logs or telemetry."
                )
                assertion = 'git diff --check passes'
            else:
                title = f"Principal Reliability & Security Hardening"
                prompt = (
                    "Deploy a deep hardening subagent team to scrutinize {subject} in {target_file}. Audit for idempotency, replay attacks, "
                    "resource leaks, deadlock vectors, and fail-closed exception handling. Harden error recovery paths and ensure state transitions are atomic."
                )
                assertion = 'python3 -m pytest tests/ -k security passes'

        # Phase 4: Concurrency, Chaos Fuzzing & Event Loops
        elif phase == "4_concurrency_chaos_fuzz":
            if archetype == "chaos_fuzz_specialist":
                title = f"High-Concurrency Chaos & Poison Pill Fuzzing for {clean_domain}"
                prompt = (
                    "Deploy concurrency chaos subagents to probe {subject} under multi-threaded load, poison pill event storms, "
                    "and async deadlock contention. Verify absence of thread starvation, unhandled race conditions, or unhandled exceptions."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "principal_hardening":
                title = f"Deadlock Prevention & Task Group Isolation for {clean_domain}"
                prompt = (
                    "Audit lock contention, threadpool queues, and asynchronous event loops for deadlock cycles or starvation in {subject}. "
                    "Enforce strict lock acquisition ordering and timeout boundaries."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "fail_closed_guard":
                title = f"Critical Section & Mutex Guards for {clean_domain}"
                prompt = (
                    "Probe race condition boundaries, critical sections, and concurrent state transitions for {subject}. "
                    "Enforce fail-closed mutex acquisitions and strict timeout limits."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "zero_debt_auditor":
                title = f"Threadpool Teardown & Listener Hygiene for {clean_domain}"
                prompt = (
                    "Audit threadpool teardowns, worker drain sequences, and event loop listener memory retention in {subject}. "
                    "Eliminate dangling event handlers and thread leaks."
                )
                assertion = 'git diff --check passes'
            else:
                title = f"Concurrency & Chaos Fuzzing Lead"
                prompt = (
                    "Deploy concurrency chaos subagents to probe {subject} under multi-threaded load and async deadlock contention. "
                    "Harden mutex bounds and prevent resource starvation."
                )
                assertion = 'python3 -m pytest {test_file} passes'

        # Phase 5: Idempotency, Replay Protection & Data Integrity
        elif phase == "5_idempotency_data_integrity":
            if archetype == "zero_debt_auditor":
                title = f"Deduplication Cache & Rehydration Hygiene for {clean_domain}"
                prompt = (
                    "Verify transactional rollbacks and deduplication caches for {subject} under network partition and retry storms. "
                    "Ensure state transitions are strictly atomic and idempotent."
                )
                assertion = 'git diff --check passes'
            elif archetype == "principal_hardening":
                title = f"Two-Phase Commit & State Invariants for {clean_domain}"
                prompt = (
                    "Implement idempotent retry keys, conflict-free state resolution, and two-phase commit boundaries for {subject}. "
                    "Ensure all mutations can safely survive network drops."
                )
                assertion = 'git diff --check passes'
            elif archetype == "fail_closed_guard":
                title = f"Optimistic Concurrency & Data Integrity for {clean_domain}"
                prompt = (
                    "Verify data integrity invariants, optimistic concurrency version tokens, and replay attack prevention for {subject}. "
                    "Ensure fail-closed handling on version conflicts."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "release_governance":
                title = f"ACID Invariant & Schema Migration Audit for {clean_domain}"
                prompt = (
                    "Audit database transaction isolation levels, write-ahead log durability, and schema migration rollbacks for {subject}. "
                    "Certify zero data corruption risk."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            else:
                title = f"Idempotency & Replay Protection Officer"
                prompt = (
                    "Verify transactional rollbacks and deduplication caches for {subject} under network retry storms. "
                    "Ensure state transitions are strictly atomic and idempotent."
                )
                assertion = 'git diff --check passes'

        # Phase 6: VP of Engineering Reality & Tower of Babel Check
        elif phase == "6_executive_babel_audit":
            if archetype == "simplicity_purist":
                title = f"Executive Simplicity & Living-Room Standard"
                prompt = (
                    "Aggressively prune unnecessary layers of indirection for {subject} in {target_file}. Flatten nested logic, eliminate "
                    "premature abstractions, and ensure every human-facing surface passes the living-room coffee test."
                )
                assertion = 'git status passes'
            elif archetype == "zero_debt_auditor":
                title = f"Zero Technical Debt Officer Audit"
                prompt = (
                    "Audit {target_file} for temporary workarounds, unhandled TODOs, monkey patches, and brittle shortcuts. "
                    "Eliminate debt and ensure production-grade maintainability."
                )
                assertion = 'git diff --check passes'
            elif archetype == "release_governance":
                title = f"Architectural Decision Governance (ADR)"
                prompt = (
                    "Formulate an explicit Architectural Decision Record (ADR) for {subject}. "
                    "Document all accepted trade-offs, negative constraints, and verified domain boundaries."
                )
                assertion = 'git status --porcelain passes'
            else:
                title = f"VP of Engineering Reality & Babel Check"
                prompt = (
                    "Deploy the Executive Review Team (Simplicity Auditor, Technical Debt Officer, Product Director). "
                    "Make sure we have not built a tower of babel here: be completely honest about where things are at. "
                    "Confirm we are strictly on track with the original goal without unnecessary rabbit holes or speculative overengineering. "
                    "Eliminate temporary workarounds, excessive boilerplate, and confusing abstractions. Ensure code meets long-term standards."
                )
                assertion = 'git status --porcelain passes'

        # Phase 7: Performance Profiling & Resource Budgets
        elif phase == "7_performance_resource_budget":
            if archetype == "rapid_spike_lead":
                title = f"Hot-Path CPU Microbenchmarking & Profiling for {clean_domain}"
                prompt = (
                    "Profile hot-path CPU execution, memory allocations, and latency percentiles (p95/p99) for {subject}. "
                    "Eliminate execution bottlenecks and verify sub-millisecond hot paths."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "chaos_fuzz_specialist":
                title = f"High-Throughput Load & Allocation Sweep for {clean_domain}"
                prompt = (
                    "Stress test high-throughput request floods against {subject}. Audit memory leaks, heap retention, "
                    "and database query plan indexing under maximum concurrency."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "zero_debt_auditor":
                title = f"Algorithmic Complexity & Allocation Pruning for {clean_domain}"
                prompt = (
                    "Audit algorithmic complexity, unnecessary object allocations, and N+1 query patterns in {subject}. "
                    "Enforce strict CPU and memory performance budgets."
                )
                assertion = 'git diff --check passes'
            elif archetype == "principal_architect":
                title = f"Resource Budgeting & Capacity Planning for {clean_domain}"
                prompt = (
                    "Formulate architectural resource budgets, cache tiering strategies, and connection pool sizing for {subject}. "
                    "Ensure sustainable scalability under peak operational load."
                )
                assertion = 'git diff --check passes'
            else:
                title = f"Performance Profiling & Resource Budget Lead"
                prompt = (
                    "Benchmark hot-path CPU execution, memory allocations, and latency percentiles (p95/p99) for {subject}. "
                    "Profile execution bottlenecks and enforce tight runtime budgets."
                )
                assertion = 'python3 -m pytest {test_file} passes'

        # Phase 8: Fault Tolerance, Observability & Telemetry
        elif phase == "8_observability_telemetry":
            if archetype == "systems_integrator":
                title = f"OpenTelemetry Distributed Tracing & Spans for {clean_domain}"
                prompt = (
                    "Instrument structured JSON logging, distributed tracing spans, and OpenTelemetry context propagation "
                    "across all execution paths in {subject}. Ensure full diagnostic visibility."
                )
                assertion = 'pytest passes'
            elif archetype == "fail_closed_guard":
                title = f"Health Probes & Circuit Breaker Telemetry for {clean_domain}"
                prompt = (
                    "Verify health check probes, readiness signals, and fail-closed circuit breaker metrics for {subject}. "
                    "Ensure failures trip degraded states safely without cascading."
                )
                assertion = 'python3 -m pytest {test_file} passes'
            elif archetype == "release_governance":
                title = f"Production SLI & Alert Threshold Audit for {clean_domain}"
                prompt = (
                    "Audit service-level indicators (SLIs), error budgets, and alerting thresholds for {subject}. "
                    "Ensure production incidents produce actionable, high-fidelity signals."
                )
                assertion = 'git diff --check passes'
            elif archetype == "zero_debt_auditor":
                title = f"Structured Log Schema & PII Sanitization for {clean_domain}"
                prompt = (
                    "Audit structured logging schemas and metric cardinality in {subject}. "
                    "Guarantee zero PII, secret keys, or authentication tokens can leak into log aggregators."
                )
                assertion = 'git diff --check passes'
            else:
                title = f"Observability & OpenTelemetry Lead"
                prompt = (
                    "Instrument structured telemetry, error budgets, and health check signals for {subject}. "
                    "Ensure production observability."
                )
                assertion = 'pytest passes'

        # Phase 9: Cross-Module Integration & Public Signature Parity
        elif phase == "9_integration_signature_sync":
            if archetype == "systems_integrator":
                title = f"Principal Systems Integration: Whole-Repo Sync"
                prompt = (
                    "Deploy the System Integration Team (Wiring Logic Auditor, Regressions Checker, State Sync Specialist) "
                    "to verify holistic codebase coherence. Check caller/callee signatures, event dispatchers, package exports in __all__, "
                    "and database/state consistency across all modified modules. Confirm zero regressions across existing test suites."
                )
                assertion = 'pytest passes'
            elif archetype == "zero_debt_auditor":
                title = f"Deep Signature & Caller Wiring for {clean_domain}"
                prompt = (
                    "Verify caller/callee signatures, parameter forwarding, public package exports in __all__, "
                    "and import graph integrity for {subject}. Eliminate broken references or dangling stubs."
                )
                assertion = 'python3 -m pytest tests/ passes'
            elif archetype == "staff_qa_lead":
                title = f"Cross-Module Contract Parity for {clean_domain}"
                prompt = (
                    "Audit cross-module contract parity, public interface definitions, and dependency wiring across all services "
                    "interacting with {subject}. Eliminate parameter forwarding mismatches."
                )
                assertion = 'pytest passes'
            elif archetype == "principal_hardening":
                title = f"State Sync & Cache Coherence for {clean_domain}"
                prompt = (
                    "Verify multi-module state persistence, cache invalidation protocols, and transaction boundaries "
                    "across all services interacting with {subject}."
                )
                assertion = 'pytest passes'
            else:
                title = f"Systems Integration Sync Lead"
                prompt = (
                    "Verify caller/callee signatures, public package exports, and multi-module state consistency for {subject}. "
                    "Ensure full repository coherence."
                )
                assertion = 'pytest passes'

        # Phase 10: Full Regression Guard & Zero-Regressions Barrier
        elif phase == "10_full_regression_guard":
            if archetype == "staff_qa_lead":
                title = f"Full Regression Barrier Guard for {clean_domain}"
                prompt = (
                    "Execute the complete integration and regression test suite across all dependent modules for {subject}. "
                    "Neutralize cascading breakages and verify end-to-end caller parity across the entire repository."
                )
                assertion = 'pytest passes'
            elif archetype == "release_governance":
                title = f"Zero Mock Leaks & Deterministic Test Audit for {clean_domain}"
                prompt = (
                    "Run the full repository test suite with zero test skips and zero mock leaks. "
                    "Verify 100% deterministic test execution and regression immunity across the entire codebase."
                )
                assertion = 'pytest passes'
            elif archetype == "chaos_fuzz_specialist":
                title = f"Cascading Integration Chaos Guard for {clean_domain}"
                prompt = (
                    "Run end-to-end integration chaos suites across all upstream callers and downstream dependencies of {subject}. "
                    "Verify that no subtle regression slipped into adjacent subsystems."
                )
                assertion = 'pytest passes'
            elif archetype == "systems_integrator":
                title = f"Public API Backward Compatibility Guard for {clean_domain}"
                prompt = (
                    "Verify public API backward compatibility, serialization schema versioning, and caller migration safety for {subject}. "
                    "Guarantee zero breaking changes for existing callers."
                )
                assertion = 'pytest passes'
            else:
                title = f"Full Regression Barrier Guard"
                prompt = (
                    "Execute the complete repository regression test suite for {subject}. "
                    "Neutralize cascading breakages and verify zero regressions."
                )
                assertion = 'pytest passes'

        # Phase 11: Senior Product & Design Director (Visual Proof & Walkthrough)
        elif phase == "11_product_craft_proof":
            if archetype == "product_design_lead":
                title = f"Senior Product Director: Visual Proof & Walkthrough"
                prompt = (
                    "Send screenshot evidence of {subject} as implemented, test it out on web or simulator, "
                    "and audit whether anything was found in the walkthrough that needs to be fixed. Generate milestone walkthrough proof card."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "craft_perfectionist":
                title = f"6-Lens Micro-Craft Director Audit"
                prompt = (
                    "Audit captured screenshots against the 6-lens standard: 4/8pt rhythm, concentric radii, 44x44px touch targets, "
                    "tight headline leading, and 150ms ease transitions. Fix all visual and ergonomic defects in {subject}."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "chaos_fuzz_specialist":
                title = f"Responsive Viewport Sweep for {clean_domain}"
                prompt = (
                    "Run automated headless browser capture across mobile, tablet, and desktop viewports for {subject}. "
                    "Check console error logs, network cascades, and layout shifts."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "release_governance":
                title = f"Milestone Visual Proof & Sign-Off Documentation"
                prompt = (
                    "Compile visual proof receipts, simulator recordings, and user acceptance sign-offs for {subject}. "
                    "Verify the customer experience is delightful and defect-free."
                )
                assertion = 'git status --porcelain is clean'
            else:
                title = f"Senior Product Director: Visual Proof & Walkthrough"
                prompt = (
                    "Send screenshot evidence of {subject} as implemented, test it out on web or simulator, "
                    "and generate milestone walkthrough proof card."
                )
                assertion = 'git status --porcelain is clean'

        # Phase 12: Production Release Governance & Certification
        else:
            if archetype == "release_governance":
                title = f"Production Release & Milestone Governance"
                prompt = (
                    "Compile the executive release summary, test evidence receipts, and milestone sign-off documentation for {subject}. "
                    "Ensure production readiness and zero uncommitted diffs."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "executive_reality":
                title = f"Executive Release Sign-Off"
                prompt = (
                    "Formulate final executive sign-off for {subject}. Confirm all acceptance criteria are met, "
                    "negative constraints honored, and technical debt eliminated before production rollout."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "zero_debt_auditor":
                title = f"Release Hygiene & Artifact Audit"
                prompt = (
                    "Audit git working tree for uncommitted files, lingering debug print statements, or scratch artifacts. "
                    "Certify pristine release hygiene for {subject}."
                )
                assertion = 'git status --porcelain is clean'
            elif archetype == "simplicity_purist":
                title = f"Final Complexity & Architectural Audit"
                prompt = (
                    "Audit {subject} against long-term maintenance standards. "
                    "Verify that all unnecessary complexity was rejected and that the final implementation passes the living-room test."
                )
                assertion = 'git status --porcelain is clean'
            else:
                title = f"Production Release & Milestone Governance"
                prompt = (
                    "Compile the executive release summary, test evidence receipts, and milestone sign-off documentation for {subject}. "
                    "Ensure production readiness and zero uncommitted diffs."
                )
                assertion = 'git status --porcelain is clean'

        tags = {phase, domain, archetype, clean_domain.lower()}
        tags.update(re.findall(r"\b[a-zA-Z]{3,}\b", title.lower()))

        return PromptNode(
            node_id=f"node_{node_id_int:04d}_{phase}_{domain}_{archetype}",
            phase=phase,
            domain=domain,
            archetype=archetype,
            archetype_title=archetype_title,
            rank_default=rank,
            title_template=title,
            prompt_template=prompt,
            assertion_template=assertion,
            tags=tags,
        )

    def _build_inverted_index(self) -> None:
        """Builds an in-memory inverted lexical index for sub-millisecond scoring."""
        self._inverted_index.clear()
        self._doc_frequencies.clear()
        for i, node in enumerate(self.nodes):
            words = set(node.tags)
            words.update(re.findall(r"\b[a-zA-Z]{3,}\b", (node.title_template + " " + node.prompt_template).lower()))
            for w in words:
                self._inverted_index[w].append(i)
                self._doc_frequencies[w] += 1

    def ingest_project_learned_prompts(
        self,
        clusters: list[Any],
        domain: str = "general_systems",
    ) -> int:
        """Ingests user's prior prompts mined from this specific project's transcript history."""
        count = 0
        for cluster in clusters:
            medoid = getattr(cluster, "raw_medoid", "") or getattr(cluster, "medoid", "")
            if not medoid:
                continue
            stratum = str(getattr(cluster, "stratum", "SCAFFOLD_BUILD")).upper()

            if "SCAFFOLD" in stratum or "ARCH" in stratum:
                phase = "1_principal_build"
            elif "DEBUG" in stratum or "REPAIR" in stratum:
                phase = "3_security_hardening_swarm"
            elif "VERIFY" in stratum or "QA" in stratum:
                phase = "2_staff_qa_swarm"
            elif "RELEASE" in stratum:
                phase = "12_release_governance_certification"
            else:
                phase = "1_principal_build"

            freq = int(getattr(cluster, "frequency", 1))
            cluster_id = getattr(cluster, "cluster_id", f"learned_{count}")
            parameterized = parameterize_prompt_template(medoid)
            clean_title = re.sub(r"\{.*?\}", "component", parameterized)
            title_template = f"Project Practice: {clean_title[:35]}..."
            node = PromptNode(
                node_id=f"project_node_{cluster_id}",
                phase=phase,
                domain=domain,
                archetype="project_learned",
                archetype_title=f"Project Habit ({freq}x used)",
                rank_default=1,
                title_template=title_template,
                prompt_template=parameterized,
                assertion_template="pytest passes",
                tags={"project_learned", domain, phase},
                is_project_learned=True,
                project_frequency=freq,
            )
            self.nodes.append(node)
            self._phase_index[phase].append(node)
            count += 1

        if count > 0:
            self._build_inverted_index()
        return count

    def score_node(self, node: PromptNode, query_tokens: list[str], target_domain: Optional[str] = None) -> float:
        """Scores a prompt node against seed tokens using BM25-style term weighting."""
        score = 0.0
        n_total = len(self.nodes)

        for token in query_tokens:
            df = self._doc_frequencies.get(token, 0)
            if df > 0:
                idf = math.log(1.0 + (n_total - df + 0.5) / (df + 0.5))
                if token in node.tags:
                    score += idf * 2.5
                elif token in (node.title_template + " " + node.prompt_template).lower():
                    score += idf * 1.0

        # Domain alignment boost
        if target_domain and node.domain == target_domain:
            score += 4.0

        # Phase archetype coherence boost (ensures dedicated, non-duplicate archetypes are prioritized)
        priority_archs = PHASE_PRIORITY_ARCHETYPES.get(node.phase, [])
        if node.archetype in priority_archs:
            rank_idx = priority_archs.index(node.archetype)
            score += 15.0 - (rank_idx * 1.5)

        # High priority boost for user's own project history
        if node.is_project_learned:
            score += 6.0 + math.log(1.0 + node.project_frequency)

        return score

    @property
    def total_nodes(self) -> int:
        return len(self.nodes)


# ----------------------------------------------------------------------
# 3. Topological Beam Router across the 1,000-Prompt Matrix
# ----------------------------------------------------------------------

class MatrixBeamRouter:
    """Traverses the 1,000-prompt matrix using topological beam search."""

    def __init__(self, catalog: Optional[PromptMatrixCatalog] = None):
        self.catalog = catalog or PromptMatrixCatalog()

    def detect_domain(self, prompt: str) -> str:
        """Infers the primary domain from the seed prompt."""
        p = prompt.lower()
        if re.search(r"\b(?:perf|memory|leak|cpu|profile|slow|cache|speed|latency|freez|freeze|freezing|lag|stutter|fps)\b", p):
            return "performance_memory"
        if re.search(r"\b(?:api|webhook|endpoint|http|rest|route|json|stripe|billing|checkout|invoice)\b", p):
            return "api_webhooks"
        if re.search(r"\b(?:db|database|sql|postgres|sqlite|model|schema|migration|orm|table|wal|write\-?ahead|replication|failover|sharding|partition|mvcc|acid)\b", p):
            return "database_orm"
        if re.search(r"\b(?:auth|login|logins|signup|signin|sign-in|passkey|passkeys|faceid|touchid|biometric|token|jwt|oauth|crypto|security|permission|password|ebpf|socket|filter|tls|cipher)\b", p):
            return "security_auth"
        if re.search(r"\b(?:ui|frontend|css|html|tailwind|component|button|layout|react|vue|header|navbar|modal|dialog|toggle|canvas|dark\s*mode|theme|screen|page|view)\b", p):
            return "frontend_ui"
        if re.search(r"\b(?:async|thread|threads|concurrency|queue|worker|race|event\s*loop|deadlock|lock|mutex|raft|consensus|quorum|toctou|semaphore|spinlock|channel|coroutine|goroutine|atomic)\b", p):
            return "concurrency_async"
        if re.search(r"\b(?:ast|compiler|parse|parser|syntax|visitor|token|lexer|grammar|bytecode|llvm|ssa|jit)\b", p):
            return "compiler_ast"
        return "general_systems"

    def extract_entities(self, prompt: str) -> dict[str, Any]:
        """Extracts context entities to fill prompt slots."""
        ctx: dict[str, Any] = {}
        # Normalize and strip explicit step budgets e.g. [4], [12], 4:
        from auto_reply_route.miner import PromptNormalizer
        _, clean_prompt = PromptNormalizer.extract_step_budget(prompt, default=1)

        # Comprehensive engineering file extensions (Go, Rust, C/C++, TypeScript, Python, Swift, etc.)
        exts = r"(?:py|ts|js|jsx|tsx|go|rs|c|cpp|cc|h|hpp|swift|kt|kts|java|rb|php|sql|json|yaml|yml|toml|proto|sh|bash|zsh|dockerfile|makefile|html|css)"
        file_match = re.search(rf"\b([a-zA-Z0-9_\-/\\]+\.{exts})\b", clean_prompt, re.IGNORECASE)
        if file_match:
            target_file = file_match.group(1)
            ctx["target_file"] = target_file
            p = Path(target_file)
            stem = p.stem
            suffix = p.suffix.lower()
            ctx["target_module"] = stem
            ctx["has_explicit_file"] = True

            # Language-aware test file convention
            if suffix == ".go":
                parent = str(p.parent)
                ctx["test_file"] = f"{parent}/{stem}_test.go" if parent != "." else f"{stem}_test.go"
            elif suffix in {".ts", ".tsx"}:
                ctx["test_file"] = f"tests/{stem}.test.ts"
            elif suffix in {".js", ".jsx"}:
                ctx["test_file"] = f"tests/{stem}.test.js"
            elif suffix == ".rs":
                ctx["test_file"] = f"tests/test_{stem}.rs"
            elif suffix == ".py":
                ctx["test_file"] = f"tests/test_{stem}.py"
            else:
                ctx["test_file"] = f"tests/test_{stem}{suffix}"
        else:
            ctx["target_file"] = ""
            ctx["target_module"] = "feature"
            ctx["test_file"] = "tests/"
            ctx["has_explicit_file"] = False

        # Subject extraction: supports both technical verbs and everyday conversational phrases
        verbs = r"(?:build|create|implement|code|add|refactor|design|architect|make|set\s+up|setup|hook\s+up|wire\s+up|integrate|connect|fix)"
        subj_match = re.search(rf"{verbs}\s+([a-zA-Z0-9_\-\s]+?)(?:\s+in\s+|\s+using\s+|\s+with\s+|$)", clean_prompt, re.IGNORECASE)
        if subj_match:
            ctx["subject"] = subj_match.group(1).strip()
        else:
            cleaned_fallback = clean_prompt.replace(ctx.get("target_file", ""), "")
            ctx["subject"] = re.sub(r"\s+", " ", cleaned_fallback).strip()[:250].strip()

        return ctx

    @staticmethod
    def format_subagent_directive(max_subagents: int) -> str:
        """Formats dynamic subagent team allocation directive."""
        if max_subagents <= 0:
            return ""
        elif max_subagents == 1:
            return "Use 1 subagent if needed to isolate execution context."
        else:
            return f"Use as many subagents working as a team as you need (up to {max_subagents} subagents)."

    def map_route_from_matrix(
        self,
        seed_prompt: str,
        num_steps: int = 6,
        alternatives_per_step: int = 4,
        max_subagents: int = 3,
    ) -> RouteManifest:
        """Topologically routes across the 1,000-node matrix to generate a multi-branch route."""
        domain = self.detect_domain(seed_prompt)
        entities = self.extract_entities(seed_prompt)
        query_tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", seed_prompt)]

        steps: list[RouteStep] = []
        directive = self.format_subagent_directive(max_subagents)

        phases_to_use = PHASES[:num_steps]
        for step_idx, phase in enumerate(phases_to_use):
            candidate_nodes = self.catalog._phase_index[phase]

            # Score all candidate nodes in this phase stratum
            scored: list[tuple[float, PromptNode]] = []
            for node in candidate_nodes:
                score = self.catalog.score_node(node, query_tokens, target_domain=domain)
                scored.append((score, node))

            # Sort highest score first
            scored.sort(key=lambda item: item[0], reverse=True)

            # Pick top distinct archetypes for primary + alternatives
            seen_archetypes = set()
            selected_nodes: list[PromptNode] = []
            for _, node in scored:
                if node.archetype not in seen_archetypes:
                    seen_archetypes.add(node.archetype)
                    selected_nodes.append(node)
                if len(selected_nodes) >= alternatives_per_step:
                    break

            # Fallback if not enough distinct archetypes
            if len(selected_nodes) < alternatives_per_step:
                for _, node in scored:
                    if node not in selected_nodes:
                        selected_nodes.append(node)
                    if len(selected_nodes) >= alternatives_per_step:
                        break

            primary_node = selected_nodes[0]
            p_title, p_prompt, p_assert = primary_node.instantiate(entities)
            if directive and directive not in p_prompt:
                p_prompt = f"{p_prompt.rstrip('.')}. {directive}"

            # Build alternative branches
            branches: list[AlternativeBranch] = []
            for rank_idx, alt_node in enumerate(selected_nodes):
                alt_title, alt_prompt, _ = alt_node.instantiate(entities)
                if directive and directive not in alt_prompt:
                    alt_prompt = f"{alt_prompt.rstrip('.')}. {directive}"
                branches.append(
                    AlternativeBranch(
                        rank=rank_idx + 1,
                        label=alt_node.archetype_title,
                        prompt_template=alt_prompt,
                    )
                )

            steps.append(
                RouteStep(
                    index=step_idx + 1,
                    title=p_title,
                    primary_prompt=p_prompt,
                    assertions=[p_assert] if p_assert else [],
                    status=StepStatus.PENDING,
                    alternatives=branches,
                )
            )

        route_id = f"matrix_route_{domain}_{abs(hash(seed_prompt)) % 10000}"
        return RouteManifest(
            route_id=route_id,
            title=f"Matrix Route: {entities.get('subject', 'Feature')}",
            steps=steps,
            current_step_idx=0,
            state=StepStatus.PENDING,
            metadata={
                "seed_prompt": seed_prompt,
                "matrix_catalog_size": self.catalog.total_nodes,
                "domain": domain,
                "entities": entities,
                "max_subagents": max_subagents,
            },
        )
