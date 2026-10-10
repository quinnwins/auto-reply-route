# Audit Only Route

1. Run comprehensive static analysis and security audit.
   Inspect source code and configuration for vulnerabilities, injection vectors, and structural flaws.
   Verify compliance with security policies and best practices.
   - *Dependency Check*: Audit external package vulnerabilities.
   - *Code Quality*: Check code style, types, and architectural boundaries.
   - *Fallback*: Scan git diff for sensitive data and insecure patterns.
   - Assert: git diff --check passes

2. Verify test coverage and check for brittle mocks.
   Run existing test suites with coverage analysis and audit test assertions for realism.
   Identify missing edge case coverage and test tampering.
   - *Mutation Audit*: Verify tests fail when assertions or critical logic are modified.
   - *Fast Check*: Run critical unit test suite without slow integration suites.
   - *Fallback*: Check test file counts and basic test suite execution.
   - Assert: python3 -m pytest tests/ -v passes
