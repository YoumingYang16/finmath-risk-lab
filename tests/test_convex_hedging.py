import numpy as np
import pytest
from risklab.convex_hedging import causal_design,fit_cvar_hedge,evaluate_cvar_hedge
from risklab.advanced_hedging import account_positions,empirical_es
from risklab.paths import simulate_paths
from risklab.pricing import bs_price


def test_linear_program_certificate_and_independent_accounting():
    paths=simulate_paths(32,5,21/252,mu=0,seed=181);premium=bs_price(100,100,21/252,0,.2)
    fit=fit_cvar_hedge(paths,premium,budget=.5,penalty=.03)
    assert fit['success'],fit
    assert abs(fit['duality_gap'])<1e-6
    assert abs(fit['objective_reconciliation_gap'])<1e-6
    assert fit['max_primal_inequality_violation']<1e-7
    assert fit['max_stationarity_residual']<1e-7
    assert fit['train_position_min']>=-1e-7 and fit['train_position_max']<=1+1e-7
    run=evaluate_cvar_hedge(paths,fit,premium)
    assert empirical_es(-run['pnl'])==pytest.approx(fit['train_es'],abs=1e-7)
    base,phi=causal_design(paths)
    baseline=account_positions(paths,base,100,0,21/252,premium,5)
    assert fit['objective']<=empirical_es(-baseline['pnl'])+1e-7


def test_future_does_not_enter_earlier_features():
    a=simulate_paths(15,21,21/252,mu=0,seed=194);b=a.copy();b[:,10:]*=1.4
    aa,ap=causal_design(a);bb,bp=causal_design(b)
    np.testing.assert_array_equal(aa[:,:10],bb[:,:10]);np.testing.assert_array_equal(ap[:,:10],bp[:,:10])


def test_loss_is_convex_in_parameters_with_fees():
    paths=simulate_paths(30,9,21/252,mu=0,seed=61);base,phi=causal_design(paths)
    a=np.array([.01,-.05,.03,.005]);b=np.array([-.04,.03,-.01,.02]);weight=.31
    def losses(theta):return -account_positions(paths,base+phi@theta,100,0,21/252,2.3,5)['pnl']
    assert np.all(losses(weight*a+(1-weight)*b)<=weight*losses(a)+(1-weight)*losses(b)+1e-12)


def test_no_budget_feasible_case_reports_status():
    paths=simulate_paths(15,4,21/252,mu=0,seed=30)
    fit=fit_cvar_hedge(paths,2.3,budget=0,coefficient_bound=1e-8)
    assert not fit['success'] and fit['solver_status']==2
    with pytest.raises(ValueError):evaluate_cvar_hedge(paths,fit,2.3)


@pytest.mark.parametrize('kwargs',[{'alpha':1},{'budget':-1},{'cost_bps':0},{'penalty':-1}])
def test_invalid_objective_parameters(kwargs):
    with pytest.raises(ValueError):fit_cvar_hedge(np.full((15,3),100.),2.3,**kwargs)
