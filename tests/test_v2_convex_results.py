"""Audit the executed convex study, including actual baseline state extrema."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_v2_artifacts", ROOT / "scripts/verify_v2_artifacts.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


@pytest.fixture(scope="module")
def summary():
    path = ROOT / "results/v2_convex_summary.json"
    if not path.exists():
        pytest.skip("Execute run_convex_study.py before checking empirical artifacts")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reconstructed(summary):
    return VERIFY.convex_reconstruction(ROOT)


def test_twenty_four_fits_have_auditable_certificates(summary):
    assert len(summary["fits"]) == 24
    assert all(fit["success"] and fit["solver_status"] == 0 for fit in summary["fits"])
    assert {(f["replicate"], f["penalty"]) for f in summary["fits"]} == {(r, p) for r in range(8) for p in [0., .01, .1]}
    for fit in summary["fits"]:
        for key in ["duality_gap", "objective_reconciliation_gap", "max_primal_inequality_violation", "max_stationarity_residual"]:
            assert np.isfinite(fit[key]) and abs(fit[key]) < 1e-6
        assert fit["objective"]-fit["dual_objective"] == pytest.approx(fit["duality_gap"], abs=1e-10)


def test_all_train_objectives_and_validation_choices_reconstruct(reconstructed):
    assert reconstructed["fit_certificates_checked"] == 24
    assert reconstructed["validation_choices_reconstructed"] == 8


def test_all_forty_eight_test_outcomes_independently_reconstruct(reconstructed):
    assert reconstructed["test_rows_reconstructed"] == 48
    assert reconstructed["maximum_absolute_recomputed_mse_error"] < 1e-10


def test_daily_extrema_are_observed_not_theoretical(reconstructed):
    assert reconstructed["daily_position_extrema_checked"] == 16


def test_actual_unseen_position_violations_are_retained(summary, reconstructed):
    rows = [r for r in summary["test_rows"] if r["position_violation_fraction"] > 0]
    assert len(rows) == reconstructed["out_of_sample_position_violation_rows"]
    # Sample-constrained learning must report values outside [0,1] unchanged.
    for row in rows:
        assert row["position_min"] < -1e-8 or row["position_max"] > 1+1e-8


def test_convex_intervals_use_eight_complete_repetitions(summary):
    detail = VERIFY.recalc_convex_comparisons(summary)
    assert detail == {"convex_intervals_recomputed": 6, "independent_units_per_interval": 8}
    for row in summary["contrasts"]:
        assert row["n"] == 8


def test_covariance_pairing_cannot_be_replaced_by_test_path_count(summary):
    changed = deepcopy(summary)
    changed["contrasts"][0]["n"] = 4096
    with pytest.raises(AssertionError, match="convex interval n"):
        VERIFY.recalc_convex_comparisons(changed)


def test_convex_protocol_and_source_bytes_match_executed_results(summary):
    assert summary["design"]["protocol_sha256"] == hashlib.sha256((ROOT / "docs/v2_protocol.json").read_bytes()).hexdigest()
    for name, expected in summary["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected


def test_false_daily_minimum_is_detected_without_modifying_result_files(summary, monkeypatch):
    changed = deepcopy(summary)
    daily = next(row for row in changed["test_rows"] if row["replicate"] == 0 and row["scenario"] == "matched_heston" and row["method"] == "daily")
    daily["position_min"] = -7.
    real_loader = VERIFY.load_json
    def altered_loader(path):
        return changed if Path(path).name == "v2_convex_summary.json" else real_loader(path)
    monkeypatch.setattr(VERIFY, "load_json", altered_loader)
    with pytest.raises(AssertionError, match="actual position minimum"):
        VERIFY.convex_reconstruction(ROOT)
