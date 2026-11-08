"""Policy engine. Caps and first-match precedence live only here."""

from __future__ import annotations

from payrecover.models import ActionRequest, ActionType, Case, CaseStatus, Diagnosis
from payrecover.razorpay_reasons import transient_corroborated

MAX_LINKS = 2
MAX_REMINDERS = 3
ESCALATE_AMOUNT_PAISE = 500_000  # ₹5,000; escalate when strictly greater
MIN_CONFIDENCE = 0.6
DISPUTE_SIGNAL_THRESHOLD = 0.70
TRANSIENT_SIGNAL_THRESHOLD = 0.70
CUSTOMER_FAULT_BLOCK_THRESHOLD = 0.50
_TRANSIENT_CAUSES = frozenset({"bank_downtime", "issuer_unavailable"})
_TERMINAL = {
    CaseStatus.RECOVERED,
    CaseStatus.STOPPED,
    CaseStatus.ESCALATED,
    CaseStatus.EXHAUSTED,
}


def decide(case: Case, diagnosis: Diagnosis, *, kill_switch: bool) -> ActionRequest:
    if kill_switch:
        return _stop(case, "kill_switch")
    if case.opted_out:
        return _stop(case, "opt_out")
    if case.status in _TERMINAL:
        return _stop(case, "already_terminal")
    if case.failure.amount_paise > ESCALATE_AMOUNT_PAISE:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="high_amount",
        )
    if _signal(diagnosis, "requests_dispute") >= DISPUTE_SIGNAL_THRESHOLD:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="requests_dispute",
        )
    # Corroborated transient wait precedes the ambiguous escalate so out-of-taxonomy
    # rail failures (payment_timed_out / gateway_technical_error) get WAIT, not ESCALATE.
    if _corroborated_transient_wait(case, diagnosis):
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.WAIT,
            rationale="transient_corroborated",
        )
    if diagnosis.cause == "ambiguous":
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="ambiguous",
        )
    if diagnosis.confidence < MIN_CONFIDENCE:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ESCALATE,
            rationale="low_confidence",
        )
    if _should_wait(case, diagnosis):
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.WAIT,
            rationale=_wait_rationale(diagnosis),
        )
    if case.active_payment_link_id is None and case.link_count < MAX_LINKS:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.ISSUE_LINK,
            rationale="issue_link",
            amount_paise=case.failure.amount_paise,
        )
    if case.active_payment_link_id is not None and case.reminder_count < MAX_REMINDERS:
        return ActionRequest.from_policy(
            case_id=case.case_id,
            action_type=ActionType.REMIND,
            rationale="remind",
            payment_link_id=case.active_payment_link_id,
        )
    return _stop(case, "exhausted")


def _corroborated_transient_wait(case: Case, diagnosis: Diagnosis) -> bool:
    if case.wait_completed:
        return False
    if not transient_corroborated(case.failure.error_reason):
        return False
    cause_ok = diagnosis.cause in _TRANSIENT_CAUSES
    signal_ok = _signal(diagnosis, "is_transient") >= TRANSIENT_SIGNAL_THRESHOLD
    if not (cause_ok or signal_ok):
        return False
    if _signal(diagnosis, "customer_fault") >= CUSTOMER_FAULT_BLOCK_THRESHOLD:
        return False
    if _signal(diagnosis, "requests_dispute") >= DISPUTE_SIGNAL_THRESHOLD:
        return False
    return True


def _should_wait(case: Case, diagnosis: Diagnosis) -> bool:
    if case.wait_completed:
        return False
    if diagnosis.cause in _TRANSIENT_CAUSES:
        return True
    # Jev multi-signal wait: only when Noul signals are present and strong.
    if diagnosis.signals is None:
        return False
    if _signal(diagnosis, "is_transient") < TRANSIENT_SIGNAL_THRESHOLD:
        return False
    if _signal(diagnosis, "customer_fault") >= CUSTOMER_FAULT_BLOCK_THRESHOLD:
        return False
    if _signal(diagnosis, "requests_dispute") >= DISPUTE_SIGNAL_THRESHOLD:
        return False
    return True


def _wait_rationale(diagnosis: Diagnosis) -> str:
    if diagnosis.cause in _TRANSIENT_CAUSES:
        return "transient_rail"
    return "transient_signal"


def _signal(diagnosis: Diagnosis, name: str) -> float:
    if diagnosis.signals is None:
        return 0.0
    try:
        return float(diagnosis.signals.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _stop(case: Case, reason: str) -> ActionRequest:
    return ActionRequest.from_policy(
        case_id=case.case_id,
        action_type=ActionType.STOP,
        rationale=reason,
    )
