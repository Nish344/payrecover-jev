from __future__ import annotations

import random
from datetime import UTC, datetime

from payrecover.models import Case, CaseStatus, GroundTruth, PaymentFailure
from payrecover.store import Store

BATCH_SIZE = 80
JEV_BATCH_SIZE = 40

PROFILE_COUNTS: tuple[tuple[str, int], ...] = (
    ("pays_on_first_link", 16),
    ("pays_after_reminder", 14),
    ("pays_if_fast", 8),
    ("pays_after_wait", 8),
    ("never_pays", 18),
    ("opts_out", 10),
    ("high_value", 6),
)

JEV_PROFILE_COUNTS: tuple[tuple[str, int], ...] = (
    ("pays_on_first_link", 8),
    ("pays_after_reminder", 6),
    ("pays_if_fast", 4),
    ("pays_after_wait", 4),
    ("never_pays", 8),
    ("opts_out", 5),
    ("high_value", 5),
)

# (error_reason, method, international, error_code, error_source, error_step, description)
_CAUSES: tuple[tuple[str, str, bool | None, str, str, str, str], ...] = (
    (
        "international_transaction_not_allowed",
        "card",
        True,
        "BAD_REQUEST_ERROR",
        "business",
        "payment_initiation",
        "This business accepts domestic (Indian) card payments only.",
    ),
    (
        "insufficient_funds",
        "card",
        False,
        "GATEWAY_ERROR",
        "bank",
        "payment_authorization",
        "Payment failed due to insufficient funds.",
    ),
    (
        "bank_downtime",
        "upi",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "The customer's bank is currently unavailable.",
    ),
    (
        "issuer_unavailable",
        "card",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "The card issuer is currently unavailable.",
    ),
    (
        "invalid_otp",
        "upi",
        False,
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authentication",
        "Authentication failed due to incorrect otp.",
    ),
    (
        "",
        "card",
        False,
        "BAD_REQUEST_ERROR",
        "unknown",
        "payment_authorization",
        "Payment could not be completed. Please try again.",
    ),
)

# Unmapped-reason cohort: rules cannot match; Jev must read the description.
# (true_cause, method, international, error_code, error_source, error_step, description)
_JEV_CAUSES: tuple[tuple[str, str, bool | None, str, str, str, str], ...] = (
    (
        "insufficient_funds",
        "card",
        False,
        "GATEWAY_ERROR",
        "bank",
        "payment_authorization",
        "Your bank declined the charge because the account balance was too low.",
    ),
    (
        "bank_downtime",
        "upi",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "NPCI UPI switch reports the customer's bank is under scheduled maintenance.",
    ),
    (
        "issuer_unavailable",
        "card",
        False,
        "GATEWAY_ERROR",
        "issuer",
        "payment_processing",
        "Visa network returned issuer temporarily unavailable; try again later.",
    ),
    (
        "invalid_otp",
        "upi",
        False,
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authentication",
        "Customer entered an incorrect OTP three times during authentication.",
    ),
    (
        "incorrect_pin",
        "card",
        False,
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authentication",
        "Debit card PIN verification failed at the ATM-style challenge.",
    ),
    (
        "international_transaction_not_allowed",
        "card",
        True,
        "BAD_REQUEST_ERROR",
        "business",
        "payment_initiation",
        "Foreign-issued card was blocked by merchant domestic-only policy.",
    ),
    (
        "ambiguous",
        "card",
        False,
        "BAD_REQUEST_ERROR",
        "unknown",
        "payment_authorization",
        "Payment could not be completed. Please try again.",
    ),
    (
        "ambiguous",
        "upi",
        False,
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authorization",
        "Customer disputes this charge and wants a full refund / chargeback.",
    ),
)


def seed_batch(store: Store, *, seed: int, profile: str = "classic") -> str:
    """Create synthetic failed cases. Same seed+profile reproduces the batch."""
    existing = store.batch_for_seed(seed)
    if existing is not None:
        return existing
    if profile == "jev":
        return _seed_jev_batch(store, seed=seed)
    if profile == "bench":
        return _seed_bench_batch(store, seed=seed)
    return _seed_classic_batch(store, seed=seed)


def _seed_bench_batch(store: Store, *, seed: int) -> str:
    """Rich held-out diagnosis corpus. Prefer seed=100; split is independent of seed."""
    from payrecover.simulator.dataset import assign_splits, build_specs

    assigned = assign_splits(build_specs(), seed=100)
    batch_id = f"batch_bench_{seed}"
    rng = random.Random(seed)
    for index, (spec, split) in enumerate(assigned):
        case_id = f"b{seed}_{index:03d}"
        amount = rng.randint(10000, 250000)
        if spec.true_cause == "international_transaction_not_allowed":
            amount = min(amount, 249999)
        _write_case(
            store,
            case_id=case_id,
            profile="bench",
            pay_on_reminder=None,
            true_cause=spec.true_cause,
            amount_paise=amount,
            error_reason=spec.error_reason,
            method=spec.method,
            international=spec.international,
            error_code=spec.error_code,
            error_source=spec.error_source,
            error_step=spec.error_step,
            error_description=spec.description,
            family=spec.family,
            split=split,
            expect_is_transient=spec.expect_is_transient,
            expect_customer_fault=spec.expect_customer_fault,
            expect_requests_dispute=spec.expect_requests_dispute,
        )
    store.record_batch(batch_id, seed)
    return batch_id


def _seed_classic_batch(store: Store, *, seed: int) -> str:
    rng = random.Random(seed)
    batch_id = f"batch_{seed}"
    profiles = _expand_profiles(rng, PROFILE_COUNTS, BATCH_SIZE)
    for index, profile in enumerate(profiles):
        case_id = f"c{seed}_{index:02d}"
        cause = _CAUSES[index % len(_CAUSES)]
        amount = 750000 if profile == "high_value" else rng.randint(10000, 250000)
        pay_on_reminder = None
        if profile == "pays_after_reminder":
            pay_on_reminder = 1 if rng.random() < 0.5 else 2
        true_cause = cause[0] if cause[0] else "ambiguous"
        _write_case(
            store,
            case_id=case_id,
            profile=profile,
            pay_on_reminder=pay_on_reminder,
            true_cause=true_cause,
            amount_paise=amount,
            error_reason=cause[0],
            method=cause[1],
            international=cause[2],
            error_code=cause[3],
            error_source=cause[4],
            error_step=cause[5],
            error_description=cause[6],
        )
    store.record_batch(batch_id, seed)
    return batch_id


def _seed_jev_batch(store: Store, *, seed: int) -> str:
    """Seed an enriched cohort: empty error_reason, labeled true_cause for eval."""
    rng = random.Random(seed)
    batch_id = f"batch_jev_{seed}"
    profiles = _expand_profiles(rng, JEV_PROFILE_COUNTS, JEV_BATCH_SIZE)
    for index, profile in enumerate(profiles):
        case_id = f"j{seed}_{index:02d}"
        cause = _JEV_CAUSES[index % len(_JEV_CAUSES)]
        amount = 750000 if profile == "high_value" else rng.randint(10000, 250000)
        pay_on_reminder = None
        if profile == "pays_after_reminder":
            pay_on_reminder = 1 if rng.random() < 0.5 else 2
        _write_case(
            store,
            case_id=case_id,
            profile=profile,
            pay_on_reminder=pay_on_reminder,
            true_cause=cause[0],
            amount_paise=amount,
            error_reason="",  # force model path
            method=cause[1],
            international=cause[2],
            error_code=cause[3],
            error_source=cause[4],
            error_step=cause[5],
            error_description=cause[6],
        )
    store.record_batch(batch_id, seed)
    return batch_id


def _write_case(
    store: Store,
    *,
    case_id: str,
    profile: str,
    pay_on_reminder: int | None,
    true_cause: str | None,
    amount_paise: int,
    error_reason: str,
    method: str,
    international: bool | None,
    error_code: str,
    error_source: str,
    error_step: str,
    error_description: str,
    family: str | None = None,
    split: str | None = None,
    expect_is_transient: bool | None = None,
    expect_customer_fault: bool | None = None,
    expect_requests_dispute: bool | None = None,
) -> None:
    failure = PaymentFailure(
        payment_id=f"pay_sim_{case_id}",
        order_id=f"order_sim_{case_id}",
        amount_paise=amount_paise,
        method=method,
        status="failed",
        error_reason=error_reason,
        error_code=error_code,
        error_source=error_source,
        error_step=error_step,
        error_description=error_description,
        international=international,
    )
    case = Case(
        case_id=case_id,
        failure=failure,
        status=CaseStatus.DETECTED,
        created_at=datetime.now(UTC),
    )
    store.upsert_case(case)
    store.save_ground_truth(
        GroundTruth(
            case_id=case_id,
            profile=profile,
            pay_on_reminder=pay_on_reminder,
            true_cause=true_cause,
            family=family,
            split=split,  # type: ignore[arg-type]
            expect_is_transient=expect_is_transient,
            expect_customer_fault=expect_customer_fault,
            expect_requests_dispute=expect_requests_dispute,
        )
    )


def _expand_profiles(
    rng: random.Random,
    counts: tuple[tuple[str, int], ...],
    expected: int,
) -> list[str]:
    slots: list[str] = []
    for name, count in counts:
        slots.extend([name] * count)
    if len(slots) != expected:
        raise RuntimeError("profile counts must sum to expected batch size")
    rng.shuffle(slots)
    return slots
