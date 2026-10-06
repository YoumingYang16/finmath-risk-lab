import importlib.util
from pathlib import Path

import numpy as np
import pytest

from risklab.advanced_hedging import band_hedge
from risklab.paths import simulate_paths

_path=Path(__file__).resolve().parents[1]/'scripts/run_selection_study.py'
_spec=importlib.util.spec_from_file_location('selection_study',_path)
study=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


def test_es_fractional_empirical_tail():
    assert study.empirical_es(np.arange(16.),.9)==pytest.approx((15+.6*14)/1.6)
    assert study.empirical_es(np.array([2.,2.,2.]),.9)==pytest.approx(2.)


def test_mse_decomposition_exact_and_fee_equivalence():
    paths=simulate_paths(250,21,21/252,seed=413,mu=0)
    for policy in study.POLICIES.values():
        nofee=band_hedge(paths,100,0,21/252,.2,2.,policy=policy,cost_bps=0,record_path=None)
        for fee in [5.,20.]:
            direct=band_hedge(paths,100,0,21/252,.2,2.,policy=policy,cost_bps=fee,record_path=None)
            derived=nofee['pnl']-nofee['turnover']*fee/10000
            np.testing.assert_allclose(direct['pnl'],derived,atol=1e-11,rtol=1e-11)
            row=study.metrics(nofee['pnl'],nofee['turnover'],fee)
            assert row['mse']==pytest.approx(row['variance']+row['bias_squared'],abs=1e-13)


def rows():
    return [dict(candidate='a',multiplier=.75,qlike=1.,mean_cost=.1,mse=5.,es90=2.),
            dict(candidate='b',multiplier=.75,qlike=1.,mean_cost=.2,mse=1.,es90=1.),
            dict(candidate='c',multiplier=1.,qlike=2.,mean_cost=.1,mse=2.,es90=3.),
            dict(candidate='d',multiplier=1.25,qlike=3.,mean_cost=.1,mse=4.,es90=1.)]


def test_selectors_use_distinct_objectives_same_budget():
    data=rows()
    assert study.select_candidate(data,'forecast_first',.15)[0]['candidate']=='a'
    assert study.select_candidate(data,'joint_mse',.15)[0]['candidate']=='c'
    assert study.select_candidate(data,'joint_es90',.15)[0]['candidate']=='d'
    assert study.select_candidate(data,'joint_mse',.25)[0]['candidate']=='b'


def test_forecast_first_fallback_stays_in_selected_model():
    data=rows()
    data[0]['mean_cost']=.3; data[1]['mean_cost']=.25
    chosen,feasible=study.select_candidate(data,'forecast_first',.15)
    assert chosen['candidate']=='b' and not feasible
    assert study.select_candidate(data,'joint_mse',.15)[0]['candidate']=='c'


def test_no_feasible_fallback_is_visible_and_lowest_cost():
    chosen,feasible=study.select_candidate(rows(),'joint_mse',.01)
    assert not feasible and chosen['candidate']=='c'


def test_stream_separation_and_reproducibility():
    a=np.random.default_rng(study.seed_for(1,2,3)).normal(size=20)
    b=np.random.default_rng(study.seed_for(1,2,3)).normal(size=20)
    c=np.random.default_rng(study.seed_for(1,2,4)).normal(size=20)
    np.testing.assert_array_equal(a,b)
    assert not np.array_equal(a,c)


def test_shift_mapping_has_matched_validation_and_shifted_test():
    for model in ['heston_shift','jump_shift']:
        mapping=study.IMPLEMENTATION['scenario_mapping'][model]
        assert mapping['calibration']==mapping['validation']=='heston'
        assert mapping['test']==mapping['reference']==model
