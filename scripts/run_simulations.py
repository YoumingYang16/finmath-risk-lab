"""Execute a frozen scenario protocol; no strategy selection on test paths."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from risklab.pricing import bs_price, crr_price, mc_price
from risklab.paths import simulate_paths
from risklab.hedging import hedge_paths
from risklab.statistics import summarize_pnl, paired_mean_ci

POLICIES = {
    'daily': {'kind': 'fixed', 'every': 1},
    'every5': {'kind': 'fixed', 'every': 5},
    'every21': {'kind': 'fixed', 'every': 21},
    'band02': {'kind': 'threshold', 'threshold': .02},
    'band05': {'kind': 'threshold', 'threshold': .05},
    'band10': {'kind': 'threshold', 'threshold': .10},
}
SCENARIOS = [
    {'id': 'S1', 'name': 'Matched GBM', 'model': 'gbm', 'hedge': .2},
    {'id': 'S2', 'name': 'Underestimated volatility', 'model': 'gbm', 'hedge': .15},
    {'id': 'S3', 'name': 'Overestimated volatility', 'model': 'gbm', 'hedge': .30},
    {'id': 'S4', 'name': 'Finite calibration 20 observations', 'model': 'gbm', 'calibration': 20},
    {'id': 'S5', 'name': 'Finite calibration 120 observations', 'model': 'gbm', 'calibration': 120},
    {'id': 'S6', 'name': 'Volatility regime change', 'model': 'regime', 'hedge': .2,
     'kwargs': {'vol2': .4, 'switch_fraction': .5}},
    {'id': 'S7', 'name': 'Jump stress', 'model': 'jump', 'hedge': .2,
     'kwargs': {'jump_intensity': 1., 'jump_mean': -.1, 'jump_std': .15}},
]
PROTOCOL = {
    'version': '1.0.0', 'spot': 100., 'strike': 100., 'horizon': .5,
    'rate': .03, 'physical_drift': .03, 'base_vol': .2, 'steps': 126,
    'validation_seed_base': 13000, 'test_seed_base': 73000,
    'calibration_seed_offset': 200000, 'n_validation': 1024, 'n_test': 8192,
    'fees_bps': [0., 5., 20.], 'policies': POLICIES, 'scenarios': SCENARIOS,
    'selection': 'Minimum validation RMSE among policies with validation mean terminalized cost <= 0.50 per initial spot 100',
    'mean_cost_budget': .50,
    'no_feasible_rule': 'Choose minimum validation cost, label fallback and retain budget violation',
    'tie_break': 'RMSE, mean_cost, then policy name lexicographically',
    'primary_contrast': 'S1 at 5 bps: selected policy versus every5 on paired squared terminal losses',
    'primary_interval': 'Pointwise two-sided 95% t interval over independent paired test paths',
    'other_contrasts': 'Exploratory pointwise intervals; no familywise claim',
    'premium': 'Identical BS(base_vol=0.2) premium for all scenarios and policies; not repriced with hidden path parameters',
    'claims': 'Discrete hypothetical replication under stated conventions; no executable trading or causal market evidence',
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def generate(scenario, n, seed):
    paths = simulate_paths(n, PROTOCOL['steps'], PROTOCOL['horizon'],
                           spot=100., vol=.2, mu=.03, seed=seed,
                           model=scenario['model'], **scenario.get('kwargs', {}))
    if 'calibration' in scenario:
        rng = np.random.default_rng(seed + PROTOCOL['calibration_seed_offset'])
        history = rng.normal(0., .2 / np.sqrt(252), (n, scenario['calibration']))
        estimate = history.std(axis=1, ddof=1) * np.sqrt(252)
        hedge_vol = np.broadcast_to(estimate[:, None], (n, PROTOCOL['steps'])).copy()
    else:
        hedge_vol = scenario['hedge']
    return paths, hedge_vol


def numerical_benchmarks():
    benchmark = float(bs_price(100., 100., 1., .05, .2))
    rows = []
    for n in [16, 32, 64, 128, 256, 512, 1024]:
        start = time.perf_counter()
        value = crr_price(100., 100., 1., .05, .2, steps=n)
        rows.append({'method': 'CRR', 'size': n, 'price': float(value),
                     'absolute_error': abs(value-benchmark), 'elapsed_seconds': time.perf_counter()-start,
                     'standard_error': 0., 'independent_units': 0})
    for n in [2000, 10000, 50000, 200000]:
        for anti in [False, True]:
            start = time.perf_counter()
            item = mc_price(100., 100., 1., .05, .2, n_paths=n, seed=9017,
                            antithetic=anti)
            rows.append({'method': 'MC antithetic' if anti else 'MC plain', 'size': n,
                         'price': float(item['price']), 'absolute_error': abs(item['price']-benchmark),
                         'elapsed_seconds': time.perf_counter()-start,
                         'standard_error': float(item['standard_error']),
                         'independent_units': item['independent_units']})
    return {'parameters': {'spot':100,'strike':100,'horizon':1,'rate':.05,'vol':.2},
            'analytic_price': benchmark, 'rows': rows,
            'interpretation': 'MC error is random, not necessarily monotone; CRR subsequence is even-step. Timing single-process, one run per size, descriptive only.'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--quick', action='store_true', help='smoke-only, writes results/smoke; not report evidence')
    args = p.parse_args()
    out = ROOT/'results'/('smoke' if args.quick else '')
    protocol = dict(PROTOCOL)
    if args.quick:
        protocol.update(n_validation=128, n_test=256)
    raw = json.dumps(protocol, sort_keys=True, separators=(',', ':')).encode()
    protocol_hash = hashlib.sha256(raw).hexdigest()
    # Save the exact protocol before any outcomes are calculated.
    dump(ROOT/'docs'/('simulation_protocol_smoke.json' if args.quick else 'simulation_protocol.json'), protocol)
    started = time.perf_counter()
    rows, selections, contrasts, ledger = [], [], [], []
    premium = float(bs_price(100, 100, .5, .03, .2))
    for si, scenario in enumerate(SCENARIOS):
        val_paths, val_vol = generate(scenario, protocol['n_validation'], 13000+si)
        test_paths, test_vol = generate(scenario, protocol['n_test'], 73000+si)
        for fee in protocol['fees_bps']:
            val_summaries, test_runs = {}, {}
            for name, policy in POLICIES.items():
                for split, paths, vol in [('validation', val_paths, val_vol), ('test', test_paths, test_vol)]:
                    run = hedge_paths(paths, 100., .03, .5, vol, premium,
                                      policy=policy, cost_bps=fee, record_path=0)
                    summary = summarize_pnl(run['pnl'], run['cost'], run['trades'])
                    rows.append({'scenario':scenario['id'], 'name':scenario['name'], 'split':split,
                                 'fee_bps':fee, 'policy':name, **summary})
                    if split == 'validation':
                        val_summaries[name] = summary
                    else:
                        test_runs[name] = run
                        if scenario['id']=='S1' and fee==5 and name=='every5':
                            ledger = run['ledger']
            feasible = [name for name,s in val_summaries.items() if s['mean_cost'] <= .5]
            if feasible:
                selected = min(feasible,key=lambda k:(val_summaries[k]['rmse'], val_summaries[k]['mean_cost'], k))
            else:
                selected = min(POLICIES,key=lambda k:(val_summaries[k]['mean_cost'], val_summaries[k]['rmse'], k))
            test = summarize_pnl(test_runs[selected]['pnl'],test_runs[selected]['cost'],test_runs[selected]['trades'])
            selections.append({'scenario':scenario['id'],'fee_bps':fee,'selected_policy':selected,
                               'validation_feasible':bool(feasible),'validation_rmse':val_summaries[selected]['rmse'],
                               'validation_mean_cost':val_summaries[selected]['mean_cost'],
                               'test_mean_cost':test['mean_cost'],'test_budget_met':test['mean_cost']<=.5,
                               'test_rmse':test['rmse'],'test_es95':test['es95']})
            contrast = paired_mean_ci(test_runs[selected]['pnl']**2, test_runs['every5']['pnl']**2)
            contrasts.append({'scenario':scenario['id'],'fee_bps':fee,'selected_policy':selected,
                              'baseline':'every5','metric':'squared terminal replication loss',
                              'primary':scenario['id']=='S1' and fee==5, **contrast})
            print(f"{scenario['id']} fee={fee:g} selected={selected} test RMSE={test['rmse']:.4f}", flush=True)
    numerical = numerical_benchmarks()
    result = {'protocol':protocol,'protocol_sha256':protocol_hash,'premium':premium,
              'rows':rows,'selections':selections,'paired_comparisons':contrasts,'numerical':numerical,
              'runtime_seconds':time.perf_counter()-started,'environment':{'python':sys.version,'platform':platform.platform(),'numpy':np.__version__},
              'limitations':['Scenario-specific validation choice is not a universal optimal policy.',
                             'Confidence intervals are pointwise; all but one prespecified contrast exploratory.',
                             'Mean validation cost feasibility does not guarantee test or per-path budget feasibility.',
                             'Terminal loss includes initial premium, financing, entry/rebalance/exit costs and payoff.',
                             'No market quote calibration, margin, liquidity or execution model.']}
    dump(out/'simulation_summary.json',result)
    write_csv(out/'simulation_metrics.csv', rows)
    write_csv(out/'simulation_selection.csv', selections)
    write_csv(out/'simulation_comparisons.csv', contrasts)
    write_csv(out/'simulation_ledger.csv', ledger)
    write_csv(out/'numerical_benchmarks.csv', numerical['rows'])
    print(json.dumps({'output':str(out),'seconds':result['runtime_seconds'],'protocol_hash':protocol_hash}))


if __name__ == '__main__':
    main()
