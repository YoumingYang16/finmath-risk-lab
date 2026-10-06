"""Finite, explicitly defined descriptive and paired-path research statistics."""

from __future__ import annotations

import numpy as np
from scipy.stats import t as student_t


def _sample(values, name):
    sample = np.asarray(values, dtype=float)
    if sample.ndim != 1 or sample.size == 0 or not np.all(np.isfinite(sample)):
        raise ValueError(f"{name} must be a nonempty finite one-dimensional sample")
    return sample


def summarize_pnl(pnl, cost=None, trades=None):
    """Summarize seller net P&L (premium, hedge and all costs included).

    Loss=-P&L; negative VaR/ES is allowed when all outcomes are gains. VaR95 is
    NumPy's linearly interpolated empirical quantile. ES95 is the integral of
    the upper 5% of the *empirical distribution*, using fractional boundary
    mass, so ties and noninteger tail sample counts do not inflate tail mass.
    RMSE is sqrt(mean(P&L**2)), relative to zero target P&L. std uses ddof=1 for
    n>1 and reports zero for a one-element descriptive sample.
    """
    p = _sample(pnl, "pnl")
    n = p.size
    loss = -p
    descending = np.sort(loss)[::-1]
    tail_count = 0.05 * n
    whole = int(np.floor(tail_count))
    fraction = tail_count - whole
    tail_sum = float(np.sum(descending[:whole]))
    if fraction > 0:
        tail_sum += fraction * float(descending[whole])
    es = tail_sum / tail_count
    outputs = {"n": int(n), "mean_pnl": float(np.mean(p)),
               "std_pnl": float(np.std(p, ddof=1)) if n > 1 else 0.0,
               "rmse": float(np.sqrt(np.mean(p ** 2))), "mean_loss": float(np.mean(loss)),
               "var95": float(np.quantile(loss, 0.95, method="linear")), "es95": es,
               "mean_cost": None, "mean_trades": None}
    for name, values in [("cost", cost), ("trades", trades)]:
        if values is not None:
            array = _sample(values, name)
            if array.shape != p.shape or np.any(array < 0):
                raise ValueError(f"{name} must match pnl and be nonnegative")
            outputs[f"mean_{name}"] = float(np.mean(array))
    if any(not np.isfinite(v) for v in outputs.values() if v is not None):
        raise ValueError("sample magnitude causes nonfinite summary")
    return outputs


def paired_mean_ci(a, b, confidence=0.95):
    """Pointwise Student-t CI for mean(a-b) across independent paired paths.

    This does not justify an independent-path CI for overlapping historical
    episodes, or simultaneous coverage across many strategy comparisons.
    """
    a, b = _sample(a, "a"), _sample(b, "b")
    if a.shape != b.shape or a.size < 2:
        raise ValueError("paired samples must have equal length >=2")
    if np.ndim(confidence) != 0 or not np.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between 0 and 1")
    delta = a - b
    mean = float(np.mean(delta))
    se = float(np.std(delta, ddof=1) / np.sqrt(delta.size))
    half = float(student_t.ppf(0.5 + confidence / 2, delta.size - 1) * se)
    result = {"difference": mean, "standard_error": se, "ci_low": mean - half,
              "ci_high": mean + half, "n": int(delta.size)}
    if not all(np.isfinite(v) for v in result.values()):
        raise ValueError("sample magnitude causes nonfinite paired interval")
    return result
