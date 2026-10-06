"""Download and freeze the official ECB reference-rate snapshot, without filling gaps."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
SOURCE_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
LICENSE_URL = "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html"
START = "1999-01-04"
END = "2025-12-31"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_snapshot(raw: bytes) -> tuple[pd.DataFrame, dict]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Expected exactly one ECB CSV in the downloaded archive")
        frame = pd.read_csv(io.BytesIO(archive.read(members[0])), na_values=["N/A"])
    frame.columns = [str(c).strip() for c in frame.columns]
    selected = frame.loc[:, ["Date", "USD", "JPY"]].rename(columns={"Date": "date"})
    selected["date"] = pd.to_datetime(selected["date"], errors="raise")
    duplicate_count = int(selected["date"].duplicated().sum())
    if duplicate_count:
        raise ValueError("Duplicate reference dates: investigate instead of silently dropping")
    for currency in ["USD", "JPY"]:
        selected[currency] = pd.to_numeric(selected[currency], errors="raise")
    source_start = str(selected["date"].min().date())
    source_end = str(selected["date"].max().date())
    selected = selected.loc[selected["date"].between(START, END)].sort_values("date").reset_index(drop=True)
    if not np.isfinite(selected[["USD", "JPY"]].to_numpy()).all():
        raise ValueError("Missing or nonfinite selected reference quotes")
    if (selected[["USD", "JPY"]] <= 0).any().any():
        raise ValueError("Nonpositive FX reference rate")
    if str(selected["date"].max().date()) != END:
        raise ValueError("Snapshot does not reach the fixed endpoint")
    gaps = selected["date"].diff().dt.days.dropna()
    audit = {
        "download_rows": len(frame), "download_start": source_start, "download_end": source_end,
        "processed_rows": len(selected), "processed_start": str(selected["date"].min().date()),
        "processed_end": str(selected["date"].max().date()), "duplicate_dates": duplicate_count,
        "missing_selected_quotes": int(selected[["USD", "JPY"]].isna().sum().sum()),
        "nonpositive_selected_quotes": int((selected[["USD", "JPY"]] <= 0).sum().sum()),
        "max_calendar_gap_days": int(gaps.max()),
        "gaps_over_three_days": int((gaps > 3).sum()),
        "calendar_gap_treatment": "No interpolation or forward fill. Returns use successive published observations; a 252-observation year is a convention, not equal calendar spacing.",
        "processing": "Select USD and JPY currency units per EUR; sort dates; retain 1999-01-04 through 2025-12-31 inclusive. No quote correction, return winsorisation, filling or observation deletion.",
    }
    selected["date"] = selected["date"].dt.strftime("%Y-%m-%d")
    return selected, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Replace the frozen snapshot explicitly; old results must then be regenerated")
    args = parser.parse_args()
    destination = ROOT / "data"
    destination.mkdir(exist_ok=True)
    raw_path = destination / "ecb_reference_snapshot.zip"
    manifest_path = destination / "source_manifest.json"
    if raw_path.exists() and manifest_path.exists() and not args.refresh:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(raw_path) != manifest["files"]["ecb_reference_snapshot.zip"]["sha256"]:
            raise ValueError("Stored raw data does not match its frozen source hash")
        print(json.dumps({"status": "using_frozen_snapshot", "raw_sha256": sha256(raw_path)}))
        return
    response = requests.get(DATA_URL, timeout=90, headers={"User-Agent": "FinMathRiskLab/1.0 academic reproducibility"})
    response.raise_for_status()
    frame, audit = process_snapshot(response.content)
    raw_path.write_bytes(response.content)
    csv_path = destination / "ecb_usd_jpy.csv"
    frame.to_csv(csv_path, index=False, float_format="%.12g", lineterminator="\n")
    (destination / "data_quality.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    manifest = {
        "publisher": "European Central Bank (ECB)", "dataset": "Euro foreign exchange reference rates",
        "source_url": SOURCE_URL, "download_url": DATA_URL, "license_url": LICENSE_URL,
        "retrieved_at_hong_kong": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "fixed_analysis_endpoint": END,
        "units": "USD and JPY per one EUR. These are reference observations, not executable market quotes.",
        "reuse_summary": "ECB permits free use of information obtained directly from its website subject to accurate reproduction, ECB attribution and explicit identification of modifications. Sales require notice of free availability. Named-author publications have a separate permission exception. No ECB endorsement is implied.",
        "processing_notice": audit["processing"] + " Downstream analyses derive log returns, variance proxies and hypothetical normalized paths; these are our transformations, not ECB outputs.",
        "limitations": ["Reference rates are published for information; ECB discourages transaction use.", "Snapshot may contain revisions known at retrieval rather than point-in-time vintages.", "Currency series share EUR as denominator and are not independent replications."],
        "files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in [raw_path, csv_path, destination / "data_quality.json"]},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "downloaded", "processed_rows": len(frame), "raw_sha256": sha256(raw_path)}))


if __name__ == "__main__":
    main()
