"""Execute the frozen historical FX forecasting and hypothetical hedge protocol."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd
import scipy
import sklearn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from risklab.historical import (FEATURE_COLUMNS, SPLITS, choose_threshold, forecast_evaluation,
                               historical_episodes, moving_block_mean_ci, select_forecasts)
from risklab.pricing import bs_price
from risklab.hedging import hedge_paths
from risklab.statistics import summarize_pnl

THRESHOLDS = [0.025, 0.05, 0.10, 0.15, 0.20]
COST_BPS = [0.0, 5.0, 10.0]
SELECTION_COST_BPS = 5.0
COST_BUDGET = 0.12


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def episode_strategies(episodes: dict, chosen_threshold: float) -> dict:
    n, steps = episodes["paths"].shape[0], episodes["steps"]
    frozen = np.repeat(episodes["premium_vol"][:, None], steps, axis=1)
    return {
        "frozen_rolling63_daily": {"vol": frozen, "policy": {"kind": "fixed", "every": 1}},
        "rolling63_daily": {"vol": episodes["hedge_vol"]["rolling63"], "policy": {"kind": "fixed", "every": 1}},
        "ewma_daily": {"vol": episodes["hedge_vol"]["ewma"], "policy": {"kind": "fixed", "every": 1}},
        "ridge_daily": {"vol": episodes["hedge_vol"]["ridge"], "policy": {"kind": "fixed", "every": 1}},
        "selected_daily": {"vol": episodes["hedge_vol"]["selected"], "policy": {"kind": "fixed", "every": 1}},
        "selected_every5": {"vol": episodes["hedge_vol"]["selected"], "policy": {"kind": "fixed", "every": 5}},
        "selected_threshold": {"vol": episodes["hedge_vol"]["selected"], "policy": {"kind": "threshold", "threshold": chosen_threshold}},
    }


def hedge_episode_set(episodes: dict, vol: np.ndarray, policy: dict, cost_bps: float) -> dict:
    premium = bs_price(100.0, 100.0, episodes["horizon"], 0.0, episodes["premium_vol"])
    return hedge_paths(episodes["paths"], 100.0, 0.0, episodes["horizon"], vol, premium,
                       policy=policy, cost_bps=cost_bps, record_path=0)


def run_currency(currency: str, rates: pd.Series) -> tuple[dict, pd.DataFrame, list, list]:
    forecasts, selection = select_forecasts(rates)
    evaluation = forecast_evaluation(forecasts)
    episode_sets = {split: historical_episodes(rates, forecasts, split) for split in ["validation", "test"]}
    candidates = []
    val = episode_sets["validation"]
    for threshold in THRESHOLDS:
        output = hedge_episode_set(val, val["hedge_vol"]["selected"], {"kind": "threshold", "threshold": threshold}, SELECTION_COST_BPS)
        candidates.append({"threshold": threshold, **summarize_pnl(output["pnl"], output["cost"], output["trades"])})
    chosen, rule = choose_threshold(candidates, COST_BUDGET)
    threshold_selection = {**rule, "chosen_threshold": chosen["threshold"], "selected_on": "validation only", "cost_bps": SELECTION_COST_BPS, "candidates": candidates}
    summaries, intervals, episode_rows, ledger_rows = [], [], [], []
    for split, episodes in episode_sets.items():
        definitions = episode_strategies(episodes, chosen["threshold"])
        for cost_bps in COST_BPS:
            outputs = {}
            for strategy, settings in definitions.items():
                output = hedge_episode_set(episodes, settings["vol"], settings["policy"], cost_bps)
                outputs[strategy] = output
                summary = summarize_pnl(output["pnl"], output["cost"], output["trades"])
                summary["gross_replication_rmse"] = float(np.sqrt(np.mean((output["pnl"] + output["cost"]) ** 2)))
                summaries.append({"split": split, "strategy": strategy, "cost_bps": cost_bps,
                                  "mean_cost_exceeds_validation_budget": summary["mean_cost"] > COST_BUDGET, **summary})
                premium = bs_price(100.0, 100.0, episodes["horizon"], 0.0, episodes["premium_vol"])
                for episode_id in range(len(output["pnl"])):
                    episode_rows.append({"currency": currency, "split": split, "episode_id": episode_id,
                                         "start_date": episodes["start_dates"][episode_id], "end_date": episodes["end_dates"][episode_id],
                                         "strategy": strategy, "cost_bps": cost_bps,
                                         "common_premium": float(premium[episode_id]), "premium_vol": float(episodes["premium_vol"][episode_id]),
                                         "pnl": float(output["pnl"][episode_id]), "loss": -float(output["pnl"][episode_id]),
                                         "cost": float(output["cost"][episode_id]), "gross_replication_pnl": float(output["pnl"][episode_id] + output["cost"][episode_id]),
                                         "turnover": float(output["turnover"][episode_id]), "trades": int(output["trades"][episode_id])})
                # One complete test ledger per currency, strategy and cost assumption.
                if split == "test":
                    decision_dates = rates.loc[episodes["start_dates"][0]:episodes["end_dates"][0]].index
                    for row in output["ledger"]:
                        ledger_rows.append({"currency": currency, "split": split, "episode_id": 0, "strategy": strategy,
                                            "cost_bps": cost_bps, "date": str(decision_dates[row["step"]].date()), **row})
            if split == "test" and cost_bps == SELECTION_COST_BPS:
                for candidate, reference in [("ridge_daily", "rolling63_daily"), ("selected_threshold", "selected_daily"), ("selected_every5", "selected_daily")]:
                    a, b = outputs[candidate], outputs[reference]
                    for metric, differences in [("squared_net_pnl", a["pnl"] ** 2 - b["pnl"] ** 2), ("cost", a["cost"] - b["cost"])]:
                        for block_length in [1, 3, 6]:
                            intervals.append({"candidate": candidate, "reference": reference, "metric": metric,
                                              "cost_bps": cost_bps, "negative_favors_candidate": True,
                                              **moving_block_mean_ci(differences, block_length, seed=29)})
    counts = {split: int((forecasts["split"] == split).sum()) for split in SPLITS}
    episode_info = {split: {key: value for key, value in eps.items() if key in ["steps", "split", "observations_in_split", "unused_final_return_count", "horizon"]} | {"n": len(eps["paths"]), "first_start": eps["start_dates"][0], "last_end": eps["end_dates"][-1]} for split, eps in episode_sets.items()}
    output = {"currency": currency, "units": f"{currency} per EUR", "forecast_rows": counts, "selection": selection,
              "forecast_evaluation": evaluation, "episode_counts": episode_info, "threshold_selection": threshold_selection,
              "hedging_metrics": summaries, "hedging_test_difference_intervals": intervals}
    # Forecasts are available at the decision; the next target is joined later for evaluation.
    forecast_csv = forecasts.copy().reset_index(names="decision_date")
    forecast_csv.insert(0, "currency", currency)
    forecast_csv["decision_date"] = forecast_csv["decision_date"].dt.strftime("%Y-%m-%d")
    forecast_csv["target_date"] = forecast_csv["target_date"].dt.strftime("%Y-%m-%d")
    # In-sample training fitted forecasts are labelled, not presented as out-of-sample evidence.
    forecast_csv["evaluation_role"] = np.where(forecast_csv["split"] == "train", "in_sample_not_performance_evidence", "temporal_out_of_sample")
    return output, forecast_csv, episode_rows, ledger_rows


def main() -> None:
    source = json.loads((ROOT / "data/source_manifest.json").read_text(encoding="utf-8"))
    for name, expected in source["files"].items():
        actual = hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest()
        if actual != expected["sha256"]:
            raise ValueError(f"Source integrity mismatch: {name}")
    data = pd.read_csv(ROOT / "data/ecb_usd_jpy.csv", parse_dates=["date"]).set_index("date")
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    currencies, forecast_frames, all_episodes, all_ledgers = {}, [], [], []
    for currency in ["USD", "JPY"]:
        result, forecasts, episodes, ledgers = run_currency(currency, data[currency])
        currencies[currency] = result
        forecast_frames.append(forecasts)
        all_episodes.extend(episodes)
        all_ledgers.extend(ledgers)
        print(json.dumps({"currency": currency, "forecast_rows": result["forecast_rows"], "selected_forecast": result["selection"]["selected_forecast_family"], "threshold": result["threshold_selection"]["chosen_threshold"]}))
    pd.concat(forecast_frames, ignore_index=True).to_csv(results / "historical_forecasts.csv", index=False, float_format="%.16g", lineterminator="\n")
    pd.DataFrame(all_episodes).to_csv(results / "historical_episodes.csv", index=False, float_format="%.16g", lineterminator="\n")
    pd.DataFrame(all_ledgers).to_csv(results / "historical_ledger.csv", index=False, float_format="%.16g", lineterminator="\n")
    summary = {
        "schema_version": "1.0", "status": "executed", "experiment": "ECB reference FX causal forecasting and hypothetical option hedging",
        "analysis_endpoint": "2025-12-31", "source": source,
        "data_quality": json.loads((ROOT / "data/data_quality.json").read_text(encoding="utf-8")),
        "protocol": {"temporal_splits": SPLITS, "warmup": "1999-2004 observations initialize features only; supervised training begins at target dates in 2005.",
                     "observation_year": 252, "episode_steps": 21, "option": "hypothetical European ATM call, normalized spot=strike=100", "rate": 0, "dividend": 0,
                     "premium": "Common to every strategy in the same episode: Black-Scholes with the starting rolling63 variance. Does not use future episode realized volatility.",
                     "volatility_mapping": "One-observation variance forecast times 252, square rooted; used as flat remaining-life BS delta input. This is an approximation, not a term-structure forecast.",
                     "cost_bps": COST_BPS, "threshold_selection_cost_bps": SELECTION_COST_BPS, "threshold_grid": THRESHOLDS,
                     "cost_budget": COST_BUDGET, "feature_columns": FEATURE_COLUMNS,
                     "selection_commitment": "Candidate grids, splits, cost assumptions, primary QLIKE metric and threshold budget are fixed in source; no test-based parameter updates or refitting.",
                     "hedge_strategies": ["frozen_rolling63_daily", "rolling63_daily", "ewma_daily", "ridge_daily", "selected_daily", "selected_every5", "selected_threshold"],
                     "bootstrap": "2000 draws; daily loss differences use blocks 5/21/63; ordered nonoverlapping episode differences use blocks 1/3/6. Noncircular overlapping moving blocks, same paired observations."},
        "metric_definitions": {
            "qlike": "mean(log(h_t) + y_t/h_t), h>0 and y=next squared log-return. Target-only terms omitted; negative values valid, lower better; comparisons only on identical target observations.",
            "mse": "mean((y_t-h_t)^2) in unannualized squared-variance units, lower better.",
            "net_rmse": "sqrt(mean(net terminal seller P&L squared)); zero-P&L target includes fixed common premium and all entry/rebalance/exit fees.",
            "gross_replication_rmse": "sqrt(mean((net P&L + terminal-value transaction costs)^2)); separates replication from fee effects.",
            "loss_var_es": "Loss=-net P&L. VaR95=linear empirical quantile, ES95=upper 5% empirical tail with fractional boundary mass. Only about three test episodes support this tail, so interpret cautiously.",
        },
        "limitations": [
            "These are ECB reference rates, not tradeable prices; no option quotes, bid-ask spreads, market impact or actual execution are measured.",
            "The hypothetical ledger assumes observe-and-rebalance at the reference quote; actual publication delay and quote executability are not modeled.",
            "Historical hedges are hypothetical path experiments, not backtested achievable trading profits or validation of real option pricing.",
            "Domestic and foreign interest rates are deliberately zero; normalized FX paths are treated as zero-carry underlyings, not correctly calibrated real FX options.",
            "Squared next return is a noisy second-moment proxy; identifying it with conditional variance assumes negligible conditional mean.",
            "Models are frozen after 2016; causal features and filter states update, but model refitting and structural-break adaptation are not claimed.",
            "Daily reference observations omit intraday risk and overnight execution constraints; 252 observations/year and constant remaining-life delta volatility are simplifications.",
            "The current download is a revised historical snapshot, not point-in-time vintage data. Chronological splitting controls algorithmic leakage but cannot remove unknown source revisions.",
            "Bootstrap intervals are pointwise and conditional on selected models; serial dependence/nonstationarity and selection uncertainty limit their interpretation.",
            "USD and JPY share the EUR denominator, are dependent, and are reported separately without pooled significance claims.",
            "Validation cost feasibility is not a guaranteed future cost cap; test budget exceedances are reported rather than re-tuned.",
            "Train rows in forecast CSV contain in-sample fitted values and must not be cited as generalization evidence.",
        ],
        "currencies": currencies,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__},
        "files": {name: {"sha256": hashlib.sha256((results / name).read_bytes()).hexdigest(), "bytes": (results / name).stat().st_size} for name in ["historical_forecasts.csv", "historical_episodes.csv", "historical_ledger.csv"]},
        "implementation_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT / "risklab/historical.py", ROOT / "risklab/pricing.py", ROOT / "risklab/hedging.py", ROOT / "risklab/statistics.py", Path(__file__)]},
    }
    write_json(results / "historical_summary.json", summary)
    print(json.dumps({"status": "executed", "forecast_csv_rows": sum(map(len, forecast_frames)), "episode_csv_rows": len(all_episodes), "ledger_csv_rows": len(all_ledgers)}))


if __name__ == "__main__":
    main()
