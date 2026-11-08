from __future__ import annotations

from datetime import UTC, datetime

from payrecover.diagnosis import diagnose
from payrecover.models import Case, DiagnosisPath, PaymentFailure
from tests.helpers import make_settings


def _case(description: str, reason: str = "") -> Case:
    return Case(
        case_id="k1",
        failure=PaymentFailure(
            amount_paise=10000,
            error_reason=reason,
            error_description=description,
            method="card",
        ),
        created_at=datetime.now(UTC),
    )


def test_keyword_matches_insufficient_funds() -> None:
    diagnosis = diagnose(
        _case("Issuer response: NSF — not sufficient funds on the linked account."),
        settings=make_settings(),
        mode="keyword",
    )
    assert diagnosis.path == DiagnosisPath.KEYWORD
    assert diagnosis.cause == "insufficient_funds"


def test_keyword_dispute_escalates_to_ambiguous() -> None:
    diagnosis = diagnose(
        _case("Customer disputes this charge and wants a full refund / chargeback."),
        settings=make_settings(),
        mode="keyword",
    )
    assert diagnosis.cause == "ambiguous"
    assert diagnosis.signals is not None
    assert diagnosis.signals["requests_dispute"] >= 0.7


def test_keyword_no_match_is_ambiguous() -> None:
    diagnosis = diagnose(
        _case("Payment could not be completed. Please try again."),
        settings=make_settings(),
        mode="keyword",
    )
    assert diagnosis.cause == "ambiguous"
