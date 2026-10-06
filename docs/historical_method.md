# Historical FX study

## Purpose and evidence boundary

This is an executed study of finite-data variance forecasting and hypothetical option hedging on historical reference-rate paths. It is not a trading service, a realized trading return study, or a validation of actual FX option-market prices. The source is the European Central Bank (ECB); USD and JPY are both quoted as currency units per EUR and are analyzed separately. They share a denominator and are not independent replications.

The research question is whether a more accurate one-observation variance forecast also improves a cost-aware, discrete hedge. A simple learned model is compared against explicit baselines. Negative or inconclusive findings remain in the release.

## Data provenance and quality

- Official dataset: [ECB euro foreign exchange reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).
- Official download: <https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip>.
- Reuse terms: [ECB disclaimer and copyright](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html).
- `data/source_manifest.json` records retrieval time, source URLs, units, processing, reuse summary, file sizes and SHA-256 hashes.
- `data/ecb_reference_snapshot.zip` is the original downloaded snapshot; `data/ecb_usd_jpy.csv` contains the selected and date-sorted USD/JPY columns through the fixed endpoint **2025-12-31**.
- `data/data_quality.json` records duplicate, missing, nonpositive and date-gap checks. There are 6,913 published dates from 1999-01-04 through 2025-12-31 in this frozen selection. No rates are filled, winsorized or corrected.

ECB permits reuse subject to attribution, accurate reproduction and disclosure of modifications, with further conditions for sold information and named-author publications. The derived returns, models and normalized hedge experiments here are our transformations, not ECB analyses or endorsements. ECB describes these reference rates as informational and discourages transaction use.

The download is a present-day historical snapshot, not an archive of point-in-time vintages. Chronological code does not eliminate unknown historical revisions. Holidays and weekends create unequal calendar gaps; we do not manufacture missing observations. “Daily” below means successive published observations. Annualization at 252 observations per year is a modeling convention.

## Causal alignment and temporal splits

For rate S_t, define r_t = log(S_t/S_(t-1)) and y_(t+1) = r_(t+1)^2. A decision row at t includes information through S_t, then forecasts y_(t+1). **The target date determines the split**, so the last 2016 decision that predicts the first 2017 observation belongs to validation and cannot train the model.

| Role | Target dates | Rows per currency | Permitted use |
|---|---|---:|---|
| Warm-up | 1999-2004 | Not scored | Initialize causal features and filters |
| Training | 2005-2016 | 3,073 | Fit scaler, regression, mean-ratio correction and constant baseline |
| Validation | 2017-2020 | 1,022 | Select forecast hyperparameters/family and threshold policy |
| Locked chronological test | 2021-2025 | 1,281 | Final evaluation only |

No random split, whole-sample scaler, future-centered window, test-dependent refit or test-driven parameter selection is used. Model coefficients remain frozen after 2016; rolling features and EWMA states update with observations that have already arrived. This deliberately simple frozen-model experiment does not claim adaptive refitting.

The selected design and grids were implemented before the first test run. “Locked” describes this source-level procedure; the study was not externally preregistered. Changes to algorithms after reading results would require a new exploratory-study label or new untouched data, rather than pretending the old test remained untouched.

## Features and forecasting models

The seven regression features at t are log trailing mean squared returns over 1, 5, 21, 63 and 126 observations; the trailing five-return sum; and the negative-return fraction over 21 observations. Every window ends at t. Standardization uses training rows only.

The four reported forecast families are:

1. **Training constant**: the mean squared target return in the 2005-2016 training period, frozen thereafter.
2. **Rolling63**: the trailing 63-return mean of squared returns; window length fixed by design.
3. **EWMA**: h_(t+1) = lambda h_t + (1-lambda) r_t^2. Initialization uses the first available squared return. Candidate lambda values are 0.94, 0.97 and 0.99; mean validation QLIKE selects one.
4. **Log-variance Ridge**: training response log(max(y, 1e-10)); standardized features; L2 penalty alpha selected from 0.1, 1, 10 and 100 by validation QLIKE. The scikit-learn Ridge objective is residual squared error plus alpha times coefficient squared norm. Predictions are exponentiated and multiplied by c = mean_training(y / exp(fitted_log)). This training-only multiplicative calibration is a modeling approximation, not a proof of conditionally unbiased variance prediction. It is not estimated from validation or test residuals.

Strictly positive variance outputs are bounded at [1e-10, 0.04] per observation as prespecified numerical safeguards. The stored results record **zero clipped forecast outputs** for all four families and both currencies. The variance proxy is an uncentered conditional second moment; its interpretation as conditional variance assumes negligible conditional mean. It is noisy even under that approximation.

Hyperparameters, scaler moments, regression coefficients, intercept and calibration are included in `results/historical_summary.json`, making the fitted model inspectable without unsafe binary model loading. The implementation uses scikit-learn's documented [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html).

## Forecast losses and uncertainty

QLIKE is mean(log(h) + y/h), with h > 0. Target-only terms are omitted; therefore values can be negative and should only be compared on the same target observations. MSE is mean((y-h)^2) in unannualized squared-variance units. Lower values are better for both. Neither a lower proxy loss nor a small raw difference guarantees a better hedge.

The relevance of proxy choice and loss functions follows the discussion in Andrew J. Patton (2011), *Volatility forecast comparison using imperfect volatility proxies*, Journal of Econometrics 160(1), 246-256, [DOI 10.1016/j.jeconom.2010.03.034](https://doi.org/10.1016/j.jeconom.2010.03.034), [author-hosted paper](https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf). We use its motivation for proxy-aware evaluation; our empirical data need not satisfy all of its theoretical conditions.

We compare each candidate to Rolling63 using **paired loss differences on the same dates**. A fixed-length, overlapping, noncircular moving-block bootstrap draws starts uniformly from 0 to n-L, concatenates ceiling(n/L) blocks and truncates to n. Two thousand draws give percentile 95% intervals. Block lengths 5, 21 and 63 are all reported, not chosen by favorable results. This is not the random-length stationary bootstrap. See Hans R. Künsch (1989), *The Jackknife and the Bootstrap for General Stationary Observations*, Annals of Statistics 17(3), 1217-1241, [DOI 10.1214/aos/1176347265](https://doi.org/10.1214/aos/1176347265).

These are pointwise descriptive intervals conditional on the selected methods. They assume approximately stationary, weakly dependent sampling behavior, exclude model-selection uncertainty, and carry no simultaneous-coverage claim across all comparisons. The dataset contains possible structural changes. Year-by-year test results are therefore retained alongside aggregate scores, but are not used to choose parameters.

## Hypothetical option experiment

Each currency and temporal split is divided into complete, nonoverlapping **21-return** episodes, requiring 22 quotes. Adjacent episodes share only a boundary quote, not returns. Each path is normalized to S_0 = 100, with an ATM European call K = 100 and horizon 21/252. There are **48 validation episodes and 60 test episodes per currency**. Thirteen trailing validation returns and twenty trailing test returns do not make a complete episode and are excluded. Test episodes start on 2021-01-04 and the last ends on 2025-12-01; the forecasting evaluation still extends through 2025-12-31.

Domestic and foreign carry are both fixed at zero (r = q = 0). This is a normalized zero-carry path experiment, not an empirical calibration of real FX options. There are no observed option premiums. Every strategy on an episode receives the **same** Black-Scholes premium calculated from the starting Rolling63 volatility. The premium never uses future episode returns and is never adjusted to favor a strategy.

At decision t, the forecast h_(t+1) is converted to annualized volatility sqrt(252 h_(t+1)) and used as a flat remaining-life delta input. This extrapolation is a simplifying control rule, not a forecast of the full term structure. Each entry, rebalance and exit is charged cost_bps / 10000 times absolute traded notional. The fee scenarios are 0, 5 and 10 basis points and are stylized assumptions, not estimates of actual spreads. The cash ledger has no outside cash injection, default stop, margin constraint or borrowing spread.

Seven strategies are reported:

- Starting Rolling63 volatility frozen for the episode, rebalance every observation.
- Dynamic Rolling63, dynamic selected EWMA, and dynamic selected Ridge, each rebalanced every observation.
- Validation-selected forecast family with every-observation, every-five-observation, or threshold rebalancing.

The selected family is EWMA in both currencies, so `selected_daily` deliberately duplicates `ewma_daily`; it is a policy comparator, not an additional independent model. A threshold trades only when the absolute difference between desired and held delta reaches the threshold. Entry and expiry liquidation always occur.

Threshold candidates 0.025, 0.05, 0.10, 0.15 and 0.20 are evaluated **only on validation**, at 5 basis points. We select minimum validation net-P&L RMSE among candidates whose mean validation cost is at most 0.12 units per 100 initial spot. If none were feasible, the prespecified fallback would select minimum mean cost and report infeasibility. This is a validation budget criterion, not a hard cap on every episode or a guarantee for the test sample. The selected threshold is then used unchanged at all three test cost assumptions.

Net RMSE = sqrt(mean(net terminal P&L squared)). Gross replication RMSE adds terminalized fees back before taking RMSE, separating replication and fee effects. Loss is minus net P&L. VaR95 uses a linear empirical quantile; ES95 uses the upper 5% empirical tail with fractional boundary weighting. With only 60 test episodes, this tail rests on roughly three observations and is fragile. Paired episode cost and squared-net-P&L differences use the same moving-block procedure with block lengths 1, 3 and 6. Nonoverlap does not imply independent episodes.

The reference quote is assumed observable and usable for the hypothetical immediate rebalance. Its real publication delay, executability, intraday paths and bid-ask spread are not represented. Thus even a positive modeled P&L would not establish an achievable profit.

## Executed findings

Validation selects EWMA lambda = 0.97 for both currencies. Selected Ridge alpha is 100 for USD and 0.1 for JPY. The selected threshold is 0.10 for USD and 0.05 for JPY. These choices are frozen for test.

| Currency | Test QLIKE Rolling63 | EWMA | Ridge | Ridge minus Rolling63 95% interval at block 21 |
|---|---:|---:|---:|---|
| USD | -9.779225 | -9.782140 | -9.783746 | -0.004521 [-0.027194, 0.013618] |
| JPY | -9.398012 | -9.436722 | -9.468054 | -0.070042 [-0.129258, -0.022762] |

Although Ridge is the lowest of these test QLIKE point estimates, the validation-selected operational family remains EWMA. We do not retroactively replace it. USD provides no clear loss-difference evidence from this interval; JPY shows a lower QLIKE for Ridge under the stated pointwise bootstrap approximation. Block-length sensitivity is available in full in the JSON.

At 5 basis points, USD selected-daily net RMSE is 0.317515 with mean cost 0.114798; its threshold version lowers mean cost to 0.096046 but raises net RMSE to 0.337122. JPY selected-daily net RMSE is 0.425496 with mean cost 0.126016; its threshold version gives 0.424957 and 0.117697. The chosen thresholds lower observed costs in both series but do not establish a universal risk improvement. The relevant three-episode-block squared-P&L intervals include zero for both currencies.

JPY Ridge daily net RMSE is 0.419217 versus Rolling63 daily 0.424266, yet their squared-net-P&L difference interval includes zero [-0.017831, 0.007734]. Better forecasting evidence is therefore not automatically equivalent to a clearly better downstream hedge. The limited episode sample is part of the finding, not a reason to omit uncertainty.

## Files and reproduction

From the project root with dependencies installed:

```text
python scripts/fetch_ecb.py
python scripts/run_historical.py
python -m pytest tests/test_historical.py
```

The first command reuses the archived snapshot unless `--refresh` is explicitly passed. A refresh changes source provenance and requires regenerated results. The runner verifies hashes before any calculation and writes JSON with `allow_nan=False`.

- `results/historical_summary.json`: executed protocol, fitted parameters, test/validation metrics, all block-length intervals, caveats, software versions and file hashes.
- `results/historical_forecasts.csv`: 10,752 decision rows across two currencies, including clearly marked in-sample training rows. Each row contains decision date, next target date, quote, observed return, next squared-return target and all forecasts.
- `results/historical_episodes.csv`: 4,536 currency/split/episode/strategy/cost rows with common premium, net/gross P&L, cost, turnover and trade count. These rows are not 4,536 independent episodes.
- `results/historical_ledger.csv`: 924 step-level records, covering the first test episode for each currency, strategy and cost assumption.

Tests perturb future quotes to ensure earlier features and validation-selected models remain unchanged, check year-boundary target alignment, validate filter recursion, verify episode information timing and common-premium inputs, test budget selection and bootstrap behavior, and verify the frozen ECB source hashes. Core accounting tests independently validate the hedge engine used here.
