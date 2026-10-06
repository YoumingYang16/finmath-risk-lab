"""Fail-closed cross-artifact audit of executed research evidence and SQLite.

This script checks consistency and provenance; it does not turn descriptive
experiments into externally validated financial, health or admissions claims.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from risklab.pricing import bs_price


def require(condition, message):
    if not bool(condition):
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Nonfinite JSON constant {x}")))


def finite_json(value, path="root"):
    if isinstance(value, float):
        require(math.isfinite(value), f"Nonfinite number at {path}")
    elif isinstance(value, dict):
        for key, item in value.items():
            finite_json(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite_json(item, f"{path}[{index}]")


def close(a, b, message, atol=1e-10, rtol=1e-9):
    require(np.allclose(np.asarray(a, float), np.asarray(b, float), atol=atol, rtol=rtol, equal_nan=False), message)


def compare_frames(actual, expected, keys, label):
    require(set(actual.columns) == set(expected.columns), f"{label}: columns differ")
    require(not actual.duplicated(keys).any() and not expected.duplicated(keys).any(), f"{label}: duplicate keys")
    a = actual.sort_values(keys).reset_index(drop=True)[expected.columns]
    b = expected.sort_values(keys).reset_index(drop=True)
    require(len(a) == len(b), f"{label}: row counts differ")
    for column in b.columns:
        if pd.api.types.is_numeric_dtype(b[column]) and not pd.api.types.is_bool_dtype(b[column]):
            close(a[column], b[column], f"{label}: mismatched numeric column {column}", atol=1e-13, rtol=1e-10)
        else:
            require(a[column].astype(str).tolist() == b[column].astype(str).tolist(), f"{label}: mismatched field {column}")


def finite_frame(frame, label, allow_terminal_vol=False):
    for column in frame.select_dtypes(include="number").columns:
        values = frame[column]
        if allow_terminal_vol and column == "hedge_vol":
            require(frame.loc[values.isna(), "event"].eq("settlement").all(), f"{label}: missing nonterminal hedge volatility")
            values = values.dropna()
        require(np.isfinite(values.to_numpy()).all(), f"{label}: nonfinite {column}")


def verify_simulation(root):
    protocol = read_json(root / "docs/simulation_protocol.json")
    summary = read_json(root / "results/simulation_summary.json")
    finite_json(summary)
    canonical_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(summary["protocol"] == protocol, "Simulation summary protocol differs from frozen protocol")
    require(summary["protocol_sha256"] == canonical_hash, "Simulation protocol hash mismatch")
    require(protocol["n_validation"] == 1024 and protocol["n_test"] == 8192, "Formal simulation evidence was replaced by smoke or different sample sizes")
    require(len(protocol["scenarios"]) == 7 and len(protocol["fees_bps"]) == 3 and len(protocol["policies"]) == 6, "Formal simulation design dimensions changed")
    rows = pd.DataFrame(summary["rows"])
    finite_frame(rows, "simulation metrics")
    expected_keys = set(itertools.product([s["id"] for s in protocol["scenarios"]], ["validation", "test"], protocol["fees_bps"], protocol["policies"]))
    keys = ["scenario", "split", "fee_bps", "policy"]
    actual_keys = set(rows[keys].itertuples(index=False, name=None))
    require(len(rows) == 252 and actual_keys == expected_keys and not rows.duplicated(keys).any(), "Simulation does not cover exactly 252 unique formal conditions")
    require(rows.loc[rows.split == "validation", "n"].eq(protocol["n_validation"]).all(), "Validation sample sizes mismatch")
    require(rows.loc[rows.split == "test", "n"].eq(protocol["n_test"]).all(), "Test sample sizes mismatch")
    compare_frames(pd.read_csv(root / "results/simulation_metrics.csv"), rows, keys, "Simulation JSON/CSV")
    selections = pd.DataFrame(summary["selections"])
    comparisons = pd.DataFrame(summary["paired_comparisons"])
    require(len(selections) == len(comparisons) == 21, "Expected 21 scenario/fee selections and comparisons")
    compare_frames(pd.read_csv(root / "results/simulation_selection.csv"), selections, ["scenario", "fee_bps"], "Selection JSON/CSV")
    compare_frames(pd.read_csv(root / "results/simulation_comparisons.csv"), comparisons, ["scenario", "fee_bps"], "Contrast JSON/CSV")
    budget = protocol["mean_cost_budget"]
    for selected in summary["selections"]:
        scenario, fee = selected["scenario"], selected["fee_bps"]
        block = rows.loc[(rows.scenario == scenario) & (rows.fee_bps == fee)]
        val = block.loc[block.split == "validation"]
        feasible = val.loc[val.mean_cost <= budget]
        order = ["rmse", "mean_cost", "policy"] if len(feasible) else ["mean_cost", "rmse", "policy"]
        best = (feasible if len(feasible) else val).sort_values(order).iloc[0]
        require(selected["selected_policy"] == best["policy"], f"{scenario}/{fee}: strategy was not selected from validation as specified")
        require(selected["validation_feasible"] == bool(len(feasible)), "Validation feasibility label differs")
        test = block.loc[(block.split == "test") & (block.policy == selected["selected_policy"])].iloc[0]
        for field, truth in [("validation_rmse", best.rmse), ("validation_mean_cost", best.mean_cost), ("test_rmse", test.rmse), ("test_mean_cost", test.mean_cost), ("test_es95", test.es95)]:
            close(selected[field], truth, f"{scenario}/{fee}: {field} mismatch")
        require(selected["test_budget_met"] == bool(test.mean_cost <= budget), "Test budget label differs")
    verify_primary_contrasts(comparisons)
    for item in summary["paired_comparisons"]:
        block = rows.loc[(rows.scenario == item["scenario"]) & (rows.fee_bps == item["fee_bps"]) & (rows.split == "test")].set_index("policy")
        close(item["difference"], block.loc[item["selected_policy"], "rmse"] ** 2 - block.loc["every5", "rmse"] ** 2, "Paired squared-loss difference differs from reported RMSEs")
        require(item["standard_error"] >= 0 and item["n"] == protocol["n_test"], "Invalid paired interval metadata")
        half = student_t.ppf(0.975, item["n"] - 1) * item["standard_error"]
        close([item["ci_low"], item["ci_high"]], [item["difference"] - half, item["difference"] + half], "Paired CI bounds are inconsistent")
    expected_premium = bs_price(protocol["spot"], protocol["strike"], protocol["horizon"], protocol["rate"], protocol["base_vol"])
    close(summary["premium"], expected_premium, "Common simulation premium mismatch")
    ledger = pd.read_csv(root / "results/simulation_ledger.csv")
    ledger_check = verify_ledger(ledger, summary["premium"], protocol["rate"], protocol["horizon"], protocol["strike"], 5.0)
    require(len(ledger) == protocol["steps"] + 1, "Simulation sample ledger length mismatch")
    return {"protocol_sha256": canonical_hash, "conditions": 252, "selections": 21, "primary_contrasts": 1, "ledger": ledger_check}


def verify_primary_contrasts(comparisons):
    require(pd.api.types.is_bool_dtype(comparisons["primary"]), "Primary flags must be booleans")
    primary = comparisons.loc[comparisons["primary"]]
    require(len(primary) == 1, "Exactly one prespecified primary contrast is required")
    p = primary.iloc[0]
    require(p.scenario == "S1" and p.fee_bps == 5 and p.baseline == "every5", "Primary contrast is not the prespecified S1/5bps/every5 comparison")


def verify_ledger(frame, premium, rate, horizon, strike, fee_bps):
    frame = frame.sort_values("step").reset_index(drop=True)
    finite_frame(frame, "ledger", allow_terminal_vol=True)
    require(frame.step.tolist() == list(range(len(frame))), "Ledger steps missing or duplicated")
    require(frame.iloc[0]["event"] == "entry" and frame.iloc[-1]["event"] == "settlement", "Ledger boundary events invalid")
    close(frame.iloc[0].cash_before, premium, "Ledger starts with wrong premium")
    close(frame.iloc[0].time, 0, "Ledger starts at nonzero time")
    close(frame.iloc[-1].time, horizon, "Ledger ends at wrong horizon")
    held, cash, cumulative_cost, cumulative_turnover = 0.0, float(premium), 0.0, 0.0
    previous_time = 0.0
    for row in frame.itertuples(index=False):
        close(row.cash_before, cash, "Ledger prior cash does not link to previous row")
        dt = row.time - previous_time
        require(dt >= 0, "Ledger time decreased")
        interest = cash * np.expm1(rate * dt)
        close(row.interest, interest, "Ledger interest mismatch")
        fee = abs(row.trade) * row.spot * fee_bps / 10000
        close(row.fee, fee, "Ledger transaction fee mismatch")
        terminal_fee = fee * np.exp(rate * (horizon - row.time))
        close(row.terminal_value_fee, terminal_fee, "Ledger terminalized fee mismatch")
        payoff = max(row.spot - strike, 0) if row.event == "settlement" else 0.0
        close(row.payoff, payoff, "Ledger payoff mismatch")
        cash += interest - row.trade * row.spot - fee - payoff
        held += row.trade
        cumulative_cost += terminal_fee
        cumulative_turnover += abs(row.trade) * row.spot
        close([row.cash_after, row.position, row.wealth, row.cumulative_cost, row.cumulative_turnover], [cash, held, cash + held * row.spot, cumulative_cost, cumulative_turnover], "Ledger accounting identity mismatch")
        previous_time = row.time
    close(held, 0, "Ledger does not liquidate at settlement")
    return {"rows": len(frame), "terminal_pnl": cash, "terminal_cost": cumulative_cost}


def verify_historical(root):
    summary = read_json(root / "results/historical_summary.json")
    finite_json(summary)
    source = read_json(root / "data/source_manifest.json")
    require(summary["source"] == source, "Historical source manifest differs from summary")
    for name, info in source["files"].items():
        require(sha256(root / "data" / name) == info["sha256"], f"Historical source hash mismatch: {name}")
    for name, info in summary["files"].items():
        require(sha256(root / "results" / name) == info["sha256"], f"Historical result hash mismatch: {name}")
    for name, expected in summary["implementation_sha256"].items():
        require(sha256(root / name) == expected, f"Historical implementation changed since execution: {name}")
    forecasts = pd.read_csv(root / "results/historical_forecasts.csv")
    episodes = pd.read_csv(root / "results/historical_episodes.csv")
    ledger = pd.read_csv(root / "results/historical_ledger.csv")
    finite_frame(forecasts, "historical forecasts")
    finite_frame(episodes, "historical episodes")
    finite_frame(ledger, "historical ledger", allow_terminal_vol=True)
    require(not forecasts.duplicated(["currency", "target_date"]).any(), "Duplicate historical forecast target dates")
    require((forecasts.decision_date < forecasts.target_date).all(), "Forecast target does not follow decision date")
    require(forecasts.target_date.max() == summary["analysis_endpoint"] == "2025-12-31", "Historical test endpoint mismatch")
    common = episodes.groupby(["currency", "split", "episode_id"])["common_premium"].nunique()
    require(common.eq(1).all(), "Competing strategies have different episode premiums")
    episode_keys = ["currency", "split", "episode_id", "strategy", "cost_bps"]
    require(not episodes.duplicated(episode_keys).any(), "Duplicate historical episode rows")
    for currency, report in summary["currencies"].items():
        rows = forecasts.loc[forecasts.currency == currency]
        for split, n in report["forecast_rows"].items():
            require(len(rows.loc[rows.split == split]) == n, "Historical forecast split count mismatch")
        expected_family = min(report["selection"]["validation_family_qlike"], key=report["selection"]["validation_family_qlike"].get)
        require(expected_family == report["selection"]["selected_forecast_family"], "Historical family was not selected by validation")
        close(rows.selected, rows[expected_family], "Selected forecasts differ from frozen selected family")
        for split in ["validation", "test"]:
            selected = rows.loc[rows.split == split]
            for name, metrics in report["forecast_evaluation"][split]["metrics"].items():
                y, h = selected.target.to_numpy(), selected[name].to_numpy()
                require((h > 0).all(), "Historical variance forecast not positive")
                close(metrics["qlike"], np.mean(np.log(h) + y / h), "Historical QLIKE mismatch")
                close(metrics["mse"], np.mean((y - h) ** 2), "Historical MSE mismatch", atol=1e-16)
            require(episodes.loc[(episodes.currency == currency) & (episodes.split == split), "episode_id"].nunique() == report["episode_counts"][split]["n"], "Historical episode count mismatch")
        for metric in report["hedging_metrics"]:
            rows_ep = episodes.loc[(episodes.currency == currency) & (episodes.split == metric["split"]) & (episodes.strategy == metric["strategy"]) & (episodes.cost_bps == metric["cost_bps"])]
            require(len(rows_ep) == metric["n"], "Historical hedge metric sample count mismatch")
            close([np.mean(rows_ep.pnl), np.sqrt(np.mean(rows_ep.pnl ** 2)), np.mean(rows_ep.cost), np.mean(rows_ep.trades)], [metric["mean_pnl"], metric["rmse"], metric["mean_cost"], metric["mean_trades"]], "Historical hedge aggregate differs from CSV")
    ledger_groups = 0
    for key, group in ledger.groupby(episode_keys):
        mask = np.ones(len(episodes), dtype=bool)
        for column, value in zip(episode_keys, key):
            mask &= episodes[column].to_numpy() == value
        matching = episodes.loc[mask]
        require(len(matching) == 1, "Historical ledger has no unique matching episode")
        row = matching.iloc[0]
        result = verify_ledger(group, row.common_premium, 0, 21 / 252, 100, row.cost_bps)
        close([result["terminal_pnl"], result["terminal_cost"]], [row.pnl, row.cost], "Historical ledger terminal values differ from episode evidence")
        require(result["rows"] == 22, "Historical sample ledger should contain 22 observations")
        ledger_groups += 1
    require(ledger_groups == 42 and len(ledger) == 924, "Historical sample ledger coverage mismatch")
    return {"forecast_rows": len(forecasts), "episode_strategy_cost_rows": len(episodes), "ledger_groups": ledger_groups, "ledger_rows": len(ledger), "data_and_implementation_hashes": "matched"}


def verify_competencies(root):
    union = read_json(root / "docs/competency_union.json")
    programs, dimensions = union["programs"], union["competencies"]
    require(union["operation"] == "union", "Competency operation is not union")
    program_ids = {p["id"] for p in programs}
    require(len(programs) == len(program_ids) == 10, "Expected ten distinct programs")
    require(len(dimensions) == 18 and {d["id"] for d in dimensions} == {f"C{i:02d}" for i in range(1, 19)}, "Expected eighteen uniquely identified union dimensions")
    mapped = set()
    for dimension in dimensions:
        references = set(dimension["programs"])
        require(references and references <= program_ids, "Competency has empty or unknown program mapping")
        require(dimension["name"] and dimension["description"], "Competency description is missing")
        mapped |= references
        if dimension["id"] in ["C15", "C16", "C17", "C18"]:
            require(dimension["status"] == "external_evidence_required", "External-evidence competency improperly claimed as completed")
    require(mapped == program_ids, "At least one program is absent from the union")
    require(any(len(d["programs"]) < 10 for d in dimensions), "Union collapsed to an all-program intersection")
    require(all(p["url"].startswith("https://") for p in programs), "Missing program source URL")
    return {"operation": "union", "programs": 10, "dimensions": 18, "external_evidence_dimensions": 4}


def verify_sqlite(root):
    database = root / "results/research.sqlite"
    require(database.exists(), "Research SQLite database has not been built")
    con = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        require(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity check failed")
        require(not con.execute("PRAGMA foreign_key_check").fetchall(), "SQLite foreign key violations")
        sources = pd.read_sql_query("SELECT * FROM source_file", con)
        mapping = {
            "results/simulation_metrics.csv": ("simulation_metric", ["scenario", "split", "fee_bps", "policy"], ["scenario", "split", "fee_bps", "policy", "n", "mean_pnl", "rmse", "es95", "mean_cost", "mean_trades"]),
            "results/historical_forecasts.csv": ("forecast", ["currency", "target_date"], ["currency", "decision_date", "target_date", "split", "target", "train_constant", "rolling63", "ewma", "ridge", "selected"]),
            "results/historical_episodes.csv": ("episode", ["currency", "split", "episode_id", "strategy", "cost_bps"], ["currency", "split", "episode_id", "start_date", "end_date", "strategy", "cost_bps", "pnl", "cost", "gross_replication_pnl", "trades"]),
        }
        require(set(sources.path) == set(mapping) and len(sources) == 3, "SQLite source catalog mismatch")
        counts = {}
        for relative, (table, keys, columns) in mapping.items():
            path = root / relative
            source = sources.loc[sources.path == relative].iloc[0]
            expected = pd.read_csv(path)
            require(source.sha256 == sha256(path) and source.rows == len(expected), f"SQLite source provenance mismatch: {relative}")
            actual = pd.read_sql_query(f"SELECT * FROM {table}", con)
            require(actual.source_id.eq(source.id).all(), f"SQLite rows have incorrect source lineage: {table}")
            compare_frames(actual[columns], expected[columns], keys, f"SQLite {table}/source CSV")
            counts[table] = len(actual)
        episodes = pd.read_csv(root / "results/historical_episodes.csv")
        test = episodes.loc[episodes.split == "test"].assign(mean_squared_loss=lambda x: x.pnl ** 2)
        group_keys = ["currency", "strategy", "cost_bps"]
        expected = test.groupby(group_keys).agg(episodes=("pnl", "size"), mean_squared_loss=("mean_squared_loss", "mean"), mean_cost=("cost", "mean")).reset_index()
        actual = pd.read_sql_query("SELECT * FROM test_risk", con)
        compare_frames(actual, expected, group_keys, "SQL test_risk/Pandas CSV aggregate")
        return {"database_sha256": sha256(database), "tables": counts, "test_risk_rows": len(actual), "foreign_key_violations": 0, "csv_row_equivalence": "passed"}
    finally:
        con.close()


def run_audit(root=ROOT):
    root = Path(root).resolve()
    checks = []
    for name, function in [("formal_simulation", verify_simulation), ("historical_evidence", verify_historical), ("competency_union", verify_competencies), ("research_sqlite", verify_sqlite)]:
        try:
            details = function(root)
            checks.append({"name": name, "status": "passed", "details": details})
        except Exception as error:
            checks.append({"name": name, "status": "failed", "error_type": type(error).__name__, "error": str(error)})
    return {"schema_version": "1.0", "status": "passed" if all(c["status"] == "passed" for c in checks) else "failed", "checks": checks,
            "scope": "Cross-artifact consistency, ledger accounting, source provenance and SQL equivalence. Does not certify model validity, executable returns, admissions eligibility or personal mastery.",
            "auditor_sha256": sha256(Path(__file__))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = run_audit(args.root)
    destination = args.root / "results/artifact_audit.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
