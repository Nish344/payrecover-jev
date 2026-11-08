from __future__ import annotations

from pathlib import Path

from payrecover.simulator.batchgen import seed_batch
from payrecover.simulator.dataset import assign_splits, build_specs, corpus_summary
from payrecover.store import Store


def test_corpus_meets_size_and_has_families() -> None:
    specs = build_specs()
    assert len(specs) >= 240
    families = {spec.family for spec in specs}
    assert {
        "clean",
        "unmapped",
        "hard_ambiguous",
        "conflicting",
        "dispute",
        "adversarial",
    }.issubset(families)


def test_split_is_deterministic_and_disjoint() -> None:
    a = assign_splits(build_specs(), seed=100)
    b = assign_splits(build_specs(), seed=100)
    assert [(s.true_cause, s.family, s.description, sp) for s, sp in a] == [
        (s.true_cause, s.family, s.description, sp) for s, sp in b
    ]
    train = {id(spec) for spec, split in a if split == "train"}
    # identity won't work across rebuilds; use description+family key
    train_keys = {(s.family, s.description, s.true_cause) for s, sp in a if sp == "train"}
    test_keys = {(s.family, s.description, s.true_cause) for s, sp in a if sp == "test"}
    assert train_keys.isdisjoint(test_keys)
    assert train_keys and test_keys
    summary = corpus_summary(a)
    assert summary["total"] == len(a)
    assert summary["splits"]["train"] + summary["splits"]["test"] == len(a)


def test_bench_seed_persists_split_labels(tmp_path: Path) -> None:
    store = Store(tmp_path / "bench.db")
    seed_batch(store, seed=100, profile="bench")
    truths = store.list_ground_truths()
    assert store.case_count() >= 240
    splits = {truth.split for truth in truths.values()}
    assert splits == {"train", "test"}
    families = {truth.family for truth in truths.values()}
    assert "adversarial" in families
    assert "unmapped" in families
