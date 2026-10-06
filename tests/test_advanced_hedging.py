import numpy as np
import pytest
from risklab.advanced_hedging import account_positions,band_hedge,empirical_es,risk_summary
from risklab.hedging import hedge_paths
from risklab.paths import simulate_paths
from risklab.pricing import bs_delta


def test_zero_band_equals_daily_with_financing():
    paths=simulate_paths(31,21,.1,seed=22)
    a=band_hedge(paths,100,.03,.1,.2,3,{'kind':'band','width':0},5)
    b=hedge_paths(paths,100,.03,.1,.2,3,cost_bps=5)
    np.testing.assert_allclose(a['pnl'],b['pnl'],atol=2e-12)
    np.testing.assert_allclose(a['cost'],b['cost'],atol=1e-12)


def test_boundary_trade_is_not_reset_to_center():
    paths=np.array([[100.,110.,111.]])
    result=band_hedge(paths,100,0,.1,.2,3,{'kind':'band','width':.05},5)
    desired=bs_delta(110,100,.05,0,.2)
    assert result['positions'][0,1]==pytest.approx(desired-.05)
    assert result['ledger'][-1]['position']==0
    assert result['ledger'][-1]['trade']<0


def test_large_band_has_no_interior_trades():
    paths=simulate_paths(9,12,.2,seed=3)
    result=band_hedge(paths,100,0,.2,.2,4,{'kind':'band','width':2},5)
    assert np.all(result['trades']==2)


def test_cost_terminal_wealth_identity_and_hand_gain():
    paths=np.array([[100.,104.,102.],[100.,98.,97.]])
    positions=np.array([[.4,.8],[.5,.1]])
    a=account_positions(paths,positions,100,0,.1,4,7)
    b=account_positions(paths,positions,100,0,.1,4,0)
    manual=4+np.sum(positions*np.diff(paths,axis=1),axis=1)-np.maximum(paths[:,-1]-100,0)
    np.testing.assert_allclose(b['pnl'],manual,atol=2e-14)
    np.testing.assert_allclose(b['pnl']-a['pnl'],a['cost'],atol=2e-14)


def test_past_positions_unchanged_after_future_perturbation():
    paths=simulate_paths(7,21,.1,seed=9);mut=paths.copy();mut[:,12:]*=1.4
    a=band_hedge(paths,100,0,.1,.2,3,{'kind':'band','width':.05})
    b=band_hedge(mut,100,0,.1,.2,3,{'kind':'band','width':.05})
    np.testing.assert_array_equal(a['positions'][:,:12],b['positions'][:,:12])


def test_risk_decomposition_and_fractional_es():
    pnl=np.arange(-17,6,dtype=float);m=risk_summary(pnl,np.ones_like(pnl))
    assert m['mse']==pytest.approx(m['variance_pnl']+m['bias_squared'])
    assert empirical_es(-pnl,.9)==pytest.approx((17+16+.3*15)/2.3)


@pytest.mark.parametrize('width',[-1,np.nan,np.inf])
def test_bad_band(width):
    with pytest.raises(ValueError):band_hedge(np.array([[100.,101.]]),100,0,.1,.2,3,{'kind':'band','width':width})
