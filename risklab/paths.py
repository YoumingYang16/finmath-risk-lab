"""Reproducible paths under explicitly stated data-generating mechanisms.

``mu`` is the expected proportional growth rate, not automatically a risk-free
rate. Use mu=r for risk-neutral GBM pricing with zero dividends; simulations of
physical outcomes may use another declared drift. The regime model is one
deterministic volatility change, not a fitted hidden-Markov model. Merton jumps
are compensated so the expected growth remains mu under the supplied measure.
"""

from __future__ import annotations

import numpy as np


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _finite(value, name):
    if np.ndim(value) != 0:
        raise ValueError(f"{name} must be scalar")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def simulate_paths(n_paths, steps, horizon, spot=100.0, vol=0.2, mu=0.03,
                   seed=1, model="gbm", **kwargs):
    """Return positive prices with shape (n_paths, steps+1).

    ``regime`` options: vol2 (default 0.4), switch_fraction (default 0.5).
    ``jump`` options: jump_intensity (annual, default 1), jump_mean (mean log
    jump, default -0.1), jump_std (log jump standard deviation, default 0.15).
    A regime switch occurs at the first grid interval whose start is at or
    beyond switch_fraction of the horizon. Inputs causing overflow/underflow
    are rejected instead of returning unusable nonfinite or zero prices.
    """
    n_paths = _positive_integer(n_paths, "n_paths")
    steps = _positive_integer(steps, "steps")
    horizon, spot, vol, mu = [_finite(v, name) for v, name in
                             [(horizon, "horizon"), (spot, "spot"), (vol, "vol"), (mu, "mu")]]
    if horizon < 0 or spot <= 0 or vol < 0:
        raise ValueError("horizon/vol must be nonnegative and spot strictly positive")
    if model not in {"gbm", "regime", "jump"}:
        raise ValueError("model must be gbm, regime, or jump")
    allowed = {"gbm": set(), "regime": {"vol2", "switch_fraction"},
               "jump": {"jump_intensity", "jump_mean", "jump_std"}}[model]
    if set(kwargs) - allowed:
        raise ValueError(f"unsupported {model} parameters: {sorted(set(kwargs) - allowed)}")
    dt = horizon / steps
    rng = np.random.default_rng(seed)
    sigma = np.full(steps, vol)
    if model == "regime":
        vol2 = _finite(kwargs.get("vol2", 0.4), "vol2")
        switch = _finite(kwargs.get("switch_fraction", 0.5), "switch_fraction")
        if vol2 < 0 or not 0 <= switch <= 1:
            raise ValueError("vol2 must be nonnegative; switch_fraction must be in [0,1]")
        sigma = np.where(np.arange(steps) / steps >= switch, vol2, vol)
    with np.errstate(over="ignore", invalid="ignore"):
        increments = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * rng.standard_normal((n_paths, steps))
        if model == "jump":
            intensity = _finite(kwargs.get("jump_intensity", 1.0), "jump_intensity")
            mean = _finite(kwargs.get("jump_mean", -0.1), "jump_mean")
            std = _finite(kwargs.get("jump_std", 0.15), "jump_std")
            if intensity < 0 or std < 0:
                raise ValueError("jump_intensity and jump_std must be nonnegative")
            compensation = np.expm1(mean + 0.5 * std ** 2)
            if not np.isfinite(compensation) or not np.isfinite(intensity * dt):
                raise ValueError("jump parameters exceed supported numerical range")
            counts = rng.poisson(intensity * dt, size=(n_paths, steps))
            jumps = mean * counts + std * np.sqrt(counts) * rng.standard_normal((n_paths, steps))
            increments += jumps - intensity * compensation * dt
        result = np.empty((n_paths, steps + 1), dtype=float)
        result[:, 0] = spot
        result[:, 1:] = spot * np.exp(np.cumsum(increments, axis=1))
    if not np.all(np.isfinite(result)) or np.any(result <= 0):
        raise ValueError("path parameters cause nonfinite or nonpositive prices")
    return result
