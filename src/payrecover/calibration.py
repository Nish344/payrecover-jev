"""Calibration analysis and train-only threshold sweeps."""

from __future__ import annotations

from dataclasses import dataclass

from payrecover.stats import CalibrationReport, expected_calibration_error


@dataclass(frozen=True)
class Prediction:
    case_id: str
    true_cause: str
    predicted: str
    confidence: float
    family: str | None = None


def calibration_from_predictions(rows: list[Prediction]) -> CalibrationReport:
    confidences = [row.confidence for row in rows]
    correct = [row.predicted == row.true_cause for row in rows]
    return expected_calibration_error(confidences, correct)


def reliability_markdown(report: CalibrationReport, *, title: str) -> str:
    lines = [
        f"### {title}",
        f"- n: {report.n}",
        f"- ECE: {report.ece:.4f}",
        "",
        "| bin | lo | hi | count | avg_conf | accuracy | gap |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report.bins:
        if int(row["count"]) == 0:
            continue
        lines.append(
            f"| {row['bin']} | {row['lo']} | {row['hi']} | {row['count']} | "
            f"{row['avg_confidence']} | {row['accuracy']} | {row['gap']} |"
        )
    lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class ThresholdPoint:
    min_confidence: float
    accuracy: float
    escalate_rate: float
    n: int


def confidence_threshold_sweep(
    rows: list[Prediction],
    *,
    thresholds: list[float] | None = None,
) -> list[ThresholdPoint]:
    """Train-only helper: accuracy if we escalate whenever confidence < t."""
    values = thresholds or [round(x * 0.05, 2) for x in range(2, 19)]
    points: list[ThresholdPoint] = []
    n = len(rows)
    for threshold in values:
        kept = [row for row in rows if row.confidence >= threshold]
        escalated = n - len(kept)
        if not kept:
            acc = 0.0
        else:
            acc = sum(1 for row in kept if row.predicted == row.true_cause) / len(kept)
        points.append(
            ThresholdPoint(
                min_confidence=threshold,
                accuracy=round(acc, 4),
                escalate_rate=round(escalated / n, 4) if n else 0.0,
                n=n,
            )
        )
    return points


def ambiguous_confidence_stats(rows: list[Prediction]) -> dict[str, float | int]:
    """Quantify the v1 bug pattern: confidence when true_cause is ambiguous."""
    amb = [row for row in rows if row.true_cause == "ambiguous"]
    if not amb:
        return {"n": 0, "mean_confidence": 0.0, "high_conf_wrong": 0}
    mean = sum(row.confidence for row in amb) / len(amb)
    high_wrong = sum(
        1 for row in amb if row.confidence >= 0.8 and row.predicted != "ambiguous"
    )
    return {
        "n": len(amb),
        "mean_confidence": round(mean, 4),
        "high_conf_wrong": high_wrong,
    }
