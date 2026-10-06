"""V2 tests target information timing, accounting comparisons and inference."""
import numpy as np
import pandas as pd
import pytest

from risklab.term_forecasting import (FEATURE_COLUMNS, horizon_frame, supervised_mask,
    fit_purged, annual_forecasts, build_episodes, risk_metrics, choose_candidates,
    empirical_es, block_difference_inference, holm_adjust)


@pytest.fixture(scope="module")
def long_rates():
    dates = pd.bdate_range("1999-01-01", "2026-09-30")
    rng = np.random.default_rng(4907)
    returns = rng.normal(0., .005, len(dates))
    return pd.Series(1.2 * np.exp(returns.cumsum()), index=dates)


def test_multistep_target_is_mean_of_future_squares(long_rates):
    h = 21
    frame = horizon_frame(long_rates, h)
    returns = np.log(long_rates).diff()
    for i in [126, 512, 4000]:
        expected = np.mean(returns.iloc[i+1:i+h+1].to_numpy() ** 2)
        assert frame.iloc[i]["target"] == pytest.approx(expected)
        assert frame.iloc[i]["target_start"] == long_rates.index[i+1]
        assert frame.iloc[i]["target_end"] == long_rates.index[i+h]
    assert frame["target"].tail(h).isna().all()


def test_purge_uses_end_not_decision_or_first_target(long_rates):
    frame = horizon_frame(long_rates, 21)
    pick = supervised_mask(frame, "2005-01-01", "2018-01-01")
    assert frame.loc[pick, "target_end"].max() < pd.Timestamp("2018-01-01")
    crossing = ((frame.index < pd.Timestamp("2018-01-01")) &
                (frame["target_start"] < pd.Timestamp("2018-01-01")) &
                (frame["target_end"] >= pd.Timestamp("2018-01-01")))
    assert crossing.sum() >= 19
    assert not pick[crossing].any()
    assert frame.loc[pick, "target_start"].min() >= pd.Timestamp("2005-01-01")


def test_future_mutation_does_not_change_purged_fit_or_scaler(long_rates):
    changed = long_rates.copy()
    changed.loc["2018-01-01":] *= np.exp(np.linspace(1, 3, len(changed.loc["2018-01-01":])))
    a, ai = fit_purged(horizon_frame(long_rates, 21), 1., "2005-01-01", "2018-01-01")
    b, bi = fit_purged(horizon_frame(changed, 21), 1., "2005-01-01", "2018-01-01")
    np.testing.assert_allclose(a.scaler_.mean_, b.scaler_.mean_, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(a.regressor_.coef_, b.regressor_.coef_, rtol=1e-9, atol=1e-11)
    assert a.correction_ == pytest.approx(b.correction_, rel=1e-11)
    assert ai["target_end_max"] == bi["target_end_max"]


def test_training_scaler_equals_only_eligible_features(long_rates):
    frame = horizon_frame(long_rates, 21)
    model, info = fit_purged(frame, 10., "2005-01-01", "2018-01-01")
    eligible = frame.loc[supervised_mask(frame, "2005-01-01", "2018-01-01")]
    np.testing.assert_allclose(model.scaler_.mean_, eligible[FEATURE_COLUMNS].mean().to_numpy(), atol=1e-12)
    assert info["n"] == len(eligible)


def test_outer_values_cannot_change_inner_choice_or_refit(long_rates):
    # Price at and beyond Jan 2020 changes dramatically. Neither inner choice
    # nor the final model trained before 2020 may change.
    changed = long_rates.copy()
    changed.loc["2020-01-01":] *= np.exp(np.linspace(.5, 1., len(changed.loc["2020-01-01":])))
    _, a, ai = annual_forecasts(long_rates, 2020, horizons=(1, 21))
    _, b, bi = annual_forecasts(changed, 2020, horizons=(1, 21))
    assert ai["selected_alphas"] == bi["selected_alphas"]
    assert ai["forecast_first_model"] == bi["forecast_first_model"]
    for name in ai["validation_model_qlike"]:
        assert ai["validation_model_qlike"][name] == pytest.approx(bi["validation_model_qlike"][name], rel=1e-10)
    np.testing.assert_allclose(a.term[21].regressor_.coef_, b.term[21].regressor_.coef_, rtol=1e-8, atol=1e-10)
    assert ai["validation_fit"]["term"]["21"]["target_end_max"] < "2018-01-01"
    assert ai["outer_refit"]["term"]["21"]["target_end_max"] < "2020-01-01"
    assert ai["outer_refit"]["term"]["21"]["n"] > ai["validation_fit"]["term"]["21"]["n"]
    assert ai["validation_score_first_target"] >= "2018-01-01"
    assert ai["validation_score_last_target"] < "2020-01-01"


def test_episode_horizons_and_no_reused_returns(long_rates):
    _, model, info = annual_forecasts(long_rates, 2020)
    episodes = build_episodes(long_rates, model, "2020-01-01", "2020-12-31")
    assert episodes["paths"].shape[1] == 22
    np.testing.assert_array_equal(episodes["paths"][:, 0], 100.)
    assert episodes["end_dates"][:-1] == episodes["start_dates"][1:]
    first = episodes["decision_rows"][:21]
    assert [r["remaining_horizon"] for r in first] == list(range(21, 0, -1))
    dates = pd.DatetimeIndex([r["decision_date"] for r in first])
    expected = model.predict(dates, np.arange(21, 0, -1))
    np.testing.assert_allclose(episodes["hedge_vol"]["ridge_term"][0] ** 2 / 252, expected["ridge_term"])
    assert episodes["premium_vol"][0] == pytest.approx(episodes["hedge_vol"]["rolling63"][0, 0])
    assert first[-1]["decision_date"] < episodes["end_dates"][0]


def test_mse_decomposition_and_fractional_es():
    pnl = np.array([-4., -1., 2., 3., 5., 6.])
    metrics = risk_metrics(pnl, np.ones(6) * .1, np.ones(6))
    assert metrics["mse"] == pytest.approx(metrics["pnl_variance"] + metrics["bias_squared"])
    assert metrics["es90"] == pytest.approx(4.)
    # Upper 1.5 observations: one loss 6 and half loss 5.
    assert empirical_es(np.arange(1., 7.), .75) == pytest.approx((6 + .5 * 5) / 1.5)


def test_selectors_differ_and_fallback_is_explicit():
    rows = [{"model": "a", "policy": "daily", "mean_cost": .1, "mse": 2., "es90": 3.},
            {"model": "b", "policy": "daily", "mean_cost": .1, "mse": 1., "es90": 4.},
            {"model": "b", "policy": "band", "mean_cost": .11, "mse": 3., "es90": 2.}]
    result = choose_candidates(rows, "a", .12)
    assert result["forecast_first"]["model"] == "a"
    assert result["joint_mse"]["model"] == "b" and result["joint_mse"]["policy"] == "daily"
    assert result["joint_es90"]["policy"] == "band"
    fallback = choose_candidates(rows, "a", .01)
    assert all(not row["validation_feasible"] for row in fallback.values())
    assert all(row["validation_mean_cost"] == .1 for row in fallback.values())


def test_centered_null_p_is_not_uncentered_percentile_tail():
    positive = block_difference_inference(np.ones(30), 3, 1000, 71)
    assert positive["p_centered_approx"] == pytest.approx(1 / 1001)
    assert positive["ci_low"] == positive["ci_high"] == 1.
    zero = block_difference_inference(np.zeros(30), 3, 1000, 71)
    assert zero["p_centered_approx"] == 1.
    a = block_difference_inference(np.sin(np.arange(100.)) + .05, 6, 1000, 71)
    b = block_difference_inference(np.sin(np.arange(100.)) + .05, 6, 1000, 71)
    assert a == b


def test_holm_adjustment_known_values_and_order():
    assert holm_adjust([.01, .04, .03]) == pytest.approx([.03, .06, .06])
    assert holm_adjust([.04, .01, .03]) == pytest.approx([.06, .03, .06])
    assert holm_adjust([0., 1.]) == [0., 1.]


@pytest.mark.parametrize("h", [0, -1, True, 1.5])
def test_reject_invalid_horizon(long_rates, h):
    with pytest.raises(ValueError):
        horizon_frame(long_rates, h)


@pytest.mark.parametrize("block", [0, 101, True, 1.5])
def test_reject_invalid_block(block):
    with pytest.raises(ValueError):
        block_difference_inference(np.ones(100), block)
