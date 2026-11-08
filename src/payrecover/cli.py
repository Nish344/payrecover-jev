from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import ValidationError

from payrecover import __version__
from payrecover.config import Settings
from payrecover.models import ActionRequest, Case, Diagnosis
from payrecover.razorpay_client import (
    RazorpayAuthError,
    RazorpayClient,
    RazorpayClientError,
)
from payrecover.simulator.batchgen import seed_batch
from payrecover.store import Store

app = typer.Typer(name="payrecover", no_args_is_help=True, add_completion=False)

_REPORTS_DIR = Path("reports")
DiagnosisChoice = Literal["auto", "rules", "jev", "gemini", "keyword"]
SeedProfile = Literal["classic", "jev", "bench"]
EvalSplit = Literal["all", "train", "test"]


@app.callback()
def _configure(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError:
        typer.echo("Missing credentials. Copy .env.example to .env and fill test keys.", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def ping() -> None:
    """Verify test-mode Razorpay credentials with a single authenticated read."""
    settings = _settings()
    try:
        client = RazorpayClient(settings)
        result = client.ping()
    except RazorpayAuthError as exc:
        typer.echo(f"auth failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except RazorpayClientError as exc:
        typer.echo(f"razorpay error: {exc.__class__.__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from None
    count = result.get("count", len(result.get("items", [])))
    typer.echo(f"ok  payrecover {__version__}  test-mode ping  payments_visible={count}")


@app.command()
def detect() -> None:
    """Read failed Razorpay payments and upsert them as cases (no writes)."""
    from payrecover.detector import ingest_failed_payments

    settings = _settings()
    try:
        client = RazorpayClient(settings)
        result = client.list_payments()
    except RazorpayAuthError as exc:
        typer.echo(f"auth failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except RazorpayClientError as exc:
        typer.echo(f"razorpay error: {exc.__class__.__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from None
    items = result.get("items") or []
    payments = [item for item in items if isinstance(item, dict)]
    store = Store(settings.db_path)
    ingested = ingest_failed_payments(store, payments)
    suffix = ""
    if ingested:
        suffix = "  " + " ".join(case.case_id for case in ingested[:20])
    typer.echo(
        f"ok  detected {len(ingested)} failed payments  "
        f"scanned={len(payments)}  db={settings.db_path}{suffix}"
    )


@app.command()
def realgen(
    scenarios: Annotated[
        str,
        typer.Option(
            "--scenarios",
            help="all | comma list of scenario keys (see plan §23)",
        ),
    ] = "all",
    repeat: Annotated[
        int,
        typer.Option("--repeat", help="Links per scenario (max 5)"),
    ] = 2,
    cohort: Annotated[
        str,
        typer.Option("--cohort", help="Cohort tag written into notes.pr_cohort"),
    ] = "real-v1",
    amount_max: Annotated[
        int,
        typer.Option(
            "--amount-max",
            help="Amount in rupees (kept under ₹5,000 escalate cap)",
        ),
    ] = 2499,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for realgen_<cohort>.json"),
    ] = Path("data/real"),
) -> None:
    """Create test-mode Payment Links for the real cohort (manual pay → Failure)."""
    from payrecover.realgen import (
        RealgenError,
        format_checklist,
        generate_links,
        parse_scenarios,
        write_manifest,
    )

    settings = _settings()
    if not settings.razorpay_key_id.startswith("rzp_test_"):
        typer.echo("refusing non-test Razorpay key", err=True)
        raise typer.Exit(code=1)
    try:
        selected = parse_scenarios(scenarios)
        client = RazorpayClient(settings)
        links = generate_links(
            client,
            scenarios=selected,
            repeat=repeat,
            cohort=cohort,
            amount_max_rupees=amount_max,
        )
    except RealgenError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    except RazorpayAuthError as exc:
        typer.echo(f"auth failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except RazorpayClientError as exc:
        typer.echo(f"razorpay error: {exc.__class__.__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from None

    manifest = write_manifest(output_dir / f"realgen_{cohort}.json", links)
    typer.echo(format_checklist(links))
    typer.echo(
        f"ok  realgen created {len(links)} links  cohort={cohort}  "
        f"manifest={manifest}"
    )


@app.command()
def seed(
    seed: int = typer.Option(42, "--seed", help="Deterministic batch seed"),
    force: bool = typer.Option(False, "--force", help="Wipe existing cases and reseed"),
    profile: Annotated[
        SeedProfile,
        typer.Option(
            "--profile",
            help="classic | jev | bench (rich held-out corpus, prefer --seed 100)",
        ),
    ] = "classic",
) -> None:
    """Create synthetic failed-payment cases (local; no Razorpay writes)."""
    settings = _settings()
    store = Store(settings.db_path)
    if store.batch_for_seed(seed) is not None and not force:
        typer.echo(f"batch for seed={seed} already exists. Pass --force to replace.")
        return
    if force:
        store.wipe()
    batch_id = seed_batch(store, seed=seed, profile=profile)
    typer.echo(
        f"ok  seeded {store.case_count()} cases  batch_id={batch_id}  "
        f"profile={profile}  db={settings.db_path}"
    )


@app.command()
def run(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--live", help="Dry-run (default) or real test-mode writes"),
    ] = True,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Process only the first N cases")
    ] = None,
    case_id: Annotated[
        str | None, typer.Option("--case", help="Process a single case id")
    ] = None,
    inject_timeout: Annotated[
        bool, typer.Option("--inject-timeout", help="Fail writes with RazorpayTimeoutError")
    ] = False,
    diagnosis: Annotated[
        DiagnosisChoice,
        typer.Option(
            "--diagnosis",
            help="Diagnosis arm: auto (default), rules, keyword, jev, or gemini",
        ),
    ] = "auto",
) -> None:
    """Process the batch: detect → diagnose → policy → act → simulate."""
    from payrecover.audit import SqliteAudit, ensure_schema
    from payrecover.diagnosis import diagnose as diagnose_case
    from payrecover.jev_client import JevAuthError, JevClient
    from payrecover.policy import decide
    from payrecover.razorpay_client import InjectedTimeoutClient
    from payrecover.runner import run_batch

    settings = _settings()
    store = Store(settings.db_path)
    if store.case_count() == 0:
        typer.echo("No cases. Run `payrecover seed` first.", err=True)
        raise typer.Exit(code=1)
    if case_id is not None and store.get_case(case_id) is None:
        typer.echo(f"unknown case_id {case_id}", err=True)
        raise typer.Exit(code=1)
    ensure_schema(store.conn)
    if inject_timeout:
        client: object | None = InjectedTimeoutClient()
        dry_run = False
    elif dry_run:
        client = None
    else:
        if case_id is None and limit is None:
            typer.echo("refusing unbounded --live. Pass --case or --limit N.", err=True)
            raise typer.Exit(code=1)
        client = RazorpayClient(settings)
        typer.echo("LIVE test-mode writes enabled", err=True)

    jev_client: JevClient | None = None
    if diagnosis in {"auto", "jev"} and settings.openrouter_api_key.get_secret_value().strip():
        try:
            jev_client = JevClient(settings)
        except JevAuthError as exc:
            typer.echo(f"jev auth failed: {exc}", err=True)
            raise typer.Exit(code=1) from None

    def _diagnose(case: Case) -> Diagnosis:
        return diagnose_case(
            case,
            settings=settings,
            mode=diagnosis,
            jev_client=jev_client,
        )

    def _decide(case: Case, diagnosis_result: Diagnosis) -> ActionRequest:
        return decide(case, diagnosis_result, kill_switch=settings.kill_switch)

    try:
        finished = run_batch(
            store,
            settings=settings,
            audit=SqliteAudit(store.conn),
            diagnose=_diagnose,
            decide=_decide,
            client=client,  # type: ignore[arg-type]
            dry_run=dry_run,
            limit=limit,
            case_id=case_id,
        )
    finally:
        if jev_client is not None:
            jev_client.close()
    suffix = ""
    if len(finished) <= 5:
        suffix = "  " + " ".join(case.case_id for case in finished)
    typer.echo(
        f"ok  processed {len(finished)} cases  dry_run={dry_run}  "
        f"diagnosis={diagnosis}{suffix}"
    )


@app.command()
def report(
    output_dir: Annotated[Path, typer.Option("--output-dir")] = _REPORTS_DIR,
) -> None:
    """Write the recovery report (markdown + JSON)."""
    from payrecover.audit import list_all
    from payrecover.metrics import build_report

    settings = _settings()
    store = Store(settings.db_path)
    cases = store.list_cases()
    events = list_all(store.conn)
    path = build_report(
        cases,
        events,
        output_dir=output_dir,
        truths=store.list_ground_truths(),
    )
    typer.echo(f"ok  report {path}")


@app.command("audit")
def audit_cmd(case_id: str = typer.Argument(..., help="Case id, e.g. c42_00")) -> None:
    """Show the append-only audit trail for a case."""
    from payrecover.audit import export_text, list_for_case

    settings = _settings()
    store = Store(settings.db_path)
    events = list_for_case(store.conn, case_id)
    typer.echo(export_text(events))


@app.command("eval")
def eval_cmd(
    arms: Annotated[
        str,
        typer.Option("--arms", help="Comma-separated: rules,keyword,jev,gemini"),
    ] = "rules,keyword,jev,gemini",
    split: Annotated[
        EvalSplit,
        typer.Option("--split", help="Evaluate all | train | test (prefer test)"),
    ] = "test",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Markdown report path"),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="Response cache directory"),
    ] = Path("reports/cache"),
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Disable response cache"),
    ] = False,
    train_sweep: Annotated[
        bool,
        typer.Option("--train-sweep", help="Append train-only confidence threshold sweep"),
    ] = False,
) -> None:
    """Compare diagnosis arms on the held-out split (fair baseline ladder)."""
    from payrecover.eval import Arm, evaluate_arms, format_eval_report, predictions_for_arm
    from payrecover.jev_client import JevAuthError, JevClient

    settings = _settings()
    store = Store(settings.db_path)
    if store.case_count() == 0:
        typer.echo(
            "No cases. Run `payrecover seed --profile bench --seed 100 --force` first.",
            err=True,
        )
        raise typer.Exit(code=1)
    selected: list[Arm] = []
    for raw in arms.split(","):
        name = raw.strip().lower()
        if name not in {"rules", "keyword", "jev", "gemini"}:
            typer.echo(f"unknown arm {raw!r}; use rules,keyword,jev,gemini", err=True)
            raise typer.Exit(code=1)
        selected.append(name)  # type: ignore[arg-type]

    jev_client: JevClient | None = None
    if "jev" in selected and settings.openrouter_api_key.get_secret_value().strip():
        try:
            jev_client = JevClient(settings)
        except JevAuthError as exc:
            typer.echo(f"jev auth failed: {exc}", err=True)
            raise typer.Exit(code=1) from None
    try:
        results = evaluate_arms(
            store,
            settings=settings,
            arms=selected,
            split=split,
            jev_client=jev_client,
            cache_dir=None if no_cache else cache_dir,
            use_cache=not no_cache,
        )
        train_preds = None
        sweep_arm: Arm | None = None
        if train_sweep and "jev" in selected:
            sweep_arm = "jev"
            train_results = evaluate_arms(
                store,
                settings=settings,
                arms=["jev"],
                split="train",
                jev_client=jev_client,
                cache_dir=None if no_cache else cache_dir,
                use_cache=not no_cache,
            )
            train_preds = predictions_for_arm(train_results[0])
    finally:
        if jev_client is not None:
            jev_client.close()
    text = format_eval_report(
        results,
        train_sweep_arm=sweep_arm,
        train_predictions=train_preds,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"ok  eval {output}")
    else:
        typer.echo(text)


@app.command("consistency")
def consistency_cmd(
    arm: Annotated[
        Literal["jev", "gemini"],
        typer.Option("--arm", help="Model arm to re-run"),
    ] = "jev",
    split: Annotated[EvalSplit, typer.Option("--split")] = "test",
    runs: Annotated[int, typer.Option("--runs", min=2, max=10)] = 5,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Optional case cap for cost control"),
    ] = 20,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Self-consistency: re-run cases N times (spends credits; no cache)."""
    from payrecover.eval import run_self_consistency
    from payrecover.jev_client import JevAuthError, JevClient

    settings = _settings()
    store = Store(settings.db_path)
    if store.case_count() == 0:
        typer.echo("No cases. Seed bench first.", err=True)
        raise typer.Exit(code=1)

    # Optional limit via temporary filtered store view: truncate case list by monkeypatch
    # is awkward; instead wrap diagnose over a sliced case list inside a local Store proxy.
    truths = store.list_ground_truths()
    cases = [
        case
        for case in store.list_cases()
        if split == "all"
        or (truths.get(case.case_id) is not None and truths[case.case_id].split == split)
    ]
    if limit is not None:
        cases = cases[:limit]

    class _SliceStore:
        def list_cases(self) -> list[Case]:
            return cases

        def list_ground_truths(self) -> dict:
            return truths

    jev_client: JevClient | None = None
    if arm == "jev":
        if not settings.openrouter_api_key.get_secret_value().strip():
            typer.echo("OPENROUTER_API_KEY required for jev consistency", err=True)
            raise typer.Exit(code=1)
        try:
            jev_client = JevClient(settings)
        except JevAuthError as exc:
            typer.echo(f"jev auth failed: {exc}", err=True)
            raise typer.Exit(code=1) from None
    try:
        result = run_self_consistency(
            _SliceStore(),  # type: ignore[arg-type]
            settings=settings,
            arm=arm,
            split="all",  # already filtered
            runs=runs,
            jev_client=jev_client,
        )
    finally:
        if jev_client is not None:
            jev_client.close()
    text = (
        f"# Self-consistency\n\n"
        f"- arm: {result.arm}\n"
        f"- cases: {result.cases}\n"
        f"- runs: {result.runs}\n"
        f"- mean_change_rate: {result.mean_change_rate}\n"
        f"- mean_confidence_std: {result.mean_confidence_std}\n"
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"ok  consistency {output}")
    else:
        typer.echo(text)


@app.command("dataset-info")
def dataset_info() -> None:
    """Print synthetic bench corpus summary (no API keys needed)."""
    from payrecover.simulator.dataset import assign_splits, build_specs, corpus_summary

    summary = corpus_summary(assign_splits(build_specs()))
    typer.echo(json_dumps(summary))


def json_dumps(payload: object) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


if __name__ == "__main__":
    app()
