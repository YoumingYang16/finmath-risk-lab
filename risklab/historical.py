"""Causal forecasting and serial-dependence-aware historical experiments.

A row at decision date t uses quotes through t only and predicts the squared
log-return observed at the next published reference date. The target date,
rather than the feature date, assigns forecasting rows to temporal splits.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

VAR_FLOOR = 1e-10
VAR_CEILING = 0.04
FEATURE_COLUMNS = ["log_m2_1", "log_m2_5", "log_m2_21", "log_m2_63", "log_m2_126", "return_sum_5", "negative_fraction_21"]
ALPHAS = (0.1, 1.0, 10.0, 100.0)
EWMA_LAMBDAS = (0.94, 0.97, 0.99)
SPLITS = {"train": ("2005-01-01", "2016-12-31"), "validation": ("2017-01-01", "2020-12-31"), "test": ("2021-01-01", "2025-12-31")}


def split_labels(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    dates = pd.DatetimeIndex(dates)
    result = np.full(len(dates), "warmup", dtype=object)
    for label, (start, end) in SPLITS.items():
        result[(dates >= start) & (dates <= end)] = label
    return result


def validate_rates(rates: pd.Series) -> pd.Series:
    rates = rates.copy().astype(float)
    rates.index = pd.DatetimeIndex(rates.index)
    if rates.empty or not rates.index.is_monotonic_increasing or rates.index.has_duplicates:
        raise ValueError("Rates need a nonempty, strictly increasing, unique date index")
    if rates.index.isna().any() or not np.isfinite(rates.to_numpy()).all() or (rates <= 0).any():
        raise ValueError("Rates and dates must be finite and rates strictly positive")
    return rates


def causal_features(rates: pd.Series) -> pd.DataFrame:
    """Return features including the current return, never the future target."""
    rates = validate_rates(rates)
    returns = np.log(rates).diff()
    squared = returns.square() if hasattr(returns, "square") else returns ** 2
    features = pd.DataFrame(index=rates.index)
    features["spot"] = rates
    features["return"] = returns
    for window in (1, 5, 21, 63, 126):
        m2 = squared.rolling(window, min_periods=window).mean()
        features[f"m2_{window}"] = m2
        features[f"log_m2_{window}"] = np.log(m2.clip(lower=VAR_FLOOR))
    features["return_sum_5"] = returns.rolling(5, min_periods=5).sum()
    # The first undefined return is explicitly left undefined, not coded as >= 0.
    negative = returns.lt(0).astype(float).where(returns.notna())
    features["negative_fraction_21"] = negative.rolling(21, min_periods=21).mean()
    return features


def make_forecast_frame(rates: pd.Series) -> pd.DataFrame:
    frame = causal_features(rates)
    frame["target"] = (np.log(rates).diff() ** 2).shift(-1)
    frame["target_date"] = pd.Series(rates.index, index=rates.index).shift(-1)
    frame["split"] = split_labels(frame["target_date"])
    return frame.dropna(subset=FEATURE_COLUMNS + ["target", "target_date"])


def ewma_variance(rates: pd.Series, decay: float = 0.94) -> pd.Series:
    """h(t+1) = decay*h(t) + (1-decay)*r(t)^2, recursively from first return."""
    if not np.isfinite(decay) or not 0 < decay < 1:
        raise ValueError("EWMA decay must be strictly between zero and one")
    rates = validate_rates(rates)
    squared = np.log(rates).diff() ** 2
    return squared.ewm(alpha=1 - decay, adjust=False).mean().clip(VAR_FLOOR, VAR_CEILING)


def variance_loss(target: np.ndarray, forecast: np.ndarray, metric: str = "qlike") -> np.ndarray:
    target, forecast = np.broadcast_arrays(np.asarray(target, float), np.asarray(forecast, float))
    if target.size == 0 or not np.isfinite(target).all() or not np.isfinite(forecast).all():
        raise ValueError("Nonempty finite targets and forecasts required")
    if (target < 0).any() or (forecast <= 0).any():
        raise ValueError("Variance targets must be nonnegative and forecasts strictly positive")
    if metric == "qlike":
        # Target-only terms are omitted; this remains defined for zero returns.
        return np.log(forecast) + target / forecast
    if metric == "mse":
        return (target - forecast) ** 2
    raise ValueError("metric must be qlike or mse")


@dataclass
class LogVarianceRidge:
    """Ridge on log squared returns, with a training-only multiplicative correction.

    The correction mean(y/exp(fitted_log)) matches the training average ratio.
    It is an in-sample calibration assumption, not an unbiased variance theorem.
    Coefficients, scaling and calibration are frozen after training.
    """
    alpha: float = 1.0
    floor: float = VAR_FLOOR
    ceiling: float = VAR_CEILING

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LogVarianceRidge":
        x, y = np.asarray(x, float), np.asarray(y, float)
        if x.ndim != 2 or y.ndim != 1 or len(x) != len(y) or len(y) < 20:
            raise ValueError("Need a two-dimensional feature matrix and at least 20 aligned targets")
        if not np.isfinite(x).all() or not np.isfinite(y).all() or (y < 0).any():
            raise ValueError("Training data must be finite and targets nonnegative")
        if not (np.isfinite(self.alpha) and self.alpha > 0 and 0 < self.floor < self.ceiling):
            raise ValueError("Invalid regularization or variance bounds")
        self.scaler_ = StandardScaler().fit(x)
        self.regressor_ = Ridge(alpha=self.alpha, solver="svd").fit(self.scaler_.transform(x), np.log(np.maximum(y, self.floor)))
        log_fitted = self.regressor_.predict(self.scaler_.transform(x))
        self.correction_ = float(np.mean(y / np.exp(np.clip(log_fitted, -50, 10))))
        if not np.isfinite(self.correction_) or self.correction_ <= 0:
            raise ValueError("Training targets must contain positive variation")
        self.n_train_ = len(y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not hasattr(self, "regressor_"):
            raise ValueError("Fit the model before prediction")
        x = np.asarray(x, float)
        if x.ndim != 2 or not np.isfinite(x).all():
            raise ValueError("Finite two-dimensional features required")
        log_prediction = self.regressor_.predict(self.scaler_.transform(x))
        prediction = np.exp(np.clip(log_prediction, -50, 10)) * self.correction_
        return np.clip(prediction, self.floor, self.ceiling)

    def describe(self) -> dict[str, Any]:
        return {
            "model": "Ridge(log(max(next_squared_return,1e-10))) with train-only mean-ratio correction",
            "alpha": self.alpha, "n_train": self.n_train_, "correction": self.correction_,
            "intercept": float(self.regressor_.intercept_),
            "coefficients_standardized_features": self.regressor_.coef_.tolist(),
            "scaler_mean": self.scaler_.mean_.tolist(), "scaler_scale": self.scaler_.scale_.tolist(),
            "features": FEATURE_COLUMNS, "variance_floor": self.floor, "variance_ceiling": self.ceiling,
        }


def select_forecasts(rates: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Fit only through 2016, select hyperparameters on 2017-2020, freeze for test."""
    frame = make_forecast_frame(rates)
    frame = frame.loc[frame["split"] != "warmup"].copy()
    train, validation = frame["split"].eq("train"), frame["split"].eq("validation")
    if train.sum() < 100 or validation.sum() < 100:
        raise ValueError("Insufficient train or validation observations")
    y_train = frame.loc[train, "target"].to_numpy()
    x_train = frame.loc[train, FEATURE_COLUMNS].to_numpy()
    x_all = frame.loc[:, FEATURE_COLUMNS].to_numpy()
    frame["train_constant"] = float(np.clip(y_train.mean(), VAR_FLOOR, VAR_CEILING))
    frame["rolling63"] = frame["m2_63"].clip(VAR_FLOOR, VAR_CEILING)
    candidates = []
    fitted = {}
    for alpha in ALPHAS:
        model = LogVarianceRidge(alpha=alpha).fit(x_train, y_train)
        name = f"ridge_alpha_{alpha:g}"
        frame[name] = model.predict(x_all)
        score = float(variance_loss(frame.loc[validation, "target"], frame.loc[validation, name]).mean())
        candidates.append({"family": "ridge", "value": alpha, "model": name, "validation_qlike": score})
        fitted[name] = model
    for decay in EWMA_LAMBDAS:
        name = f"ewma_lambda_{decay:g}"
        frame[name] = ewma_variance(rates, decay).reindex(frame.index)
        score = float(variance_loss(frame.loc[validation, "target"], frame.loc[validation, name]).mean())
        candidates.append({"family": "ewma", "value": decay, "model": name, "validation_qlike": score})
    best_ridge = min((c for c in candidates if c["family"] == "ridge"), key=lambda c: c["validation_qlike"])
    best_ewma = min((c for c in candidates if c["family"] == "ewma"), key=lambda c: c["validation_qlike"])
    frame["ridge"] = frame[best_ridge["model"]]
    frame["ewma"] = frame[best_ewma["model"]]
    family_scores = {name: float(variance_loss(frame.loc[validation, "target"], frame.loc[validation, name]).mean()) for name in ["train_constant", "rolling63", "ewma", "ridge"]}
    selected_name = min(family_scores, key=family_scores.get)
    frame["selected"] = frame[selected_name]
    info = {
        "train_target_start": str(frame.loc[train, "target_date"].min().date()),
        "train_target_end": str(frame.loc[train, "target_date"].max().date()),
        "selection_target_start": str(frame.loc[validation, "target_date"].min().date()),
        "selection_target_end": str(frame.loc[validation, "target_date"].max().date()),
        "hyperparameter_candidates": candidates, "ridge_alpha": best_ridge["value"],
        "ewma_lambda": best_ewma["value"], "validation_family_qlike": family_scores,
        "selected_forecast_family": selected_name, "selected_ridge": fitted[best_ridge["model"]].describe(),
        "refit_policy": "No refit after training. Coefficients, standardization and calibration frozen from 2005-2016. Rolling/EWMA states and features update causally as new observations arrive.",
        "split_rule": "Target date assigns forecast split; the 2016-12-30 decision predicting the first 2017 quote is validation, never training.",
        "clipping_counts": {name: int(((frame[name] <= VAR_FLOOR) | (frame[name] >= VAR_CEILING)).sum()) for name in ["train_constant", "rolling63", "ewma", "ridge"]},
    }
    keep = ["spot", "return", "target", "target_date", "split", "train_constant", "rolling63", "ewma", "ridge", "selected"]
    return frame.loc[:, keep], info


def moving_block_mean_ci(values: np.ndarray, block_length: int = 21, n_bootstrap: int = 2000, seed: int = 17, confidence: float = 0.95) -> dict:
    """Percentile interval from overlapping, noncircular, fixed-length blocks.

    Draw block starts uniformly from 0..n-L, concatenate ceil(n/L) blocks and
    truncate to n. This is a moving-block bootstrap, not stationary bootstrap.
    """
    values = np.asarray(values, float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("At least two finite ordered observations required")
    if isinstance(block_length, (bool, np.bool_)) or not isinstance(block_length, (int, np.integer)) or not 1 <= block_length <= len(values):
        raise ValueError("block_length must be an integer between 1 and sample size")
    if isinstance(n_bootstrap, (bool, np.bool_)) or not isinstance(n_bootstrap, (int, np.integer)) or n_bootstrap < 100:
        raise ValueError("At least 100 bootstrap replicates required")
    if not np.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(len(values) / block_length)
    estimates = np.empty(n_bootstrap)
    offsets = np.arange(block_length)
    for start in range(0, n_bootstrap, 100):
        count = min(100, n_bootstrap - start)
        starts = rng.integers(0, len(values) - block_length + 1, size=(count, blocks_per_sample))
        indices = (starts[:, :, None] + offsets).reshape(count, -1)[:, :len(values)]
        estimates[start:start + count] = values[indices].mean(axis=1)
    lower, upper = np.quantile(estimates, [(1 - confidence) / 2, 1 - (1 - confidence) / 2])
    return {"mean": float(values.mean()), "ci_low": float(lower), "ci_high": float(upper),
            "confidence": confidence, "n": len(values), "block_length": block_length,
            "n_bootstrap": n_bootstrap, "seed": seed, "method": "overlapping noncircular moving-block percentile bootstrap",
            "interpretation": "Pointwise descriptive interval; stationary/weak-dependence approximation, no multiple-comparison adjustment, ignores model-selection uncertainty."}


def forecast_evaluation(frame: pd.DataFrame) -> dict:
    results = {}
    methods = ["train_constant", "rolling63", "ewma", "ridge"]
    for split in ["validation", "test"]:
        part = frame.loc[frame["split"] == split]
        results[split] = {
            "n": len(part), "target_start": str(part["target_date"].min().date()), "target_end": str(part["target_date"].max().date()),
            "metrics": {name: {metric: float(variance_loss(part["target"], part[name], metric).mean()) for metric in ["qlike", "mse"]} for name in methods},
        }
    test = frame.loc[frame["split"] == "test"]
    comparisons = []
    for method in ["train_constant", "ewma", "ridge"]:
        for metric in ["qlike", "mse"]:
            differences = variance_loss(test["target"], test[method], metric) - variance_loss(test["target"], test["rolling63"], metric)
            for length in [5, 21, 63]:
                comparisons.append({"candidate": method, "reference": "rolling63", "metric": metric, "negative_favors_candidate": True, **moving_block_mean_ci(differences, length)})
    results["test_loss_difference_intervals"] = comparisons
    results["test_yearly"] = []
    for year, part in test.groupby(test["target_date"].dt.year):
        for method in methods:
            results["test_yearly"].append({"year": int(year), "method": method, "n": len(part), **{metric: float(variance_loss(part["target"], part[method], metric).mean()) for metric in ["qlike", "mse"]}})
    return results


def historical_episodes(rates: pd.Series, forecasts: pd.DataFrame, split: str, steps: int = 21) -> dict:
    """Complete episodes wholly inside a split, sharing only boundary observations.

    Normalization maps each episode's first quote to 100. No return is reused
    within a currency/split. The terminal observation is not a hedge decision.
    """
    if split not in ["validation", "test"] or isinstance(steps, (bool, np.bool_)) or not isinstance(steps, (int, np.integer)) or steps < 1:
        raise ValueError("Expected validation/test and positive integer episode steps")
    rates = validate_rates(rates)
    start, end = SPLITS[split]
    part = rates.loc[start:end]
    paths, starts, ends, matrices, premium_vol = [], [], [], {n: [] for n in ["rolling63", "ewma", "ridge", "selected"]}, []
    for position in range(0, len(part) - steps, steps):
        path = part.iloc[position:position + steps + 1]
        decision_dates = path.index[:-1]
        if not decision_dates.isin(forecasts.index).all():
            raise ValueError("Missing causal forecasts for one or more episode decisions")
        rows = forecasts.loc[decision_dates]
        # These rows need not share a target label at the boundary; every target
        # used here is inside the episode, which is wholly in the requested split.
        paths.append(path.to_numpy() / path.iloc[0] * 100)
        starts.append(str(path.index[0].date()))
        ends.append(str(path.index[-1].date()))
        premium_vol.append(float(np.sqrt(252 * rows.iloc[0]["rolling63"])))
        for name in matrices:
            matrices[name].append(np.sqrt(252 * rows[name].to_numpy()))
    if not paths:
        raise ValueError("No complete historical option episodes")
    return {"paths": np.asarray(paths), "start_dates": starts, "end_dates": ends,
            "premium_vol": np.asarray(premium_vol), "hedge_vol": {name: np.asarray(vals) for name, vals in matrices.items()},
            "steps": steps, "split": split, "observations_in_split": len(part),
            "unused_final_return_count": (len(part) - 1) % steps, "horizon": steps / 252}


def choose_threshold(validation_results: list[dict], cost_budget: float = 0.12) -> tuple[dict, dict]:
    """Select validation net-RMSE among cost-feasible thresholds; declare fallback."""
    if not validation_results or not np.isfinite(cost_budget) or cost_budget < 0:
        raise ValueError("Nonempty candidate results and nonnegative budget required")
    for result in validation_results:
        if not all(np.isfinite(result[k]) for k in ["threshold", "mean_cost", "rmse"]) or result["mean_cost"] < 0 or result["rmse"] < 0:
            raise ValueError("Invalid threshold candidate")
    feasible = [row for row in validation_results if row["mean_cost"] <= cost_budget]
    selected = min(feasible, key=lambda row: (row["rmse"], row["threshold"])) if feasible else min(validation_results, key=lambda row: (row["mean_cost"], row["rmse"]))
    return selected, {"cost_budget_per_100_initial_notional": cost_budget, "feasible_candidate_count": len(feasible),
                      "selection_rule": "Smallest validation net RMSE among mean-cost-feasible thresholds; if none feasible, minimum mean cost with an explicit infeasible flag.",
                      "budget_feasible_in_validation": bool(feasible), "budget_is_validation_constraint_not_test_guarantee": True}
