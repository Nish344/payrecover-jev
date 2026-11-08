"""Small stats helpers for honest reporting (Wilson CI, ECE)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WilsonInterval:
    low: float
    high: float
    center: float


def wilson_ci(successes: int, n: int, *, z: float = 1.96) -> WilsonInterval:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return WilsonInterval(0.0, 0.0, 0.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n))
    return WilsonInterval(
        low=max(0.0, center - margin),
        high=min(1.0, center + margin),
        center=center,
    )


@dataclass(frozen=True)
class CalibrationReport:
    ece: float
    bins: list[dict[str, float | int]]
    n: int


def expected_calibration_error(
    confidences: list[float],
    correct: list[bool],
    *,
    n_bins: int = 10,
) -> CalibrationReport:
    """ECE over equal-width confidence bins."""
    if not confidences or len(confidences) != len(correct):
        return CalibrationReport(ece=0.0, bins=[], n=0)
    bins: list[dict[str, float | int]] = []
    ece = 0.0
    n = len(confidences)
    for index in range(n_bins):
        lo = index / n_bins
        hi = (index + 1) / n_bins
        idxs = [
            i
            for i, conf in enumerate(confidences)
            if (conf >= lo and conf < hi) or (index == n_bins - 1 and conf == 1.0)
        ]
        if not idxs:
            bins.append(
                {
                    "bin": index,
                    "lo": lo,
                    "hi": hi,
                    "count": 0,
                    "avg_confidence": 0.0,
                    "accuracy": 0.0,
                    "gap": 0.0,
                }
            )
            continue
        avg_conf = sum(confidences[i] for i in idxs) / len(idxs)
        acc = sum(1 for i in idxs if correct[i]) / len(idxs)
        gap = abs(avg_conf - acc)
        ece += (len(idxs) / n) * gap
        bins.append(
            {
                "bin": index,
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "count": len(idxs),
                "avg_confidence": round(avg_conf, 4),
                "accuracy": round(acc, 4),
                "gap": round(gap, 4),
            }
        )
    return CalibrationReport(ece=round(ece, 4), bins=bins, n=n)
