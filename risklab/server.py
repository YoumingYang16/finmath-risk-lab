"""Local, read-only research dashboard and bounded numerical API.

Run from the project directory: ``python -m risklab.server --port 8872``.
This deliberately has no order execution, upload, account, or arbitrary file API.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 16_384
MAX_ARTIFACT_BYTES = 24 * 1024 * 1024
COMPUTE_SLOTS = threading.BoundedSemaphore(2)


def number(data, key, default, low, high, *, integer=False):
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{key} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{key} must be finite and between {low} and {high}")
    if integer and int(value) != value:
        raise ValueError(f"{key} must be an integer")
    return int(value) if integer else float(value)


def choice(data, key, default, allowed):
    value = data.get(key, default)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{key} must be one of {', '.join(allowed)}")
    return value


def allowed_keys(data, allowed):
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError("Unknown fields: " + ", ".join(sorted(unknown)))


def safe_json(value):
    if isinstance(value, np.ndarray):
        return safe_json(value.tolist())
    if isinstance(value, np.generic):
        return safe_json(value.item())
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Computation produced a non-finite result")
    return value


def price_request(data):
    from .pricing import bs_price, bs_greeks, crr_price, mc_price, implied_volatility

    allowed_keys(data, {"spot", "strike", "maturity", "rate", "vol", "kind", "dividend", "steps", "n_paths", "seed", "market_price"})
    params = {
        "spot": number(data, "spot", 100, .001, 1_000_000),
        "strike": number(data, "strike", 100, .001, 1_000_000),
        "maturity": number(data, "maturity", .25, .0001, 10),
        "rate": number(data, "rate", .03, -.2, .5),
        "vol": number(data, "vol", .2, .001, 3),
        "kind": choice(data, "kind", "call", ("call", "put")),
        "dividend": number(data, "dividend", 0, 0, .5),
    }
    steps = number(data, "steps", 256, 2, 1024, integer=True)
    n_paths = number(data, "n_paths", 20_000, 100, 100_000, integer=True)
    seed = number(data, "seed", 42, 0, 2**32 - 1, integer=True)
    result = {"parameters": params, "bs": float(bs_price(**params)),
              "crr": float(crr_price(**params, steps=steps)),
              "mc": mc_price(**params, n_paths=n_paths, seed=seed),
              "greeks": bs_greeks(**params),
              "units": {"delta": "price change per 1 spot unit", "gamma": "delta change per 1 spot unit", "vega": "price change per 1.0 volatility (divide by 100 for 1 percentage point)", "theta": "price change per calendar year", "rho": "price change per 1.0 rate (divide by 100 for 1 percentage point)"},
              "settings": {"crr_steps": steps, "mc_paths": n_paths, "seed": seed}}
    grid = np.linspace(params["spot"] * .65, params["spot"] * 1.35, 49)
    result["curve"] = [{"spot": float(s), "price": float(bs_price(**{**params, "spot": float(s)})), "delta": float(bs_greeks(**{**params, "spot": float(s)})["delta"])} for s in grid]
    if "market_price" in data and data["market_price"] is not None:
        price = number(data, "market_price", 0, 0, 1_000_000)
        iv_params = {key: value for key, value in params.items() if key != "vol"}
        result["implied_volatility"] = float(implied_volatility(price=price, **iv_params))
    return safe_json(result)


def simulate_request(data):
    from .pricing import bs_price
    from .paths import simulate_paths
    from .hedging import hedge_paths
    from .statistics import summarize_pnl, paired_mean_ci

    allowed_keys(data, {"n_paths", "steps", "horizon", "spot", "strike", "rate", "vol", "hedge_vol", "mu", "seed", "model", "vol2", "switch_fraction", "jump_intensity", "jump_mean", "jump_std", "policy", "every", "threshold", "cost_bps", "kind"})
    n_paths = number(data, "n_paths", 500, 10, 3000, integer=True)
    steps = number(data, "steps", 63, 2, 252, integer=True)
    if n_paths * (steps + 1) > 400_000:
        raise ValueError("n_paths × (steps + 1) must not exceed 400000 cells")
    horizon = number(data, "horizon", .25, .001, 3)
    spot = number(data, "spot", 100, .01, 100_000)
    strike = number(data, "strike", 100, .01, 100_000)
    rate = number(data, "rate", .03, -.1, .3)
    vol = number(data, "vol", .2, .001, 1.5)
    hedge_vol = number(data, "hedge_vol", .2, .001, 1.5)
    mu = number(data, "mu", .03, -.5, .5)
    seed = number(data, "seed", 42, 0, 2**32 - 1, integer=True)
    cost_bps = number(data, "cost_bps", 5, 0, 100)
    model = choice(data, "model", "gbm", ("gbm", "regime", "jump"))
    kind = choice(data, "kind", "call", ("call", "put"))
    policy_kind = choice(data, "policy", "fixed", ("fixed", "threshold"))
    policy = {"kind": policy_kind}
    if policy_kind == "fixed":
        policy["every"] = number(data, "every", 5, 1, steps, integer=True)
    else:
        policy["threshold"] = number(data, "threshold", .05, .001, 1)
    model_params = {}
    if model == "regime":
        model_params = {"vol2": number(data, "vol2", .4, .001, 1.5), "switch_fraction": number(data, "switch_fraction", .5, .01, .99)}
    elif model == "jump":
        model_params = {"jump_intensity": number(data, "jump_intensity", 1, 0, 10), "jump_mean": number(data, "jump_mean", -.08, -.5, .5), "jump_std": number(data, "jump_std", .12, 0, .5)}
    paths = simulate_paths(n_paths=n_paths, steps=steps, horizon=horizon, spot=spot, vol=vol, mu=mu, seed=seed, model=model, **model_params)
    premium = float(bs_price(spot, strike, horizon, rate, hedge_vol, kind=kind))
    common = {"paths": paths, "strike": strike, "rate": rate, "horizon": horizon, "hedge_vol": hedge_vol, "premium": premium, "cost_bps": cost_bps, "kind": kind}
    chosen = hedge_paths(**common, policy=policy)
    reference = hedge_paths(**common, policy={"kind": "fixed", "every": 1})
    counts, edges = np.histogram(chosen["pnl"], bins=30)
    result = {
        "parameters": {"n_paths": n_paths, "steps": steps, "horizon": horizon, "spot": spot, "strike": strike, "rate": rate, "vol": vol, "hedge_vol": hedge_vol, "physical_drift": mu, "seed": seed, "model": model, "model_parameters": model_params, "policy": policy, "cost_bps": cost_bps, "kind": kind},
        "premium": premium,
        "summary": summarize_pnl(chosen["pnl"], chosen["cost"], chosen["trades"]),
        "reference": summarize_pnl(reference["pnl"], reference["cost"], reference["trades"]),
        "paired_pnl_difference": paired_mean_ci(chosen["pnl"], reference["pnl"]),
        "paths": paths[:8], "histogram": {"counts": counts, "edges": edges},
        "ledger": chosen["ledger"],
        "conventions": ["One short option, long delta hedge; loss = -P&L.", "Same premium and same paths for both policies; q=0.", "Entry, rebalance and liquidation costs included; cost accumulated to maturity.", "Reference rebalances every observation. The pointwise interval compares paired independent simulated paths.", "Simulated physical paths, not market quotes or investment performance."],
    }
    return safe_json(result)


def read_artifact(path):
    if not path.is_file():
        return {"status": "missing", "message": "尚未生成此项研究结果"}
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            return {"status": "too_large", "message": "结果摘要超过 24 MiB 读取上限，请在本地检查文件"}
        with path.open(encoding="utf-8-sig") as handle:
            content = handle.read(MAX_ARTIFACT_BYTES + 1)
        if len(content.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            return {"status": "too_large", "message": "结果摘要超过 24 MiB 读取上限，请在本地检查文件"}
        data = json.loads(content)
        safe_json(data)
        return {"status": "available", "data": data}
    except (OSError, ValueError, TypeError):
        return {"status": "invalid", "message": "结果文件不可读取或内容无效"}


class Handler(BaseHTTPRequestHandler):
    server_version = "FinMathRiskLab/2.0"

    def send_content(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, data):
        payload = json.dumps(safe_json(data), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_content(status, payload, "application/json; charset=utf-8")

    def valid_host(self):
        host = self.headers.get("Host", "")
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in expected:
            self.send_json(403, {"error": "Only the local research origin is allowed"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{item}" for item in expected}:
            self.send_json(403, {"error": "Cross-origin requests are not allowed"})
            return False
        return True

    def do_GET(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        root = self.server.root
        if path == "/api/health":
            self.send_json(200, {"status": "ok", "service": "FinMath Risk Lab", "version": "2.0.0", "mode": "local-research", "limits": {"body_bytes": MAX_BODY, "artifact_bytes": MAX_ARTIFACT_BYTES, "simulation_cells": 400000, "concurrent_computations": 2}})
        elif path == "/api/results":
            self.send_json(200, {name: read_artifact(root / "results" / f"{name}_summary.json") for name in ("simulation", "historical")} | {"validation": read_artifact(root / "results" / "validation.json")})
        elif path == "/api/competencies":
            self.send_json(200, read_artifact(root / "docs" / "competency_union.json"))
        elif path == "/api/research-v2":
            artifacts = {
                "historical": root / "results" / "v2_historical_summary.json",
                "selection": root / "results" / "v2_selection_summary.json",
                "convex": root / "results" / "v2_convex_summary.json",
                "publication_routes": root / "docs" / "publication_routes.json",
                "protocol": root / "docs" / "v2_protocol.json",
            }
            self.send_json(200, {name: read_artifact(file) for name, file in artifacts.items()})
        elif path in {"/", "/index.html", "/styles.css", "/app.js"}:
            filename = "index.html" if path == "/" else path[1:]
            asset = root / "web" / filename
            if not asset.is_file():
                self.send_json(404, {"error": "Asset not found"})
                return
            mime = {".html": "text/html", ".css": "text/css", ".js": "application/javascript"}[asset.suffix]
            self.send_content(200, asset.read_bytes(), mime + "; charset=utf-8")
        else:
            self.send_json(404, {"error": "Route not found"})

    def do_POST(self):
        if not self.valid_host():
            return
        route = urlsplit(self.path).path
        if route not in {"/api/price", "/api/simulate"}:
            self.send_json(404, {"error": "Route not found"})
            return
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self.send_json(400, {"error": "Transfer-Encoding is not supported"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            self.close_connection = True
            self.send_json(413, {"error": f"Request body must contain 1 to {MAX_BODY} bytes"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json(415, {"error": "Content-Type must be application/json"})
            return
        try:
            data = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
        except (ValueError, UnicodeError):
            self.send_json(400, {"error": "Invalid JSON object"})
            return
        if not COMPUTE_SLOTS.acquire(blocking=False):
            self.send_json(429, {"error": "Two computations are already running; try again shortly"})
            return
        try:
            operation = price_request if route == "/api/price" else simulate_request
            self.send_json(200, operation(data))
        except (ValueError, TypeError, OverflowError, FloatingPointError) as exc:
            self.send_json(422, {"error": str(exc)})
        except ImportError:
            self.send_json(503, {"error": "Numerical core is not available; install the project dependencies"})
        except Exception:
            self.log_error("Numerical request failed")
            self.send_json(500, {"error": "Computation failed; inspect local server logs"})
        finally:
            COMPUTE_SLOTS.release()


def make_server(port=8872, root=ROOT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.root = Path(root)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8872)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    server = make_server(args.port)
    print(f"FinMath Risk Lab: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
