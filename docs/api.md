# Local research workbench API

Start from the repository root with `python -m risklab.server --port 8872`, then open `http://127.0.0.1:8872`. The service binds only to IPv4 loopback. It is a local research tool, not a hosted multi-user service. There is no account system, order execution, upload endpoint, arbitrary file access, or server-side write API.

## Routes

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/health` | Availability, version and resource limits |
| GET | `/api/results` | Read-only wrappers for simulation, historical and validation results; each has `status: available/missing/invalid` |
| GET | `/api/competencies` | Read-only `docs/competency_union.json` wrapper, or explicit unavailable state |
| POST | `/api/price` | Actual analytical, CRR and Monte Carlo prices, Greeks, a 49-point analytical price curve, optional implied volatility |
| POST | `/api/simulate` | Actual path simulation, chosen policy and every-step baseline, paired mean P&L difference, histogram, first eight paths and first path ledger |

Only `/`, `/index.html`, `/styles.css` and `/app.js` are served as static assets. Unknown paths, including traversal attempts, return 404.

POST bodies must be JSON objects, with `Content-Type: application/json`, at most 16,384 bytes. Unknown fields are rejected. NaN, infinity, booleans in numeric fields, out-of-range values and fractional integer parameters are rejected. Maximum two numerical requests run concurrently; further requests receive 429. Host and optional Origin headers must match the local port at localhost or 127.0.0.1. Responses have no-store, nosniff, a same-origin content policy and no cross-origin permission. Request bodies are not logged. This is bounded loopback protection, not a production security certification.

## Price request

Defaults: `{"spot":100,"strike":100,"maturity":0.25,"rate":0.03,"vol":0.2,"dividend":0,"kind":"call","steps":256,"n_paths":20000,"seed":42}`.

`kind` is call/put, maturity is years, volatility/rate/dividend are decimal annualized values. CRR steps are 2–1024, Monte Carlo paths 100–100000. An optional `market_price` requests implied volatility inversion and is checked by the pricing core against arbitrage bounds. The analytical chart changes spot while keeping other inputs constant. Vega/rho are per unit change in volatility/rate, not per percentage point; theta is per year. Monte Carlo uses antithetic pair means as independent units and reports its independent unit count and sampling confidence interval. Invalid CRR risk-neutral probabilities are rejected, never silently clipped.

## Simulation request

Defaults: `{"n_paths":500,"steps":63,"horizon":0.25,"spot":100,"strike":100,"rate":0.03,"vol":0.2,"hedge_vol":0.2,"mu":0.03,"seed":42,"model":"gbm","policy":"fixed","every":5,"cost_bps":5,"kind":"call"}`.

Models: `gbm`; `regime` (vol2 default .4, switch_fraction .5); `jump` (jump_intensity 1, jump_mean -.08, jump_std .12). Policies: fixed with `every`, or threshold with `threshold` default .05. Path count 10–3000, steps 2–252, and `n_paths * (steps + 1) <= 400000`. A seed is an integer from 0 through 2^32−1. Model-specific and policy-specific fields are optional; only fields for the selected option are applied.

Both policies receive exactly the same simulated paths and initial Black–Scholes premium based on hedge_vol. Paths use physical drift mu; pricing/cash use rate r. No dividends in hedging. Entry, rebalances and liquidation incur costs; costs are terminalized. The premium is not recalibrated to each policy. P&L is for one short option plus its hedge, loss = −P&L. There is no claim of investment performance. The paired interval is a pointwise t interval across independent simulated paths, not a simultaneous confidence claim.

The interface clearly marks stale displayed output after editing inputs. API calls are synchronous and bounded; output uses real core functions. Experiment artifact views never generate fabricated fallback results. The historical view retains the full JSON for provenance inspection and translates essential schema sections into tables. Downloading the current simulation uses an in-memory browser Blob and does not write to the server.

## Error response

Errors are JSON objects with `error`: 400 malformed JSON, 403 invalid origin/host, 404 route missing, 413 size/length violation, 415 incorrect content type, 422 invalid parameters/numerical domain, 429 compute slots busy, 503 numerical dependencies unavailable. Unexpected failures return a generic 500 without exposing internal paths. Missing result artifacts return 200 with explicit missing status because lack of research evidence is a valid view state.

## Executed product checks

`tests/test_server.py` contains 18 parametrized checks covering real pricing and implied-volatility inversion, deterministic seeds, costs and path consistency, variants, missing/corrupt evidence, resource limits, invalid JSON, origin restrictions and static traversal rejection. Run with `python -m pytest tests/test_server.py`; on a machine with a restricted default temporary directory, pass a new dedicated workspace path as `--basetemp`.

`tests/browser_qa.cjs` exercises a real running service using Playwright. Its 34 checks cover actual pricing and put Greeks, stale-output messages, real simulations, changed seeds and fees, three generating mechanisms, two policies, oversized input, downloadable records, currency switching, all 18 capabilities and 10 official source links, keyboard navigation, five mobile layouts, labeled controls, loading and visible failure. A single intentional HTTP 422 failure probe tests error presentation; it is distinguished from unexpected JavaScript errors. A developer with Node and Playwright installed can run `node tests/browser_qa.cjs`; environment variables are `RISKLAB_URL`, `RISKLAB_QA_DIR` and `RISKLAB_BROWSER_CHANNEL` (default `msedge`; choose an installed Playwright channel). Numerical tests do not require Node or a browser.

Final visual review covered five desktop and five mobile states. Tables scroll within their own containers; navigation is keyboard accessible; graphs retain labels and SVG descriptions. This inspection and the automated checks are not user research or a formal accessibility certification. The historical page reads the stored model and strategy results rather than recomputing model selection in the browser, preserving the locked evaluation protocol.
