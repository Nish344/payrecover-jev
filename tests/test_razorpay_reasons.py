from __future__ import annotations

from payrecover.razorpay_reasons import (
    RAZORPAY_REASONS,
    lookup_reason,
    normalize_reason,
    transient_corroborated,
)

# §23 documented rows (discover rows must stay absent until observed).
_DOCUMENTED = {
    "insufficient_fund": ("insufficient_funds", "alias"),
    "authentication_failed": ("invalid_otp", "alias"),
    "payment_timed_out": ("ambiguous", "transient"),
    "gateway_technical_error": ("ambiguous", "transient"),
    "international_transaction_not_allowed": (
        "international_transaction_not_allowed",
        "exact",
    ),
    "payment_cancelled": ("customer_abandoned", "alias"),
    "card_declined": ("ambiguous", "out_of_taxonomy"),
    "card_disabled_for_online_payments": ("ambiguous", "out_of_taxonomy"),
    "card_number_invalid": ("ambiguous", "out_of_taxonomy"),
}


def test_every_documented_reason_maps() -> None:
    for raw, (cause, kind) in _DOCUMENTED.items():
        assert raw in RAZORPAY_REASONS
        info = RAZORPAY_REASONS[raw]
        assert info.cause == cause
        assert info.kind == kind


def test_discover_rows_absent() -> None:
    for key in (
        "upi_failure",
        "netbanking_failure",
        "wallet_failure",
        "short_otp",
        "failure@razorpay",
    ):
        assert key not in RAZORPAY_REASONS


def test_observed_payment_failed_is_out_of_taxonomy_not_transient() -> None:
    info = RAZORPAY_REASONS["payment_failed"]
    assert info.cause == "ambiguous"
    assert info.kind == "out_of_taxonomy"
    assert info.is_transient is False
    assert transient_corroborated("payment_failed") is False


def test_unknown_is_out_of_taxonomy_ambiguous() -> None:
    info = lookup_reason("totally_unknown_reason")
    assert info.kind == "out_of_taxonomy"
    assert info.cause == "ambiguous"
    assert lookup_reason(None).cause == "ambiguous"
    assert lookup_reason("").cause == "ambiguous"


def test_normalize_aliases_and_idempotent() -> None:
    assert normalize_reason("insufficient_fund") == "insufficient_funds"
    assert normalize_reason("Insufficient_Fund") == "insufficient_funds"
    assert normalize_reason("authentication_failed") == "invalid_otp"
    assert normalize_reason("  BANK_DOWNTIME ") == "bank_downtime"
    assert normalize_reason("payment_timed_out") == "payment_timed_out"
    for raw in list(_DOCUMENTED) + ["bank_downtime", "issuer_unavailable", None, ""]:
        once = normalize_reason(raw)
        assert normalize_reason(once) == once


def test_transient_corroborated_set() -> None:
    for raw in (
        "bank_downtime",
        "issuer_unavailable",
        "payment_timed_out",
        "gateway_technical_error",
        "PAYMENT_TIMED_OUT",
    ):
        assert transient_corroborated(raw) is True
    for raw in (
        "insufficient_fund",
        "insufficient_funds",
        "authentication_failed",
        "card_declined",
        "payment_cancelled",
        None,
        "",
        "nope",
    ):
        assert transient_corroborated(raw) is False


def test_authentication_failed_alias_confidence() -> None:
    assert RAZORPAY_REASONS["authentication_failed"].confidence == 0.80
    assert RAZORPAY_REASONS["invalid_otp"].confidence == 0.90
