from __future__ import annotations

import json
from pathlib import Path
import pytest

from auto_reply_route.miner import (
    BranchCandidate,
    IntentCluster,
    IntentClusterer,
    IntentStratum,
    PromptNormalizer,
    PromptRouteMiner,
    SequenceMarkovModel,
)


# ============================================================================
# 1. Normalization & Slot Masking Tests
# ============================================================================

class TestPromptNormalizer:
    @pytest.fixture
    def normalizer(self) -> PromptNormalizer:
        return PromptNormalizer()

    def test_extract_user_request_with_xml_tags(self, normalizer: PromptNormalizer):
        raw = """<USER_REQUEST>
Fix the bug in server.py
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-09-02T13:27:05-07:00.
The user has uploaded 1 image(s):
- /tmp/antigravity/brain/abc/media.png
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` to Flash.
</USER_SETTINGS_CHANGE>"""
        extracted = normalizer.extract_user_request(raw)
        assert extracted == "Fix the bug in server.py"

    def test_extract_user_request_without_xml_tags(self, normalizer: PromptNormalizer):
        raw = "Create a new database schema for user profiles"
        extracted = normalizer.extract_user_request(raw)
        assert extracted == "Create a new database schema for user profiles"

    def test_slot_masking_file_paths(self, normalizer: PromptNormalizer):
        # Dynamic path using Path.home() and generic mock path: -> [PATH:py]
        home_foo = Path.home() / "foo.py"
        text1 = f"Error in {home_foo} line 12"
        masked1 = normalizer.mask_slots(text1)
        assert "[PATH:py]" in masked1

        generic_path = "/mock/dev/project/foo.py"
        assert "[PATH:py]" in normalizer.mask_slots(f"Error in {generic_path} line 12")

        text2 = "Check C:\\Users\\Administrator\\project\\app.ts and ./src/miner.py and /var/log/syslog"
        masked2 = normalizer.mask_slots(text2)
        assert "[PATH:ts]" in masked2
        assert "[PATH:py]" in masked2
        assert "[PATH]" in masked2

        text3 = "edit components/Button.tsx and style.css"
        masked3 = normalizer.mask_slots(text3)
        assert "[PATH:tsx]" in masked3
        assert "[PATH:css]" in masked3

    def test_slot_masking_urls_and_localhost(self, normalizer: PromptNormalizer):
        text = "Service at http://localhost:3000 and https://api.github.com/v1/repos and 127.0.0.1:8080"
        masked = normalizer.mask_slots(text)
        assert "http://localhost:3000" not in masked
        assert "https://api.github.com" not in masked
        assert "[URL]" in masked

    def test_slot_masking_git_hashes(self, normalizer: PromptNormalizer):
        sha40 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        text = f"Revert commit {sha40} or commit a1b2c3d"
        masked = normalizer.mask_slots(text)
        assert sha40 not in masked
        assert "[GIT_HASH]" in masked

    def test_slot_masking_uuids(self, normalizer: PromptNormalizer):
        uuid_str = "12345678-1234-1234-1234-123456789abc"
        text = f"Entity with id {uuid_str} not found"
        masked = normalizer.mask_slots(text)
        assert uuid_str not in masked
        assert "[UUID]" in masked

    def test_slot_masking_ports_and_numbers(self, normalizer: PromptNormalizer):
        text = "Listen on port 8080 at line 42 with 5 retries, or :9000"
        masked = normalizer.mask_slots(text)
        assert "[PORT]" in masked
        assert "[NUM]" in masked

    def test_strip_fluff(self, normalizer: PromptNormalizer):
        text = "Could you please kindly fix the issue, thank you!"
        stripped = normalizer.strip_fluff(text)
        assert "please" not in stripped.lower()
        assert "kindly" not in stripped.lower()
        assert "thank you" not in stripped.lower()
        assert "fix the issue" in stripped

    def test_expand_telegraphic_prompts(self, normalizer: PromptNormalizer):
        assert normalizer.expand_telegraphic("ok") == "proceed with plan"
        assert normalizer.expand_telegraphic("commit") == "commit and release changes"
        assert normalizer.expand_telegraphic("why?") == "explain root cause"
        assert normalizer.expand_telegraphic("test") == "run tests and verify behavior"

        # Context-aware expansion
        assert normalizer.expand_telegraphic("ok", context_stratum=IntentStratum.ARCH_DESIGN) == "proceed with implementation plan"
        assert normalizer.expand_telegraphic("commit", context_stratum=IntentStratum.VERIFY_QA) == "commit and release verified changes"

    def test_full_normalization_pipeline(self, normalizer: PromptNormalizer):
        home_path = Path.home() / "foo.py"
        raw = f"""<USER_REQUEST>
Please fix the bug at {home_path}:8080 on http://localhost:3000!
</USER_REQUEST>
<ADDITIONAL_METADATA>
info
</ADDITIONAL_METADATA>"""
        norm = normalizer.normalize(raw)
        assert "[PATH:py]" in norm
        assert "[PORT]" in norm
        assert "[URL]" in norm
        assert "please" not in norm.lower()


# ============================================================================
# 2. Stratum Categorization & Clustering Tests
# ============================================================================

class TestIntentClusterer:
    @pytest.fixture
    def clusterer(self) -> IntentClusterer:
        return IntentClusterer()

    def test_stratum_categorization(self, clusterer: IntentClusterer):
        test_cases = [
            ("Design the system architecture and evaluate trade-offs", IntentStratum.ARCH_DESIGN),
            ("Create architectural blueprint and database schema spec", IntentStratum.ARCH_DESIGN),
            ("Implement user authentication module and write endpoints", IntentStratum.SCAFFOLD_BUILD),
            ("Add scaffold boilerplate for new frontend component", IntentStratum.SCAFFOLD_BUILD),
            ("Fix syntax error and broken traceback in [PATH:py]", IntentStratum.DEBUG_REPAIR),
            ("Resolve bug crash exception in data processing loop", IntentStratum.DEBUG_REPAIR),
            ("Run pytest and check coverage with screenshot audit", IntentStratum.VERIFY_QA),
            ("Verify accessibility and lint all typescript files", IntentStratum.VERIFY_QA),
            ("Commit changes, tag release v1.0, and deploy with git push", IntentStratum.RELEASE_OPS),
            ("Create pull request and ship docker container", IntentStratum.RELEASE_OPS),
        ]
        for prompt, expected in test_cases:
            assert clusterer.categorize_stratum(prompt) == expected

    def test_ngram_jaccard_similarity(self, clusterer: IntentClusterer):
        sim_same = clusterer.jaccard_similarity("fix bug in [PATH:py]", "fix bug in [PATH:py]")
        assert sim_same == 1.0

        sim_overlap = clusterer.jaccard_similarity("fix bug in [PATH:py]", "fix syntax bug in [PATH:py]")
        assert 0.3 < sim_overlap < 1.0

        sim_diff = clusterer.jaccard_similarity("design architecture plan", "commit and git push")
        assert sim_diff == 0.0

    def test_clustering_and_medoid_extraction(self, clusterer: IntentClusterer):
        prompts = [
            {"raw": "Please fix bug in app.py", "normalized": "fix bug in [PATH:py]"},
            {"raw": "Could you fix the bug in auth.py?", "normalized": "fix bug in [PATH:py]"},
            {"raw": "There is a bug in router.py", "normalized": "bug in [PATH:py]"},
            {"raw": "Design architecture spec", "normalized": "design architecture spec"},
            {"raw": "Run pytest and verify", "normalized": "run pytest and verify"},
        ]
        clusters = clusterer.cluster_prompts(prompts)
        assert len(clusters) >= 3

        # Locate the DEBUG_REPAIR cluster
        debug_clusters = [c for c in clusters if c.stratum == IntentStratum.DEBUG_REPAIR]
        assert len(debug_clusters) == 1
        debug_c = debug_clusters[0]
        assert debug_c.frequency == 3
        assert "[PATH:py]" in debug_c.medoid
        # Medoid has a real raw representative prompt
        assert debug_c.raw_medoid in ["Please fix bug in app.py", "Could you fix the bug in auth.py?", "There is a bug in router.py"]


# ============================================================================
# 3. Markov Sequence Modeling & MMR Diversity Ranking Tests
# ============================================================================

class TestSequenceMarkovModel:
    @pytest.fixture
    def markov_model(self) -> SequenceMarkovModel:
        return SequenceMarkovModel(lambda_2=0.7, lambda_1=0.8, mmr_lambda=0.6)

    @pytest.fixture
    def sample_clusters(self) -> dict[str, IntentCluster]:
        return {
            "c_arch": IntentCluster(
                cluster_id="c_arch",
                stratum=IntentStratum.ARCH_DESIGN,
                medoid="design system architecture and plan",
                raw_medoid="Plan the system architecture",
                frequency=5,
            ),
            "c_build": IntentCluster(
                cluster_id="c_build",
                stratum=IntentStratum.SCAFFOLD_BUILD,
                medoid="implement core module code",
                raw_medoid="Implement the core module",
                frequency=8,
            ),
            "c_debug": IntentCluster(
                cluster_id="c_debug",
                stratum=IntentStratum.DEBUG_REPAIR,
                medoid="fix syntax error and traceback",
                raw_medoid="Fix the traceback error",
                frequency=4,
            ),
            "c_verify": IntentCluster(
                cluster_id="c_verify",
                stratum=IntentStratum.VERIFY_QA,
                medoid="run automated tests and verify",
                raw_medoid="Run all tests to verify",
                frequency=7,
            ),
            "c_release": IntentCluster(
                cluster_id="c_release",
                stratum=IntentStratum.RELEASE_OPS,
                medoid="commit and push release tag",
                raw_medoid="Commit and push release",
                frequency=6,
            ),
        }

    def test_variable_order_transitions_and_backoff(
        self,
        markov_model: SequenceMarkovModel,
        sample_clusters: dict[str, IntentCluster],
    ):
        sequences = [
            ["c_arch", "c_build", "c_verify", "c_release"],
            ["c_arch", "c_build", "c_debug", "c_verify", "c_release"],
            ["c_build", "c_verify", "c_release"],
        ]
        markov_model.fit(sequences, sample_clusters)

        # 1. Order 2 Transition Probability
        p_verify_from_arch_build = markov_model.transition_probability(
            "c_verify", history=["c_arch", "c_build"]
        )
        p_debug_from_arch_build = markov_model.transition_probability(
            "c_debug", history=["c_arch", "c_build"]
        )
        assert p_verify_from_arch_build > 0.0
        assert p_debug_from_arch_build > 0.0

        # Distribution sums to 1.0
        dist = markov_model.get_transition_distribution(["c_arch", "c_build"])
        assert pytest.approx(sum(dist.values()), rel=1e-4) == 1.0

        # 2. Backoff to Order 1 when Order 2 unseen
        p_unseen_order2 = markov_model.transition_probability(
            "c_verify", history=["c_debug", "c_build"]
        )
        assert p_unseen_order2 > 0.0  # backed off to c_build -> c_verify

        # 3. Backoff to Order 0 (unigram) when Order 1 unseen
        p_unseen_order1 = markov_model.transition_probability(
            "c_arch", history=["c_unknown"]
        )
        assert p_unseen_order1 > 0.0

    def test_mmr_diversity_ranking_functional_roles(
        self,
        markov_model: SequenceMarkovModel,
        sample_clusters: dict[str, IntentCluster],
    ):
        sequences = [
            ["c_arch", "c_build", "c_verify", "c_release"],
            ["c_arch", "c_build", "c_debug", "c_verify", "c_release"],
            ["c_arch", "c_build", "c_verify", "c_release"],
        ]
        markov_model.fit(sequences, sample_clusters)

        # From state c_build, generate 4-way diverse branch candidates
        branches = markov_model.generate_branch_candidates(["c_arch", "c_build"], top_k=4)

        assert len(branches) == 4

        # Verify exact 1st-4th functional roles
        assert branches[0].rank == 1
        assert branches[0].role == "primary_forward"

        assert branches[1].rank == 2
        assert branches[1].role == "qa_defensive"
        assert branches[1].stratum in (IntentStratum.VERIFY_QA.value, IntentStratum.DEBUG_REPAIR.value)

        assert branches[2].rank == 3
        assert branches[2].role == "alternative"

        assert branches[3].rank == 4
        assert branches[3].role == "fallback"

        # Ensure all 4 candidates are unique intents (diversity check)
        selected_ids = [b.intent_id for b in branches]
        assert len(set(selected_ids)) == 4


# ============================================================================
# 4. Route Markdown Export Tests
# ============================================================================

class TestRouteExport:
    def test_export_route_markdown(self):
        miner = PromptRouteMiner()
        mock_route_data = {
            "route_id": "route_dev_cycle",
            "title": "Autonomous Engineering Canonical Path",
            "total_sessions": 10,
            "total_transitions": 24,
            "total_intents": 5,
            "steps": [
                {
                    "step_index": 1,
                    "intent_id": "intent_arch_1",
                    "stratum": "ARCH_DESIGN",
                    "medoid": "design system architecture and plan",
                    "raw_medoid": "Can we plan the architecture?",
                    "frequency": 10,
                    "branches": [
                        {
                            "rank": 1,
                            "role": "primary_forward",
                            "intent_id": "intent_build_1",
                            "stratum": "SCAFFOLD_BUILD",
                            "medoid": "implement core module code",
                            "raw_prompt": "Let's implement the core module",
                            "probability": 0.65,
                            "score": 0.95,
                        },
                        {
                            "rank": 2,
                            "role": "qa_defensive",
                            "intent_id": "intent_verify_1",
                            "stratum": "VERIFY_QA",
                            "medoid": "run automated tests and verify",
                            "raw_prompt": "Run tests to verify",
                            "probability": 0.20,
                            "score": 0.55,
                        },
                        {
                            "rank": 3,
                            "role": "alternative",
                            "intent_id": "intent_arch_alt",
                            "stratum": "ARCH_DESIGN",
                            "medoid": "evaluate alternative blueprint",
                            "raw_prompt": "Consider an alternative blueprint",
                            "probability": 0.10,
                            "score": 0.40,
                        },
                        {
                            "rank": 4,
                            "role": "fallback",
                            "intent_id": "intent_ops_1",
                            "stratum": "RELEASE_OPS",
                            "medoid": "commit draft and review diff",
                            "raw_prompt": "Commit work in progress",
                            "probability": 0.05,
                            "score": 0.35,
                        },
                    ],
                }
            ],
        }

        md = miner.export_route_markdown(mock_route_data)

        # Markdown format assertions
        assert "# Auto-Reply Route Map: Autonomous Engineering Canonical Path" in md
        assert "```mermaid" in md
        assert "flowchart TD" in md
        assert "Step1" in md
        assert "Primary Forward" in md
        assert "QA / Defensive" in md
        assert "Alternative" in md
        assert "Fallback / Exit" in md
        assert "65.0%" in md


# ============================================================================
# 5. End-to-End Mining with Synthetic Multi-Turn Fixture
# ============================================================================

class TestEndToEndMining:
    @pytest.fixture
    def synthetic_transcripts_dir(self, tmp_path: Path) -> Path:
        transcripts_dir = tmp_path / "mock_transcripts"
        transcripts_dir.mkdir()

        home_db_path = Path.home() / "dev" / "db.py"
        # Session 1: Plan -> Build -> Verify -> Release
        session_1 = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Plan the database schema and architecture</USER_REQUEST>"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Here is the schema plan."},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"<USER_REQUEST>Implement the database models in {home_db_path}</USER_REQUEST>"},
            {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Models created."},
            {"step_index": 4, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Run pytest to verify all models</USER_REQUEST>"},
            {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "All tests pass."},
            {"step_index": 6, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Commit and push release tag v1.0</USER_REQUEST>"},
        ]

        # Session 2: Plan -> Build -> Debug -> Verify -> Release
        session_2 = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Please design architecture for authentication service</USER_REQUEST>"},
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Build the auth endpoint code in src/auth.py</USER_REQUEST>"},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Fix syntax error crash traceback at line 42</USER_REQUEST>"},
            {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Run pytest and check coverage</USER_REQUEST>"},
            {"step_index": 4, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Commit changes to git and push</USER_REQUEST>"},
        ]

        # Session 3: Build -> Verify -> Release
        session_3 = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Create helper utility functions in utils.py</USER_REQUEST>"},
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Run test suite and verify checks</USER_REQUEST>"},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>Commit and tag release</USER_REQUEST>"},
        ]

        for idx, sess in enumerate([session_1, session_2, session_3], start=1):
            file_path = transcripts_dir / f"session_{idx}.jsonl"
            with open(file_path, "w", encoding="utf-8") as f:
                for line in sess:
                    f.write(json.dumps(line) + "\n")

        return transcripts_dir

    def test_mine_transcripts_end_to_end(self, synthetic_transcripts_dir: Path):
        miner = PromptRouteMiner()
        routes = miner.mine_transcripts([str(synthetic_transcripts_dir)])

        assert len(routes) == 1
        route = routes[0]

        assert route["total_sessions"] == 3
        assert route["total_transitions"] > 0
        assert len(route["steps"]) >= 3

        # Verify step attributes and 4-way diverse branching
        for step in route["steps"]:
            assert "step_index" in step
            assert "stratum" in step
            assert "medoid" in step
            assert "raw_medoid" in step
            assert len(step["branches"]) == 4

            roles = [b["role"] for b in step["branches"]]
            assert roles == ["primary_forward", "qa_defensive", "alternative", "fallback"]

        # Verify Markdown export
        md = miner.export_route_markdown(route)
        assert len(md) > 100
        assert "```mermaid" in md
        assert "flowchart TD" in md
        assert "🟢 Primary Forward" in md
        assert "🛡️ QA / Defensive" in md
