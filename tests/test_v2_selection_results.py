"""Check the executed evidence for selection/accounting/inference consistency."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from risklab.statistics import paired_mean_ci

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def evidence():
    path=ROOT/'results/v2_selection_summary.json'
    if not path.exists():
        pytest.skip('Execute scripts/run_selection_study.py for artifact consistency checks')
    result=json.loads(path.read_text(encoding='utf-8'))
    with (ROOT/'results/v2_selection_choices.csv').open(encoding='utf-8',newline='') as handle:
        choices=list(csv.DictReader(handle))
    with (ROOT/'results/v2_selection_candidates.csv').open(encoding='utf-8',newline='') as handle:
        candidates=list(csv.DictReader(handle))
    return result,choices,candidates


def test_expected_sizes_and_decompositions(evidence):
    result,choices,candidates=evidence
    assert result['counts']['independent_replicates_per_scenario']==24
    assert len(choices)==24*4*3*2*3
    assert len(candidates)==24*4*2*12*5
    assert sum(row['primary'] for row in result['comparisons'])==1
    for row in candidates:
        assert float(row['mse'])==pytest.approx(float(row['variance'])+float(row['bias_squared']),abs=1e-10)


def test_primary_interval_recomputed_over_replicates(evidence):
    result,choices,_=evidence
    condition=[r for r in choices if r['scenario']=='heston' and int(r['validation_n'])==64 and float(r['fee_bps'])==5]
    index={(r['selector'],int(r['replicate'])):r for r in condition}
    a=[float(index[('joint_mse',r)]['test_mse']) for r in range(24)]
    b=[float(index[('forecast_first',r)]['test_mse']) for r in range(24)]
    recomputed=paired_mean_ci(a,b)
    for key,value in recomputed.items():
        assert result['primary_comparison'][key]==pytest.approx(value)


def test_selection_frequencies_sum_and_reference_difference(evidence):
    result,choices,_=evidence
    groups={}
    for row in result['selection_frequencies']:
        key=(row['scenario'],row['validation_n'],row['fee_bps'],row['selector'])
        groups[key]=groups.get(key,0)+row['count']
    assert all(count==24 for count in groups.values())
    for row in choices:
        assert float(row['reference_mse_gap'])==pytest.approx(float(row['reference_selected_mse'])-float(row['reference_best_mse']))
        if row['reference_selected_budget_met']=='True' and row['reference_any_feasible']=='True':
            assert float(row['reference_mse_gap']) >= -1e-12


def test_discretization_levels_are_actual_distinct_grids(evidence):
    result,_,_=evidence
    rows=result['discretization']
    assert len(rows)==10
    for scenario in ['heston','heston_shift']:
        group=[r for r in rows if r['scenario']==scenario]
        assert [r['substeps'] for r in group]==[1,2,4,8,16]
        assert all(r['n_paths']==32768 for r in group)
        assert all(r['effective_dt']==pytest.approx(1/(252*r['substeps'])) for r in group)
