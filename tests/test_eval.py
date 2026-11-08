from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from payrecover.eval import evaluate_arms, format_eval_report
from payrecover.simulator.batchgen import JEV_BATCH_SIZE, seed_batch
from payrecover.store import Store
from tests.fakes import FakeJev, default_jev_decision
from tests.helpers import make_settings


def test_jev_profile_seed_has_true_cause_and_empty_reason(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=43, profile="jev")
    assert store.case_count() == JEV_BATCH_SIZE
    for case in store.list_cases():
        assert (case.failure.error_reason or "") == ""
        truth = store.get_ground_truth(case.case_id)
        assert truth is not None
        assert truth.true_cause is not None


def test_evaluate_rules_arm_on_classic_batch(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=42, profile="classic")
    settings = make_settings(db_path=store.path)
    results = evaluate_arms(store, settings=settings, arms=["rules"], split="all")
    assert len(results) == 1
    assert results[0].labeled == 80
    assert results[0].accuracy >= 0.8
    assert results[0].accuracy_ci_low <= results[0].accuracy <= results[0].accuracy_ci_high
    text = format_eval_report(results)
    assert "arm=rules" in text
    assert "Wilson" in text or "95%" in text


def test_evaluate_keyword_on_bench(tmp_path: Path) -> None:
    store = Store(tmp_path / "bench.db")
    seed_batch(store, seed=100, profile="bench")
    settings = make_settings(db_path=store.path)
    results = evaluate_arms(
        store,
        settings=settings,
        arms=["keyword", "rules"],
        split="test",
    )
    assert results[0].arm == "keyword"
    assert results[0].labeled > 0
    by_arm = {row.arm: row for row in results}
    assert by_arm["keyword"].accuracy > 0.3
    assert by_arm["rules"].labeled == by_arm["keyword"].labeled


def test_evaluate_jev_arm_with_fake(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    seed_batch(store, seed=43, profile="jev")
    settings = make_settings(
        db_path=store.path,
        openrouter_api_key=SecretStr("sk-or-test"),
    )
    fake = FakeJev(default_jev_decision(cause="insufficient_funds"))
    results = evaluate_arms(
        store,
        settings=settings,
        arms=["jev"],
        split="all",
        jev_client=fake,
        use_cache=False,
    )
    assert results[0].arm == "jev"
    assert results[0].labeled == JEV_BATCH_SIZE
    assert results[0].path_counts.get("jev", 0) == JEV_BATCH_SIZE


def test_response_cache_roundtrip(tmp_path: Path) -> None:
    from payrecover.eval import ResponseCache

    cache = ResponseCache(tmp_path / "cache")
    cache.put("k", {"cause": "ambiguous", "confidence": 0.4})
    assert cache.get("k")["cause"] == "ambiguous"
