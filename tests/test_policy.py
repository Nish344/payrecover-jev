from __future__ import annotations

from datetime import UTC, datetime

from payrecover.models import (
    ActionType,
    Case,
    CaseStatus,
    Diagnosis,
    DiagnosisPath,
    PaymentFailure,
)
from payrecover.policy import decide


def _case(**updates: object) -> Case:
    base = Case(
        case_id="c1",
        failure=PaymentFailure(amount_paise=10000, error_reason="insufficient_funds"),
        created_at=datetime.now(UTC),
    )
    return base.model_copy(update=updates) if updates else base


def _diag(*, confidence: float = 0.9, cause: str = "insufficient_funds") -> Diagnosis:
    return Diagnosis(
        case_id="c1",
        cause=cause,
        confidence=confidence,
        rationale="t",
        path=DiagnosisPath.RULES,
    )


def test_kill_switch_wins() -> None:
    action = decide(_case(opted_out=True), _diag(), kill_switch=True)
    assert action.action_type == ActionType.STOP
    assert action.rationale == "kill_switch"
    assert action.origin == "policy"


def test_opt_out() -> None:
    action = decide(_case(opted_out=True), _diag(), kill_switch=False)
    assert action.rationale == "opt_out"


def test_high_amount_beats_high_confidence() -> None:
    case = _case(failure=PaymentFailure(amount_paise=750000, error_reason="insufficient_funds"))
    action = decide(case, _diag(confidence=0.99), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "high_amount"


def test_low_confidence_escalates() -> None:
    action = decide(_case(), _diag(confidence=0.59), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "low_confidence"


def test_ambiguous_never_reaches_an_action() -> None:
    action = decide(_case(), _diag(confidence=0.9, cause="ambiguous"), kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "ambiguous"


def test_wait_then_link() -> None:
    waiting = decide(_case(), _diag(cause="bank_downtime"), kill_switch=False)
    assert waiting.action_type == ActionType.WAIT
    after = decide(_case(wait_completed=True), _diag(cause="bank_downtime"), kill_switch=False)
    assert after.action_type == ActionType.ISSUE_LINK
    assert after.amount_paise == 10000


def test_remind_then_exhaust() -> None:
    linked = _case(active_payment_link_id="plink_1", link_count=1, reminder_count=0)
    remind = decide(linked, _diag(), kill_switch=False)
    assert remind.action_type == ActionType.REMIND
    exhausted = decide(
        linked.model_copy(update={"reminder_count": 3}),
        _diag(),
        kill_switch=False,
    )
    assert exhausted.action_type == ActionType.STOP
    assert exhausted.rationale == "exhausted"


def test_already_terminal_is_noop() -> None:
    action = decide(_case(status=CaseStatus.RECOVERED), _diag(), kill_switch=False)
    assert action.rationale == "already_terminal"


def test_no_second_live_link() -> None:
    case = _case(active_payment_link_id="plink_1", link_count=1)
    action = decide(case, _diag(), kill_switch=False)
    assert action.action_type == ActionType.REMIND


def test_requests_dispute_signal_escalates() -> None:
    diagnosis = Diagnosis(
        case_id="c1",
        cause="insufficient_funds",
        confidence=0.95,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"requests_dispute": 0.91, "is_transient": 0.01, "customer_fault": 0.2},
    )
    action = decide(_case(), diagnosis, kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "requests_dispute"


def test_transient_signal_waits_when_cause_not_transient() -> None:
    diagnosis = Diagnosis(
        case_id="c1",
        cause="insufficient_funds",
        confidence=0.9,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"is_transient": 0.74, "customer_fault": 0.1, "requests_dispute": 0.05},
    )
    action = decide(_case(), diagnosis, kill_switch=False)
    assert action.action_type == ActionType.WAIT
    assert action.rationale == "transient_signal"


def test_customer_fault_blocks_transient_signal_wait() -> None:
    diagnosis = Diagnosis(
        case_id="c1",
        cause="insufficient_funds",
        confidence=0.9,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"is_transient": 0.95, "customer_fault": 0.8, "requests_dispute": 0.05},
    )
    action = decide(_case(), diagnosis, kill_switch=False)
    assert action.action_type == ActionType.ISSUE_LINK


def test_corroborated_transient_waits_even_when_cause_ambiguous() -> None:
    case = _case(
        failure=PaymentFailure(amount_paise=10000, error_reason="payment_timed_out")
    )
    diagnosis = Diagnosis(
        case_id="c1",
        cause="ambiguous",
        confidence=0.55,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"is_transient": 0.85, "customer_fault": 0.1, "requests_dispute": 0.05},
    )
    action = decide(case, diagnosis, kill_switch=False)
    assert action.action_type == ActionType.WAIT
    assert action.rationale == "transient_corroborated"


def test_uncorroborated_ambiguous_with_high_transient_still_escalates() -> None:
    case = _case(
        failure=PaymentFailure(amount_paise=10000, error_reason="card_declined")
    )
    diagnosis = Diagnosis(
        case_id="c1",
        cause="ambiguous",
        confidence=0.9,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"is_transient": 0.95, "customer_fault": 0.1, "requests_dispute": 0.05},
    )
    action = decide(case, diagnosis, kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "ambiguous"


def test_wait_completed_disables_corroborated_transient_rung() -> None:
    case = _case(
        failure=PaymentFailure(amount_paise=10000, error_reason="gateway_technical_error"),
        wait_completed=True,
    )
    diagnosis = Diagnosis(
        case_id="c1",
        cause="ambiguous",
        confidence=0.7,
        rationale="t",
        path=DiagnosisPath.JEV,
        signals={"is_transient": 0.9, "customer_fault": 0.1, "requests_dispute": 0.05},
    )
    action = decide(case, diagnosis, kill_switch=False)
    assert action.action_type == ActionType.ESCALATE
    assert action.rationale == "ambiguous"
