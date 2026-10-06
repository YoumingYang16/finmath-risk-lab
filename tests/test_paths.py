import numpy as np
import pytest

from risklab.paths import simulate_paths


@pytest.mark.parametrize("model", ["gbm","regime","jump"])
def test_paths_shape_positive_and_reproducible(model):
    first = simulate_paths(100,20,.5,seed=17,model=model)
    assert first.shape == (100,21)
    assert np.all(first > 0)
    assert np.all(first[:,0] == 100)
    np.testing.assert_array_equal(first, simulate_paths(100,20,.5,seed=17,model=model))


def test_zero_volatility_is_exact_deterministic_growth():
    result = simulate_paths(3,12,1,vol=0,mu=.07)
    expected = 100*np.exp(.07*np.arange(13)/12)
    np.testing.assert_allclose(result, np.broadcast_to(expected,result.shape), rtol=1e-14)
    np.testing.assert_array_equal(simulate_paths(3,12,0), np.full((3,13),100.))


def test_regime_switch_changes_only_declared_later_intervals():
    baseline = simulate_paths(200,10,1,vol=.2,seed=921)
    regime = simulate_paths(200,10,1,vol=.2,seed=921,model="regime",vol2=.6,switch_fraction=.5)
    np.testing.assert_array_equal(baseline[:,:6],regime[:,:6])
    assert not np.array_equal(baseline[:,6:],regime[:,6:])


def test_compensated_jumps_preserve_expected_growth_statistically():
    terminal = simulate_paths(100000,4,1,vol=.1,mu=.04,seed=281,model="jump",
                              jump_intensity=2,jump_mean=-.15,jump_std=.15)[:,-1]
    exact = 100*np.exp(.04)
    assert abs(terminal.mean()-exact) < 4*terminal.std(ddof=1)/np.sqrt(terminal.size)


def test_zero_intensity_jump_equals_gbm_for_same_seed():
    np.testing.assert_array_equal(simulate_paths(8,12,1,seed=5),
                                  simulate_paths(8,12,1,seed=5,model="jump",jump_intensity=0))


@pytest.mark.parametrize("override", [dict(n_paths=0),dict(steps=True),dict(horizon=-1),
    dict(vol=np.nan),dict(mu=np.inf),dict(spot=0),dict(model="unknown"),
    dict(model="regime",switch_fraction=1.1),dict(model="regime",vol2=-1),
    dict(model="jump",jump_intensity=-1),dict(model="jump",jump_std=-1),dict(unknown=3)])
def test_invalid_path_inputs(override):
    arguments = dict(n_paths=5,steps=12,horizon=1)
    arguments.update(override)
    with pytest.raises(ValueError):
        simulate_paths(**arguments)
