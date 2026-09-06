"""Automated tests guaranteeing first-class support for serious human coders and systems builders."""

from __future__ import annotations

import pytest

from auto_reply_route.classifier import HumanIntentClassifier, PromptIntentTier
from auto_reply_route.prompt_matrix import MatrixBeamRouter


@pytest.fixture
def router():
    return MatrixBeamRouter()


def test_serious_coder_go_raft_concurrency(router):
    prompt = "[4] Implement Raft consensus quorum in cluster/raft.go with lease reads"
    intent = HumanIntentClassifier.classify(prompt)
    assert intent.tier == PromptIntentTier.CODE_BUILD
    assert intent.suggested_steps == 4
    assert intent.explicit_prefix_override is True

    manifest = router.map_route_from_matrix(prompt, num_steps=intent.suggested_steps)
    entities = manifest.metadata["entities"]
    assert entities["target_file"] == "cluster/raft.go"
    assert entities["test_file"] == "cluster/raft_test.go"
    assert manifest.metadata["domain"] == "concurrency_async"
    assert "go vet cluster/raft.go passes" in manifest.steps[0].assertions[0]


def test_serious_coder_rust_toctou_atomics(router):
    prompt = "Fix TOCTOU race condition in storage/atomic_rename.rs with O_EXCL file lock"
    manifest = router.map_route_from_matrix(prompt, num_steps=2)
    entities = manifest.metadata["entities"]
    assert entities["target_file"] == "storage/atomic_rename.rs"
    assert entities["test_file"] == "tests/test_atomic_rename.rs"
    assert manifest.metadata["domain"] == "concurrency_async"


def test_serious_coder_ast_compiler_optimization(router):
    prompt = "Refactor AST traversal in compiler/parser.py to eliminate exponential backtracking"
    manifest = router.map_route_from_matrix(prompt, num_steps=2)
    entities = manifest.metadata["entities"]
    assert entities["target_file"] == "compiler/parser.py"
    assert manifest.metadata["domain"] == "compiler_ast"
    assert "compiler/parser.py" in manifest.steps[0].primary_prompt


def test_serious_coder_multi_region_replication_clean_subject(router):
    prompt = "[12] Multi-region PostgreSQL logical replication failover in db/replication.py"
    manifest = router.map_route_from_matrix(prompt, num_steps=12)
    entities = manifest.metadata["entities"]
    assert entities["target_file"] == "db/replication.py"
    assert manifest.metadata["domain"] == "database_orm"
    # Ensure explicit prefix [12] did NOT leak into the extracted subject
    assert "[12]" not in entities["subject"]
    assert "Multi-region PostgreSQL logical replication failover" in entities["subject"]


def test_serious_coder_ebpf_socket_c_code(router):
    prompt = "Add eBPF socket filter for SYN flood protection in net/filter.c"
    manifest = router.map_route_from_matrix(prompt, num_steps=2)
    entities = manifest.metadata["entities"]
    assert entities["target_file"] == "net/filter.c"
    assert entities["test_file"] == "tests/test_filter.c"
    assert manifest.metadata["domain"] == "security_auth"
