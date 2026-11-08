"""Razorpay error_reason → PayRecover taxonomy. Single source of truth for Part III."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReasonKind = Literal["exact", "alias", "transient", "out_of_taxonomy"]


@dataclass(frozen=True)
class ReasonInfo:
    cause: str  # our taxonomy label, or "ambiguous"
    kind: ReasonKind
    confidence: float | None  # rules confidence when kind in {exact, alias}
    is_transient: bool = False


# Documented Razorpay test-mode reasons only (§23). Discover rows are absent until observed.
RAZORPAY_REASONS: dict[str, ReasonInfo] = {
    "international_transaction_not_allowed": ReasonInfo(
        cause="international_transaction_not_allowed",
        kind="exact",
        confidence=0.95,
    ),
    "insufficient_funds": ReasonInfo(
        cause="insufficient_funds",
        kind="exact",
        confidence=0.90,
    ),
    "insufficient_fund": ReasonInfo(
        cause="insufficient_funds",
        kind="alias",
        confidence=0.90,
    ),
    "bank_downtime": ReasonInfo(
        cause="bank_downtime",
        kind="exact",
        confidence=0.88,
        is_transient=True,
    ),
    "issuer_unavailable": ReasonInfo(
        cause="issuer_unavailable",
        kind="exact",
        confidence=0.88,
        is_transient=True,
    ),
    "invalid_otp": ReasonInfo(
        cause="invalid_otp",
        kind="exact",
        confidence=0.90,
    ),
    "incorrect_pin": ReasonInfo(
        cause="incorrect_pin",
        kind="exact",
        confidence=0.90,
    ),
    "authentication_failed": ReasonInfo(
        cause="invalid_otp",
        kind="alias",
        confidence=0.80,
    ),
    "payment_timed_out": ReasonInfo(
        cause="ambiguous",
        kind="transient",
        confidence=None,
        is_transient=True,
    ),
    "gateway_technical_error": ReasonInfo(
        cause="ambiguous",
        kind="transient",
        confidence=None,
        is_transient=True,
    ),
    "payment_cancelled": ReasonInfo(
        cause="customer_abandoned",
        kind="alias",
        confidence=0.85,
    ),
    "customer_abandoned": ReasonInfo(
        cause="customer_abandoned",
        kind="exact",
        confidence=0.85,
    ),
    "card_declined": ReasonInfo(
        cause="ambiguous",
        kind="out_of_taxonomy",
        confidence=None,
    ),
    "card_disabled_for_online_payments": ReasonInfo(
        cause="ambiguous",
        kind="out_of_taxonomy",
        confidence=None,
    ),
    "card_number_invalid": ReasonInfo(
        cause="ambiguous",
        kind="out_of_taxonomy",
        confidence=None,
    ),
    # Observed 2026-11-08 discovery (netbanking + wallet Failure clicks). Same
    # structured reason for both; do NOT mark transient — wallet description said
    # "temporary issue" but netbanking was a bank decline under the same key.
    "payment_failed": ReasonInfo(
        cause="ambiguous",
        kind="out_of_taxonomy",
        confidence=None,
    ),
}


def normalize_reason(raw: str | None) -> str:
    """Lowercase/strip; map aliases onto our taxonomy key."""
    key = (raw or "").strip().lower()
    info = RAZORPAY_REASONS.get(key)
    if info is not None and info.kind == "alias":
        return info.cause
    return key


def lookup_reason(raw: str | None) -> ReasonInfo:
    """Catalogue row for a raw reason; unknown → out_of_taxonomy / ambiguous."""
    key = (raw or "").strip().lower()
    if key in RAZORPAY_REASONS:
        return RAZORPAY_REASONS[key]
    return ReasonInfo(cause="ambiguous", kind="out_of_taxonomy", confidence=None)


def transient_corroborated(raw: str | None) -> bool:
    """True when structured error_reason may corroborate a transient/wait judgment."""
    key = (raw or "").strip().lower()
    info = RAZORPAY_REASONS.get(key)
    if info is not None:
        return info.is_transient
    return key in {
        "bank_downtime",
        "issuer_unavailable",
        "payment_timed_out",
        "gateway_technical_error",
    }
