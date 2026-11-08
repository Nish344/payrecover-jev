from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from payrecover.detector import case_from_payment, ingest_failed_payments, label_real_case
from payrecover.diagnosis import diagnose
from payrecover.eval import EXPECTED_VERDICTS, expected_verdict_for_reason, format_real_report
from payrecover.models import ActionType, Case, CaseStatus, Diagnosis, DiagnosisPath, PaymentFailure
from payrecover.policy import decide
from payrecover.runner import run_batch
from payrecover.store import Store
from tests.fakes import FakeJev, MemoryAudit, default_jev_decision
from tests.helpers import make_settings

FIXTURES = Path(__file__).parent / "fixtures" / "razorpay_real"


def _payload(raw_reason: str, **extra: object) -> dict:
    base = {
        "id": f"pay_fixture_{raw_reason}",
        "status": "failed",
        "amount": 10000,
        "currency": "INR",
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": raw_reason,
        "error_description": f"fixture for {raw_reason}",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "international": raw_reason == "international_transaction_not_allowed",
        "notes": {
            "pr_cohort": "fixture",
            "pr_scenario": raw_reason,
            "pr_label": {
                "insufficient_fund": "insufficient_funds",
                "authentication_failed": "invalid_otp",
                "international_transaction_not_allowed": "international_transaction_not_allowed",
                "payment_timed_out": "ambiguous",
                "gateway_technical_error": "ambiguous",
                "card_declined": "ambiguous",
                "card_disabled_for_online_payments": "ambiguous",
                "card_number_invalid": "ambiguous",
                "payment_cancelled": "customer_abandoned",
            }.get(raw_reason, "ambiguous"),
        },
    }
    base.update(extra)
    return base


def test_expected_verdict_matrix_with_auto_and_fake_jev() -> None:
    settings = make_settings(openrouter_api_key=SecretStr("sk-or-test"))
    for raw_reason, expected in EXPECTED_VERDICTS.items():
        case = case_from_payment(_payload(raw_reason), case_id=f"rzp_pay_fixture_{raw_reason}")
        # FakeJev: transient signal for timed_out / gateway; otherwise ambiguous-friendly.
        if raw_reason in {"payment_timed_out", "gateway_technical_error"}:
            fake = FakeJev(
                default_jev_decision(
                    cause="ambiguous",
                    confidence=0.55,
                    is_transient=0.9,
                    customer_fault=0.05,
                    requests_dispute=0.01,
                )
            )
        elif raw_reason in {
            "insufficient_fund",
            "authentication_failed",
            "international_transaction_not_allowed",
        }:
            # Rules should short-circuit; FakeJev unused.
            fake = FakeJev()
        else:
            fake = FakeJev(
                default_jev_decision(
                    cause="ambiguous",
                    confidence=0.5,
                    is_transient=0.1,
                    customer_fault=0.1,
                )
            )
        diagnosis = diagnose(case, settings=settings, mode="auto", jev_client=fake)
        action = decide(case, diagnosis, kill_switch=False)
        assert action.action_type == expected, (
            f"{raw_reason}: got {action.action_type} ({action.rationale}) "
            f"cause={diagnosis.cause} expected={expected}"
        )
        assert expected_verdict_for_reason(raw_reason) == expected


def test_fixtures_ingest_and_dry_run_auto(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    payloads = []
    for path in sorted(FIXTURES.glob("pay_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != "failed":
            continue
        payloads.append(data)
    assert payloads
    ingested = ingest_failed_payments(store, payloads, raw_dir=tmp_path / "raw")
    assert ingested
    settings = make_settings(
        db_path=tmp_path / "t.db",
        openrouter_api_key=SecretStr("sk-or-test"),
    )
    fake = FakeJev(default_jev_decision(cause="ambiguous", confidence=0.4))
    audit = MemoryAudit()

    def _diagnose(case: Case) -> Diagnosis:
        return diagnose(case, settings=settings, mode="auto", jev_client=fake)

    def _decide(case: Case, diagnosis: Diagnosis):
        return decide(case, diagnosis, kill_switch=False)

    finished = run_batch(
        store,
        settings=settings,
        audit=audit,
        diagnose=_diagnose,
        decide=_decide,
        client=None,
        dry_run=True,
    )
    assert len(finished) == len(ingested)


def test_format_real_report_mentions_limitations() -> None:
    from payrecover.eval import ArmResult

    empty = ArmResult(
        arm="rules",
        split="real",
        labeled=0,
        correct=0,
        accuracy=0.0,
        accuracy_ci_low=0.0,
        accuracy_ci_high=1.0,
        path_counts={},
        cost_usd=0.0,
        cost_per_1k=0.0,
        by_cause={},
        by_family={},
        predictions=(),
    )
    text = format_real_report([empty])
    assert "Not a benchmark" in text
    assert "In-taxonomy accuracy" in text
    assert "payment_cancelled" in text


def test_label_generated_from_fixture_notes() -> None:
    payload = json.loads((FIXTURES / "pay_gen_insufficient.json").read_text())
    truth = label_real_case(payload)
    assert truth.label_source == "generated"
    assert truth.true_cause == "insufficient_funds"
    assert truth.split == "real"
