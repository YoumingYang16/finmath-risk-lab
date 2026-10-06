"""Prove the release auditor detects specific cross-file corruptions."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from scripts.verify_artifacts import (compare_frames, finite_frame, finite_json,
    verify_ledger, verify_primary_contrasts, verify_simulation, verify_sqlite)

ROOT = Path(__file__).resolve().parents[1]


def test_cross_file_comparison_detects_single_numeric_change():
    expected = pd.DataFrame({"key": ["a", "b"], "value": [0.001, 0.002]})
    actual = expected.copy()
    actual.loc[1, "value"] += 0.0001
    with pytest.raises(ValueError, match="mismatched numeric"):
        compare_frames(actual, expected, ["key"], "tampered")


def test_nonfinite_json_and_csv_fail_audit():
    with pytest.raises(ValueError, match="Nonfinite"):
        finite_json({"nested": [1, float("inf")]})
    with pytest.raises(ValueError, match="nonfinite"):
        finite_frame(pd.DataFrame({"metric": [1.0, np.nan]}), "broken")


def test_duplicate_primary_contrasts_rejected():
    rows = pd.DataFrame([{"scenario": "S1", "fee_bps": 5.0, "baseline": "every5", "primary": True},
                         {"scenario": "S2", "fee_bps": 5.0, "baseline": "every5", "primary": True}])
    with pytest.raises(ValueError, match="Exactly one"):
        verify_primary_contrasts(rows)


def test_changed_protocol_is_not_accepted_with_old_hash(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "results").mkdir()
    protocol = json.loads((ROOT / "docs/simulation_protocol.json").read_text(encoding="utf-8"))
    protocol["mean_cost_budget"] += 0.1
    (tmp_path / "docs/simulation_protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    shutil.copyfile(ROOT / "results/simulation_summary.json", tmp_path / "results/simulation_summary.json")
    with pytest.raises(ValueError, match="protocol differs"):
        verify_simulation(tmp_path)


def test_interior_ledger_cash_corruption_is_detected():
    ledger = pd.read_csv(ROOT / "results/simulation_ledger.csv")
    premium = float(ledger.iloc[0].cash_before)
    ledger.loc[5, "cash_after"] += 0.01
    with pytest.raises(ValueError, match="accounting identity"):
        verify_ledger(ledger, premium, 0.03, 0.5, 100, 5)


@pytest.mark.parametrize("update,expected_message", [
    ("UPDATE episode SET pnl=pnl+1 WHERE rowid=1", "mismatched numeric"),
    ("UPDATE episode SET source_id=99999 WHERE rowid=1", "foreign key violations"),
    ("UPDATE source_file SET sha256='incorrect' WHERE id=1", "provenance mismatch"),
])
def test_sqlite_tampering_is_detected_even_with_unchanged_csv(tmp_path, update, expected_message):
    (tmp_path / "results").mkdir()
    for name in ["research.sqlite", "simulation_metrics.csv", "historical_forecasts.csv", "historical_episodes.csv"]:
        source = ROOT / "results" / name
        if not source.exists():
            pytest.skip("Build research SQLite before auditing generated evidence")
        shutil.copyfile(source, tmp_path / "results" / name)
    with sqlite3.connect(tmp_path / "results/research.sqlite") as connection:
        connection.execute(update)
    with pytest.raises(ValueError, match=expected_message):
        verify_sqlite(tmp_path)


def test_failed_cli_audit_returns_nonzero_and_writes_failure_record(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/verify_artifacts.py"), "--root", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    report = json.loads((tmp_path / "results/artifact_audit.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert all(check["status"] == "failed" for check in report["checks"])
