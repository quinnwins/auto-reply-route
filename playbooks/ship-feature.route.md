# Ship Feature Route

1. Build the requested feature cleanly with minimal blast radius.
   Implement the core logic, state models, and interfaces required for the user story.
   Keep changes strictly scoped to necessary files and preserve existing architecture.
   - *Quick Spike*: Build a minimal working prototype first without optimizations.
   - *QA Defensive*: Implement strict input validation, invariants, and defensive exception handling.
   - *Fallback*: Implement standard library or lightweight alternative without dependencies.
   - Assert: python3 -m pytest tests/ -v passes

2. Review implementation with 3-agent QA team and fix defects.
   Conduct multi-perspective code inspection focusing on edge cases, race conditions, and error recovery.
   Fix all discovered bugs immediately.
   - *Security Focus*: Audit strictly for auth bypasses, injection, and data leaks.
   - *Defensive Review*: Audit resource bounds, memory leaks, and timeout protections.
   - *Fallback*: Self-inspect full diff against quality checklist.
   - Assert: git diff --check passes

3. Review for executive-level compromises, architectural shortcuts, or hidden debt.
   Audit design decisions to ensure code quality meets long-term standards.
   Eliminate temporary hacks, technical debt, or brittle assumptions.
   - *Performance Audit*: Check memory allocations, latency bottlenecks, and query plans.
   - *Simplification*: Refactor complex branches into straightforward linear code.
   - *Fallback*: Document accepted trade-offs explicitly in code comments.
   - Assert: git status passes

4. Verify end-to-end functionality and capture screenshot proof in browser.
   Run full end-to-end test scenarios and record visual proof of user-facing interfaces.
   Verify responsiveness, console clean state, and touch ergonomics.
   - *Headless Run*: Run headless automated browser verification script.
   - *Unit Verification*: Run comprehensive integration tests when browser is unavailable.
   - *Fallback*: Perform manual CLI test scenario walkthrough.
   - Assert: python3 -m pytest tests/ -k e2e passes

5. Review visual walkthrough evidence and fix remaining rough edges.
   Inspect captured screenshots and recorded artifacts for layout flaws or rough transitions.
   Polish final micro-interactions and update walkthrough documentation.
   - *Micro Polish*: Fix spacing, alignment, and button microcopy defects.
   - *Documentation*: Finalize walkthrough markdown with before/after comparisons.
   - *Fallback*: Verify code diff cleanliness and tag completion.
   - Assert: git status --porcelain is clean
