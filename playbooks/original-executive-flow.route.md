# Original Executive Flow Route

1. Code this feature cleanly with minimal blast radius.
   Implement the core functionality, domain models, and interfaces specified in the user story.
   Stay strictly focused on the user's core goal: avoid speculative rabbit holes, unrequested dependencies, or premature refactors.
   Preserve existing architecture, ensure strict typing, and avoid unnecessary external dependencies.
   - *Quick Spike*: Build a minimal working prototype in scratch first to validate core algorithmic feasibility.
   - *QA Defensive*: Implement strict input validation, invariants, boundary checks, and defensive exception handling from the start.
   - *Standard Library Only*: Implement using pure standard library components without adding new package dependencies.
   - *Fallback*: Generate stubbed interfaces with comprehensive test harnesses to drive implementation via TDD.
   - Assert: python3 -c "import auto_reply_route" passes

2. Review with a 3 person subagent QA team and fix.
   Deploy the 3-person QA team (Edge Case Auditor, Security Auditor, Test Coverage Specialist) to inspect the newly implemented code.
   Audit boundary conditions, race conditions, auth/injection vulnerabilities, and missing assertions. Fix all identified defects immediately.
   - *Strict Security Focus*: Focus the entire audit on injection vectors, path traversal, auth bypasses, and secret exposure.
   - *Chaos & Edge Cases*: Simulate high-concurrency races, timeout disruptions, and resource exhaustion edge cases.
   - *Test Coverage Verification*: Focus on missing test assertions, mutation testing, and mock realism.
   - *Fallback*: Self-inspect diff against verification checklist and AST anti-cheat scanner.
   - Assert: git diff --check passes

3. Send this through another 3 person subagent QA team and fix.
   Deploy a second, fresh 3-person subagent QA team with zero cognitive bias from the first review.
   Adversarially probe error recovery paths, state transitions, exception handling, and mock realism. Fix all newly discovered flaws.
   - *Stress & Invariant Audit*: Probe edge-case state mutations and boundary condition fuzzing.
   - *Dependency & Sandboxing*: Audit external library calls, system subprocess isolation, and network boundaries.
   - *Contract Conformance*: Verify typed interfaces, schema validation, and serialization round-trips.
   - *Fallback*: Run test suite under full isolation and verify 100% deterministic green run.
   - Assert: python3 -m pytest tests/ -v passes

4. Send this to an executive team, were there any compromises taken or rabbit holes gone down that an executive would reject, fix if so.
   Deploy the Executive Review Team (Simplicity Auditor, Technical Debt Officer, Product Director) to scrutinize architectural decisions.
   Make sure we have not built a tower of babel here: be completely honest about where things are at.
   Confirm we are strictly on track with the original goal without unnecessary rabbit holes or speculative overengineering.
   Differentiate clearly: if we diverted, was the sidetracking additive and necessary (e.g. required schema or dependency prerequisites) or an unproductive tangent?
   Eliminate temporary workarounds, excessive boilerplate, tangent refactors, and confusing abstractions. Ensure code meets long-term standards.
   - *Strict Security Audit*: Pivot executive review into a high-stakes security, vulnerability, and risk governance audit.
   - *Simplicity First*: Aggressively prune unnecessary layers of abstraction, flatten nesting, and apply the living-room standard.
   - *Zero Technical Debt*: Eliminate temporary hacks, unhandled TODOs, and brittle workarounds.
   - *Fallback*: Formulate an explicit architectural decision record (ADR) documenting accepted trade-offs.
   - Assert: git status passes

5. Review a final time with a subagent team checking for any bugs, wiring logic, feature sync with existing codebase.
   Deploy the System Integration Team (Wiring Logic Auditor, Regressions Checker, State Sync Specialist) to verify holistic codebase coherence.
   Check caller/callee signatures, event dispatchers, package exports, and database/state consistency across all modified modules.
   - *Wiring Logic Deep Audit*: Trace caller/callee signatures, public exports, and parameter forwarding.
   - *Full Regression Guard*: Run complete integration and regression suite against existing components.
   - *State Sync & Concurrency*: Verify multi-threaded persistence, atomic writes, and cache coherence.
   - *Fallback*: Validate package __all__ exports and module import graph integrity.
   - Assert: python3 -m pytest tests/ passes

6. Send me screenshot evidence of this feature as implemented, test it out on web or simulator or whatever, and review whether anything was found in your screenshots or walkthrough that needs to be fixed.
   Deploy the Visual Proof Team (Screenshot / Simulator Verifier, Walkthrough Auditor) to capture visual proof in the browser or simulator.
   Inspect captured screenshots for 4/8pt rhythm, concentric radii, touch ergonomics (>=44px), contrast, and layout shift. Fix any visual flaws and generate a Stratum 3 milestone card.
   - *Headless Browser Capture*: Run automated browser capture for responsive viewports and check console error logs.
   - *Simulator Walkthrough*: Capture mobile simulator interactions across landscape and portrait orientations.
   - *6-Lens Craft Audit*: Audit screenshots for 4/8pt rhythm, concentric radii, and 44x44px tap targets.
   - *Fallback*: Generate ASCII terminal milestone card and diff walkthrough.
   - Assert: git status --porcelain is clean
