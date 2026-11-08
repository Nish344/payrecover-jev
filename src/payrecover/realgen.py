"""Generate Razorpay test-mode Payment Links for the real cohort (C2)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from payrecover.razorpay_reasons import RAZORPAY_REASONS

MAX_REPEAT = 5
DEFAULT_AMOUNT_MAX_RUPEES = 2499
DEFAULT_COHORT = "real-v1"
_SAFE_REF = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    pr_label: str
    cards: str
    how_to_fail: str
    method_hint: str = "card"


# §23 documented rows + discover rows (keys only; reasons filled after C3 observation).
SCENARIOS: dict[str, ScenarioSpec] = {
    "insufficient_fund": ScenarioSpec(
        key="insufficient_fund",
        pr_label="insufficient_funds",
        cards="4100 2800 0008 0001 / 5305 6200 0005 0001",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "authentication_failed": ScenarioSpec(
        key="authentication_failed",
        pr_label="invalid_otp",
        cards="4100 2800 0000 0009 / 5305 6200 0007 0009",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "payment_timed_out": ScenarioSpec(
        key="payment_timed_out",
        pr_label="ambiguous",
        cards="4100 2800 0009 0000 / 5305 6200 0006 0000",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "gateway_technical_error": ScenarioSpec(
        key="gateway_technical_error",
        pr_label="ambiguous",
        cards="4100 2800 0002 0007 / 5305 6200 0009 0007",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "international_transaction_not_allowed": ScenarioSpec(
        key="international_transaction_not_allowed",
        pr_label="international_transaction_not_allowed",
        cards="4012 8888 8888 1881 (intl Visa on domestic-only account)",
        how_to_fail="Open link → pay with intl card → mock bank page → Failure",
    ),
    "payment_cancelled": ScenarioSpec(
        key="payment_cancelled",
        pr_label="customer_abandoned",
        cards="4100 2800 0007 0002 / 5305 6200 0004 0002",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "card_declined": ScenarioSpec(
        key="card_declined",
        pr_label="ambiguous",
        cards="4100 2800 0006 0003 / 5305 6200 0003 0003",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "card_disabled_for_online_payments": ScenarioSpec(
        key="card_disabled_for_online_payments",
        pr_label="ambiguous",
        cards="4100 2800 0003 0006 / 5305 6200 0000 0006",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "card_number_invalid": ScenarioSpec(
        key="card_number_invalid",
        pr_label="ambiguous",
        cards="4100 2800 0001 0008 / 5305 6200 0008 0008",
        how_to_fail="Open link → pay with card → mock bank page → Failure",
    ),
    "upi_failure": ScenarioSpec(
        key="upi_failure",
        pr_label="discover",
        cards="VPA failure@razorpay",
        how_to_fail="Open link → UPI → VPA failure@razorpay → Failure",
        method_hint="upi",
    ),
    "netbanking_failure": ScenarioSpec(
        key="netbanking_failure",
        pr_label="discover",
        cards="any test bank",
        how_to_fail="Open link → Netbanking → any bank → mock page → Failure",
        method_hint="netbanking",
    ),
    "wallet_failure": ScenarioSpec(
        key="wallet_failure",
        pr_label="discover",
        cards="any test wallet",
        how_to_fail="Open link → Wallet → mock page → Failure",
        method_hint="wallet",
    ),
    "short_otp": ScenarioSpec(
        key="short_otp",
        pr_label="discover",
        cards="domestic success test card only (NOT 4111… — that is international on domestic-only accounts)",
        how_to_fail=(
            "Open link → card → domestic success card from Razorpay test docs → "
            "enter 1–3 digit OTP → submit (must reach OTP page)"
        ),
    ),
}

# Sanity: documented card scenarios agree with razorpay_reasons where present.
for _key, _spec in SCENARIOS.items():
    if _spec.pr_label == "discover":
        continue
    info = RAZORPAY_REASONS.get(_key)
    if info is not None and info.cause != _spec.pr_label:
        raise RuntimeError(
            f"realgen label mismatch for {_key}: {_spec.pr_label} vs {info.cause}"
        )


class SupportsPaymentLinkCreate(Protocol):
    def create_payment_link(
        self,
        *,
        case_id: str,
        amount_paise: int,
        description: str,
        customer: Mapping[str, str],
        reference_id: str,
        notes: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class GeneratedLink:
    cohort: str
    scenario: str
    index: int
    reference_id: str
    link_id: str
    short_url: str
    amount_paise: int
    pr_label: str
    cards: str
    how_to_fail: str
    method_hint: str


class RealgenError(ValueError):
    """User-facing validation failure for realgen options."""


def parse_scenarios(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text or text.lower() == "all":
        return list(SCENARIOS)
    keys: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        key = part.strip()
        if not key:
            continue
        if key not in SCENARIOS:
            raise RealgenError(
                f"unknown scenario {key!r}; choose from: {', '.join(SCENARIOS)}"
            )
        if key not in seen:
            keys.append(key)
            seen.add(key)
    if not keys:
        raise RealgenError("no scenarios selected")
    return keys


def _reference_id(cohort: str, scenario: str, index: int) -> str:
    safe_cohort = _SAFE_REF.sub("_", cohort.strip()) or "cohort"
    safe_scenario = _SAFE_REF.sub("_", scenario)
    # Razorpay reference_id max length is 40; always keep "_{index}" intact.
    index_part = f"_{index}"
    budget = 40 - len(index_part)
    body = f"{safe_cohort}_{safe_scenario}"
    if len(body) <= budget:
        return body + index_part
    for cohort_len in range(len(safe_cohort), 0, -1):
        head = safe_cohort[:cohort_len]
        scenario_budget = budget - len(head) - 1
        if scenario_budget < 1:
            continue
        body = f"{head}_{safe_scenario[:scenario_budget]}"
        if len(body) <= budget:
            return body + index_part
    return safe_scenario[:budget] + index_part


def generate_links(
    client: SupportsPaymentLinkCreate,
    *,
    scenarios: list[str],
    repeat: int = 2,
    cohort: str = DEFAULT_COHORT,
    amount_max_rupees: int = DEFAULT_AMOUNT_MAX_RUPEES,
) -> list[GeneratedLink]:
    if repeat < 1:
        raise RealgenError("--repeat must be >= 1")
    if repeat > MAX_REPEAT:
        raise RealgenError(f"refusing --repeat > {MAX_REPEAT}")
    if amount_max_rupees < 1 or amount_max_rupees > 4999:
        raise RealgenError("--amount-max must be between 1 and 4999 rupees")
    cohort = (cohort or "").strip()
    if not cohort:
        raise RealgenError("--cohort must be non-empty")

    amount_paise = amount_max_rupees * 100
    out: list[GeneratedLink] = []
    for scenario in scenarios:
        spec = SCENARIOS[scenario]
        for i in range(1, repeat + 1):
            reference_id = _reference_id(cohort, scenario, i)
            case_id = f"real_{reference_id}"
            created = client.create_payment_link(
                case_id=case_id,
                amount_paise=amount_paise,
                description="PayRecover real cohort",
                customer={
                    "name": "PayRecover realgen",
                    "email": f"{reference_id}@payrecover.test",
                    "contact": "+918765432109",
                },
                reference_id=reference_id,
                notes={
                    "pr_cohort": cohort,
                    "pr_scenario": scenario,
                    "pr_label": spec.pr_label,
                },
            )
            out.append(
                GeneratedLink(
                    cohort=cohort,
                    scenario=scenario,
                    index=i,
                    reference_id=reference_id,
                    link_id=str(created.get("id") or ""),
                    short_url=str(created.get("short_url") or created.get("url") or ""),
                    amount_paise=amount_paise,
                    pr_label=spec.pr_label,
                    cards=spec.cards,
                    how_to_fail=spec.how_to_fail,
                    method_hint=spec.method_hint,
                )
            )
    return out


def write_manifest(path: Path, links: list[GeneratedLink]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cohort": links[0].cohort if links else "",
        "count": len(links),
        "links": [asdict(link) for link in links],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_checklist(links: list[GeneratedLink]) -> str:
    lines = [
        "| # | scenario | reference_id | short_url | card / instrument | click |",
        "|---|---|---|---|---|---|",
    ]
    for n, link in enumerate(links, start=1):
        lines.append(
            f"| {n} | `{link.scenario}` | `{link.reference_id}` | "
            f"{link.short_url or link.link_id} | {link.cards} | {link.how_to_fail} |"
        )
    return "\n".join(lines)
