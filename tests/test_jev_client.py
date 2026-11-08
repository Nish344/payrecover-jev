from __future__ import annotations

import httpx
import pytest

from payrecover.jev_client import (
    JevAPIError,
    JevAuthError,
    JevClient,
    JevRateLimitError,
    parse_decision,
)
from tests.fakes import jev_raw_response
from tests.helpers import make_settings


def test_parse_decision_happy_path() -> None:
    decision = parse_decision(jev_raw_response())
    assert decision.cause == "insufficient_funds"
    assert decision.confidence == 0.82
    assert decision.is_transient == 0.05
    assert decision.cost_usd == 0.00001


def test_parse_decision_rejects_missing_answers() -> None:
    with pytest.raises(JevAPIError):
        parse_decision({"model": "jev-1.14.0"})


def test_client_posts_and_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "Authorization" in request.headers
        return httpx.Response(200, json=jev_raw_response())

    transport = httpx.MockTransport(handler)
    settings = make_settings(openrouter_api_key="sk-or-test")
    client = JevClient(settings, transport=transport)
    decision = client.decide_payment_failure(
        {
            "error_reason": "",
            "error_description": "balance too low",
            "amount_paise": 10000,
            "method": "card",
        }
    )
    assert decision.cause == "insufficient_funds"
    client.close()


def test_client_auth_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="nope"))
    settings = make_settings(openrouter_api_key="sk-or-test", jev_read_retries=1)
    client = JevClient(settings, transport=transport)
    with pytest.raises(JevAuthError):
        client.decide_payment_failure({"amount_paise": 1})
    client.close()


def test_client_rate_limit_retries_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "0"}, text="slow down")

    transport = httpx.MockTransport(handler)
    settings = make_settings(
        openrouter_api_key="sk-or-test",
        jev_read_retries=2,
    )
    client = JevClient(settings, transport=transport, sleep=lambda _: None)
    with pytest.raises(JevRateLimitError):
        client.decide_payment_failure({"amount_paise": 1})
    assert calls["n"] == 2
    client.close()


def test_empty_key_refused() -> None:
    with pytest.raises(JevAuthError):
        JevClient(make_settings(openrouter_api_key=""))
