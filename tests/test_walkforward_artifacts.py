"""Independent checks of the released V2 empirical evidence and its provenance."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from risklab.term_forecasting import choose_candidates, holm_adjust

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def evidence():
    path = ROOT / "results/v2_historical_summary.json"
    if not path.exists():
        pytest.skip("Run scripts/run_walkforward.py to generate empirical evidence")
    summary = json.loads(path.read_text(encoding="utf-8"))
    episodes = pd.read_csv(ROOT / "results/v2_historical_episodes.csv")
    selected = pd.read_csv(ROOT / "results/v2_historical_selections.csv")
    predictions = pd.read_csv(ROOT / "results/v2_historical_predictions.csv")
    return summary, episodes, selected, predictions


def test_frozen_protocol_source_and_implementation_hashes(evidence):
    summary = evidence[0]
    assert hashlib.sha256((ROOT / "docs/v2_protocol.json").read_bytes()).hexdigest() == summary["protocol_sha256"]
    for filename, digest in summary["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    for filename, info in summary["files"].items():
        assert hashlib.sha256((ROOT / "results" / filename).read_bytes()).hexdigest() == info["sha256"]
    assert hashlib.sha256((ROOT / "data/ecb_reference_snapshot.zip").read_bytes()).hexdigest() == summary["source"]["archived_raw_sha256"]
    assert hashlib.sha256((ROOT / "data/v2_ecb_six_currencies.csv").read_bytes()).hexdigest() == summary["source"]["processed_sha256"]


def test_complete_frozen_grid_and_true_unique_episode_counts(evidence):
    summary, episodes, selected, predictions = evidence
    assert len(summary["folds"]) == 72
    assert len(episodes) == summary["counts"]["episode_strategy_fee_rows"]
    assert len(selected) == summary["counts"]["selected_metrics"]
    assert len(predictions) == summary["counts"]["decision_prediction_rows"]
    for fold in summary["folds"]:
        assert len(fold["validation_metrics"]) == len(fold["outer_metrics"]) == 48
    outer = episodes.loc[episodes["role"].eq("outer")]
    counts = outer.groupby(["currency", "period"])["start_date"].nunique()
    assert (counts.xs("retrospective", level="period") == 132).all()
    assert (counts.xs("additional_2026", level="period") == 9).all()


def test_fit_label_end_boundaries_in_all_folds(evidence):
    for fold in evidence[0]["folds"]:
        year = fold["year"]
        for phase, cutoff in [("validation_fit", f"{year-2}-01-01"), ("outer_refit", f"{year}-01-01")]:
            fit = fold[phase]
            for record in [fit["flat"], *fit["term"].values()]:
                assert record["target_end_max"] < cutoff
                assert record["target_start_min"] >= "2005-01-01"
                assert record["feature_date_max"] < record["target_end_max"]
                assert record["cutoff_exclusive"] == cutoff
        assert fold["validation_score_first_target"] >= f"{year-2}-01-01"
        assert fold["validation_score_last_target"] < f"{year}-01-01"


def test_selectors_reconstruct_using_validation_only(evidence):
    summary = evidence[0]
    for fold in summary["folds"]:
        candidates = [r for r in fold["validation_metrics"] if r["cost_bps"] == 5.]
        reconstructed = choose_candidates(candidates, fold["forecast_first_model"], .12)
        assert reconstructed == fold["selections"]


def test_same_chosen_pair_frozen_across_sensitivity_fees(evidence):
    selections = evidence[2]
    for _, group in selections.groupby(["currency", "year", "role", "selector"]):
        assert len(group) == 3
        assert group["model"].nunique() == group["policy"].nunique() == 1
        assert set(group["cost_bps"]) == {0., 5., 10.}


def test_every_strategy_receives_common_episode_premium(evidence):
    episodes = evidence[1]
    unique = episodes.groupby(["currency", "year", "role", "episode_id"])["common_premium"].nunique()
    assert (unique == 1).all()


def test_pnl_fee_identity_across_all_cost_scenarios(evidence):
    episodes = evidence[1].copy()
    episodes["gross"] = episodes["pnl"] + episodes["cost"]
    # Rebalancing has no dependence on cost in any frozen candidate.
    variation = episodes.groupby(["currency", "year", "role", "episode_id", "model", "policy"])["gross"].agg(["min", "max"])
    assert np.max(np.abs(variation["max"] - variation["min"])) < 1e-10


def test_summary_metrics_recompute_from_episode_rows(evidence):
    summary, episodes, _, _ = evidence
    keys = ["currency", "year", "role", "model", "policy", "cost_bps"]
    table = episodes.assign(square=episodes["pnl"]**2).groupby(keys).agg(mean_pnl=("pnl", "mean"), mse=("square", "mean"), mean_cost=("cost", "mean"))
    for fold in summary["folds"]:
        for row in fold["validation_metrics"] + fold["outer_metrics"]:
            actual = table.loc[tuple(row[key] for key in keys)]
            for name in ["mean_pnl", "mse", "mean_cost"]:
                assert row[name] == pytest.approx(actual[name], rel=1e-10, abs=1e-12)
            assert row["mse"] == pytest.approx(row["pnl_variance"] + row["bias_squared"], rel=1e-12)


def test_primary_mean_differences_and_holm_families(evidence):
    summary, episodes, _, _ = evidence
    for period in ["retrospective", "additional_2026"]:
        rows = [r for r in summary["primary_comparisons"] if r["period"] == period and r["block_length"] == 3]
        assert len(rows) == 6
        expected = holm_adjust([r["p_centered_approx"] for r in rows])
        for row, adjusted in zip(rows, expected):
            assert row["holm_six_currency_p"] == adjusted
            part = episodes.loc[(episodes["role"] == "outer") & (episodes["period"] == period) &
                                (episodes["currency"] == row["currency"]) & (episodes["cost_bps"] == 5) &
                                (episodes["policy"] == "band05")]
            mse = part.assign(square=part["pnl"]**2).groupby("model")["square"].mean()
            assert row["difference"] == pytest.approx(mse["ridge_term"] - mse["ridge_flat"], rel=1e-9, abs=1e-13)


def test_prediction_records_are_before_expiry_and_have_correct_remaining_horizon(evidence):
    pred = evidence[3]
    assert np.all(pred["remaining_horizon"] == 21 - pred["step"])
    assert pred[["rolling63", "ewma97", "ridge_flat", "ridge_term"]].ge(1e-10).all().all()
    assert pred[["rolling63", "ewma97", "ridge_flat", "ridge_term"]].le(.04).all().all()
    assert (pred.groupby(["currency", "year", "role", "episode_id"])["step"].nunique() == 21).all()
