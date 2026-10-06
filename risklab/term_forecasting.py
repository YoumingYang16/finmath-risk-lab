"""Purged annual, maturity-aligned forecasts and finite-class decisions.

Historical evaluation is retrospective exploratory research. All model fitting
is nonetheless causal: a supervised row becomes available only when its LAST
target observation has arrived. A h-return target is the average of the next h
squared log returns, not the square of their sum or a Q-measure option price.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .historical import (FEATURE_COLUMNS, LogVarianceRidge, VAR_FLOOR, VAR_CEILING,
                         causal_features, ewma_variance, validate_rates, variance_loss)
from .statistics import summarize_pnl

MODELS = ("rolling63", "ewma97", "ridge_flat", "ridge_term")
POLICIES = {"daily": {"kind": "fixed", "every": 1},
            "every5": {"kind": "fixed", "every": 5},
            "band05": {"kind": "band", "width": 0.05},
            "band10": {"kind": "band", "width": 0.10}}
SELECTORS = ("forecast_first", "joint_mse", "joint_es90")


def horizon_frame(rates: pd.Series, horizon: int) -> pd.DataFrame:
    """Feature-date t has target mean(r[t+1:t+h+1]^2), with explicit ends."""
    if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    rates = validate_rates(rates)
    frame = causal_features(rates)
    squared = np.log(rates).diff() ** 2
    frame["target"] = squared.rolling(horizon, min_periods=horizon).mean().shift(-horizon)
    dates = pd.Series(rates.index, index=rates.index)
    frame["target_start"] = dates.shift(-1)
    frame["target_end"] = dates.shift(-horizon)
    frame["horizon"] = int(horizon)
    return frame


def supervised_mask(frame: pd.DataFrame, start: str, end_before: str) -> pd.Series:
    """Labels must lie wholly inside [start,end_before), and features exist."""
    return ((frame["target_start"] >= pd.Timestamp(start)) &
            (frame["target_end"] < pd.Timestamp(end_before)) &
            frame[FEATURE_COLUMNS + ["target"]].notna().all(axis=1))


def fit_purged(frame: pd.DataFrame, alpha: float, training_start: str,
               label_end_before: str) -> tuple[LogVarianceRidge, dict]:
    mask = supervised_mask(frame, training_start, label_end_before)
    part = frame.loc[mask]
    if len(part) < 100:
        raise ValueError("Need at least 100 complete purged training labels")
    model = LogVarianceRidge(alpha=alpha).fit(part[FEATURE_COLUMNS].to_numpy(), part["target"].to_numpy())
    info = {"n": len(part), "target_start_min": str(part["target_start"].min().date()),
            "target_end_max": str(part["target_end"].max().date()),
            "feature_date_max": str(part.index.max().date()), "cutoff_exclusive": label_end_before,
            "horizon": int(part["horizon"].iloc[0]), **model.describe()}
    return model, info


def make_frames(rates: pd.Series, horizons: list[int]) -> dict[int, pd.DataFrame]:
    return {h: horizon_frame(rates, h) for h in horizons}


@dataclass
class ForecastBundle:
    """Models fitted at one historical cutoff; prediction reads causal features."""
    frames: dict[int, pd.DataFrame]
    ewma: pd.Series
    flat: LogVarianceRidge
    term: dict[int, LogVarianceRidge]
    fit_info: dict

    def predict(self, dates: pd.DatetimeIndex, remaining: int | np.ndarray) -> dict[str, np.ndarray]:
        dates = pd.DatetimeIndex(dates)
        frame = self.frames[1].reindex(dates)
        if frame[FEATURE_COLUMNS].isna().any().any():
            raise ValueError("Missing causal features at requested decision dates")
        rem = np.broadcast_to(np.asarray(remaining, dtype=int), (len(dates),))
        if any(int(h) not in self.term for h in np.unique(rem)):
            raise ValueError("Remaining horizons must be fitted")
        x = frame[FEATURE_COLUMNS].to_numpy()
        term_predictions = np.empty(len(dates))
        for h in np.unique(rem):
            pick = rem == h
            term_predictions[pick] = self.term[int(h)].predict(x[pick])
        return {"rolling63": frame["m2_63"].clip(VAR_FLOOR, VAR_CEILING).to_numpy(),
                "ewma97": self.ewma.reindex(dates).to_numpy(),
                "ridge_flat": self.flat.predict(x), "ridge_term": term_predictions}


def fit_bundle(frames: dict[int, pd.DataFrame], ewma: pd.Series,
               flat_alpha: float, term_alpha: float,
               training_start: str, label_end_before: str) -> ForecastBundle:
    flat, flat_info = fit_purged(frames[1], flat_alpha, training_start, label_end_before)
    models, information = {}, {}
    for h, frame in frames.items():
        models[h], information[str(h)] = fit_purged(frame, term_alpha, training_start, label_end_before)
    return ForecastBundle(frames, ewma, flat, models, {"flat": flat_info, "term": information})


def annual_forecasts(rates: pd.Series, year: int, alphas=(0.1, 1., 10., 100.),
                     horizons=tuple(range(1, 22)), training_start="2005-01-01") -> tuple[ForecastBundle, ForecastBundle, dict]:
    """Select on two past calendar years; refit only after fixing both alphas.

    Both alpha families are scored on the SAME complete 21-observation validation
    target windows. Flat fits h=1 but predicts a constant remaining-life input;
    term alpha is selected using h=21 and then shared across h=1..21 to limit the
    search space. Validation hedge forecasts retain the pre-validation fit.
    """
    if 1 not in horizons or 21 not in horizons:
        raise ValueError("The frozen study requires horizons 1 and 21")
    frames = make_frames(rates, list(horizons))
    ewma = ewma_variance(rates, .97)
    val_start, outer_start = f"{year - 2}-01-01", f"{year}-01-01"
    score_frame = frames[21].loc[supervised_mask(frames[21], val_start, outer_start)]
    if len(score_frame) < 100:
        raise ValueError("Insufficient complete inner validation targets")
    x_score, y_score = score_frame[FEATURE_COLUMNS].to_numpy(), score_frame["target"].to_numpy()
    candidates = []
    chosen = {}
    for family, h in [("ridge_flat", 1), ("ridge_term", 21)]:
        family_candidates = []
        for alpha in alphas:
            model, info = fit_purged(frames[h], alpha, training_start, val_start)
            score = float(variance_loss(y_score, model.predict(x_score)).mean())
            row = {"family": family, "alpha": float(alpha), "validation_qlike": score,
                   "fit_horizon": h, "fit_n": info["n"], "training_target_end_max": info["target_end_max"]}
            candidates.append(row); family_candidates.append(row)
        chosen[family] = min(family_candidates, key=lambda r: (r["validation_qlike"], r["alpha"]))["alpha"]
    validation = fit_bundle(frames, ewma, chosen["ridge_flat"], chosen["ridge_term"], training_start, val_start)
    forecasts = validation.predict(score_frame.index, 21)
    scores = {m: float(variance_loss(y_score, forecasts[m]).mean()) for m in MODELS}
    selected = min(MODELS, key=lambda m: (scores[m], m))
    outer = fit_bundle(frames, ewma, chosen["ridge_flat"], chosen["ridge_term"], training_start, outer_start)
    info = {"year": year, "validation_start": val_start, "validation_end_exclusive": outer_start,
            "validation_score_n": len(score_frame),
            "validation_score_first_target": str(score_frame["target_start"].min().date()),
            "validation_score_last_target": str(score_frame["target_end"].max().date()),
            "selected_alphas": chosen, "alpha_candidates": candidates,
            "validation_model_qlike": scores, "forecast_first_model": selected,
            "validation_fit": validation.fit_info, "outer_refit": outer.fit_info,
            "selection_interpretation": "Finite inner-validation choices; overlapping maturity targets and same validation reused for alpha/model/policy selection; final outer evaluation is temporally separate."}
    return validation, outer, info


def build_episodes(rates: pd.Series, bundle: ForecastBundle, start: str, end: str,
                   steps: int = 21) -> dict:
    """Complete nonoverlapping returns; all decisions precede their next return."""
    if steps != 21:
        raise ValueError("The frozen annual study uses 21-step episodes")
    rates = validate_rates(rates)
    part = rates.loc[start:end]
    positions = list(range(0, len(part) - steps, steps))
    if not positions:
        raise ValueError("No complete episodes")
    paths, dates, ends, premium_vol, decision_rows = [], [], [], [], []
    volatilities = {m: [] for m in MODELS}
    for episode_id, pos in enumerate(positions):
        segment = part.iloc[pos:pos + steps + 1]
        decision_dates = segment.index[:-1]
        remaining = np.arange(steps, 0, -1)
        estimates = bundle.predict(decision_dates, remaining)
        paths.append(segment.to_numpy() / segment.iloc[0] * 100.)
        dates.append(str(segment.index[0].date())); ends.append(str(segment.index[-1].date()))
        premium_vol.append(float(np.sqrt(252 * estimates["rolling63"][0])))
        for name in MODELS:
            volatilities[name].append(np.sqrt(252 * estimates[name]))
        for j, date in enumerate(decision_dates):
            decision_rows.append({"episode_id": episode_id, "step": j, "decision_date": str(date.date()),
                                  "remaining_horizon": int(remaining[j]), "normalized_spot": float(paths[-1][j]),
                                  **{name: float(estimates[name][j]) for name in MODELS}})
    return {"paths": np.asarray(paths), "start_dates": dates, "end_dates": ends,
            "premium_vol": np.asarray(premium_vol), "hedge_vol": {m: np.asarray(v) for m, v in volatilities.items()},
            "steps": steps, "horizon": steps / 252, "decision_rows": decision_rows,
            "observations": len(part), "unused_final_returns": (len(part) - 1) % steps}


def empirical_es(loss: np.ndarray, alpha: float = .90) -> float:
    loss = np.asarray(loss, float)
    if loss.ndim != 1 or not len(loss) or not np.isfinite(loss).all() or not 0 < alpha < 1:
        raise ValueError("Finite nonempty loss sample and alpha in (0,1) required")
    desc = np.sort(loss)[::-1]
    count = (1 - alpha) * len(desc)
    whole = min(int(np.floor(count)), len(desc))
    remainder = count - whole
    return float((desc[:whole].sum() + (remainder * desc[whole] if whole < len(desc) else 0.)) / count)


def risk_metrics(pnl: np.ndarray, cost: np.ndarray, trades: np.ndarray) -> dict:
    pnl = np.asarray(pnl, float)
    result = summarize_pnl(pnl, cost, trades)
    result.update(mse=float(np.mean(pnl ** 2)), pnl_variance=float(np.var(pnl, ddof=0)),
                  bias_squared=float(pnl.mean() ** 2), es90=empirical_es(-pnl, .9),
                  tail90_equivalent_observations=float(.1 * len(pnl)),
                  gross_mse=float(np.mean((pnl + cost) ** 2)))
    if not np.isclose(result["mse"], result["pnl_variance"] + result["bias_squared"], rtol=1e-11, atol=1e-13):
        raise ArithmeticError("MSE decomposition failed")
    return result


def choose_candidates(rows: list[dict], forecast_model: str, budget: float = .12) -> dict:
    """Deterministic finite candidate selection; explicit infeasible fallback."""
    if not rows or budget < 0 or not np.isfinite(budget):
        raise ValueError("Nonempty rows and finite nonnegative budget required")
    for row in rows:
        if not all(np.isfinite(row[k]) for k in ["mean_cost", "mse", "es90"]):
            raise ValueError("Candidate metrics must be finite")
    selections = {}
    for selector in SELECTORS:
        allowed = [r for r in rows if selector != "forecast_first" or r["model"] == forecast_model]
        if not allowed:
            raise ValueError("Forecast-selected family absent from candidates")
        feasible = [r for r in allowed if r["mean_cost"] <= budget]
        objective = "es90" if selector == "joint_es90" else "mse"
        if feasible:
            choice = min(feasible, key=lambda r: (r[objective], r["mean_cost"], r["model"], r["policy"]))
        else:
            choice = min(allowed, key=lambda r: (r["mean_cost"], r[objective], r["model"], r["policy"]))
        selections[selector] = {"selector": selector, "model": choice["model"], "policy": choice["policy"],
                                "selection_objective": objective, "validation_feasible": bool(feasible),
                                "feasible_candidates": len(feasible), "validation_mse": choice["mse"],
                                "validation_es90": choice["es90"], "validation_mean_cost": choice["mean_cost"],
                                "cost_budget": budget}
    return selections


def block_difference_inference(differences: np.ndarray, block_length: int = 3,
                               n_bootstrap: int = 4000, seed: int = 7619) -> dict:
    """Paired MBB interval and approximate centered-null, two-sided p-value.

    P uses resampled means of d-mean(d) under a zero-mean null, not the fraction
    of uncentered percentile replicates crossing zero. Dependence/stationarity
    and boundary-weighting approximations remain; no exact randomization claim.
    """
    d = np.asarray(differences, float)
    if d.ndim != 1 or len(d) < 2 or not np.isfinite(d).all():
        raise ValueError("At least two finite ordered paired differences required")
    if not isinstance(block_length, (int, np.integer)) or isinstance(block_length, bool) or not 1 <= block_length <= len(d):
        raise ValueError("Valid integer block length required")
    if not isinstance(n_bootstrap, (int, np.integer)) or n_bootstrap < 100:
        raise ValueError("At least 100 bootstrap replicates required")
    rng = np.random.default_rng(seed)
    means = np.empty(n_bootstrap)
    blocks = math.ceil(len(d) / block_length)
    offset = np.arange(block_length)
    for pos in range(0, n_bootstrap, 200):
        count = min(200, n_bootstrap - pos)
        starts = rng.integers(0, len(d) - block_length + 1, (count, blocks))
        indexes = (starts[:, :, None] + offset).reshape(count, -1)[:, :len(d)]
        means[pos:pos + count] = d[indexes].mean(axis=1)
    estimate = float(d.mean())
    null_means = means - estimate
    p = float((1 + np.count_nonzero(np.abs(null_means) >= abs(estimate))) / (n_bootstrap + 1))
    low, high = np.quantile(means, [.025, .975])
    return {"difference": estimate, "ci_low": float(low), "ci_high": float(high),
            "p_centered_approx": p, "n": len(d), "block_length": int(block_length),
            "n_bootstrap": int(n_bootstrap), "seed": seed,
            "interpretation": "Exploratory pointwise percentile MBB CI and approximate two-sided centered-null bootstrap p; conditional on evaluated procedures, assumes approximately stationary weak dependence."}


def holm_adjust(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, float)
    if p.ndim != 1 or not len(p) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Finite p-values in [0,1] required")
    order = np.argsort(p, kind="stable")
    adjusted = np.minimum(1., np.maximum.accumulate((len(p) - np.arange(len(p))) * p[order]))
    result = np.empty(len(p)); result[order] = adjusted
    return result.tolist()
