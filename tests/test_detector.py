from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from payrecover.detector import (
    case_from_payment,
    export_fixture,
    ingest_failed_payments,
    label_real_case,
    list_failed_payments,
    notes_as_dict,
    parse_since,
    redact_payment,
    upsert_detected,
)
from payrecover.models import Case, CaseStatus, PaymentFailure
from payrecover.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "razorpay_real"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_case_from_payment_maps_reason_and_international() -> None:
    case = case_from_payment(
        {
            "id": "pay_TVGlLnELbwZeV2",
            "order_id": "order_x",
            "amount": 10000,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "international": True,
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "international_transaction_not_allowed",
            "error_source": "business",
            "error_step": "payment_initiation",
            "error_description": "domestic cards only",
        },
        case_id="c1",
    )
    assert case.failure.error_reason == "international_transaction_not_allowed"
    assert case.failure.international is True
    assert case.failure.error_code == "BAD_REQUEST_ERROR"


def test_redetect_does_not_reset_terminal(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    existing = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=100, payment_id="pay_1"),
        status=CaseStatus.RECOVERED,
        created_at=datetime.now(UTC),
    )
    store.upsert_case(existing)
    incoming = case_from_payment({"id": "pay_1", "amount": 100, "status": "failed"}, case_id="c1")
    result = upsert_detected(store, incoming)
    assert result.status == CaseStatus.RECOVERED


def test_ingest_skips_non_failed_and_uses_rzp_prefix(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    ingested = ingest_failed_payments(
        store,
        [
            {"id": "pay_ok", "status": "captured", "amount": 10000},
            {
                "id": "pay_fail",
                "status": "failed",
                "amount": 5000,
                "error_reason": "insufficient_funds",
            },
            {"id": "", "status": "failed", "amount": 100},
        ],
        raw_dir=None,
    )
    assert [case.case_id for case in ingested] == ["rzp_pay_fail"]
    stored = store.get_case("rzp_pay_fail")
    assert stored is not None
    assert stored.failure.payment_id == "pay_fail"
    assert stored.failure.error_reason == "insufficient_funds"
    truth = store.get_ground_truth("rzp_pay_fail")
    assert truth is not None
    assert truth.split == "real"
    assert truth.label_source == "derived"


def test_every_fixture_ingests(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    payloads = [_load_fixture(path.name) for path in sorted(FIXTURES.glob("*.json"))]
    assert payloads
    ingested = ingest_failed_payments(store, payloads, raw_dir=tmp_path / "raw")
    assert len(ingested) == len(payloads)
    for case in ingested:
        assert store.get_ground_truth(case.case_id) is not None


def test_label_precedence_generated_beats_derived() -> None:
    payload = _load_fixture("pay_gen_insufficient.json")
    # Even if manual says otherwise, generated wins when pr_label present.
    truth = label_real_case(
        payload,
        overrides={
            "pay_gen_insufficient": {"true_cause": "ambiguous", "note": "nope"},
        },
    )
    assert truth.label_source == "generated"
    assert truth.true_cause == "insufficient_funds"
    assert truth.raw_reason == "insufficient_fund"
    assert truth.family == "real:insufficient_fund"


def test_label_precedence_manual_beats_derived() -> None:
    payload = _load_fixture("pay_TVGlLnELbwZeV2.json")
    truth = label_real_case(
        payload,
        overrides={
            "pay_TVGlLnELbwZeV2": {
                "true_cause": "international_transaction_not_allowed",
                "note": "manual confirm",
            }
        },
    )
    assert truth.label_source == "manual"
    assert truth.true_cause == "international_transaction_not_allowed"


def test_label_derived_when_no_tags() -> None:
    payload = _load_fixture("pay_TVGlLnELbwZeV2.json")
    truth = label_real_case(payload)
    assert truth.label_source == "derived"
    assert truth.true_cause == "international_transaction_not_allowed"


def test_order_notes_fallback_and_cohort_filter(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    payload = _load_fixture("pay_order_notes_fallback.json")

    def fetch_order(order_id: str) -> dict:
        assert order_id == "order_with_pr_notes"
        return {
            "id": order_id,
            "notes": {
                "pr_cohort": "real-v1",
                "pr_scenario": "card_declined",
                "pr_label": "ambiguous",
            },
        }

    ingested = ingest_failed_payments(
        store,
        [payload],
        cohort="real-v1",
        fetch_order=fetch_order,
        raw_dir=None,
    )
    assert len(ingested) == 1
    truth = store.get_ground_truth("rzp_pay_order_notes_fallback")
    assert truth is not None
    assert truth.label_source == "generated"
    assert truth.true_cause == "ambiguous"

    store2 = Store(tmp_path / "t2.db")
    skipped = ingest_failed_payments(
        store2,
        [payload],
        cohort="other",
        fetch_order=fetch_order,
        raw_dir=None,
    )
    assert skipped == []


def test_redaction_removes_pii_keeps_last4(tmp_path: Path) -> None:
    payload = {
        "id": "pay_pii",
        "email": "secret@example.com",
        "contact": "+919999999999",
        "card": {"name": "Ada Lovelace", "last4": "4242", "network": "Visa"},
        "notes": {
            "pr_cohort": "real-v1",
            "pr_label": "ambiguous",
            "internal": "drop-me",
        },
        "status": "failed",
        "amount": 100,
    }
    redacted = redact_payment(payload)
    assert "email" not in redacted
    assert "contact" not in redacted
    assert "name" not in redacted["card"]
    assert redacted["card"]["last4"] == "4242"
    assert redacted["notes"] == {
        "pr_cohort": "real-v1",
        "pr_label": "ambiguous",
    }
    path = export_fixture(payload, directory=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "secret@example.com" not in json.dumps(saved)


def test_pagination_stops_on_short_page() -> None:
    pages = [
        {"items": [{"id": f"pay_{i}", "status": "failed", "amount": 100} for i in range(3)]},
        {"items": [{"id": "pay_last", "status": "failed", "amount": 100}]},
    ]

    class Client:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def list_payments(self, **kwargs: object) -> dict:
            self.calls.append(dict(kwargs))
            skip = int(kwargs.get("skip") or 0)  # type: ignore[arg-type]
            idx = skip // 3
            return pages[idx]

    client = Client()
    items = list_failed_payments(client, paginate_all=True, page_size=3)
    assert len(items) == 4
    assert len(client.calls) == 2
    assert client.calls[0]["skip"] == 0
    assert client.calls[1]["skip"] == 3


def test_parse_since_relative_and_iso() -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    ts = parse_since("1d", now=now)
    assert ts == int(datetime(2026, 11, 7, 12, 0, tzinfo=UTC).timestamp())
    ts2 = parse_since("2026-11-01T00:00:00+00:00", now=now)
    assert ts2 == int(datetime(2026, 11, 1, tzinfo=UTC).timestamp())


def test_notes_as_dict_handles_empty_list() -> None:
    assert notes_as_dict([]) == {}
    assert notes_as_dict(None) == {}
    assert notes_as_dict({"a": 1}) == {"a": "1"}


def test_seed_keep_real_default(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    real_payload = _load_fixture("pay_gen_insufficient.json")
    ingest_failed_payments(store, [real_payload], raw_dir=None)
    from payrecover.simulator.batchgen import seed_batch

    # Simulate force wipe keeping real
    store.wipe(keep_real=True)
    assert store.get_case("rzp_pay_gen_insufficient") is not None
    assert store.get_ground_truth("rzp_pay_gen_insufficient") is not None
    seed_batch(store, seed=42, profile="classic")
    assert store.get_case("rzp_pay_gen_insufficient") is not None
    assert store.case_count() > 1
