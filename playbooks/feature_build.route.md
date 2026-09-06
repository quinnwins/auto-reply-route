# Canonical Feature Build Route

1. Scaffold Feature Data Models and Core Types.
   Define all domain dataclasses, enums, and serialization schemas in models.py.
   Ensure all classes are fully type-annotated and have zero external runtime dependencies.
   - *Quick Spike*: Implement minimal in-memory dataclasses first.
   - *QA Defensive*: Add comprehensive boundary checking and schema validation.
   - *Fallback*: Use raw typed dictionaries with lightweight helper functions.
   - Assert: python3 -c "import auto_reply_route.models" passes

2. Implement Route Playbook Markdown Parser.
   Build the parser to turn markdown playbooks into structured RouteManifest instances.
   Support numbered steps, indented alternative branches, and assertions.
   - *Quick Spike*: Use simple line-based regex parsing for happy paths.
   - *QA Defensive*: Build a stateful streaming line parser with edge case handling.
   - Alternative: Use an external AST parser if markdown has complex formatting.
   - Assert: pytest tests/test_parser.py passes

3. Build Route State Machine and Atomic Persistence.
   Implement the lifecycle engine for step transitions, branch swapping, and 2-retry cap.
   Persist state atomically to disk on every transition.
   - *Quick Spike*: Implement state machine with in-memory state only.
   - *QA Defensive*: Add file locking and atomic replace for multi-process safety.
   - Assert: pytest tests/test_state_machine.py passes
