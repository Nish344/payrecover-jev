"""Offline diagnosis A/B harness with splits, cache, calibration, and CIs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from payrecover.calibration import (
    Prediction,
    ambiguous_confidence_stats,
    calibration_from_predictions,
    confidence_threshold_sweep,
    reliability_markdown,
)
from payrecover.config import Settings
from payrecover.diagnosis import DiagnosisMode, diagnose
from payrecover.jev_client import JevClient
from payrecover.models import ActionType, Case, Diagnosis, DiagnosisPath, GroundTruth
from payrecover.policy import decide
from payrecover.razorpay_reasons import lookup_reason
from payrecover.stats import wilson_ci
from payrecover.store import Store

Arm = Literal["rules", "keyword", "jev", "gemini"]
SplitFilter = Literal["all", "train", "test", "real"]

# Expected policy verdicts for documented Razorpay raw_reasons (C4 matrix; C5 flips cancelled).
EXPECTED_VERDICTS: dict[str, ActionType] = {
    "insufficient_fund": ActionType.ISSUE_LINK,
    "international_transaction_not_allowed": ActionType.ISSUE_LINK,
    "authentication_failed": ActionType.ISSUE_LINK,
    "payment_timed_out": ActionType.WAIT,
    "gateway_technical_error": ActionType.WAIT,
    "card_declined": ActionType.ESCALATE,
    "card_disabled_for_online_payments": ActionType.ESCALATE,
    "card_number_invalid": ActionType.ESCALATE,
    "payment_cancelled": ActionType.ISSUE_LINK,  # C5: customer_abandoned
}


@dataclass(frozen=True)
class CasePrediction:
    case_id: str
    true_cause: str | None
    family: str | None
    split: str | None
    cause: str
    confidence: float
    path: str
    model: str | None
    cost_usd: float | None
    signals: dict[str, float] | None
    correct: bool | None
    raw_reason: str | None = None
    label_source: str | None = None
    policy_verdict: str | None = None


@dataclass(frozen=True)
class ArmResult:
    arm: Arm
    split: str
    labeled: int
    correct: int
    accuracy: float
    accuracy_ci_low: float
    accuracy_ci_high: float
    path_counts: dict[str, int]
    cost_usd: float
    cost_per_1k: float
    by_cause: dict[str, dict[str, int]]
    by_family: dict[str, dict[str, int]]
    ece: float | None = None
    ambiguous_stats: dict[str, float | int] = field(default_factory=dict)
    predictions: tuple[CasePrediction, ...] = ()


@dataclass(frozen=True)
class ConsistencyResult:
    arm: Arm
    cases: int
    runs: int
    mean_change_rate: float
    mean_confidence_std: float


class ResponseCache:
    """Disk cache of diagnosis payloads keyed by case+arm+model fingerprint."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, payload: dict[str, Any]) -> None:
        path = self._path(key)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate_arms(
    store: Store,
    *,
    settings: Settings,
    arms: list[Arm] | None = None,
    split: SplitFilter = "test",
    jev_client: JevClient | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    mask_reason: bool = False,
) -> list[ArmResult]:
    selected = arms or ["rules", "keyword", "jev", "gemini"]
    cases = store.list_cases()
    truths = store.list_ground_truths()
    cache = ResponseCache(cache_dir) if cache_dir is not None else None
    results: list[ArmResult] = []
    for arm in selected:
        results.append(
            _evaluate_arm(
                cases,
                truths,
                settings=settings,
                arm=arm,
                split=split,
                jev_client=jev_client,
                cache=cache if use_cache else None,
                mask_reason=mask_reason,
            )
        )
    return results


def _evaluate_arm(
    cases: list[Case],
    truths: dict[str, GroundTruth],
    *,
    settings: Settings,
    arm: Arm,
    split: SplitFilter,
    jev_client: JevClient | None,
    cache: ResponseCache | None,
    mask_reason: bool = False,
) -> ArmResult:
    mode: DiagnosisMode = arm
    labeled = 0
    correct = 0
    path_counts: Counter[str] = Counter()
    cost = 0.0
    by_cause: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    predictions: list[CasePrediction] = []
    calib_rows: list[Prediction] = []

    for case in cases:
        truth = truths.get(case.case_id)
        if split != "all":
            if truth is None or truth.split != split:
                continue
        subject = _maybe_mask_reason(case) if mask_reason else case
        diagnosis = _diagnose_cached(
            subject,
            settings=settings,
            mode=mode,
            arm=arm,
            jev_client=jev_client,
            cache=cache,
            mask_reason=mask_reason,
        )
        path_counts[diagnosis.path.value] += 1
        if diagnosis.cost_usd is not None:
            cost += float(diagnosis.cost_usd)

        action = decide(subject, diagnosis, kill_switch=settings.kill_switch)
        is_correct: bool | None = None
        # Headline accuracy excludes derived labels (circular for rules on real data).
        counts_for_accuracy = (
            truth is not None
            and truth.true_cause is not None
            and (split != "real" or truth.label_source in {"generated", "manual"})
        )
        if counts_for_accuracy:
            assert truth is not None and truth.true_cause is not None
            labeled += 1
            expected = truth.true_cause
            row = by_cause.setdefault(expected, {"labeled": 0, "correct": 0})
            row["labeled"] += 1
            family = truth.family or "unknown"
            fam = by_family.setdefault(family, {"labeled": 0, "correct": 0})
            fam["labeled"] += 1
            is_correct = diagnosis.cause == expected
            if is_correct:
                correct += 1
                row["correct"] += 1
                fam["correct"] += 1
            calib_rows.append(
                Prediction(
                    case_id=case.case_id,
                    true_cause=expected,
                    predicted=diagnosis.cause,
                    confidence=diagnosis.confidence,
                    family=truth.family,
                )
            )
        elif truth is not None and truth.true_cause is not None:
            is_correct = diagnosis.cause == truth.true_cause
        predictions.append(
            CasePrediction(
                case_id=case.case_id,
                true_cause=None if truth is None else truth.true_cause,
                family=None if truth is None else truth.family,
                split=None if truth is None else truth.split,
                cause=diagnosis.cause,
                confidence=diagnosis.confidence,
                path=diagnosis.path.value,
                model=diagnosis.model,
                cost_usd=diagnosis.cost_usd,
                signals=diagnosis.signals,
                correct=is_correct,
                raw_reason=(
                    None
                    if truth is None
                    else (truth.raw_reason if truth.raw_reason is not None else case.failure.error_reason)
                ),
                label_source=None if truth is None else truth.label_source,
                policy_verdict=action.action_type.value,
            )
        )

    accuracy = (correct / labeled) if labeled else 0.0
    ci = wilson_ci(correct, labeled)
    ece = calibration_from_predictions(calib_rows).ece if calib_rows else None
    amb = ambiguous_confidence_stats(calib_rows) if calib_rows else {}
    return ArmResult(
        arm=arm,
        split=split,
        labeled=labeled,
        correct=correct,
        accuracy=round(accuracy, 4),
        accuracy_ci_low=round(ci.low, 4),
        accuracy_ci_high=round(ci.high, 4),
        path_counts=dict(path_counts),
        cost_usd=round(cost, 6),
        cost_per_1k=round((cost / labeled) * 1000, 6) if labeled else 0.0,
        by_cause=by_cause,
        by_family=by_family,
        ece=ece,
        ambiguous_stats=amb,
        predictions=tuple(predictions),
    )


def _maybe_mask_reason(case: Case) -> Case:
    return case.model_copy(
        update={"failure": case.failure.model_copy(update={"error_reason": ""})}
    )


def _diagnose_cached(
    case: Case,
    *,
    settings: Settings,
    mode: DiagnosisMode,
    arm: Arm,
    jev_client: JevClient | None,
    cache: ResponseCache | None,
    mask_reason: bool = False,
) -> Diagnosis:
    if cache is None or arm in {"rules", "keyword"}:
        return diagnose(case, settings=settings, mode=mode, jev_client=jev_client)

    model_name = settings.jev_model if arm == "jev" else settings.llm_model
    key = _cache_key(case, arm=arm, model=model_name, mask_reason=mask_reason)
    hit = cache.get(key)
    if hit is not None:
        return Diagnosis(
            case_id=case.case_id,
            cause=str(hit["cause"]),
            confidence=float(hit["confidence"]),
            rationale=str(hit.get("rationale") or "cache"),
            path=DiagnosisPath(str(hit["path"])),
            model=hit.get("model"),
            probabilities=hit.get("probabilities"),
            signals=hit.get("signals"),
            cost_usd=hit.get("cost_usd"),
        )
    diagnosis = diagnose(case, settings=settings, mode=mode, jev_client=jev_client)
    cache.put(
        key,
        {
            "cause": diagnosis.cause,
            "confidence": diagnosis.confidence,
            "rationale": diagnosis.rationale,
            "path": diagnosis.path.value,
            "model": diagnosis.model,
            "probabilities": diagnosis.probabilities,
            "signals": diagnosis.signals,
            "cost_usd": diagnosis.cost_usd,
        },
    )
    return diagnosis


def _cache_key(case: Case, *, arm: Arm, model: str, mask_reason: bool = False) -> str:
    failure = case.failure.model_dump()
    blob = json.dumps(
        {"arm": arm, "model": model, "failure": failure, "mask_reason": mask_reason},
        sort_keys=True,
    )
    return blob


def expected_verdict_for_reason(raw_reason: str | None) -> ActionType | None:
    key = (raw_reason or "").strip().lower()
    return EXPECTED_VERDICTS.get(key)


def format_eval_report(
    results: list[ArmResult],
    *,
    include_calibration: bool = True,
    train_sweep_arm: Arm | None = None,
    train_predictions: list[Prediction] | None = None,
) -> str:
    lines = [
        "# PayRecover diagnosis eval",
        "",
        "> Synthetic labeled data. Tune thresholds on **train** only; headline numbers "
        "are from the requested split (prefer **test**).",
        "",
        "| arm | split | accuracy | 95% CI | ECE | cost_usd | cost/1k |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        ci = f"[{result.accuracy_ci_low:.2%}, {result.accuracy_ci_high:.2%}]"
        ece = "—" if result.ece is None else f"{result.ece:.4f}"
        lines.append(
            f"| {result.arm} | {result.split} | {result.accuracy:.2%} | {ci} | "
            f"{ece} | {result.cost_usd} | {result.cost_per_1k} |"
        )
    lines.append("")

    for result in results:
        lines.extend(
            [
                f"## arm={result.arm} (split={result.split})",
                f"- labeled: {result.labeled}",
                f"- correct: {result.correct}",
                f"- accuracy: {result.accuracy * 100:.2f}%",
                (
                    f"- 95% Wilson CI: "
                    f"[{result.accuracy_ci_low * 100:.2f}%, "
                    f"{result.accuracy_ci_high * 100:.2f}%]"
                ),
                f"- ECE: {result.ece}",
                f"- cost_usd: {result.cost_usd}",
                f"- cost_per_1k: {result.cost_per_1k}",
                f"- path_counts: {result.path_counts}",
                f"- ambiguous_stats: {result.ambiguous_stats}",
                "",
            ]
        )
        if result.by_cause:
            lines.append("### by true_cause")
            for cause, row in sorted(result.by_cause.items()):
                lines.append(f"- {cause}: {row['correct']}/{row['labeled']}")
            lines.append("")
        if result.by_family:
            lines.append("### by family")
            for family, row in sorted(result.by_family.items()):
                lines.append(f"- {family}: {row['correct']}/{row['labeled']}")
            lines.append("")
        if include_calibration and result.predictions:
            preds = [
                Prediction(
                    case_id=p.case_id,
                    true_cause=p.true_cause or "",
                    predicted=p.cause,
                    confidence=p.confidence,
                    family=p.family,
                )
                for p in result.predictions
                if p.true_cause is not None
            ]
            report = calibration_from_predictions(preds)
            lines.append(reliability_markdown(report, title=f"reliability ({result.arm})"))

    if train_sweep_arm and train_predictions:
        lines.extend(
            [
                f"## train threshold sweep ({train_sweep_arm})",
                "",
                "| min_confidence | kept_accuracy | escalate_rate |",
                "|---|---|---|",
            ]
        )
        for point in confidence_threshold_sweep(train_predictions):
            lines.append(
                f"| {point.min_confidence:.2f} | {point.accuracy:.2%} | "
                f"{point.escalate_rate:.2%} |"
            )
        lines.append("")
        lines.append(
            "_Use this table on **train** only to pick MIN_CONFIDENCE; freeze before "
            "reporting test numbers._"
        )
        lines.append("")

    lines.extend(
        [
            "## Limitations",
            "",
            "- Dataset is synthetic (diverse paraphrases + hard/adversarial families).",
            "- Single decision-model vendor (Jev via OpenRouter).",
            "- Finite n: prefer Wilson CIs over point estimates.",
            "- Do not cite train-tuned thresholds as test results.",
            "",
        ]
    )
    return "\n".join(lines)


def run_self_consistency(
    store: Store,
    *,
    settings: Settings,
    arm: Arm,
    split: SplitFilter = "test",
    runs: int = 5,
    jev_client: JevClient | None = None,
    diagnose_fn: Callable[..., Diagnosis] | None = None,
) -> ConsistencyResult:
    """Re-run each selected case N times (no cache) and measure answer churn."""
    truths = store.list_ground_truths()
    cases = [
        case
        for case in store.list_cases()
        if split == "all"
        or (truths.get(case.case_id) is not None and truths[case.case_id].split == split)
    ]
    change_rates: list[float] = []
    conf_stds: list[float] = []
    fn = diagnose_fn or diagnose
    for case in cases:
        answers: list[str] = []
        confs: list[float] = []
        for _ in range(runs):
            diagnosis = fn(
                case,
                settings=settings,
                mode=arm,
                jev_client=jev_client,
            )
            answers.append(diagnosis.cause)
            confs.append(diagnosis.confidence)
        unique = len(set(answers))
        change_rates.append(0.0 if unique <= 1 else (unique - 1) / (runs - 1))
        if len(confs) > 1:
            mean = sum(confs) / len(confs)
            var = sum((c - mean) ** 2 for c in confs) / (len(confs) - 1)
            conf_stds.append(var**0.5)
        else:
            conf_stds.append(0.0)
    n = len(cases)
    return ConsistencyResult(
        arm=arm,
        cases=n,
        runs=runs,
        mean_change_rate=round(sum(change_rates) / n, 4) if n else 0.0,
        mean_confidence_std=round(sum(conf_stds) / n, 4) if n else 0.0,
    )


def predictions_for_arm(result: ArmResult) -> list[Prediction]:
    return [
        Prediction(
            case_id=p.case_id,
            true_cause=p.true_cause or "",
            predicted=p.cause,
            confidence=p.confidence,
            family=p.family,
        )
        for p in result.predictions
        if p.true_cause is not None
    ]


def format_real_report(
    results: list[ArmResult],
    *,
    masked_results: list[ArmResult] | None = None,
) -> str:
    """Real-cohort report. Never merge these numbers into the synthetic headline table."""
    lines = [
        "# PayRecover real Razorpay cohort eval",
        "",
        "> **Not a benchmark.** Test-mode descriptions are one fixed string per reason, "
        "n is small, CIs are wide, and for card scenarios the label is often determined "
        "by which test card / notes tag was used. This validates API shape and taxonomy "
        "gaps — see plan §22.",
        "",
        "## 1. In-taxonomy accuracy",
        "",
        "Only `label_source ∈ {generated, manual}`. Derived labels excluded. n + Wilson CI.",
        "",
        "| arm | n | accuracy | 95% CI |",
        "|---|---|---|---|",
    ]
    for result in results:
        ci = f"[{result.accuracy_ci_low:.2%}, {result.accuracy_ci_high:.2%}]"
        lines.append(
            f"| {result.arm} | {result.labeled} | {result.accuracy:.2%} | {ci} |"
        )
    lines.extend(["", "## 2. Out-of-taxonomy abstention", ""])
    lines.append(
        "Rows whose structured `raw_reason` has `kind=out_of_taxonomy`. "
        "`abstain_rate` = predicted `ambiguous`. Lower mean confidence is better here."
    )
    lines.append("")
    lines.append("| arm | n | abstain_rate | mean_confidence |")
    lines.append("|---|---|---|---|")
    for result in results:
        oot = [
            p
            for p in result.predictions
            if lookup_reason(p.raw_reason).kind == "out_of_taxonomy"
        ]
        n = len(oot)
        if n == 0:
            lines.append(f"| {result.arm} | 0 | — | — |")
            continue
        abstain = sum(1 for p in oot if p.cause == "ambiguous") / n
        mean_conf = sum(p.confidence for p in oot) / n
        lines.append(
            f"| {result.arm} | {n} | {abstain:.2%} | {mean_conf:.3f} |"
        )

    lines.extend(["", "## 3. Per-`raw_reason` table", ""])
    lines.append("| arm | raw_reason | predicted | confidence | policy_verdict |")
    lines.append("|---|---|---|---|---|")
    for result in results:
        for pred in sorted(result.predictions, key=lambda p: (p.raw_reason or "", p.case_id)):
            lines.append(
                f"| {result.arm} | `{pred.raw_reason or ''}` | {pred.cause} | "
                f"{pred.confidence:.3f} | {pred.policy_verdict or '—'} |"
            )

    lines.extend(["", "## 4. Expected-verdict matrix", ""])
    lines.append("| raw_reason | expected verdict |")
    lines.append("|---|---|")
    for reason, verdict in EXPECTED_VERDICTS.items():
        lines.append(f"| `{reason}` | {verdict.value} |")

    if masked_results:
        lines.extend(
            [
                "",
                "## 5. Reason-masked",
                "",
                "`error_reason` blanked before diagnosis. Rules arm is all-`ambiguous` "
                "by construction.",
                "",
            ]
        )
        lines.append("| arm | n | accuracy | 95% CI |")
        lines.append("|---|---|---|---|")
        for result in masked_results:
            ci = f"[{result.accuracy_ci_low:.2%}, {result.accuracy_ci_high:.2%}]"
            lines.append(
                f"| {result.arm} | {result.labeled} | {result.accuracy:.2%} | {ci} |"
            )
        lines.extend(["", "### Reason-masked per-`raw_reason`", ""])
        lines.append("| arm | raw_reason | predicted | confidence | policy_verdict |")
        lines.append("|---|---|---|---|---|")
        for result in masked_results:
            for pred in sorted(
                result.predictions, key=lambda p: (p.raw_reason or "", p.case_id)
            ):
                lines.append(
                    f"| {result.arm} | `{pred.raw_reason or ''}` | {pred.cause} | "
                    f"{pred.confidence:.3f} | {pred.policy_verdict or '—'} |"
                )

    lines.extend(
        [
            "",
            "## Limitations (verbatim framing)",
            "",
            "- Not a large labeled benchmark; test-mode strings lack paraphrase diversity.",
            "- Real-cohort numbers must never appear in the synthetic headline table.",
            "- Derived labels never count toward accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


def first_diagnosis_payload(diagnosis: Diagnosis) -> dict[str, object]:
    """Helper for tests / sample dumps."""
    return {
        "cause": diagnosis.cause,
        "confidence": diagnosis.confidence,
        "path": (
            diagnosis.path.value
            if isinstance(diagnosis.path, DiagnosisPath)
            else diagnosis.path
        ),
        "model": diagnosis.model,
        "probabilities": diagnosis.probabilities,
        "signals": diagnosis.signals,
        "cost_usd": diagnosis.cost_usd,
    }
