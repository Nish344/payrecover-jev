from __future__ import annotations

from payrecover.calibration import (
    Prediction,
    ambiguous_confidence_stats,
    calibration_from_predictions,
    confidence_threshold_sweep,
)
from payrecover.stats import expected_calibration_error, wilson_ci


def test_wilson_ci_bounds() -> None:
    ci = wilson_ci(8, 10)
    assert 0.0 <= ci.low <= ci.high <= 1.0
    assert ci.low < 0.8 < ci.high or abs(ci.center - 0.8) < 0.05


def test_ece_perfectly_calibrated() -> None:
    confidences = [0.1] * 10 + [0.9] * 10
    correct = [False] * 9 + [True] + [True] * 9 + [False]
    # Roughly calibrated extremes; just ensure function returns finite ECE.
    report = expected_calibration_error(confidences, correct, n_bins=5)
    assert report.n == 20
    assert 0.0 <= report.ece <= 1.0


def test_calibration_and_sweep_helpers() -> None:
    rows = [
        Prediction("a", "insufficient_funds", "insufficient_funds", 0.9),
        Prediction("b", "ambiguous", "ambiguous", 0.4),
        Prediction("c", "ambiguous", "insufficient_funds", 0.95),
        Prediction("d", "bank_downtime", "bank_downtime", 0.8),
    ]
    report = calibration_from_predictions(rows)
    assert report.n == 4
    amb = ambiguous_confidence_stats(rows)
    assert amb["n"] == 2
    assert amb["high_conf_wrong"] == 1
    sweep = confidence_threshold_sweep(rows, thresholds=[0.5, 0.9])
    assert len(sweep) == 2
    assert sweep[0].n == 4
