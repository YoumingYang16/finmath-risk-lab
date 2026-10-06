"""Execute the frozen V2 six-currency purged annual historical study.

The archived raw ECB file is reused unchanged. V1 files/results are untouched.
The previously unscored 2026 extension is evaluated after protocol freeze and
never used to revise the candidate grid. Reproduction reruns are not new tests.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import sklearn
from risklab.advanced_hedging import band_hedge
from risklab.pricing import bs_price
from risklab.term_forecasting import (MODELS, POLICIES, SELECTORS, annual_forecasts,
    build_episodes, risk_metrics, choose_candidates, block_difference_inference, holm_adjust)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_data(protocol: dict, protocol_hash: str) -> tuple[pd.DataFrame, dict]:
    """Only schema/date/quality checks occur here, not performance evaluation."""
    prior = json.loads((ROOT / "data/source_manifest.json").read_text(encoding="utf-8"))
    raw_path = ROOT / "data/ecb_reference_snapshot.zip"
    if sha(raw_path) != prior["files"][raw_path.name]["sha256"]:
        raise ValueError("Archived ECB snapshot hash differs from V1 provenance")
    with zipfile.ZipFile(raw_path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Expected exactly one raw ECB CSV")
        frame = pd.read_csv(io.BytesIO(archive.read(members[0])), na_values=["N/A"])
    frame.columns = [str(c).strip() for c in frame.columns]
    currencies = protocol["currencies"]
    data = frame[["Date", *currencies]].rename(columns={"Date": "date"})
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    if data["date"].duplicated().any():
        raise ValueError("Duplicate source dates")
    endpoint = protocol["additional_unscored_period"][1]
    data = data.loc[data["date"].between("1999-01-04", endpoint)].sort_values("date").set_index("date")
    if str(data.index.max().date()) != endpoint:
        raise ValueError("Frozen snapshot does not reach requested extension endpoint")
    data = data.astype(float)
    if not np.isfinite(data.to_numpy()).all() or (data <= 0).any().any():
        raise ValueError("Missing, nonfinite or nonpositive selected reference rate")
    destination = ROOT / "data/v2_ecb_six_currencies.csv"
    data.to_csv(destination, index=True, float_format="%.16g", lineterminator="\n")
    quality = {"n_dates": len(data), "start": str(data.index.min().date()), "end": str(data.index.max().date()),
               "currencies": currencies, "missing": 0, "duplicates": 0, "nonpositive": 0,
               "max_calendar_gap_days": int(data.index.to_series().diff().dt.days.max()),
               "annual_counts": {str(year): int(n) for year, n in data.groupby(data.index.year).size().items()}}
    manifest = {"publisher": "European Central Bank", "source_url": prior["source_url"],
                "license_url": prior["license_url"], "reuse_summary": prior["reuse_summary"],
                "original_retrieved_at_hong_kong": prior["retrieved_at_hong_kong"],
                "archived_raw_sha256": sha(raw_path), "processed_sha256": sha(destination),
                "protocol_sha256": protocol_hash,
                "units": "Each currency units per EUR; common EUR denominator creates dependence.",
                "processing": "Select six columns and dates through 2026-09-30, sort, validate; no fill, interpolation, winsorization or quote changes.",
                "modification_notice": "Features, forecasts and normalized hypothetical hedge outcomes are project transformations, not ECB analyses or endorsement.",
                "extension_status": "2026 raw observations were archived during V1 but not performance-scored there; V2 is a source-frozen, not externally preregistered, additional evaluation.",
                "quality": quality}
    write_json(ROOT / "data/v2_source_manifest.json", manifest)
    return data, manifest


def evaluate_candidates(episodes: dict, currency: str, year: int, role: str, period: str,
                        fees: list[float]) -> tuple[list, list, list]:
    metrics, records, ledgers = [], [], []
    premium = np.asarray(bs_price(100., 100., episodes["horizon"], 0., episodes["premium_vol"]))
    for fee in fees:
        for model in MODELS:
            for name, policy in POLICIES.items():
                # Keep a complete representative ledger for each model/policy,
                # both phases, first USD fold, and the protocol selection fee.
                keep = currency == "USD" and year == 2015 and fee == 5.
                out = band_hedge(episodes["paths"], 100., 0., episodes["horizon"],
                    episodes["hedge_vol"][model], premium, policy=policy,
                    cost_bps=fee, record_path=0 if keep else None)
                meta = {"currency": currency, "year": year, "role": role, "period": period,
                        "model": model, "policy": name, "cost_bps": fee}
                metrics.append({**meta, **risk_metrics(out["pnl"], out["cost"], out["trades"])})
                for i in range(len(premium)):
                    records.append({**meta, "episode_id": i, "start_date": episodes["start_dates"][i],
                                    "end_date": episodes["end_dates"][i], "common_premium": float(premium[i]),
                                    "pnl": float(out["pnl"][i]), "loss": float(-out["pnl"][i]),
                                    "cost": float(out["cost"][i]), "turnover": float(out["turnover"][i]),
                                    "trades": int(out["trades"][i])})
                for row in out["ledger"]:
                    ledgers.append({**meta, "episode_id": 0, **row})
    return metrics, records, ledgers


def selected_metrics(rows: list[dict], selections: dict, budget: float) -> list[dict]:
    output = []
    for selector, selection in selections.items():
        for row in rows:
            if row["model"] == selection["model"] and row["policy"] == selection["policy"]:
                output.append({**row, **selection, "test_budget_met": row["mean_cost"] <= budget,
                               "test_budget_check_applies": row["role"] == "outer"})
    return output


def aggregate_results(episodes: pd.DataFrame, selected: pd.DataFrame, budget: float) -> list[dict]:
    outer = episodes.loc[episodes["role"].eq("outer")]
    result = []
    for (period, currency), data in outer.groupby(["period", "currency"], sort=True):
        candidate_rows = []
        for (model, policy, fee), part in data.groupby(["model", "policy", "cost_bps"], sort=True):
            candidate_rows.append({"model": model, "policy": policy, "cost_bps": float(fee),
                                   **risk_metrics(part["pnl"].to_numpy(), part["cost"].to_numpy(), part["trades"].to_numpy())})
        selectors = []
        picks = selected.loc[(selected["period"] == period) & (selected["currency"] == currency) & (selected["role"] == "outer")]
        for (selector, fee), pick in picks.groupby(["selector", "cost_bps"], sort=True):
            parts = []
            for _, row in pick.iterrows():
                parts.append(data.loc[(data["year"] == row["year"]) & (data["model"] == row["model"]) &
                                      (data["policy"] == row["policy"]) & (data["cost_bps"] == fee)])
            part = pd.concat(parts, ignore_index=True).sort_values("start_date")
            selectors.append({"selector": selector, "cost_bps": float(fee), "folds": len(pick),
                              "validation_infeasible_folds": int((~pick["validation_feasible"]).sum()),
                              "outer_mean_cost_budget_exceeded_folds": int((pick["mean_cost"] > budget).sum()),
                              "fold_budget_exceedance_fraction": float((pick["mean_cost"] > budget).mean()),
                              **risk_metrics(part["pnl"].to_numpy(), part["cost"].to_numpy(), part["trades"].to_numpy())})
        result.append({"period": period, "currency": currency, "independent_currency_replication_claim": False,
                       "unique_episodes": int(data[["year", "episode_id"]].drop_duplicates().shape[0]),
                       "candidate_metrics": candidate_rows, "selector_metrics": selectors})
    return result


def primary_comparisons(episodes: pd.DataFrame, currencies: list[str]) -> list[dict]:
    base = episodes.loc[episodes["role"].eq("outer") & episodes["policy"].eq("band05") & episodes["cost_bps"].eq(5.)]
    output = []
    for period in ["retrospective", "additional_2026"]:
        primary_indices, p_values = [], []
        for ci, currency in enumerate(currencies):
            part = base.loc[(base["period"] == period) & (base["currency"] == currency)]
            a = part.loc[part["model"].eq("ridge_term")].set_index(["year", "start_date", "end_date"]).sort_index()
            b = part.loc[part["model"].eq("ridge_flat")].set_index(["year", "start_date", "end_date"]).sort_index()
            if not a.index.equals(b.index):
                raise ValueError("Primary comparison episodes are not paired")
            diff = a["pnl"].to_numpy() ** 2 - b["pnl"].to_numpy() ** 2
            for block in [1, 3, 6]:
                if block > len(diff):
                    raise ValueError("Frozen bootstrap block is too long for available episodes")
                row = {"period": period, "currency": currency, "candidate": "ridge_term",
                       "reference": "ridge_flat", "policy": "band05", "cost_bps": 5.,
                       "metric": "paired squared net P&L difference", "negative_favors_candidate": True,
                       "primary_block": block == 3,
                       **block_difference_inference(diff, block, 4000, 7619 + ci + (100 if period == "additional_2026" else 0))}
                if block == 3:
                    primary_indices.append(len(output)); p_values.append(row["p_centered_approx"])
                output.append(row)
        adjusted = holm_adjust(p_values)
        for i, p in zip(primary_indices, adjusted):
            output[i]["holm_six_currency_p"] = p
            output[i]["holm_family"] = period + ": six currency comparisons at block length 3"
    return output


def main() -> None:
    start = time.perf_counter()
    protocol_path = ROOT / "docs/v2_protocol.json"
    protocol_hash = sha(protocol_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    h = protocol["historical"]
    data, manifest = load_frozen_data(h, protocol_hash)
    all_folds, all_metrics, all_episodes, all_selected, all_predictions, all_ledgers = [], [], [], [], [], []
    for currency in h["currencies"]:
        rates = data[currency]
        years = [*h["retrospective_outer_years"], 2026]
        for year in years:
            period = "additional_2026" if year == 2026 else "retrospective"
            end = h["additional_unscored_period"][1] if year == 2026 else f"{year}-12-31"
            val_bundle, outer_bundle, fit = annual_forecasts(rates, year, tuple(h["ridge_alphas"]),
                tuple(h["horizons"]), h["training_start"])
            val = build_episodes(rates, val_bundle, f"{year-2}-01-01", f"{year-1}-12-31")
            val_metrics, val_rows, val_ledgers = evaluate_candidates(val, currency, year, "validation", period, h["cost_bps"])
            selection_candidates = [row for row in val_metrics if row["cost_bps"] == h["selection_fee_bps"]]
            selections = choose_candidates(selection_candidates, fit["forecast_first_model"], h["mean_cost_budget"])
            # Selection is fully fixed before scoring this year's outcomes.
            outer = build_episodes(rates, outer_bundle, f"{year}-01-01", end)
            outer_metrics, outer_rows, outer_ledgers = evaluate_candidates(outer, currency, year, "outer", period, h["cost_bps"])
            summary = {"currency": currency, "period": period, "outer_start": f"{year}-01-01", "outer_end": end,
                       **fit, "selections": selections,
                       "episode_counts": {"validation": len(val["paths"]), "outer": len(outer["paths"])},
                       "unused_final_returns": {"validation": val["unused_final_returns"], "outer": outer["unused_final_returns"]},
                       "validation_metrics": val_metrics, "outer_metrics": outer_metrics}
            all_folds.append(summary)
            all_metrics.extend(val_metrics + outer_metrics); all_episodes.extend(val_rows + outer_rows)
            all_selected.extend(selected_metrics(val_metrics + outer_metrics, selections, h["mean_cost_budget"]))
            all_ledgers.extend(val_ledgers + outer_ledgers)
            for role, episode_set in [("validation", val), ("outer", outer)]:
                all_predictions.extend({"currency": currency, "year": year, "period": period, "role": role, **row}
                                       for row in episode_set["decision_rows"])
            print(json.dumps({"currency": currency, "year": year, "period": period,
                              "validation_episodes": len(val["paths"]), "outer_episodes": len(outer["paths"]),
                              "alphas": fit["selected_alphas"], "seconds": round(time.perf_counter()-start, 2)}), flush=True)
    if sha(protocol_path) != protocol_hash:
        raise ValueError("Frozen protocol changed during the experiment")
    episodes = pd.DataFrame(all_episodes); selected = pd.DataFrame(all_selected)
    aggregate = aggregate_results(episodes, selected, h["mean_cost_budget"])
    comparisons = primary_comparisons(episodes, h["currencies"])
    files = {
        "v2_historical_episodes.csv": episodes,
        "v2_historical_metrics.csv": pd.DataFrame(all_metrics),
        "v2_historical_selections.csv": selected,
        "v2_historical_predictions.csv": pd.DataFrame(all_predictions),
        "v2_historical_ledger.csv": pd.DataFrame(all_ledgers),
        "v2_historical_comparisons.csv": pd.DataFrame(comparisons),
    }
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    for name, frame in files.items():
        frame.to_csv(result_dir / name, index=False, float_format="%.16g", lineterminator="\n")
    summary = {
        "schema_version": "2.0", "status": "executed", "protocol_sha256": protocol_hash,
        "source": manifest, "folds": all_folds, "aggregate": aggregate,
        "primary_comparisons": comparisons,
        "counts": {"currency_year_folds": len(all_folds), "currencies": len(h["currencies"]),
                   "candidate_metrics": len(all_metrics), "episode_strategy_fee_rows": len(all_episodes),
                   "selected_metrics": len(all_selected), "decision_prediction_rows": len(all_predictions),
                   "representative_ledger_rows": len(all_ledgers)},
        "statistics": {"mse_decomposition": "Population variance (ddof=0) plus squared mean P&L equals net MSE.",
                       "es90": "Empirical upper 10% seller-loss tail with fractional boundary mass; negative loss ES is allowed.",
                       "bootstrap": "4000 overlapping noncircular block draws, blocks 1/3/6; centered-null approximate two-sided p-values, +1 correction; Holm at block3 over six currencies separately per period.",
                       "selector_inference": "Selected metrics describe a frozen annual selection/refit procedure; historical bootstrap does not rerun all inner fits or remove retrospective design selection."},
        "limitations": [
            "Retrospective years are exploratory; previously viewed V1 USD/JPY 2021–2025 cannot become untouched again.",
            "Additional 2026 was source-frozen before scoring, not externally preregistered; short period and macro dependence prevent broad confirmation claims.",
            "ECB reference prices are not executable transactions. No real option quotes, spread, intraday execution, margin, or calibrated domestic/foreign interest curves.",
            "P-measure future squared-return averages inserted into BS delta are heuristic controls, not Q-measure option prices or market implied volatility.",
            "All currencies share EUR and calendar shocks. They are not independent replications; Holm is applied to approximate marginal tests, without claiming exact familywise validity under broken bootstrap assumptions.",
            "Inner hyperparameter and policy selection reuse the same validation years, so inner scores are optimistically selected; outer years remain computationally separated.",
            "Multi-step targets overlap. Training purges target END across cutoffs; outer episode inference uses nonoverlapping 21-return paths, with annual leftover returns discarded.",
            "Mean-cost validation feasibility is not a test or pathwise budget guarantee; selection at 5bps is reused unchanged at 0/10bps as sensitivity analysis.",
            "MBB assumes approximately stationary weak dependence; annual refits, discarded annual tail returns, possible breaks, and few 2026 episodes limit inference.",
            "Common premium is starting Rolling63 BS; P&L retains premium/model misspecification. Its MSE is not pure discretization error.",
            "Candidate class, alpha grid and shared term alpha are finite design choices, not global-optimal policy or novel algorithm claims.",
        ],
        "files": {name: {"sha256": sha(result_dir / name), "rows": len(frame), "bytes": (result_dir/name).stat().st_size} for name, frame in files.items()},
        "implementation_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in
            [ROOT / "risklab/term_forecasting.py", ROOT / "risklab/advanced_hedging.py", ROOT / "risklab/historical.py", Path(__file__)]},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__},
        "runtime_seconds": time.perf_counter()-start,
    }
    write_json(result_dir / "v2_historical_summary.json", summary)
    print(json.dumps({"status": "executed", **summary["counts"], "seconds": summary["runtime_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
