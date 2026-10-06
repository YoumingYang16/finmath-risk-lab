"""Temporal integrity and statistical-contract tests for the historical study."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from risklab.historical import (FEATURE_COLUMNS, LogVarianceRidge, causal_features,
    choose_threshold, ewma_variance, historical_episodes, make_forecast_frame,
    moving_block_mean_ci, select_forecasts, split_labels, validate_rates, variance_loss)


def synthetic_rates(start="1999-01-01", end="2025-12-31"):
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(1234)
    innovations = rng.normal(0, 0.008, len(dates))
    return pd.Series(100 * np.exp(np.cumsum(innovations)), index=dates)


def test_future_observations_do_not_change_earlier_features():
    rates = synthetic_rates()
    cutoff = pd.Timestamp("2022-06-15")
    modified = rates.copy()
    modified.loc[modified.index > cutoff] *= np.linspace(1.5, 2.5, (modified.index > cutoff).sum())
    pd.testing.assert_frame_equal(causal_features(rates).loc[:cutoff], causal_features(modified).loc[:cutoff])


def test_target_date_prevents_year_boundary_training_leakage():
    frame = make_forecast_frame(synthetic_rates())
    decision = frame.loc[pd.Timestamp("2016-12-30")]
    assert decision["target_date"] == pd.Timestamp("2017-01-02")
    assert decision["split"] == "validation"
    assert frame.loc[frame["split"] == "train", "target_date"].max() <= pd.Timestamp("2016-12-31")


def test_fixed_splits_and_missing_dates():
    labels = split_labels(pd.to_datetime(["2004-12-31", "2005-01-01", "2017-01-01", "2021-01-01", "2026-01-01", None]))
    assert labels.tolist() == ["warmup", "train", "validation", "test", "warmup", "warmup"]


def test_test_path_changes_cannot_change_model_selection_or_validation_predictions():
    rates = synthetic_rates()
    original, original_selection = select_forecasts(rates)
    modified = rates.copy()
    mask = modified.index >= "2021-01-01"
    modified.loc[mask] *= np.exp(np.sin(np.arange(mask.sum())) * 0.05)
    altered, altered_selection = select_forecasts(modified)
    assert altered_selection == original_selection
    # The target on the final validation decision may be the first test target;
    # compare only forecast inputs/outputs and validation targets before 2021.
    pd.testing.assert_frame_equal(original.loc[original["split"] == "validation"], altered.loc[altered["split"] == "validation"])


def test_ewma_recurrence_has_one_step_information_alignment():
    returns = np.array([0.1, -0.2, 0.05])
    rates = pd.Series(np.exp(np.r_[0, np.cumsum(returns)]), index=pd.date_range("2020-01-01", periods=4))
    result = ewma_variance(rates, decay=0.9)
    assert result.iloc[1] == pytest.approx(0.01)
    assert result.iloc[2] == pytest.approx(0.9 * 0.01 + 0.1 * 0.04)
    assert result.iloc[3] == pytest.approx(0.9 * (0.9 * 0.01 + 0.1 * 0.04) + 0.1 * 0.0025)


def test_ridge_positive_finite_and_serializable_fit_metadata():
    frame = make_forecast_frame(synthetic_rates()).iloc[:200]
    model = LogVarianceRidge().fit(frame[FEATURE_COLUMNS], frame["target"])
    predictions = model.predict(frame[FEATURE_COLUMNS])
    assert np.isfinite(predictions).all() and (predictions > 0).all()
    assert len(model.describe()["coefficients_standardized_features"]) == len(FEATURE_COLUMNS)
    assert model.describe()["n_train"] == 200
    json.dumps(model.describe(), allow_nan=False)


def test_ridge_predict_does_not_reestimate_scaling():
    frame = make_forecast_frame(synthetic_rates()).iloc[:200]
    model = LogVarianceRidge().fit(frame[FEATURE_COLUMNS], frame["target"])
    before = model.describe()
    model.predict(frame[FEATURE_COLUMNS] * 10)
    assert model.describe() == before


def test_loss_handles_zero_return_and_reports_squared_variance_units():
    y, h = np.array([0.0, 4.0]), np.array([1.0, 2.0])
    np.testing.assert_allclose(variance_loss(y, h), [0.0, np.log(2) + 2])
    np.testing.assert_allclose(variance_loss(y, h, "mse"), [1.0, 4.0])


@pytest.mark.parametrize("y,h", [([1], [0]), ([-1], [1]), ([np.nan], [1]), ([1], [np.inf]), ([], [])])
def test_loss_rejects_invalid_evaluation(y, h):
    with pytest.raises(ValueError):
        variance_loss(y, h)


def test_moving_block_bootstrap_exact_for_constant_paired_differences():
    result = moving_block_mean_ci(np.full(60, 2.5), block_length=6, n_bootstrap=300)
    assert result["mean"] == result["ci_low"] == result["ci_high"] == 2.5


def test_moving_block_bootstrap_reproducible_and_respects_order():
    ordered = np.repeat(np.array([-1.0, 1.0]), 100)
    interval = moving_block_mean_ci(ordered, block_length=20, n_bootstrap=1000, seed=9)
    same = moving_block_mean_ci(ordered, block_length=20, n_bootstrap=1000, seed=9)
    independent = moving_block_mean_ci(ordered, block_length=1, n_bootstrap=1000, seed=9)
    assert interval == same
    assert interval["ci_high"] - interval["ci_low"] > independent["ci_high"] - independent["ci_low"]


@pytest.mark.parametrize("block", [0, -1, 11, 1.2, 3.0, True, np.bool_(True)])
def test_moving_block_bootstrap_rejects_invalid_block_length(block):
    with pytest.raises(ValueError):
        moving_block_mean_ci(np.arange(10), block_length=block)


@pytest.mark.parametrize("count", [200.0, True, np.nan, 1])
def test_moving_block_bootstrap_rejects_invalid_replicate_count(count):
    with pytest.raises(ValueError):
        moving_block_mean_ci(np.arange(10), block_length=2, n_bootstrap=count)


def test_episode_steps_rejects_float_even_when_integer_valued():
    rates = synthetic_rates()
    with pytest.raises(ValueError):
        historical_episodes(rates, pd.DataFrame(), "test", steps=21.0)


def test_episode_paths_normalize_and_do_not_overlap_returns():
    rates = synthetic_rates()
    forecasts, _ = select_forecasts(rates)
    episodes = historical_episodes(rates, forecasts, "test")
    assert episodes["paths"].shape[1] == 22
    np.testing.assert_array_equal(episodes["paths"][:, 0], 100)
    assert episodes["start_dates"][0] >= "2021-01-01"
    assert episodes["end_dates"][-1] <= "2025-12-31"
    assert episodes["end_dates"][:-1] == episodes["start_dates"][1:]
    # Every volatility in a step matrix corresponds exactly to that step's date.
    first_dates = rates.loc[episodes["start_dates"][0]:episodes["end_dates"][0]].index[:-1]
    np.testing.assert_allclose(episodes["hedge_vol"]["ridge"][0], np.sqrt(252 * forecasts.loc[first_dates, "ridge"]))
    assert episodes["premium_vol"][0] == pytest.approx(np.sqrt(252 * forecasts.loc[first_dates[0], "rolling63"]))


def test_threshold_selection_enforces_validation_budget():
    candidates = [{"threshold": 0.01, "rmse": 0.1, "mean_cost": 0.5}, {"threshold": 0.1, "rmse": 0.2, "mean_cost": 0.1}, {"threshold": 0.2, "rmse": 0.3, "mean_cost": 0.05}]
    selected, info = choose_threshold(candidates, cost_budget=0.12)
    assert selected["threshold"] == 0.1
    assert info["budget_feasible_in_validation"] is True
    selected, info = choose_threshold(candidates, cost_budget=0.01)
    assert selected["threshold"] == 0.2
    assert info["budget_feasible_in_validation"] is False


@pytest.mark.parametrize("values,dates", [([1, 1], ["2020-01-02", "2020-01-01"]), ([1, 1], ["2020-01-01", "2020-01-01"]), ([1, 0], ["2020-01-01", "2020-01-02"]), ([1, np.nan], ["2020-01-01", "2020-01-02"])])
def test_rates_fail_closed_on_invalid_sources(values, dates):
    with pytest.raises(ValueError):
        validate_rates(pd.Series(values, index=pd.to_datetime(dates)))


def test_frozen_ecb_source_integrity_and_endpoint():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "data/source_manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        assert hashlib.sha256((root / "data" / name).read_bytes()).hexdigest() == info["sha256"]
    rates = pd.read_csv(root / "data/ecb_usd_jpy.csv")
    assert rates.iloc[-1]["date"] == "2025-12-31"
    assert rates["date"].is_monotonic_increasing and not rates["date"].duplicated().any()
    assert (rates[["USD", "JPY"]] > 0).all().all()


def test_saved_experiment_has_common_premium_across_competing_strategies():
    root = Path(__file__).resolve().parents[1]
    path = root / "results/historical_episodes.csv"
    if not path.exists():
        pytest.skip("Execute run_historical.py to audit generated evidence")
    episodes = pd.read_csv(path)
    premium_counts = episodes.groupby(["currency", "split", "episode_id"])["common_premium"].nunique()
    assert (premium_counts == 1).all()
    assert not episodes.select_dtypes("number").isna().any().any()


def test_saved_ledger_reconciles_to_terminal_pnl_and_cost():
    root = Path(__file__).resolve().parents[1]
    if not (root / "results/historical_ledger.csv").exists():
        pytest.skip("Execute run_historical.py to audit generated evidence")
    ledger = pd.read_csv(root / "results/historical_ledger.csv")
    episodes = pd.read_csv(root / "results/historical_episodes.csv")
    keys = ["currency", "split", "episode_id", "strategy", "cost_bps"]
    endings = ledger.loc[ledger["event"] == "settlement"].merge(episodes, on=keys, validate="one_to_one")
    np.testing.assert_allclose(endings["cash_after"], endings["pnl"], atol=1e-12)
    np.testing.assert_allclose(endings["cumulative_cost"], endings["cost"], atol=1e-12)
    fees = ledger.groupby(keys)["fee"].sum().rename("ledger_fees").reset_index().merge(episodes, on=keys, validate="one_to_one")
    np.testing.assert_allclose(fees["ledger_fees"], fees["cost"], atol=1e-12)


def test_saved_results_dont_switch_selected_family_based_on_test_rank():
    root = Path(__file__).resolve().parents[1]
    if not (root / "results/historical_summary.json").exists():
        pytest.skip("Execute run_historical.py to audit generated evidence")
    summary = json.loads((root / "results/historical_summary.json").read_text(encoding="utf-8"))
    for currency in summary["currencies"].values():
        scores = currency["selection"]["validation_family_qlike"]
        assert currency["selection"]["selected_forecast_family"] == min(scores, key=scores.get)
        assert currency["forecast_evaluation"]["test"]["n"] == currency["forecast_rows"]["test"]
        assert currency["episode_counts"]["test"]["last_end"] <= "2025-12-31"
