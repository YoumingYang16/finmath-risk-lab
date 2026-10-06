import json

import numpy as np
import pytest
from scipy.stats import t as student_t

from risklab.statistics import summarize_pnl, paired_mean_ci


def test_summary_units_and_tail_definition():
    # 30 observations -> the worst 1.5 empirical observations form 5% mass.
    losses = np.arange(30,dtype=float)
    result = summarize_pnl(-losses,cost=np.ones(30)*2,trades=np.ones(30)*3)
    assert result["es95"] == pytest.approx((29+.5*28)/1.5)
    assert result["var95"] == pytest.approx(27.55)
    assert result["mean_pnl"] == -14.5
    assert result["mean_loss"] == 14.5
    assert result["rmse"] == pytest.approx(np.sqrt(np.mean(losses**2)))
    assert result["mean_cost"] == 2
    assert result["mean_trades"] == 3
    json.dumps(result,allow_nan=False)


def test_gain_only_and_small_sample_tail_not_clipped_to_zero():
    result = summarize_pnl([2,3,4])
    assert result["es95"] == pytest.approx(-2)
    assert result["var95"] < 0
    assert result["mean_cost"] is None
    assert summarize_pnl([7])["std_pnl"] == 0
    assert summarize_pnl([7])["es95"] == pytest.approx(-7)


def test_paired_interval_uses_path_differences():
    a = np.array([100,200,300,400],dtype=float)
    b = a-np.array([1,2,3,4])
    result = paired_mean_ci(a,b)
    se = np.std([1,2,3,4],ddof=1)/2
    assert result["difference"] == 2.5
    assert result["standard_error"] == pytest.approx(se)
    assert result["ci_low"] == pytest.approx(2.5-student_t.ppf(.975,3)*se)
    assert paired_mean_ci(a,a)["ci_high"] == 0
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("pnl", [[],[np.nan],[np.inf],[[1,2]]])
def test_nonfinite_or_invalid_shape_reject(pnl):
    with pytest.raises(ValueError):
        summarize_pnl(pnl)


@pytest.mark.parametrize("a,b,confidence", [([1],[1],.95),([1,2],[1,2,3],.95),
    ([1,2],[1,np.nan],.95),([1,2],[1,2],1),([1,2],[1,2],np.nan)])
def test_paired_invalid_inputs(a,b,confidence):
    with pytest.raises(ValueError):
        paired_mean_ci(a,b,confidence)


def test_cost_and_trade_samples_must_match():
    with pytest.raises(ValueError):
        summarize_pnl([1,2],cost=[1])
    with pytest.raises(ValueError):
        summarize_pnl([1,2],trades=[1,-1])
