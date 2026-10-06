"""Heston full-truncation Euler with log-Euler spot and visible diagnostics.

Raw variance can become negative. Both drift and diffusion use its positive
part; the raw next state is retained internally, not reset to zero. Reported
variance is the positive part at observation times. Latent variance must not
be supplied to a supposedly observable-information hedge.
"""
from __future__ import annotations

import numpy as np

from .paths import _finite, _positive_integer


def heston_paths(n_paths, steps, horizon, spot=100., mu=0., v0=.04,
                 theta=.04, kappa=2., xi=.3, rho=-.7, substeps=4, seed=1):
    """Return observed prices/variance and full-truncation diagnostics.

    For each fine step: v+=max(v,0); logS += (mu-v+/2)dt+sqrt(v+dt)Zs;
    v += kappa(theta-v+)dt + xi sqrt(v+dt)Zv, corr(Zs,Zv)=rho.
    This is a discretization, not exact Heston simulation. ``mu`` is an
    assumed physical drift; matching a pricing measure requires justification.
    """
    n_paths = _positive_integer(n_paths, 'n_paths')
    steps = _positive_integer(steps, 'steps')
    substeps = _positive_integer(substeps, 'substeps')
    horizon, spot, mu, v0, theta, kappa, xi, rho = [
        _finite(value, name) for value, name in
        [(horizon, 'horizon'), (spot, 'spot'), (mu, 'mu'), (v0, 'v0'),
         (theta, 'theta'), (kappa, 'kappa'), (xi, 'xi'), (rho, 'rho')]]
    if horizon < 0 or spot <= 0 or min(v0, theta, kappa, xi) < 0 or abs(rho) > 1:
        raise ValueError('nonnegative horizon/variance/coefficients, positive spot, |rho|<=1 required')
    fine_steps = steps * substeps
    dt = horizon / fine_steps
    rng = np.random.default_rng(seed)
    log_spot = np.full(n_paths, np.log(spot))
    raw_v = np.full(n_paths, v0)
    prices = np.empty((n_paths, steps + 1))
    variance = np.empty_like(prices)
    prices[:, 0], variance[:, 0] = spot, v0
    negative_updates = 0
    ever_negative = np.zeros(n_paths, dtype=bool)
    minimum_raw = v0
    innovation_scale = np.sqrt(max(0., 1. - rho * rho))
    with np.errstate(over='ignore', invalid='ignore'):
        for j in range(fine_steps):
            v_plus = np.maximum(raw_v, 0.)
            z_spot = rng.standard_normal(n_paths)
            z_orthogonal = rng.standard_normal(n_paths)
            z_variance = rho * z_spot + innovation_scale * z_orthogonal
            diffusion = np.sqrt(v_plus * dt)
            log_spot += (mu - .5 * v_plus) * dt + diffusion * z_spot
            raw_v += kappa * (theta - v_plus) * dt + xi * diffusion * z_variance
            negative = raw_v < 0
            negative_updates += int(np.count_nonzero(negative))
            ever_negative |= negative
            minimum_raw = min(minimum_raw, float(np.min(raw_v)))
            if (j + 1) % substeps == 0:
                column = (j + 1) // substeps
                prices[:, column] = np.exp(log_spot)
                variance[:, column] = np.maximum(raw_v, 0.)
    if (not np.all(np.isfinite(prices)) or np.any(prices <= 0)
            or not np.all(np.isfinite(variance)) or not np.all(np.isfinite(raw_v))):
        raise ValueError('parameters cause nonfinite or nonpositive simulation output')
    return {'prices': prices, 'variance': variance,
            'diagnostics': {'scheme': 'full-truncation Euler variance; log-Euler spot',
                            'fine_steps': fine_steps, 'effective_dt': dt,
                            'negative_raw_updates': negative_updates,
                            'negative_raw_update_fraction': negative_updates / (n_paths * fine_steps),
                            'paths_ever_negative': int(np.count_nonzero(ever_negative)),
                            'minimum_raw_variance': minimum_raw,
                            'feller_condition': bool(2 * kappa * theta >= xi * xi)}}
