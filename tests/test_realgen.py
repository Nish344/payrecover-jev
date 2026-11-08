from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from payrecover.cli import app
from payrecover.razorpay_client import RazorpayAuthError, RazorpayClient
from payrecover.realgen import (
    MAX_REPEAT,
    SCENARIOS,
    RealgenError,
    format_checklist,
    generate_links,
    parse_scenarios,
    write_manifest,
)
from tests.helpers import make_settings

runner = CliRunner()


class FakeLinkSDK:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.n = 0
        self.payment_link = self

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        self.n += 1
        return {
            "id": f"plink_{self.n}",
            "short_url": f"https://rzp.io/i/{self.n}",
            "reference_id": payload["reference_id"],
        }

    def notifyBy(self, *args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("realgen must never notify")


def test_parse_scenarios_all_and_unknown() -> None:
    assert parse_scenarios("all") == list(SCENARIOS)
    assert parse_scenarios("insufficient_fund,upi_failure") == [
        "insufficient_fund",
        "upi_failure",
    ]
    with pytest.raises(RealgenError, match="unknown scenario"):
        parse_scenarios("not_a_real_scenario")


def test_generate_links_payload_shape_and_unique_refs() -> None:
    sdk = FakeLinkSDK()
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    links = generate_links(
        client,
        scenarios=["insufficient_fund", "payment_timed_out"],
        repeat=2,
        cohort="real-v1",
        amount_max_rupees=100,
    )
    assert len(links) == 4
    assert len({link.reference_id for link in links}) == 4
    assert sdk.payloads
    for payload in sdk.payloads:
        assert payload["description"] == "PayRecover real cohort"
        assert payload["amount"] == 10000
        assert payload["notify"] == {"sms": False, "email": False}
        assert payload["reminder_enable"] is False
        notes = payload["notes"]
        assert notes["pr_cohort"] == "real-v1"
        assert notes["pr_scenario"] in {"insufficient_fund", "payment_timed_out"}
        assert "pr_label" in notes
        assert notes["case_id"].startswith("real_")
    labels = {p["notes"]["pr_scenario"]: p["notes"]["pr_label"] for p in sdk.payloads}
    assert labels["insufficient_fund"] == "insufficient_funds"
    assert labels["payment_timed_out"] == "ambiguous"
    assert all(len(p["reference_id"]) <= 40 for p in sdk.payloads)


def test_refuse_repeat_over_max() -> None:
    sdk = FakeLinkSDK()
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    with pytest.raises(RealgenError, match=f"refusing --repeat > {MAX_REPEAT}"):
        generate_links(
            client,
            scenarios=["card_declined"],
            repeat=MAX_REPEAT + 1,
            cohort="real-v1",
        )
    assert sdk.payloads == []


def test_write_manifest_and_checklist(tmp_path: Path) -> None:
    sdk = FakeLinkSDK()
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    links = generate_links(
        client,
        scenarios=["upi_failure"],
        repeat=1,
        cohort="disc",
        amount_max_rupees=50,
    )
    path = write_manifest(tmp_path / "realgen_disc.json", links)
    text = path.read_text(encoding="utf-8")
    assert "upi_failure" in text
    assert "discover" in text
    checklist = format_checklist(links)
    assert "`upi_failure`" in checklist
    assert "failure@razorpay" in checklist


def test_cli_realgen_uses_fake_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings()
    monkeypatch.setattr("payrecover.cli._settings", lambda: settings)
    created: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, _settings: object) -> None:
            pass

        def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
            created.append(kwargs)
            return {
                "id": f"plink_{len(created)}",
                "short_url": f"https://rzp.io/{len(created)}",
            }

    monkeypatch.setattr("payrecover.cli.RazorpayClient", FakeClient)
    result = runner.invoke(
        app,
        [
            "realgen",
            "--scenarios",
            "card_declined,short_otp",
            "--repeat",
            "1",
            "--cohort",
            "t1",
            "--amount-max",
            "99",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ok  realgen created 2 links" in result.stdout
    assert (tmp_path / "realgen_t1.json").exists()
    assert len(created) == 2
    assert created[0]["notes"]["pr_scenario"] == "card_declined"
    assert created[1]["notes"]["pr_label"] == "discover"


def test_cli_refuses_live_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(razorpay_key_id="rzp_live_nope")
    monkeypatch.setattr("payrecover.cli._settings", lambda: settings)
    result = runner.invoke(app, ["realgen", "--scenarios", "card_declined", "--repeat", "1"])
    assert result.exit_code == 1
    assert "refusing non-test" in result.output


def test_cli_refuses_repeat_over_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings()
    monkeypatch.setattr("payrecover.cli._settings", lambda: settings)

    class FakeClient:
        def __init__(self, _settings: object) -> None:
            pass

        def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("should not create")

    monkeypatch.setattr("payrecover.cli.RazorpayClient", FakeClient)
    result = runner.invoke(
        app,
        ["realgen", "--scenarios", "card_declined", "--repeat", "6"],
    )
    assert result.exit_code == 1
    assert "refusing --repeat > 5" in result.output


def test_cli_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("payrecover.cli._settings", lambda: make_settings())

    class FakeClient:
        def __init__(self, _settings: object) -> None:
            raise RazorpayAuthError("refusing non-test Razorpay key")

    monkeypatch.setattr("payrecover.cli.RazorpayClient", FakeClient)
    result = runner.invoke(app, ["realgen", "--scenarios", "card_declined", "--repeat", "1"])
    assert result.exit_code == 1
    assert "auth failed" in result.output


def test_client_still_refuses_live_even_if_cli_bypassed() -> None:
    with pytest.raises(RazorpayAuthError):
        RazorpayClient(make_settings(razorpay_key_id="rzp_live_x"))


def test_long_scenario_reference_ids_fit_and_stay_unique() -> None:
    sdk = FakeLinkSDK()
    client = RazorpayClient(make_settings(), sdk=sdk, sleep=lambda _: None)
    links = generate_links(
        client,
        scenarios=[
            "card_disabled_for_online_payments",
            "international_transaction_not_allowed",
        ],
        repeat=2,
        cohort="real-v1",
        amount_max_rupees=10,
    )
    refs = [link.reference_id for link in links]
    assert len(refs) == len(set(refs))
    assert all(len(ref) <= 40 for ref in refs)
