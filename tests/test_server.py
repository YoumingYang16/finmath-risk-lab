"""Behavioral checks for the local numerical boundary and artifact delivery."""
import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from risklab.server import make_server, price_request, simulate_request


@pytest.fixture
def local_server(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
    (tmp_path / "results").mkdir()
    server = make_server(0, root=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, tmp_path
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(server, path, data=None, *, headers=None, raw=None):
    body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
    request_headers = {"Content-Type": "application/json"} if body is not None else {}
    request_headers.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}", data=body, headers=request_headers)
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read()
        result = json.loads(content) if "json" in response.headers.get("Content-Type", "") else content.decode()
        return response.status, result, dict(response.headers)


def test_read_only_artifacts_do_not_fabricate_results(local_server):
    server, root = local_server
    status, body, _ = request(server, "/api/results")
    assert status == 200
    assert all(item["status"] == "missing" for item in body.values())
    (root / "results" / "simulation_summary.json").write_text('{"executed":true,"runs":12}', encoding="utf-8")
    (root / "results" / "historical_summary.json").write_text('{"metric":NaN}', encoding="utf-8")
    _, body, _ = request(server, "/api/results")
    assert body["simulation"]["data"] == {"executed": True, "runs": 12}
    assert body["historical"]["status"] == "invalid"
    assert request(server, "/api/competencies")[1]["status"] == "missing"


def test_static_allowlist_and_response_policy(local_server):
    server, _ = local_server
    status, html, headers = request(server, "/")
    assert status == 200 and "<!doctype html>" in html
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    for path in ("/../pyproject.toml", "/%2e%2e/pyproject.toml", "/risklab/server.py", "/results/simulation_summary.json"):
        assert request(server, path)[0] == 404


def test_research_v2_route_preserves_real_artifacts_and_missing_states(local_server):
    server, root = local_server
    status, data, _ = request(server, "/api/research-v2")
    assert status == 200
    assert set(data) == {"historical", "selection", "convex", "publication_routes", "protocol"}
    assert all(item["status"] == "missing" for item in data.values())
    (root / "docs").mkdir()
    protocol = {"version": "2.0.0", "historical": {"currencies": ["USD", "JPY", "GBP", "CHF", "CAD", "AUD"]}}
    (root / "docs" / "v2_protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    (root / "results" / "v2_historical_summary.json").write_text('{"primary":{"difference":-0.25,"ci_low":-0.5,"ci_high":0.1}}', encoding="utf-8")
    (root / "results" / "v2_convex_summary.json").write_text('{"objective":NaN}', encoding="utf-8")
    _, actual, _ = request(server, "/api/research-v2")
    assert actual["protocol"]["data"] == protocol
    assert actual["historical"]["data"]["primary"]["difference"] == -0.25
    assert actual["selection"]["status"] == "missing"
    assert actual["convex"]["status"] == "invalid"
    assert request(server, "/api/research-v2/../../README.md")[0] == 404
    assert request(server, "/api/research-v2", {})[0] == 404


def test_result_reader_limits_artifact_size(local_server, monkeypatch):
    from risklab import server as server_module
    server, root = local_server
    monkeypatch.setattr(server_module, "MAX_ARTIFACT_BYTES", 64)
    (root / "results" / "v2_selection_summary.json").write_text(json.dumps({"rows": "x" * 100}), encoding="utf-8")
    data = request(server, "/api/research-v2")[1]
    assert data["selection"]["status"] == "too_large"
    assert "data" not in data["selection"]


def test_http_boundary_rejects_cross_origin_and_malformed_body(local_server):
    server, _ = local_server
    assert request(server, "/api/price", {}, headers={"Origin": "https://example.org"})[0] == 403
    assert request(server, "/api/health", headers={"Host": "attacker.example"})[0] == 403
    assert request(server, "/api/price", raw=b'[]')[0] == 400
    assert request(server, "/api/price", raw=b'{"vol":NaN}')[0] == 400
    assert request(server, "/api/price", raw=b'broken')[0] == 400
    assert request(server, "/api/price", {}, headers={"Content-Type":"text/plain"})[0] == 415
    assert request(server, "/api/price", raw=b' ' * 17000)[0] == 413
    assert request(server, "/api/unknown", {})[0] == 404


@pytest.mark.parametrize("params", [{"n_paths":3000,"steps":252}, {"n_paths":False}, {"steps":2.5}, {"vol":float("inf")}, {"spot":-1}, {"cost_bps":-1}, {"policy":"unknown"}, {"every":100,"steps":10}, {"seed":-1}, {"output_file":"secret"}])
def test_numerical_bounds_reject_invalid_simulations(params):
    with pytest.raises(ValueError):
        simulate_request(params)


def test_price_computation_and_implied_volatility_are_real():
    result = price_request({"n_paths": 1000, "steps": 128, "seed": 18})
    assert abs(result["bs"] - result["crr"]) < .03
    assert len(result["curve"]) == 49
    assert result["curve"][0]["price"] < result["curve"][-1]["price"]
    inverted = price_request({"market_price": result["bs"], "n_paths": 1000})
    assert inverted["implied_volatility"] == pytest.approx(.2, abs=1e-8)
    put = price_request({"kind": "put", "n_paths": 1000})
    assert put["greeks"]["delta"] < 0
    assert result["greeks"]["delta"] > 0


def test_seed_cost_and_policy_behavior():
    params = {"n_paths":60,"steps":12,"seed":10,"cost_bps":0,"every":3}
    first = simulate_request(params)
    repeat = simulate_request(params)
    assert first == repeat
    fee = simulate_request({**params,"cost_bps":10})
    assert first["paths"] == fee["paths"]
    assert fee["summary"]["mean_pnl"] < first["summary"]["mean_pnl"]
    assert fee["summary"]["mean_cost"] > 0
    assert first["summary"]["mean_cost"] == 0
    assert sum(first["histogram"]["counts"]) == params["n_paths"]
    assert len(first["ledger"]) == params["steps"] + 1
    assert first["ledger"][-1]["position"] == 0
    assert simulate_request({**params,"seed":11})["paths"] != first["paths"]
    equal = simulate_request({**params,"every":1})
    assert equal["paired_pnl_difference"]["difference"] == 0
    threshold = simulate_request({**params,"policy":"threshold","threshold":.1})
    assert threshold["parameters"]["policy"] == {"kind":"threshold","threshold":.1}


@pytest.mark.parametrize("model", ["regime", "jump"])
def test_model_variants_are_finite(model):
    result = simulate_request({"model":model,"n_paths":20,"steps":10})
    assert result["parameters"]["model"] == model
    assert np.isfinite(result["summary"]["rmse"])
    assert len(result["paths"]) == 8


def test_http_numerical_round_trip(local_server):
    server, _ = local_server
    status, body, _ = request(server, "/api/price", {"n_paths":200,"steps":32})
    assert status == 200 and body["bs"] > 0
    status, body, _ = request(server, "/api/simulate", {"n_paths":20,"steps":8})
    assert status == 200 and body["summary"]["n"] == 20
    status, body, _ = request(server, "/api/simulate", {"n_paths":3000,"steps":252})
    assert status == 422 and "400000" in body["error"]
