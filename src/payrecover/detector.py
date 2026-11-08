"""Ingest failed Razorpay payments into cases (+ real-cohort labeling)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from payrecover.models import Case, CaseStatus, GroundTruth, PaymentFailure
from payrecover.razorpay_reasons import lookup_reason
from payrecover.store import Store

_TERMINAL = {
    CaseStatus.RECOVERED,
    CaseStatus.STOPPED,
    CaseStatus.ESCALATED,
    CaseStatus.EXHAUSTED,
}

_PR_NOTE_KEYS = frozenset({"pr_cohort", "pr_scenario", "pr_label", "case_id"})
DEFAULT_RAW_DIR = Path("data/real/payments")
DEFAULT_FIXTURE_DIR = Path("tests/fixtures/razorpay_real")
DEFAULT_MANUAL_LABELS = Path("data/real_labels.json")


def case_from_payment(payload: Mapping[str, Any], *, case_id: str) -> Case:
    """Normalize a Razorpay payment dict into an agent-visible Case."""
    card = payload.get("card") if isinstance(payload.get("card"), dict) else {}
    international = payload.get("international")
    if international is None and isinstance(card, dict):
        international = card.get("international")
    return Case(
        case_id=case_id,
        failure=PaymentFailure(
            payment_id=payload.get("id"),
            order_id=payload.get("order_id"),
            amount_paise=int(payload.get("amount") or 0),
            currency=str(payload.get("currency") or "INR"),
            method=payload.get("method"),
            status=payload.get("status"),
            error_code=payload.get("error_code"),
            error_description=payload.get("error_description"),
            error_reason=payload.get("error_reason"),
            error_source=payload.get("error_source"),
            error_step=payload.get("error_step"),
            international=None if international is None else bool(international),
        ),
        status=CaseStatus.DETECTED,
        created_at=datetime.now(UTC),
    )


def notes_as_dict(notes: object) -> dict[str, str]:
    """Razorpay may return notes as dict, empty list, or null."""
    if isinstance(notes, dict):
        return {str(k): str(v) for k, v in notes.items() if v is not None}
    return {}


def parse_since(raw: str, *, now: datetime | None = None) -> int:
    """Parse `--since` as relative days (`1d`) or ISO datetime → unix seconds."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty --since")
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    match = re.fullmatch(r"(\d+)\s*d", text, flags=re.IGNORECASE)
    if match:
        days = int(match.group(1))
        return int((clock - timedelta(days=days)).timestamp())
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unrecognized --since {raw!r}; use ISO or Nd (e.g. 1d)") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def load_manual_labels(path: Path | None = None) -> dict[str, dict[str, str]]:
    target = path or DEFAULT_MANUAL_LABELS
    if not target.exists():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manual labels must be an object: {target}")
    out: dict[str, dict[str, str]] = {}
    for payment_id, row in data.items():
        if not isinstance(row, dict):
            continue
        cause = row.get("true_cause")
        if cause is None:
            continue
        out[str(payment_id)] = {
            "true_cause": str(cause),
            "note": str(row.get("note") or ""),
        }
    return out


def label_real_case(
    payload: Mapping[str, Any],
    order_notes: Mapping[str, str] | None = None,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> GroundTruth:
    """Build ground truth for a real payment. Precedence: generated > manual > derived."""
    payment_id = str(payload.get("id") or "").strip()
    case_id = f"rzp_{payment_id}"
    raw_reason = payload.get("error_reason")
    raw_reason_s = None if raw_reason is None else str(raw_reason)
    family = f"real:{raw_reason_s or 'none'}"

    payment_notes = notes_as_dict(payload.get("notes"))
    merged_notes = {**(order_notes or {}), **payment_notes}
    pr_label = (merged_notes.get("pr_label") or "").strip()

    true_cause: str | None = None
    label_source: str | None = None
    if pr_label:
        true_cause = pr_label
        label_source = "generated"
    else:
        manual = (overrides or {}).get(payment_id)
        if manual and manual.get("true_cause"):
            true_cause = str(manual["true_cause"])
            label_source = "manual"
        else:
            info = lookup_reason(raw_reason_s)
            true_cause = info.cause
            label_source = "derived"

    return GroundTruth(
        case_id=case_id,
        profile="real",
        true_cause=true_cause,
        family=family,
        split="real",
        raw_reason=raw_reason_s,
        label_source=label_source,  # type: ignore[arg-type]
        expect_is_transient=lookup_reason(raw_reason_s).is_transient,
    )


def redact_payment(payload: Mapping[str, Any]) -> dict[str, Any]:
    """PII-stripped copy for committed fixtures."""
    data = json.loads(json.dumps(payload))  # deep copy via JSON
    for key in ("email", "contact"):
        data.pop(key, None)
    if isinstance(data.get("customer"), dict):
        for key in ("email", "contact", "name"):
            data["customer"].pop(key, None)
    card = data.get("card")
    if isinstance(card, dict):
        card.pop("name", None)
        # keep last4 / network / international
    notes = notes_as_dict(data.get("notes"))
    data["notes"] = {k: v for k, v in notes.items() if k in _PR_NOTE_KEYS}
    return data


def persist_raw_payment(payload: Mapping[str, Any], *, directory: Path) -> Path:
    payment_id = str(payload.get("id") or "").strip()
    if not payment_id:
        raise ValueError("payment payload missing id")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payment_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def export_fixture(payload: Mapping[str, Any], *, directory: Path) -> Path:
    payment_id = str(payload.get("id") or "").strip()
    if not payment_id:
        raise ValueError("payment payload missing id")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payment_id}.json"
    path.write_text(
        json.dumps(redact_payment(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def cohort_from_notes(
    payload: Mapping[str, Any],
    order_notes: Mapping[str, str] | None = None,
) -> str | None:
    payment_notes = notes_as_dict(payload.get("notes"))
    merged = {**(order_notes or {}), **payment_notes}
    value = (merged.get("pr_cohort") or "").strip()
    return value or None


def resolve_order_notes(
    payload: Mapping[str, Any],
    fetch_order: Callable[[str], Mapping[str, Any]] | None,
) -> dict[str, str]:
    payment_notes = notes_as_dict(payload.get("notes"))
    if payment_notes.get("pr_cohort") or payment_notes.get("pr_label"):
        return {}
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id or fetch_order is None:
        return {}
    order = fetch_order(order_id)
    return notes_as_dict(order.get("notes"))


def ingest_failed_payments(
    store: Store,
    payments: list[Mapping[str, Any]],
    *,
    cohort: str | None = None,
    fetch_order: Callable[[str], Mapping[str, Any]] | None = None,
    overrides: Mapping[str, Mapping[str, str]] | None = None,
    raw_dir: Path | None = None,
    export_fixtures: bool = False,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    label: bool = True,
) -> list[Case]:
    """Turn Razorpay payment objects into cases. Non-failed rows are ignored."""
    ingested: list[Case] = []
    for payload in payments:
        if str(payload.get("status") or "") != "failed":
            continue
        payment_id = str(payload.get("id") or "").strip()
        if not payment_id:
            continue
        order_notes = resolve_order_notes(payload, fetch_order)
        if cohort is not None:
            found = cohort_from_notes(payload, order_notes)
            if found != cohort:
                continue
        case = case_from_payment(payload, case_id=f"rzp_{payment_id}")
        upserted = upsert_detected(store, case)
        if label:
            truth = label_real_case(payload, order_notes, overrides)
            store.save_ground_truth(truth)
        if raw_dir is not None:
            persist_raw_payment(payload, directory=raw_dir)
        if export_fixtures:
            export_fixture(payload, directory=fixture_dir)
        ingested.append(upserted)
    return ingested


def list_failed_payments(
    client: Any,
    *,
    since_ts: int | None = None,
    paginate_all: bool = False,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch payment pages; optionally paginate until a short page."""
    skip = 0
    collected: list[dict[str, Any]] = []
    while True:
        result = client.list_payments(
            count=page_size,
            skip=skip,
            from_ts=since_ts,
        )
        items = result.get("items") or []
        page = [item for item in items if isinstance(item, dict)]
        collected.extend(page)
        if not paginate_all or len(page) < page_size:
            break
        skip += page_size
    return collected


def upsert_detected(store: Store, case: Case) -> Case:
    """Idempotent: same case_id keeps terminal/in-progress state on re-detect."""
    existing = store.get_case(case.case_id)
    if existing is None:
        store.upsert_case(case)
        return case
    if existing.status in _TERMINAL:
        return existing
    merged = existing.model_copy(
        update={
            "failure": case.failure,
        }
    )
    store.upsert_case(merged)
    return merged
