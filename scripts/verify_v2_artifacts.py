"""Independent cross-study evidence audit; failures produce a nonzero exit code.

No fit, selection, protocol or study result is changed. The convex audit
regenerates declared synthetic paths and independently computes positions,
pathwise cash-flow gains/costs, risks and validation choices without invoking
the production accounting or learned-policy evaluation functions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from risklab.pricing import bs_delta, bs_price
from risklab.stochastic_volatility import heston_paths


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, name="value", rtol=1e-9, atol=1e-10):
    if not np.allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=False):
        raise AssertionError(f"{name}: values disagree; actual={actual}, expected={expected}")


def independent_ci(a, b):
    d = np.asarray(a, float) - np.asarray(b, float)
    if d.ndim != 1 or len(d) < 2 or not np.isfinite(d).all():
        raise AssertionError("Invalid inference units")
    mean = float(d.mean())
    se = float(np.sqrt(np.sum((d-mean)**2)/(len(d)-1)/len(d)))
    half = float(student_t.ppf(.975, len(d)-1)*se)
    return {"difference": mean, "standard_error": se, "ci_low": mean-half, "ci_high": mean+half, "n": len(d)}


def independent_es(loss, alpha=.9):
    values = np.sort(np.asarray(loss, float))
    # Quantile-integral representation with each empirical atom's overlap
    # with [alpha,1], independently of production tail-count slicing.
    n = len(values)
    left, right = np.arange(n)/n, (np.arange(n)+1)/n
    weights = np.maximum(0., right - np.maximum(left, alpha))
    return float(np.dot(values, weights)/(1-alpha))


def independent_risk(pnl, cost):
    pnl, cost = np.asarray(pnl, float), np.asarray(cost, float)
    mean = float(np.mean(pnl))
    return {"n": len(pnl), "mean_pnl": mean, "bias_squared": mean**2,
            "variance_pnl": float(np.mean((pnl-mean)**2)), "mse": float(np.mean(pnl*pnl)),
            "rmse": float(np.sqrt(np.mean(pnl*pnl))), "es90": independent_es(-pnl),
            "mean_cost": float(cost.mean()), "gross_mse": float(np.mean((pnl+cost)**2))}


def independent_positions(paths, horizon, method, theta=None, width=None):
    """Rebuild the fixed feature class and the two baseline policies directly."""
    steps = paths.shape[1]-1
    remain = (steps-np.arange(steps))/steps
    delta = np.asarray(bs_delta(paths[:, :-1], 100., horizon*remain[None, :], 0., .2))
    if method == "daily":
        return delta
    if method == "convex_cvar":
        theta = np.asarray(theta, float)
        logm = np.clip(np.log(paths[:, :-1]/100.)/.1, -3., 3.)
        return delta + theta[0] + theta[1]*logm + theta[2]*remain[None, :] + theta[3]*4*delta*(1-delta)
    if method == "validation_selected_band":
        positions = np.empty_like(delta)
        positions[:, 0] = delta[:, 0]
        for j in range(1, steps):
            lo, hi = delta[:, j]-width, delta[:, j]+width
            positions[:, j] = np.where(positions[:, j-1] < lo, lo,
                                     np.where(positions[:, j-1] > hi, hi, positions[:, j-1]))
        return positions
    raise AssertionError("Unknown policy")


def independent_account(paths, positions, premium, fee_bps):
    held = np.concatenate([np.zeros((len(paths), 1)), positions, np.zeros((len(paths), 1))], axis=1)
    trades = held[:, 1:]-held[:, :-1]
    costs = np.sum(np.abs(trades)*paths, axis=1)*(fee_bps/10000.)
    gains = np.sum(positions*(paths[:, 1:]-paths[:, :-1]), axis=1)
    pnl = premium + gains - np.maximum(paths[:, -1]-100., 0.) - costs
    return pnl, costs


def convex_reconstruction(root=ROOT):
    """Independently replay all 24 fits' accounting and all 48 test rows."""
    root = Path(root)
    summary = load_json(root / "results/v2_convex_summary.json")
    protocol = load_json(root / "docs/v2_protocol.json")
    cfg, simulation = protocol["convex_extension"], protocol["simulation"]
    horizon = simulation["horizon"]
    premium = float(bs_price(100., 100., horizon, 0., .2))
    if len(summary["fits"]) != 24 or len(summary["choices"]) != 8 or len(summary["test_rows"]) != 48:
        raise AssertionError("Convex result coverage differs from 8 replicates × 3 penalties × 2 test laws")
    detail = {"fit_certificates_checked": 0, "validation_choices_reconstructed": 0,
              "test_rows_reconstructed": 0, "daily_position_extrema_checked": 0,
              "maximum_absolute_recomputed_mse_error": 0., "out_of_sample_position_violation_rows": 0,
              "maximum_reported_stationarity_residual": 0.}
    for replicate, seed in enumerate(cfg["seeds"]):
        train = heston_paths(cfg["training_paths"], 21, horizon, seed=seed, **simulation["heston"])["prices"]
        validation = heston_paths(cfg["validation_paths"], 21, horizon, seed=seed+100000, **simulation["heston"])["prices"]
        fits = [f for f in summary["fits"] if f["replicate"] == replicate]
        options = []
        for fit in fits:
            if not fit["success"] or fit["solver_status"] != 0:
                raise AssertionError("LP fit not successful")
            if fit["seed"] != seed or fit["n_train"] != cfg["training_paths"]:
                raise AssertionError("LP fit sample or seed inconsistent")
            for key in ["duality_gap", "objective_reconciliation_gap", "max_primal_inequality_violation", "max_stationarity_residual"]:
                if not np.isfinite(fit[key]) or abs(fit[key]) > 1e-6:
                    raise AssertionError(f"LP certificate residual {key} failed")
            close(fit["objective"]-fit["dual_objective"], fit["duality_gap"], "dual gap")
            close(fit["objective"]-fit["independent_objective"], fit["objective_reconciliation_gap"], "objective gap")
            position = independent_positions(train, horizon, "convex_cvar", theta=fit["theta"])
            pnl, cost = independent_account(train, position, premium, cfg["cost_bps"])
            exact = independent_es(-pnl, cfg["alpha"]) + fit["penalty"]*sum(abs(x) for x in fit["theta"])
            close(fit["objective"], exact, "independently recomputed LP objective", atol=1e-7)
            close(fit["train_es"], independent_es(-pnl), "training tail loss", atol=1e-7)
            close(fit["train_mean_cost"], cost.mean(), "training mean cost")
            close(fit["train_position_min"], position.min(), "training minimum position")
            close(fit["train_position_max"], position.max(), "training maximum position")
            if position.min() < -1e-7 or position.max() > 1+1e-7 or cost.mean() > cfg["budget"]+1e-7:
                raise AssertionError("Training constraints violated")
            if max(abs(x) for x in fit["theta"]) > .25+1e-8:
                raise AssertionError("Coefficient bound violated")
            vp = independent_positions(validation, horizon, "convex_cvar", theta=fit["theta"])
            vpl, vc = independent_account(validation, vp, premium, cfg["cost_bps"])
            metrics = independent_risk(vpl, vc)
            for key, value in metrics.items():
                close(fit["validation"][key], value, "validation "+key)
            options.append((fit, metrics))
            detail["fit_certificates_checked"] += 1
            detail["maximum_reported_stationarity_residual"] = max(detail["maximum_reported_stationarity_residual"], abs(fit["max_stationarity_residual"]))
        feasible = [x for x in options if x[1]["mean_cost"] <= cfg["budget"]]
        pick = min(feasible, key=lambda x: (x[1]["es90"], x[0]["penalty"])) if feasible else min(options, key=lambda x: (x[1]["mean_cost"], x[1]["es90"]))
        bands = []
        for width in [.05, .10]:
            vp = independent_positions(validation, horizon, "validation_selected_band", width=width)
            vpl, vc = independent_account(validation, vp, premium, cfg["cost_bps"])
            bands.append((width, independent_risk(vpl, vc)))
        bf = [x for x in bands if x[1]["mean_cost"] <= cfg["budget"]]
        band = min(bf, key=lambda x: (x[1]["es90"], x[0])) if bf else min(bands, key=lambda x: x[1]["mean_cost"])
        choice = next(row for row in summary["choices"] if row["replicate"] == replicate)
        if (choice["selected_penalty"] != pick[0]["penalty"] or choice["baseline_width"] != band[0]
                or choice["lp_validation_feasible"] != bool(feasible) or choice["baseline_validation_feasible"] != bool(bf)):
            raise AssertionError("Convex validation selection cannot be reconstructed")
        detail["validation_choices_reconstructed"] += 1
        for scenario, params in [("matched_heston", simulation["heston"]), ("shifted_heston", simulation["heston_shift"])]:
            paths = heston_paths(cfg["test_paths"], 21, horizon, seed=seed+200000, **params)["prices"]
            for method in ["convex_cvar", "validation_selected_band", "daily"]:
                pos = independent_positions(paths, horizon, method, theta=pick[0]["theta"], width=band[0])
                pnl, cost = independent_account(paths, pos, premium, cfg["cost_bps"])
                metrics = independent_risk(pnl, cost)
                recorded = next(r for r in summary["test_rows"] if r["replicate"] == replicate and r["scenario"] == scenario and r["method"] == method)
                for key, value in metrics.items():
                    close(recorded[key], value, f"{scenario}/{replicate}/{method}/{key}")
                close(recorded["position_min"], pos.min(), "actual position minimum")
                close(recorded["position_max"], pos.max(), "actual position maximum")
                violation = float(np.mean((pos < -1e-8) | (pos > 1+1e-8)))
                close(recorded["position_violation_fraction"], violation, "position violations")
                if recorded["test_budget_exceeded"] != bool(cost.mean() > cfg["budget"]):
                    raise AssertionError("Incorrect test budget flag")
                detail["maximum_absolute_recomputed_mse_error"] = max(detail["maximum_absolute_recomputed_mse_error"], abs(recorded["mse"]-metrics["mse"]))
                detail["test_rows_reconstructed"] += 1
                detail["daily_position_extrema_checked"] += int(method == "daily")
                detail["out_of_sample_position_violation_rows"] += int(violation > 0)
    return detail


def mse_decomposition_audit(objects):
    count = 0
    def walk(item, location):
        nonlocal count
        if isinstance(item, dict):
            if "mse" in item and "bias_squared" in item:
                variance_key = next((name for name in ["pnl_variance", "variance_pnl", "variance"] if name in item), None)
                if variance_key:
                    close(item["mse"], item[variance_key]+item["bias_squared"], location)
                    count += 1
            for prefix in ["test_", "mean_test_"]:
                if all(prefix+k in item for k in ["mse", "variance", "bias_squared"]):
                    close(item[prefix+"mse"], item[prefix+"variance"]+item[prefix+"bias_squared"], location)
                    count += 1
            for key, value in item.items():
                walk(value, location+"/"+key)
        elif isinstance(item, list):
            for i, value in enumerate(item):
                walk(value, location+"/"+str(i))
    for name, value in objects.items():
        walk(value, name)
    return {"mse_decompositions_checked": count}


def recalc_historical_primary(summary, episodes):
    rows = []
    for stored in summary["primary_comparisons"]:
        part = episodes.loc[(episodes["role"] == "outer") & (episodes["currency"] == stored["currency"]) &
                            (episodes["period"] == stored["period"]) & (episodes["policy"] == "band05") & (episodes["cost_bps"] == 5)]
        a = part.loc[part["model"] == "ridge_term"].set_index(["year", "start_date", "end_date"]).sort_index()
        b = part.loc[part["model"] == "ridge_flat"].set_index(["year", "start_date", "end_date"]).sort_index()
        if not a.index.equals(b.index):
            raise AssertionError("Historical pairing differs")
        d = a["pnl"].to_numpy()**2-b["pnl"].to_numpy()**2
        rng = np.random.default_rng(stored["seed"])
        n, block, B = len(d), stored["block_length"], stored["n_bootstrap"]
        # Different batch size from the estimator, same declared random stream.
        samples = []
        for first in range(0, B, 37):
            count = min(37, B-first)
            starts = rng.integers(0, n-block+1, (count, int(np.ceil(n/block))))
            index = (starts[:, :, None]+np.arange(block)).reshape(count, -1)[:, :n]
            samples.extend(d[index].mean(axis=1))
        means = np.asarray(samples)
        ci = np.quantile(means, [.025, .975])
        p = (1+np.sum(np.abs(means-d.mean()) >= abs(d.mean())))/(B+1)
        for name, value in {"difference": d.mean(), "ci_low": ci[0], "ci_high": ci[1], "p_centered_approx": p, "n": n}.items():
            close(stored[name], value, "historical "+name)
        rows.append(stored)
    for period in ["retrospective", "additional_2026"]:
        family = [r for r in rows if r["period"] == period and r["block_length"] == 3]
        if len(family) != 6:
            raise AssertionError("Holm family does not have six comparisons")
        ordered = sorted(family, key=lambda r: r["p_centered_approx"])
        running = 0.
        for rank, row in enumerate(ordered):
            running = min(1., max(running, (len(ordered)-rank)*row["p_centered_approx"]))
            close(row["holm_six_currency_p"], running, "Holm")
    return {"historical_bootstrap_comparisons_recomputed": len(rows), "holm_families": 2}


def recalc_simulation_comparisons(summary, choices):
    count = 0
    for stored in summary["comparisons"]:
        part = choices.loc[(choices["scenario"] == stored["scenario"]) &
                           (choices["validation_n"] == stored["validation_n"]) & (choices["fee_bps"] == stored["fee_bps"])]
        a = part.loc[part["selector"] == stored["selector"]].sort_values("replicate")
        b = part.loc[part["selector"] == "forecast_first"].sort_values("replicate")
        if a["replicate"].tolist() != list(range(24)) or b["replicate"].tolist() != list(range(24)):
            raise AssertionError("Simulation inference does not use 24 complete repetitions")
        actual = independent_ci(a[stored["metric"]], b[stored["metric"]])
        for key, value in actual.items():
            close(stored[key], value, "simulation interval "+key)
        count += 1
    primaries = [r for r in summary["comparisons"] if r["primary"]]
    if len(primaries) != 1 or primaries[0] != summary["primary_comparison"]:
        raise AssertionError("Primary simulation contrast is inconsistent")
    return {"simulation_intervals_recomputed": count, "independent_units_per_interval": 24}


def recalc_convex_comparisons(summary):
    for stored in summary["contrasts"]:
        rows = [r for r in summary["test_rows"] if r["scenario"] == stored["scenario"]]
        a = sorted((r for r in rows if r["method"] == "convex_cvar"), key=lambda r: r["replicate"])
        b = sorted((r for r in rows if r["method"] == "validation_selected_band"), key=lambda r: r["replicate"])
        if [r["replicate"] for r in a] != list(range(8)) or [r["replicate"] for r in b] != list(range(8)):
            raise AssertionError("Convex inference units are not 8 independent repetitions")
        actual = independent_ci([r[stored["metric"]] for r in a], [r[stored["metric"]] for r in b])
        for key, value in actual.items():
            close(stored[key], value, "convex interval "+key)
    return {"convex_intervals_recomputed": len(summary["contrasts"]), "independent_units_per_interval": 8}


class Audit:
    def __init__(self):
        self.checks = []
    def check(self, name, callback):
        try:
            details = callback()
            self.checks.append({"name": name, "passed": True, "details": details})
        except Exception as error:
            self.checks.append({"name": name, "passed": False, "error": f"{type(error).__name__}: {error}"})


def main():
    started = time.perf_counter()
    audit = Audit()
    protocol_path = ROOT / "docs/v2_protocol.json"
    protocol = load_json(protocol_path)
    historical = load_json(ROOT / "results/v2_historical_summary.json")
    selection = load_json(ROOT / "results/v2_selection_summary.json")
    convex = load_json(ROOT / "results/v2_convex_summary.json")
    summaries = {"historical": historical, "selection": selection, "convex": convex}
    episodes = pd.read_csv(ROOT / "results/v2_historical_episodes.csv")
    candidates = pd.read_csv(ROOT / "results/v2_selection_candidates.csv")
    choices = pd.read_csv(ROOT / "results/v2_selection_choices.csv")

    def source_checks():
        count = 0
        for source in [historical["implementation_sha256"], selection["source_sha256"], convex["source_sha256"]]:
            for name, expected in source.items():
                if sha(ROOT / name) != expected:
                    raise AssertionError("Implementation hash mismatch: "+name)
                count += 1
        expected = sha(protocol_path)
        if any(value != expected for value in [historical["protocol_sha256"], selection["execution_protocol"]["main_protocol_sha256"], convex["design"]["protocol_sha256"]]):
            raise AssertionError("Study protocol hash mismatch")
        frozen = selection["execution_protocol"]
        canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(canonical).hexdigest() != selection["execution_protocol_sha256"]:
            raise AssertionError("Simulation execution protocol hash mismatch")
        execution_file = load_json(ROOT / "results/v2_selection_execution_protocol.json")
        if execution_file != {**frozen, "execution_protocol_sha256": selection["execution_protocol_sha256"]}:
            raise AssertionError("Saved simulation execution protocol differs")
        if frozen["effective_simulation"] != protocol["simulation"] or selection["smoke_only"]:
            raise AssertionError("Report evidence is not full frozen simulation")
        if convex["protocol"] != protocol["convex_extension"]:
            raise AssertionError("Convex effective protocol differs")
        for name, info in historical["files"].items():
            if sha(ROOT / "results" / name) != info["sha256"]:
                raise AssertionError("Historical result file hash mismatch: "+name)
        if sha(ROOT / "data/ecb_reference_snapshot.zip") != historical["source"]["archived_raw_sha256"]:
            raise AssertionError("Raw ECB snapshot changed")
        if sha(ROOT / "data/v2_ecb_six_currencies.csv") != historical["source"]["processed_sha256"]:
            raise AssertionError("V2 processed data changed")
        return {"implementation_entries": count, "study_protocols": 3, "historical_hashed_csvs": len(historical["files"])}
    audit.check("Sources and frozen protocols", source_checks)

    def coverage_checks():
        if len(historical["folds"]) != 72 or len(episodes) != 123552:
            raise AssertionError("Historical coverage incomplete")
        for name, info in historical["files"].items():
            if len(pd.read_csv(ROOT / "results" / name)) != info["rows"]:
                raise AssertionError("Historical CSV row count mismatch: "+name)
        if len(candidates) != 11520 or len(choices) != 1728:
            raise AssertionError("Simulation candidate or selector coverage incomplete")
        if len(candidates) != selection["counts"]["candidate_rows"] or len(choices) != selection["counts"]["selected_rows"]:
            raise AssertionError("Simulation CSV counts differ from JSON")
        for name, records in [("v2_selection_aggregates.csv", selection["aggregates"]),
                              ("v2_selection_frequencies.csv", selection["selection_frequencies"]),
                              ("v2_selection_comparisons.csv", selection["comparisons"]),
                              ("v2_discretization.csv", selection["discretization"]),
                              ("v2_convex_metrics.csv", convex["test_rows"]),
                              ("v2_convex_choices.csv", convex["choices"])]:
            actual = pd.read_csv(ROOT / "results" / name)
            if len(actual) != len(records):
                raise AssertionError("CSV/JSON row count mismatch: "+name)
            expected = pd.DataFrame(records)
            for col in expected.columns:
                if pd.api.types.is_numeric_dtype(expected[col]) and not pd.api.types.is_bool_dtype(expected[col]):
                    close(actual[col].to_numpy(), expected[col].to_numpy(), name+"/"+col)
                elif actual[col].astype(str).tolist() != expected[col].astype(str).tolist():
                    raise AssertionError("CSV/JSON column mismatch: "+name+"/"+col)
        if len(pd.read_csv(ROOT / "results/v2_convex_ledger.csv")) != 88:
            raise AssertionError("Convex representative ledger row count mismatch")
        return {"historical_candidate_metrics": 6912, "historical_strategy_rows": len(episodes),
                "simulation_candidate_rows": len(candidates), "simulation_selected_rows": len(choices),
                "convex_fit_count": len(convex["fits"]), "convex_test_rows": len(convex["test_rows"])}
    audit.check("Full coverage and CSV/JSON agreement", coverage_checks)

    def decomposition_checks():
        items = {**summaries, "simulation_candidate_csv": candidates.to_dict("records"),
                 "simulation_selection_csv": choices.to_dict("records")}
        return mse_decomposition_audit(items)
    audit.check("All recorded MSE variance bias decompositions", decomposition_checks)
    audit.check("Historical paired bootstrap and six-currency Holm", lambda: recalc_historical_primary(historical, episodes))
    audit.check("Repeated-selection intervals use 24 repetitions", lambda: recalc_simulation_comparisons(selection, choices))
    audit.check("Convex intervals use 8 repetitions", lambda: recalc_convex_comparisons(convex))
    audit.check("Independent LP accounting choices risks and position extrema", convex_reconstruction)

    def selection_checks():
        # Rebuild the finite-class selection directly from saved validation rows.
        checked = 0
        for (scenario, replicate, n, fee), group in choices.groupby(["scenario", "replicate", "validation_n", "fee_bps"]):
            val = candidates.loc[(candidates["scenario"] == scenario) & (candidates["replicate"] == replicate) &
                                 (candidates["validation_n"] == n) & (candidates["fee_bps"] == fee) & (candidates["split"] == "validation")]
            if len(val) != 12:
                raise AssertionError("Incomplete validation candidate grid")
            budget = float(group.iloc[0]["budget"])
            for _, recorded in group.iterrows():
                eligible = val
                if recorded["selector"] == "forecast_first":
                    model = val.sort_values(["qlike", "multiplier"], kind="stable").iloc[0]["multiplier"]
                    eligible = val.loc[val["multiplier"] == model]
                feasible = eligible.loc[eligible["mean_cost"] <= budget]
                if len(feasible):
                    metric = "es90" if recorded["selector"] == "joint_es90" else "mse"
                    expected = feasible.sort_values([metric, "mean_cost", "candidate"], kind="stable").iloc[0]
                else:
                    expected = eligible.sort_values(["mean_cost", "mse", "candidate"], kind="stable").iloc[0]
                if expected["candidate"] != recorded["candidate"] or bool(len(feasible)) != recorded["validation_feasible"]:
                    raise AssertionError("Simulation choice not reconstructed from validation")
                test = candidates.loc[(candidates["scenario"] == scenario) & (candidates["replicate"] == replicate) &
                                      (candidates["fee_bps"] == fee) & (candidates["split"] == "test") &
                                      (candidates["candidate"] == recorded["candidate"])].iloc[0]
                for key in ["mse", "variance", "bias_squared", "mean_pnl", "es90", "mean_cost"]:
                    close(recorded["test_"+key], test[key], "selected test metric")
                checked += 1
        return {"simulation_validation_only_choices_reconstructed": checked}
    audit.check("Selection uses validation and maps to unchanged test candidates", selection_checks)
    result = {"status": "passed" if all(c["passed"] for c in audit.checks) else "failed",
              "passed": all(c["passed"] for c in audit.checks), "checks_total": len(audit.checks),
              "checks_passed": sum(c["passed"] for c in audit.checks), "checks": audit.checks,
              "protocol_sha256": sha(protocol_path), "auditor_sha256": sha(Path(__file__)), "runtime_seconds": time.perf_counter()-started,
              "limitations": ["Numerical and provenance checks do not establish novel theory, market executability or publication acceptance.",
                              "LP primal/dual residuals are checked and the economic objective/constraints replayed independently; complete solver primal and dual vectors are not serialized, so this is not a portable formal LP proof certificate.",
                              "Historical intervals remain retrospective and conditional; the audit does not create new untouched observations.",
                              "A fixed protocol hash proves byte consistency, not external preregistration or chronology independently witnessed by a third party."]}
    (ROOT / "results/v2_artifact_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": result["checks_total"], "passed": result["checks_passed"],
                      "failures": [c for c in audit.checks if not c["passed"]], "seconds": result["runtime_seconds"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        # Never leave an earlier successful audit as the apparent latest result
        # when a required artifact is missing, unreadable, or malformed.
        failure = {"status": "failed", "passed": False, "checks_total": 1,
                   "checks_passed": 0, "checks": [{"name": "Load required research evidence",
                   "passed": False, "error": f"{type(error).__name__}: {error}"}],
                   "auditor_sha256": sha(Path(__file__))}
        destination = ROOT / "results/v2_artifact_audit.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False))
        code = 1
    raise SystemExit(code)
