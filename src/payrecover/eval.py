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
from payrecover.models import Case, Diagnosis, DiagnosisPath, GroundTruth
from payrecover.stats import wilson_ci
from payrecover.store import Store

Arm = Literal["rules", "keyword", "jev", "gemini"]
SplitFilter = Literal["all", "train", "test"]


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
        diagnosis = _diagnose_cached(
            case,
            settings=settings,
            mode=mode,
            arm=arm,
            jev_client=jev_client,
            cache=cache,
        )
        path_counts[diagnosis.path.value] += 1
        if diagnosis.cost_usd is not None:
            cost += float(diagnosis.cost_usd)

        is_correct: bool | None = None
        if truth is not None and truth.true_cause is not None:
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


def _diagnose_cached(
    case: Case,
    *,
    settings: Settings,
    mode: DiagnosisMode,
    arm: Arm,
    jev_client: JevClient | None,
    cache: ResponseCache | None,
) -> Diagnosis:
    if cache is None or arm in {"rules", "keyword"}:
        return diagnose(case, settings=settings, mode=mode, jev_client=jev_client)

    model_name = settings.jev_model if arm == "jev" else settings.llm_model
    key = _cache_key(case, arm=arm, model=model_name)
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


def _cache_key(case: Case, *, arm: Arm, model: str) -> str:
    failure = case.failure.model_dump()
    blob = json.dumps({"arm": arm, "model": model, "failure": failure}, sort_keys=True)
    return blob


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
