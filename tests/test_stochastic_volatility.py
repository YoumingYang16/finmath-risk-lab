import numpy as np
import pytest

from risklab.stochastic_volatility import heston_paths


def test_reproducible_positive_and_shape():
    a = heston_paths(200, 21, 21 / 252, seed=45)
    b = heston_paths(200, 21, 21 / 252, seed=45)
    assert a['prices'].shape == (200, 22)
    np.testing.assert_array_equal(a['prices'], b['prices'])
    assert np.all(a['prices'] > 0) and np.all(a['variance'] >= 0)
    assert a['diagnostics']['effective_dt'] == pytest.approx(1 / 1008)


def test_zero_diffusion_variance_constant_and_spot_moments():
    run = heston_paths(80000, 2, .1, xi=0, rho=1, substeps=1, seed=4, mu=.03)
    np.testing.assert_allclose(run['variance'], .04)
    terminal = run['prices'][:, -1]
    exact_mean = 100 * np.exp(.03 * .1)
    se = terminal.std(ddof=1) / np.sqrt(len(terminal))
    assert abs(terminal.mean() - exact_mean) < 5 * se
    log_returns = np.log(terminal / 100)
    assert abs(log_returns.var() - .04 * .1) < .0001


def test_variance_mean_and_stock_martingale_fine_grid():
    run = heston_paths(50000, 12, .25, substeps=4, seed=943, v0=.09, theta=.04)
    v = run['variance'][:, -1]
    exact = .04 + (.09 - .04) * np.exp(-2 * .25)
    # A finite-step weak approximation: tolerance includes discretization.
    assert abs(v.mean() - exact) < .001
    s = run['prices'][:, -1]
    assert abs(s.mean() - 100) < 5 * s.std(ddof=1) / np.sqrt(len(s))


def test_zero_variance_deterministic_and_zero_horizon():
    run = heston_paths(3, 4, 1., v0=0, theta=0, xi=0, mu=.02)
    np.testing.assert_allclose(run['prices'], np.broadcast_to(100 * np.exp(.02 * np.arange(5) / 4), (3, 5)))
    assert np.all(run['variance'] == 0)
    flat = heston_paths(3, 4, 0)
    np.testing.assert_allclose(flat['prices'], 100)


def test_negative_raw_variance_is_diagnosed_not_hidden():
    run = heston_paths(500, 8, 1, v0=.001, theta=.001, kappa=.1, xi=2, substeps=1, seed=3)
    assert run['diagnostics']['negative_raw_updates'] > 0
    assert run['diagnostics']['minimum_raw_variance'] < 0
    assert not run['diagnostics']['feller_condition']
    assert np.all(run['variance'] >= 0)


@pytest.mark.parametrize('kwargs', [{'n_paths':True}, {'steps':0}, {'substeps':0}, {'rho':1.1},
                                    {'theta':-.1}, {'spot':0}, {'xi':np.nan}, {'horizon':-1}])
def test_invalid_inputs(kwargs):
    params = {'n_paths':3, 'steps':5, 'horizon':.1, **kwargs}
    with pytest.raises(ValueError):
        heston_paths(**params)
