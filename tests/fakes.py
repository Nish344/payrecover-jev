from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from payrecover.jev_client import JevDecision, parse_decision
from payrecover.models import AuditEvent


class MemoryAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    def list_for_case(self, case_id: str) -> list[AuditEvent]:
        return [event for event in self.events if event.case_id == case_id]


class FakeJev:
    """In-memory Jev stand-in. No network."""

    def __init__(self, decision: JevDecision | Mapping[str, Any] | None = None) -> None:
        if decision is None:
            self.decision = default_jev_decision()
        elif isinstance(decision, JevDecision):
            self.decision = decision
        else:
            self.decision = parse_decision(decision)
        self.calls: list[Mapping[str, Any]] = []
        self.closed = False

    def decide_payment_failure(self, failure: Mapping[str, Any]) -> JevDecision:
        self.calls.append(failure)
        return self.decision

    def close(self) -> None:
        self.closed = True


def default_jev_decision(**overrides: object) -> JevDecision:
    payload: dict[str, object] = {
        "cause": "insufficient_funds",
        "confidence": 0.82,
        "probabilities": {
            "insufficient_funds": 0.82,
            "ambiguous": 0.10,
            "bank_downtime": 0.02,
            "issuer_unavailable": 0.02,
            "invalid_otp": 0.02,
            "incorrect_pin": 0.01,
            "international_transaction_not_allowed": 0.01,
        },
        "is_transient": 0.05,
        "customer_fault": 0.80,
        "requests_dispute": 0.02,
        "model": "jev-1.14.0",
        "cost_usd": 0.00001,
        "input_tokens": 400,
        "output_tokens": 40,
    }
    payload.update(overrides)
    return JevDecision(**payload)  # type: ignore[arg-type]


def jev_raw_response(**overrides: object) -> dict[str, Any]:
    decision = default_jev_decision(**overrides)
    return {
        "model": decision.model,
        "answers": {
            "cause": {
                "type": "choice",
                "choice": decision.cause,
                "confidence": decision.confidence,
                "probabilities": decision.probabilities,
            },
            "is_transient": {"type": "noul", "noul": decision.is_transient},
            "customer_fault": {"type": "noul", "noul": decision.customer_fault},
            "requests_dispute": {"type": "noul", "noul": decision.requests_dispute},
        },
        "usage": {
            "input_tokens": decision.input_tokens,
            "output_tokens": decision.output_tokens,
            "cost": decision.cost_usd,
        },
    }
