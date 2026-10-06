import numpy as np
import pytest

from risklab.hedging import hedge_paths
from risklab.paths import simulate_paths
from risklab.pricing import bs_price


def test_independent_one_period_hand_accounting():
    # With r=0, sigma=0, S0>K the delta is exactly one. Premium is externally
    # fixed at 12. Entry cash=12-110-1.10=-99.10; final sell gives +120-1.20;
    # payoff=20. Therefore final net P&L=-.30 and total costs=2.30.
    result = hedge_paths([[110,120]],100,0,1,0,12,cost_bps=100)
    assert result["pnl"][0] == pytest.approx(-.3)
    assert result["cost"][0] == pytest.approx(2.3)
    assert result["turnover"][0] == pytest.approx(230)
    assert result["trades"][0] == 2
    assert result["ledger"][0]["cash_after"] == pytest.approx(-99.1)
    assert result["ledger"][-1]["cash_after"] == pytest.approx(-.3)
    assert result["ledger"][-1]["position"] == 0


def test_independent_two_period_put_accounting_with_interest_and_fees():
    # sigma=0, deeply ITM put: delta=-1 at both decision dates. At time zero
    # short 1 share, cash=7+80-.8=86.2. After one year cash grows at 5%; cover
    # at 70, pay fee .7 and payoff 30. No interior trade because delta stays -1.
    result = hedge_paths([[80,75,70]],100,.05,1,0,7,cost_bps=100,kind="put")
    expected = 86.2*np.exp(.05)-70-.7-30
    assert result["pnl"][0] == pytest.approx(expected)
    assert result["cost"][0] == pytest.approx(.8*np.exp(.05)+.7)
    assert result["turnover"][0] == 150
    assert result["trades"][0] == 2
    assert result["ledger"][1]["trade"] == 0


@pytest.mark.parametrize("kind", ["call","put"])
def test_zero_volatility_risk_neutral_replication(kind):
    paths = simulate_paths(2,30,1,spot=110,vol=0,mu=.03)
    premium = bs_price(110,100,1,.03,0,kind)
    result = hedge_paths(paths,100,.03,1,0,premium,kind=kind)
    np.testing.assert_allclose(result["pnl"],0,atol=1e-11)


@pytest.mark.parametrize("policy", [{"kind":"fixed","every":1},
    {"kind":"fixed","every":7},{"kind":"threshold","threshold":.08}])
def test_terminalized_cost_exactly_explains_fee_wealth_difference(policy):
    paths = simulate_paths(24,21,.4,mu=.02,seed=44)
    premium = bs_price(100,100,.4,.04,.2)
    free = hedge_paths(paths,100,.04,.4,.2,premium,policy=policy)
    paid = hedge_paths(paths,100,.04,.4,.2,premium,policy=policy,cost_bps=23)
    np.testing.assert_allclose(free["pnl"]-paid["pnl"],paid["cost"],atol=5e-12)
    np.testing.assert_array_equal(free["trades"],paid["trades"])
    np.testing.assert_allclose(free["turnover"],paid["turnover"])
    assert sum(row["terminal_value_fee"] for row in paid["ledger"]) == pytest.approx(paid["cost"][0])


def test_ledger_is_self_financing_at_every_observation():
    result = hedge_paths([[100,95,108,104]],100,.06,1,.25,10,cost_bps=15)
    previous_position = 0
    for j,row in enumerate(result["ledger"]):
        expected = row["cash_before"]+row["interest"]-row["trade"]*row["spot"]-row["fee"]-row["payoff"]
        assert row["cash_after"] == pytest.approx(expected)
        assert row["position"] == pytest.approx(previous_position+row["trade"])
        assert row["wealth"] == pytest.approx(row["cash_after"]+row["position"]*row["spot"])
        if j:
            assert row["interest"] == pytest.approx(row["cash_before"]*np.expm1(.06/3))
        previous_position = row["position"]


def test_future_spots_and_volatilities_cannot_change_past_actions():
    first = hedge_paths([[100,102,99,108]],100,.02,1,np.array([[.2,.21,.22]]),10)
    second = hedge_paths([[100,102,150,70]],100,.02,1,np.array([[.2,.21,.9]]),10)
    assert first["ledger"][:2] == second["ledger"][:2]
    assert first["ledger"][2]["trade"] != second["ledger"][2]["trade"]


def test_threshold_always_initializes_and_fixed_policy_only_trades_scheduled_times():
    paths = [[100,101,99,106,98]]
    threshold = hedge_paths(paths,100,0,1,.2,8,policy={"kind":"threshold","threshold":2})
    assert threshold["ledger"][0]["position"] > 0
    assert all(r["trade"] == 0 for r in threshold["ledger"][1:-1])
    assert threshold["trades"][0] == 2
    fixed = hedge_paths(paths,100,0,1,.2,8,policy={"kind":"fixed","every":2})
    assert fixed["ledger"][1]["trade"] == 0
    assert fixed["ledger"][3]["trade"] == 0
    assert fixed["ledger"][2]["trade"] != 0


def test_common_premium_change_only_changes_terminal_cash():
    paths = simulate_paths(3,10,.5,seed=3)
    low = hedge_paths(paths,100,.03,.5,.2,6)
    high = hedge_paths(paths,100,.03,.5,.2,np.array([7.,8.,9.]))
    np.testing.assert_allclose(high["pnl"]-low["pnl"],np.array([1,2,3])*np.exp(.03*.5),atol=1e-12)
    np.testing.assert_allclose(low["cost"],high["cost"])


def test_finer_costless_hedging_reduces_error_on_shared_gbm_paths():
    paths = simulate_paths(4096,126,.5,vol=.2,mu=.03,seed=5822)
    premium = bs_price(100,100,.5,.03,.2)
    fine = hedge_paths(paths,100,.03,.5,.2,premium,record_path=None)
    coarse = hedge_paths(paths,100,.03,.5,.2,premium,policy={"kind":"fixed","every":21},record_path=None)
    assert np.mean(fine["pnl"]**2) < .2*np.mean(coarse["pnl"]**2)


def test_disable_ledger_and_select_record_path():
    paths = [[100,90],[100,110]]
    assert hedge_paths(paths,100,0,1,.2,8,record_path=None)["ledger"] == []
    result = hedge_paths(paths,100,0,1,.2,8,record_path=1)
    assert result["ledger"][-1]["spot"] == 110


@pytest.mark.parametrize("override", [dict(paths=[[100,np.nan]]),dict(paths=[[100,0]]),
    dict(paths=[100,101]),dict(horizon=0),dict(rate=np.inf),dict(hedge_vol=np.nan),
    dict(hedge_vol=[[.2,.3]]),dict(cost_bps=-1),dict(premium=-1),dict(premium=[1,2]),
    dict(policy={"kind":"fixed","every":0}),dict(policy={"kind":"fixed","every":True}),
    dict(policy={"kind":"threshold","threshold":-1}),dict(policy={"kind":"surprise"}),
    dict(policy={"kind":"fixed","every":1,"threshold":.2}),dict(record_path=1),dict(kind="bad")])
def test_bad_hedge_inputs_reject(override):
    parameters = dict(paths=[[100,101]],strike=100,rate=.03,horizon=1,hedge_vol=.2,premium=8)
    parameters.update(override)
    with pytest.raises(ValueError):
        hedge_paths(**parameters)
