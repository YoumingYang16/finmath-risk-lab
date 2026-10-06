"""European Black--Scholes, CRR and Monte Carlo reference calculations.

Rates and volatilities are decimals, maturity is in years, and dividends are a
continuous yield. Greeks are per one unit of the corresponding input (vega per
1.00 volatility, rho per 1.00 rate); theta is per year of calendar-time passage.
At expiry, reported gamma/vega/theta/rho are zero. At a deterministic payoff
kink delta uses the symmetric half-delta convention and gamma is reported as
zero, *not* an assertion that a classical derivative exists at that kink.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr
from scipy.stats import t as student_t


def _kind(kind):
    if kind not in {"call", "put"}:
        raise ValueError("kind must be 'call' or 'put'")
    return 1.0 if kind == "call" else -1.0


def _inputs(spot, strike, maturity, rate, vol, dividend):
    arrays = np.broadcast_arrays(*[np.asarray(x, dtype=float) for x in
                                  (spot, strike, maturity, rate, vol, dividend)])
    if not all(np.all(np.isfinite(x)) for x in arrays):
        raise ValueError("pricing inputs must be finite")
    s, k, tau, r, sigma, q = arrays
    if np.any(s <= 0) or np.any(k <= 0):
        raise ValueError("spot and strike must be strictly positive")
    if np.any(tau < 0) or np.any(sigma < 0):
        raise ValueError("maturity and volatility must be nonnegative")
    return s, k, tau, r, sigma, q


def _finish(value):
    result = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(result)):
        raise ValueError("inputs cause non-finite numerical output")
    return float(result) if result.ndim == 0 else result


def _terms(spot, strike, maturity, rate, vol, dividend):
    s, k, tau, r, sigma, q = _inputs(spot, strike, maturity, rate, vol, dividend)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        ds, dk = s * np.exp(-q * tau), k * np.exp(-r * tau)
        active = (tau > 0) & (sigma > 0)
        root = np.sqrt(tau)
        denom = np.where(active, sigma * root, 1.0)
        d1 = (np.log(s / k) + (r - q + 0.5 * sigma ** 2) * tau) / denom
        d2 = d1 - sigma * root
    if not all(np.all(np.isfinite(x)) for x in (ds, dk, d1, d2)):
        raise ValueError("inputs exceed supported numerical range")
    return s, k, tau, r, sigma, q, ds, dk, active, root, d1, d2


def bs_price(spot, strike, maturity, rate, vol, kind="call", dividend=0.0):
    """Broadcasting Black--Scholes price, including expiry and zero volatility."""
    sign = _kind(kind)
    *_, ds, dk, active, root, d1, d2 = _terms(spot, strike, maturity, rate, vol, dividend)
    regular = sign * (ds * ndtr(sign * d1) - dk * ndtr(sign * d2))
    deterministic = np.maximum(sign * (ds - dk), 0.0)
    return _finish(np.where(active, np.maximum(regular, 0.0), deterministic))


def bs_delta(spot, strike, maturity, rate, vol, kind="call", dividend=0.0):
    """Broadcasting spot delta; deterministic ATM uses a half-delta convention."""
    sign = _kind(kind)
    _, _, tau, _, _, q, ds, dk, active, _, d1, _ = _terms(
        spot, strike, maturity, rate, vol, dividend)
    discount = np.exp(-q * tau)
    # Strict equality gives a reproducible convention without blurring the kink.
    indicator = (ds > dk).astype(float) + 0.5 * (ds == dk)
    deterministic = discount * (indicator if sign > 0 else indicator - 1.0)
    regular = sign * discount * ndtr(sign * d1)
    return _finish(np.where(active, regular, deterministic))


def bs_greeks(spot, strike, maturity, rate, vol, kind="call", dividend=0.0):
    """Return delta/gamma/vega/theta/rho in raw decimal-input units.

    Divide vega and rho by 100 for a one percentage-point change. At sigma=0
    vega is the right derivative; at the forward-ATM kink it is nonzero.
    """
    sign = _kind(kind)
    s, k, tau, r, sigma, q, ds, dk, active, root, d1, d2 = _terms(
        spot, strike, maturity, rate, vol, dividend)
    phi = np.exp(-0.5 * d1 ** 2) / np.sqrt(2.0 * np.pi)
    discount = np.exp(-q * tau)
    safe_root = np.where(active, root, 1.0)
    safe_sigma = np.where(active, sigma, 1.0)
    gamma = np.where(active, discount * phi / (s * safe_sigma * safe_root), 0.0)
    vega_zero = np.where((tau > 0) & (ds == dk), ds * root / np.sqrt(2 * np.pi), 0.0)
    vega = np.where(active, ds * phi * root, vega_zero)
    theta_regular = (-ds * phi * sigma / (2.0 * safe_root)
                     + sign * q * ds * ndtr(sign * d1)
                     - sign * r * dk * ndtr(sign * d2))
    indicator = (sign * (ds - dk) > 0).astype(float) + 0.5 * (ds == dk)
    theta_zero = sign * (q * ds - r * dk) * indicator
    theta = np.where(tau == 0, 0.0, np.where(active, theta_regular, theta_zero))
    rho = np.where(active, sign * tau * dk * ndtr(sign * d2),
                   sign * tau * dk * indicator)
    return {"delta": bs_delta(s, k, tau, r, sigma, kind, q),
            "gamma": _finish(gamma), "vega": _finish(vega),
            "theta": _finish(theta), "rho": _finish(rho)}


def crr_price(spot, strike, maturity, rate, vol, steps=256, kind="call",
              dividend=0.0, american=False):
    """Cox--Ross--Rubinstein dynamic-programming price (scalar parameters).

    An American option may exercise on the supplied grid. Invalid risk-neutral
    probabilities are rejected rather than clamped; increase steps if needed.
    The zero-volatility branch maximizes discounted deterministic exercise value.
    """
    sign = _kind(kind)
    values = _inputs(spot, strike, maturity, rate, vol, dividend)
    if any(x.ndim != 0 for x in values):
        raise ValueError("CRR accepts scalar parameters only")
    s, k, tau, r, sigma, q = map(float, values)
    if isinstance(steps, (bool, np.bool_)) or not isinstance(steps, (int, np.integer)) or not 1 <= steps <= 20000:
        raise ValueError("steps must be an integer between 1 and 20000")
    if not isinstance(american, (bool, np.bool_)):
        raise ValueError("american must be boolean")
    if tau == 0:
        return max(sign * (s - k), 0.0)
    if sigma == 0:
        times = np.linspace(0.0, tau, steps + 1) if american else np.array([tau])
        with np.errstate(over="ignore", invalid="ignore"):
            exercise_values = np.maximum(sign * (s * np.exp(-q * times) - k * np.exp(-r * times)), 0.0)
        return _finish(np.max(exercise_values))
    dt = tau / steps
    with np.errstate(over="ignore", invalid="ignore"):
        log_u = sigma * np.sqrt(dt)
        u, d, growth = np.exp(log_u), np.exp(-log_u), np.exp((r - q) * dt)
        probability = (growth - d) / (u - d)
    if not np.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("invalid CRR risk-neutral probability; use a finer grid")
    discount = np.exp(-r * dt)
    with np.errstate(over="ignore", invalid="ignore"):
        stocks = s * np.exp(log_u * (2 * np.arange(steps + 1) - steps))
        prices = np.maximum(sign * (stocks - k), 0.0)
        for level in range(steps - 1, -1, -1):
            prices = discount * ((1 - probability) * prices[:-1] + probability * prices[1:])
            if american:
                exercise_stocks = s * np.exp(log_u * (2 * np.arange(level + 1) - level))
                prices = np.maximum(prices, np.maximum(sign * (exercise_stocks - k), 0.0))
    return _finish(prices[0])


def mc_price(spot, strike, maturity, rate, vol, n_paths=10000, seed=1,
             kind="call", dividend=0.0, antithetic=True):
    """Risk-neutral terminal-payoff Monte Carlo with a pointwise Student-t CI.

    With antithetics, n_paths must be even and >=4; the *pair averages*, not
    individual paths, are the independent observations used for the standard
    error and confidence interval. The CI describes simulation error only.
    """
    sign = _kind(kind)
    values = _inputs(spot, strike, maturity, rate, vol, dividend)
    if any(x.ndim != 0 for x in values):
        raise ValueError("Monte Carlo accepts scalar pricing parameters")
    s, k, tau, r, sigma, q = map(float, values)
    if isinstance(n_paths, (bool, np.bool_)) or not isinstance(n_paths, (int, np.integer)) or n_paths < 2:
        raise ValueError("n_paths must be an integer >=2")
    if not isinstance(antithetic, (bool, np.bool_)):
        raise ValueError("antithetic must be boolean")
    if antithetic and (n_paths % 2 or n_paths < 4):
        raise ValueError("antithetic simulation requires even n_paths >=4")
    units = n_paths // 2 if antithetic else n_paths
    if tau == 0 or sigma == 0:
        exact = bs_price(s, k, tau, r, sigma, kind, q)
        return {"price": exact, "standard_error": 0.0, "ci_low": exact,
                "ci_high": exact, "n_paths": int(n_paths), "independent_units": int(units)}
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(units)
    with np.errstate(over="ignore", invalid="ignore"):
        terminal = s * np.exp((r - q - 0.5 * sigma ** 2) * tau + sigma * np.sqrt(tau) * z)
        observations = np.exp(-r * tau) * np.maximum(sign * (terminal - k), 0.0)
        if antithetic:
            opposite = s * np.exp((r - q - 0.5 * sigma ** 2) * tau - sigma * np.sqrt(tau) * z)
            observations = 0.5 * (observations + np.exp(-r * tau) * np.maximum(sign * (opposite - k), 0.0))
    _finish(observations)
    price = float(np.mean(observations))
    standard_error = float(np.std(observations, ddof=1) / np.sqrt(units))
    half = float(student_t.ppf(0.975, units - 1) * standard_error)
    return {"price": price, "standard_error": standard_error, "ci_low": price - half,
            "ci_high": price + half, "n_paths": int(n_paths), "independent_units": int(units)}


def implied_volatility(price, spot, strike, maturity, rate, kind="call", dividend=0.0):
    """Invert a European price; expiry and the infinite-volatility bound reject.

    A quote at the deterministic lower bound maps to zero volatility. A quote
    at the upper bound has no finite implied volatility and is not returned as
    an arbitrary large number.
    """
    sign = _kind(kind)
    values = _inputs(spot, strike, maturity, rate, 0.0, dividend)
    if any(x.ndim != 0 for x in values) or np.ndim(price) != 0:
        raise ValueError("implied volatility accepts scalar parameters")
    s, k, tau, r, _, q = map(float, values)
    quote = float(price)
    if not np.isfinite(quote) or quote < 0:
        raise ValueError("price must be finite and nonnegative")
    if tau == 0:
        raise ValueError("implied volatility is not identifiable at expiry")
    ds, dk = s * np.exp(-q * tau), k * np.exp(-r * tau)
    lower = max(sign * (ds - dk), 0.0)
    upper = ds if sign > 0 else dk
    if not all(np.isfinite([ds, dk, lower, upper])):
        raise ValueError("inputs exceed supported numerical range")
    if quote < lower or quote > upper:
        raise ValueError("price violates European no-arbitrage bounds")
    if quote >= upper:
        raise ValueError("upper bound has no finite implied volatility")
    if quote == lower:
        return 0.0
    objective = lambda sigma: bs_price(s, k, tau, r, sigma, kind, q) - quote
    high = 1.0
    while objective(high) < 0 and high < 1024.0:
        high *= 2
    if objective(high) < 0:
        raise ValueError("no finite volatility root in supported numerical range")
    return float(brentq(objective, 0.0, high, xtol=1e-12, rtol=1e-12))
