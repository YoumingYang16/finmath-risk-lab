import numpy as np
import pytest
from scipy.stats import t as student_t

from risklab.pricing import bs_price, bs_delta, bs_greeks, crr_price, mc_price, implied_volatility


def test_known_black_scholes_values():
    assert bs_price(100, 100, 1, .05, .2) == pytest.approx(10.450583572185565, abs=1e-12)
    assert bs_price(100, 100, 1, .05, .2, "put") == pytest.approx(5.573526022256971, abs=1e-12)
    greeks = bs_greeks(100, 100, 1, .05, .2)
    assert greeks["delta"] == pytest.approx(.6368306511756191)
    assert greeks["gamma"] == pytest.approx(.018762017345846895)
    assert greeks["vega"] == pytest.approx(37.52403469169379)
    assert greeks["theta"] == pytest.approx(-6.414027546438197)
    assert greeks["rho"] == pytest.approx(53.232481545376345)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_independent_central_differences(kind):
    s, k, tau, r, vol, q = 108., 103., .8, -.01, .31, .025
    h = 1e-4
    price = lambda S=s, T=tau, R=r, V=vol: bs_price(S, k, T, R, V, kind, q)
    g = bs_greeks(s, k, tau, r, vol, kind, q)
    assert g["delta"] == pytest.approx((price(S=s+h)-price(S=s-h))/(2*h), rel=1e-7)
    assert g["gamma"] == pytest.approx((price(S=s+h)-2*price()+price(S=s-h))/h**2, rel=2e-3)
    assert g["vega"] == pytest.approx((price(V=vol+h)-price(V=vol-h))/(2*h), rel=1e-6)
    assert g["rho"] == pytest.approx((price(R=r+h)-price(R=r-h))/(2*h), rel=1e-6)
    assert g["theta"] == pytest.approx(-(price(T=tau+h)-price(T=tau-h))/(2*h), rel=1e-6)


def test_vectorized_parity_bounds_and_delta_difference():
    s = np.array([[70.], [100.], [130.]])
    vol = np.array([0., .2, .8])
    call = bs_price(s, 100, 1.7, -.015, vol, dividend=.03)
    put = bs_price(s, 100, 1.7, -.015, vol, "put", dividend=.03)
    parity = s*np.exp(-.03*1.7)-100*np.exp(.015*1.7)
    np.testing.assert_allclose(call-put, np.broadcast_to(parity, call.shape), atol=1e-12)
    assert call.shape == (3, 3)
    assert np.all(call >= np.maximum(parity, 0)-1e-12)
    assert np.all(call <= s*np.exp(-.03*1.7))
    np.testing.assert_allclose(bs_delta(s,100,1.7,-.015,vol,dividend=.03)
                               -bs_delta(s,100,1.7,-.015,vol,"put",dividend=.03), np.exp(-.03*1.7))


def test_expiry_zero_volatility_and_convention():
    np.testing.assert_array_equal(bs_price([90,100,110],100,0,.04,.2), [0,0,10])
    np.testing.assert_array_equal(bs_delta([90,100,110],100,0,.04,.2), [0,.5,1])
    np.testing.assert_array_equal(bs_delta([90,100,110],100,0,.04,.2,"put"), [-1,-.5,0])
    for name, value in bs_greeks([90,100,110],100,0,.04,.2).items():
        if name != "delta":
            np.testing.assert_array_equal(value, [0,0,0])
    assert bs_price(110,100,1,.03,0) == pytest.approx(110-100*np.exp(-.03))
    assert bs_price(90,100,1,.03,0,"put") == pytest.approx(100*np.exp(-.03)-90)
    assert bs_greeks(100,100,1,0,0)["vega"] == pytest.approx(100/np.sqrt(2*np.pi))
    assert bs_greeks(100,100,1,0,0)["gamma"] == 0  # documented convention


@pytest.mark.parametrize("args", [
    (np.nan,100,1,.03,.2), (100,np.inf,1,.03,.2), (100,100,np.nan,.03,.2),
    (100,100,1,np.inf,.2), (100,100,1,.03,np.nan), (0,100,1,.03,.2),
    (100,-100,1,.03,.2), (100,100,-1,.03,.2), (100,100,1,.03,-.2)])
def test_bad_pricing_inputs_reject(args):
    for function in [bs_price, bs_delta, bs_greeks]:
        with pytest.raises(ValueError):
            function(*args)


def test_unknown_kind_and_overflow_reject():
    with pytest.raises(ValueError):
        bs_price(100,100,1,.03,.2,"straddle")
    with pytest.raises(ValueError):
        bs_price(100,100,1,-1000,.2)


def test_crr_convergence_and_american_exercise():
    exact = bs_price(100,100,1,.05,.2)
    coarse = crr_price(100,100,1,.05,.2,steps=32)
    fine = crr_price(100,100,1,.05,.2,steps=1024)
    assert abs(fine-exact) < abs(coarse-exact)
    assert fine == pytest.approx(exact, abs=.003)
    european = crr_price(90,100,1,.06,.25,steps=512,kind="put")
    american = crr_price(90,100,1,.06,.25,steps=512,kind="put",american=True)
    assert american >= european
    assert american >= 10
    assert crr_price(100,100,1,.05,.2,steps=512,american=True) == pytest.approx(
        crr_price(100,100,1,.05,.2,steps=512), abs=1e-12)
    dividend_american = crr_price(120,100,1,.01,.2,steps=512,dividend=.2,american=True)
    dividend_european = crr_price(120,100,1,.01,.2,steps=512,dividend=.2)
    assert dividend_american >= dividend_european
    assert dividend_american >= 20


def test_crr_deterministic_exercise_and_invalid_grid():
    assert crr_price(80,100,1,.1,0,kind="put",american=True) == pytest.approx(20)
    assert crr_price(80,100,1,.1,0,kind="put") == pytest.approx(100*np.exp(-.1)-80)
    assert crr_price(105,100,0,.03,.2) == 5
    with pytest.raises(ValueError, match="probability"):
        crr_price(100,100,1,.5,.01,steps=1)
    for step in [0,-1,1.5,True,20001]:
        with pytest.raises(ValueError):
            crr_price(100,100,1,.05,.2,steps=step)


def test_mc_pair_averages_are_independent_units():
    n, seed, s, k, r, sigma, tau = 4000, 932, 100., 105., .03, .3, .7
    result = mc_price(s,k,tau,r,sigma,n_paths=n,seed=seed)
    z = np.random.default_rng(seed).standard_normal(n//2)
    plus = np.maximum(s*np.exp((r-.5*sigma*sigma)*tau+sigma*np.sqrt(tau)*z)-k,0)*np.exp(-r*tau)
    minus = np.maximum(s*np.exp((r-.5*sigma*sigma)*tau-sigma*np.sqrt(tau)*z)-k,0)*np.exp(-r*tau)
    paired = (plus+minus)/2
    expected_se = paired.std(ddof=1)/np.sqrt(n//2)
    assert result["independent_units"] == n//2
    assert result["price"] == pytest.approx(paired.mean())
    assert result["standard_error"] == pytest.approx(expected_se)
    assert result["ci_high"]-result["price"] == pytest.approx(student_t.ppf(.975,n//2-1)*expected_se)
    wrong_iid_se = np.concatenate([plus,minus]).std(ddof=1)/np.sqrt(n)
    assert abs(wrong_iid_se-expected_se) > .01


@pytest.mark.parametrize("anti", [True,False])
def test_mc_matches_analytic_with_finite_error_and_is_reproducible(anti):
    result = mc_price(100,100,1,.03,.2,n_paths=100000,seed=25,antithetic=anti)
    exact = bs_price(100,100,1,.03,.2)
    assert abs(result["price"]-exact) < 4*result["standard_error"]
    assert result == mc_price(100,100,1,.03,.2,n_paths=100000,seed=25,antithetic=anti)
    zero = mc_price(100,95,1,.03,0,n_paths=100,antithetic=anti)
    assert zero["price"] == pytest.approx(bs_price(100,95,1,.03,0), abs=1e-12)
    assert zero["standard_error"] < 1e-14


def test_mc_invalid_sample_count():
    for count in [0,1,3,101,4.5,True]:
        with pytest.raises(ValueError):
            mc_price(100,100,1,.03,.2,n_paths=count)


@pytest.mark.parametrize("kind", ["call","put"])
@pytest.mark.parametrize("vol", [.04,.2,.8,2.0])
def test_implied_volatility_roundtrip(kind,vol):
    premium = bs_price(100,103,.7,.025,vol,kind,dividend=.01)
    implied = implied_volatility(premium,100,103,.7,.025,kind,dividend=.01)
    assert implied == pytest.approx(vol, abs=1e-10)


def test_implied_volatility_boundaries():
    lower = bs_price(110,100,1,.03,0)
    assert implied_volatility(lower,110,100,1,.03) == 0
    for bad in [-1,np.nan,111,lower-.01,np.nextafter(lower,-np.inf)]:
        with pytest.raises(ValueError):
            implied_volatility(bad,110,100,1,.03)
    with pytest.raises(ValueError, match="no finite"):
        implied_volatility(110,110,100,1,.03)
    with pytest.raises(ValueError, match="expiry"):
        implied_volatility(10,110,100,0,.03)
