"""V2 repeated full-procedure selection study; frozen protocol before results.

Only independent replicate-level statistics justify the main t interval.
Nested validation sizes and shared paths/candidate grids are paired, not
additional independent replications. No outcomes tune this implementation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scipy.stats import t as student_t

from risklab.advanced_hedging import band_hedge
from risklab.paths import simulate_paths
from risklab.pricing import bs_price
from risklab.statistics import paired_mean_ci
from risklab.stochastic_volatility import heston_paths

POLICIES = {'daily': {'kind':'fixed', 'every':1},
            'every5': {'kind':'fixed', 'every':5},
            'band05': {'kind':'band', 'width':.05},
            'band10': {'kind':'band', 'width':.10}}
IMPLEMENTATION = {
    'version': '2.0.0',
    'seed_formula': 'SeedSequence([20261006,scenario_index,replicate,stream]); stream 1=calibration,2=validation,3=test,4=reference; distinct full-procedure replicates',
    'validation_nesting': 'Within a replicate, first 16/64/256 rows of the same 256-path validation pool; not independent sizes',
    'calibration': 'Independent 60-return path under GBM for matched_gbm, matched Heston otherwise; sample standard deviation ddof=1 annualized sqrt(252)',
    'forecast': 'The 60-return volatility estimate multiplied by 0.75/1/1.25, frozen for each hedge episode; latent variance is never supplied to the candidate',
    'qlike': 'log(hedge_vol^2/252)+mean(all validation one-observation squared log returns)/(hedge_vol^2/252); noisy conditional-second-moment proxy, not option implied volatility',
    'scenario_mapping': {'matched_gbm': {'calibration':'gbm','validation':'gbm','test':'gbm','reference':'gbm'},
                         'heston': {'calibration':'heston','validation':'heston','test':'heston','reference':'heston'},
                         'heston_shift': {'calibration':'heston','validation':'heston','test':'heston_shift','reference':'heston_shift'},
                         'jump_shift': {'calibration':'heston','validation':'heston','test':'jump_shift','reference':'jump_shift'}},
    'fee_calculation': 'Risk-independent policies have identical positions at every fee. Run each once at zero fee; net_pnl=gross_pnl-turnover*fee_bps/10000 (r=0). Direct-fee equivalence independently tested.',
    'reference': 'Same 12 calibrated-volatility/policy pairs evaluated on independent 16384-path reference; minimum reference MSE among reference mean-cost-feasible pairs. All selectors compared to that pair on the SAME reference paths. If selected pair violates reference budget, its signed difference can be negative; this is not constrained feasible regret.',
    'fallback': 'If no eligible pair meets validation cost budget, choose minimum cost, then MSE, then candidate name; retain infeasibility.',
    'statistical_unit': 'Independent full-procedure replicate (24), not individual test path or repeated candidate row',
    'primary': 'heston, validation64, fee5: joint_mse minus forecast_first test MSE; pointwise two-sided Student-t interval across full-procedure replicates',
    'discretization': {'substeps':[1,2,4,8,16], 'paths':32768, 'seed_base':271800,
                       'comparisons':'Independent fine-grid ensembles, not coupled Brownian refinement. Descriptive weak-moment and risk sensitivity, not proof of exactness or convergence order.'}}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_for(scenario_index, replicate, stream):
    return np.random.SeedSequence([20261006, scenario_index, replicate, stream])


def empirical_es(loss, alpha=.9):
    loss = np.asarray(loss, dtype=float)
    if loss.ndim != 1 or len(loss) == 0 or not np.all(np.isfinite(loss)) or not 0 < alpha < 1:
        raise ValueError('finite nonempty loss vector and alpha in (0,1) required')
    values = np.sort(loss)[::-1]
    mass = (1-alpha) * len(values)
    whole = int(np.floor(mass))
    fraction = mass-whole
    return float((values[:whole].sum() + (fraction*values[whole] if fraction > 0 else 0.)) / mass)


def metrics(gross, turnover, fee_bps):
    gross, turnover = np.asarray(gross, dtype=float), np.asarray(turnover, dtype=float)
    if gross.ndim != 1 or turnover.shape != gross.shape or len(gross) == 0:
        raise ValueError('matching nonempty pnl and turnover vectors required')
    cost = turnover * fee_bps / 10000
    pnl = gross-cost
    result = {'n':int(len(pnl)), 'mse':float(np.mean(pnl*pnl)),
              'variance':float(np.var(pnl, ddof=0)), 'bias_squared':float(np.mean(pnl)**2),
              'mean_pnl':float(np.mean(pnl)), 'es90':empirical_es(-pnl),
              'mean_cost':float(np.mean(cost)), 'mean_turnover':float(np.mean(turnover))}
    if not all(np.isfinite(v) for v in result.values()):
        raise ValueError('nonfinite candidate metric')
    return result


def select_candidate(rows, selector, budget):
    if selector not in {'forecast_first', 'joint_mse', 'joint_es90'}:
        raise ValueError('unknown selector')
    eligible = rows
    if selector == 'forecast_first':
        model = min(rows, key=lambda r:(r['qlike'],r['multiplier']))['multiplier']
        eligible = [r for r in rows if r['multiplier'] == model]
    feasible = [r for r in eligible if r['mean_cost'] <= budget]
    if feasible:
        metric = 'es90' if selector == 'joint_es90' else 'mse'
        chosen = min(feasible, key=lambda r:(r[metric],r['mean_cost'],r['candidate']))
    else:
        chosen = min(eligible, key=lambda r:(r['mean_cost'],r['mse'],r['candidate']))
    return chosen, bool(feasible)


def generate(model, n, steps, horizon, cfg, seed):
    if model in {'heston', 'heston_shift'}:
        params = cfg[model]
        run = heston_paths(n, steps, horizon, spot=cfg['spot'], mu=cfg['physical_drift'],
                           seed=seed, **params)
        return run['prices'], run['diagnostics']
    kwargs = cfg['jump_shift'] if model == 'jump_shift' else {}
    paths = simulate_paths(n, steps, horizon, spot=cfg['spot'], mu=cfg['physical_drift'],
                           vol=.2, seed=seed, model='jump' if model=='jump_shift' else 'gbm', **kwargs)
    return paths, {'scheme':'exact observation-time GBM/Merton increments'}


def evaluate_grid(paths, estimate, cfg, premium):
    result = {}
    for multiplier in cfg['forecast_multipliers']:
        vol = estimate*multiplier
        variance_proxy = vol*vol/252
        qlike = float(np.log(variance_proxy)+np.mean(np.diff(np.log(paths),axis=1)**2)/variance_proxy)
        for policy_name in cfg['policies']:
            key = f'vol{multiplier:g}_{policy_name}'
            run = band_hedge(paths, cfg['strike'], cfg['rate'], cfg['horizon'],
                             vol, premium, policy=POLICIES[policy_name],cost_bps=0,record_path=None)
            result[key] = {'candidate':key,'multiplier':multiplier,'hedge_vol':vol,
                           'policy':policy_name,'gross':run['pnl'],'turnover':run['turnover'],
                           'qlike':qlike}
    return result


def summary_grid(runs, fee, n=None, paths=None):
    rows = []
    for key, run in runs.items():
        qlike = run['qlike']
        if n is not None:
            h = run['hedge_vol']**2/252
            qlike = float(np.log(h)+np.mean(np.diff(np.log(paths[:n]),axis=1)**2)/h)
        rows.append({k:run[k] for k in ['candidate','multiplier','hedge_vol','policy']} |
                    {'qlike':qlike} |
                    metrics(run['gross'][:n],run['turnover'][:n],fee))
    return rows


def interval(values):
    values = np.asarray(values)
    return paired_mean_ci(values, np.zeros_like(values))


def aggregate_selections(selected, cfg):
    grouped = defaultdict(list)
    for row in selected:
        grouped[(row['scenario'],row['validation_n'],row['fee_bps'],row['selector'])].append(row)
    aggregate, frequencies = [], []
    for (scenario,n,fee,selector), group in sorted(grouped.items()):
        common = {'scenario':scenario,'validation_n':n,'fee_bps':fee,'selector':selector,'replicates':len(group)}
        counts = Counter(row['candidate'] for row in group)
        for name,count in sorted(counts.items()):
            frequencies.append(common | {'candidate':name,'count':count,'fraction':count/len(group)})
        probabilities = np.array(list(counts.values()))/len(group)
        aggregate.append(common | {
            'mean_test_mse':float(np.mean([r['test_mse'] for r in group])),
            'mean_test_variance':float(np.mean([r['test_variance'] for r in group])),
            'mean_test_bias_squared':float(np.mean([r['test_bias_squared'] for r in group])),
            'mean_test_es90':float(np.mean([r['test_es90'] for r in group])),
            'mean_test_cost':float(np.mean([r['test_mean_cost'] for r in group])),
            'test_budget_violation_fraction':float(np.mean([not r['test_budget_met'] for r in group])),
            'validation_fallback_fraction':float(np.mean([not r['validation_feasible'] for r in group])),
            'reference_budget_violation_fraction':float(np.mean([not r['reference_selected_budget_met'] for r in group])),
            'mean_reference_signed_gap':float(np.mean([r['reference_mse_gap'] for r in group])),
            'selection_entropy_nats':float(-np.sum(probabilities*np.log(probabilities))),
            'most_selected_fraction':float(max(counts.values())/len(group))})
    comparisons = []
    index = {(r['scenario'],r['validation_n'],r['fee_bps'],r['selector'],r['replicate']):r for r in selected}
    for scenario in cfg['scenarios']:
        for n in cfg['validation_paths']:
            for fee in cfg['cost_bps']:
                for selector in ['joint_mse','joint_es90']:
                    for metric in ['test_mse','test_es90','test_mean_cost','reference_mse_gap']:
                        a = [index[(scenario,n,fee,selector,r)][metric] for r in range(cfg['replicates'])]
                        b = [index[(scenario,n,fee,'forecast_first',r)][metric] for r in range(cfg['replicates'])]
                        primary = scenario=='heston' and n==64 and fee==5 and selector=='joint_mse' and metric=='test_mse'
                        comparisons.append({'scenario':scenario,'validation_n':n,'fee_bps':fee,
                                             'selector':selector,'baseline':'forecast_first','metric':metric,
                                             'primary':primary, **paired_mean_ci(a,b)})
    return aggregate,frequencies,comparisons


def discretization(cfg, out, quick=False):
    rows = []
    n = 2048 if quick else IMPLEMENTATION['discretization']['paths']
    premium = float(bs_price(100,100,cfg['horizon'],0,.2))
    for mi,model in enumerate(['heston','heston_shift']):
        for si,substeps in enumerate(IMPLEMENTATION['discretization']['substeps']):
            params = {**cfg[model], 'substeps':substeps}
            run = heston_paths(n,cfg['steps'],cfg['horizon'],seed=271800+100*mi+si,**params)
            paths,v = run['prices'],run['variance']
            payoff = np.maximum(paths[:,-1]-100,0)
            hedge = band_hedge(paths,100,0,cfg['horizon'],.2,premium,
                               policy=POLICIES['band05'],cost_bps=5,record_path=None)
            pnl = hedge['pnl']
            mean_s = float(paths[:,-1].mean()); mean_v=float(v[:,-1].mean())
            se_s=float(paths[:,-1].std(ddof=1)/np.sqrt(n))
            se_v=float(v[:,-1].std(ddof=1)/np.sqrt(n))
            se_payoff=float(payoff.std(ddof=1)/np.sqrt(n))
            se_mse=float((pnl*pnl).std(ddof=1)/np.sqrt(n))
            rows.append({'scenario':model,'substeps':substeps,'n_paths':n,
                         'effective_dt':run['diagnostics']['effective_dt'],
                         'terminal_spot_mean':mean_s,'spot_exact_mean':100.,'spot_mean_se':se_s,
                         'terminal_variance_mean':mean_v,'variance_exact_mean':params['theta']+(params['v0']-params['theta'])*np.exp(-params['kappa']*cfg['horizon']),
                         'variance_mean_se':se_v,'call_payoff_mean':float(payoff.mean()),'call_payoff_se':se_payoff,
                         'band05_mse':float(np.mean(pnl*pnl)),'band05_mse_se':se_mse,
                         'negative_raw_update_fraction':run['diagnostics']['negative_raw_update_fraction'],
                         'paths_ever_negative':run['diagnostics']['paths_ever_negative']})
    write_csv(out/'v2_discretization.csv',rows)
    dump(out/'v2_discretization.json',{'protocol':IMPLEMENTATION['discretization'],'rows':rows,
         'interpretation':'Independent ensembles at each resolution. Monte Carlo error and time-discretization error both affect differences; no claimed monotone convergence or exact Heston reference.'})
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--quick',action='store_true',help='smoke only; separate folder, not report evidence')
    args=parser.parse_args()
    full=json.loads((ROOT/'docs/v2_protocol.json').read_text(encoding='utf-8'))
    cfg=dict(full['simulation'])
    if args.quick:
        cfg.update(replicates=3,test_paths_per_replicate=128,independent_reference_paths=512)
    out=ROOT/'results'/('smoke_v2' if args.quick else '')
    out.mkdir(parents=True,exist_ok=True)
    frozen={'main_protocol_sha256':sha(ROOT/'docs/v2_protocol.json'),'implementation':IMPLEMENTATION,'effective_simulation':cfg}
    protocol_text=json.dumps(frozen,sort_keys=True,separators=(',',':'))
    frozen_hash=hashlib.sha256(protocol_text.encode()).hexdigest()
    # Freeze this precise execution protocol before generating any outcomes.
    dump(out/'v2_selection_execution_protocol.json',frozen | {'execution_protocol_sha256':frozen_hash})
    started=time.perf_counter()
    candidates,selected,diagnostics,calibrations=[],[],[],[]
    premium=float(bs_price(cfg['spot'],cfg['strike'],cfg['horizon'],cfg['rate'],cfg['premium_volatility']))
    for si,scenario in enumerate(cfg['scenarios']):
        mapping=IMPLEMENTATION['scenario_mapping'][scenario]
        for rep in range(cfg['replicates']):
            cal_path,cal_diag=generate(mapping['calibration'],1,cfg['calibration_returns_per_replicate'],
                                       cfg['calibration_returns_per_replicate']/252,cfg,seed_for(si,rep,1))
            estimate=float(np.std(np.diff(np.log(cal_path[0])),ddof=1)*np.sqrt(252))
            if not np.isfinite(estimate) or estimate <= 0:
                raise ValueError('invalid calibrated volatility')
            calibrations.append({'scenario':scenario,'replicate':rep,'estimate':estimate,'n_returns':cfg['calibration_returns_per_replicate'],
                                 'calibration_model':mapping['calibration']})
            runs,raw_paths={},{}
            for stream,split,n in [(2,'validation',max(cfg['validation_paths'])),(3,'test',cfg['test_paths_per_replicate']),
                                  (4,'reference',cfg['independent_reference_paths'])]:
                paths,diag=generate(mapping[split],n,cfg['steps'],cfg['horizon'],cfg,seed_for(si,rep,stream))
                raw_paths[split]=paths
                diagnostics.append({'scenario':scenario,'replicate':rep,'split':split,'generator':mapping[split],**diag})
                runs[split]=evaluate_grid(paths,estimate,cfg,premium)
            for fee in cfg['cost_bps']:
                budget=cfg['mean_cost_budgets'][f'{fee:.1f}']
                test_rows=summary_grid(runs['test'],fee)
                reference_rows=summary_grid(runs['reference'],fee)
                test_index={r['candidate']:r for r in test_rows}
                reference_index={r['candidate']:r for r in reference_rows}
                reference_best,reference_feasible=select_candidate(reference_rows,'joint_mse',budget)
                for split,rows in [('test',test_rows),('reference',reference_rows)]:
                    for row in rows:
                        candidates.append({'scenario':scenario,'replicate':rep,'split':split,'validation_n':None,
                                           'fee_bps':fee,'budget':budget,**row})
                for n in cfg['validation_paths']:
                    val_rows=summary_grid(runs['validation'],fee,n,raw_paths['validation'])
                    for row in val_rows:
                        candidates.append({'scenario':scenario,'replicate':rep,'split':'validation','validation_n':n,
                                           'fee_bps':fee,'budget':budget,**row})
                    for selector in cfg['selectors']:
                        chosen,feasible=select_candidate(val_rows,selector,budget)
                        test=test_index[chosen['candidate']]; ref=reference_index[chosen['candidate']]
                        selected.append({'scenario':scenario,'replicate':rep,'validation_n':n,'fee_bps':fee,
                                          'budget':budget,'selector':selector,'candidate':chosen['candidate'],
                                          'policy':chosen['policy'],'multiplier':chosen['multiplier'],'hedge_vol':chosen['hedge_vol'],
                                          'validation_feasible':feasible,'validation_mse':chosen['mse'],
                                          'validation_es90':chosen['es90'],'validation_mean_cost':chosen['mean_cost'],
                                          **{'test_'+key:test[key] for key in ['mse','variance','bias_squared','mean_pnl','es90','mean_cost']},
                                          'test_budget_met':test['mean_cost']<=budget,
                                          'reference_best_candidate':reference_best['candidate'],
                                          'reference_any_feasible':reference_feasible,
                                          'reference_best_mse':reference_best['mse'],'reference_selected_mse':ref['mse'],
                                          'reference_selected_budget_met':ref['mean_cost']<=budget,
                                          'reference_mse_gap':ref['mse']-reference_best['mse']})
            print(f'{scenario} replicate {rep+1}/{cfg["replicates"]}; elapsed {time.perf_counter()-started:.1f}s',flush=True)
    aggregate,frequencies,comparisons=aggregate_selections(selected,cfg)
    refinement=discretization(cfg,out,args.quick)
    source_paths=['risklab/stochastic_volatility.py','risklab/advanced_hedging.py','risklab/hedging.py',
                  'risklab/pricing.py','risklab/paths.py','scripts/run_selection_study.py','docs/v2_protocol.json']
    result={'version':'2.0.0','smoke_only':args.quick,'execution_protocol':frozen,'execution_protocol_sha256':frozen_hash,
            'premium':premium,'aggregates':aggregate,'selection_frequencies':frequencies,'comparisons':comparisons,
            'primary_comparison':next(r for r in comparisons if r['primary']),
            'calibrations':calibrations,'simulation_diagnostics':diagnostics,'discretization':refinement,
            'source_sha256':{path:sha(ROOT/path) for path in source_paths},
            'counts':{'candidate_rows':len(candidates),'selected_rows':len(selected),
                      'independent_replicates_per_scenario':cfg['replicates'],
                      'scenario_count':len(cfg['scenarios']),'candidates_per_fit':len(POLICIES)*len(cfg['forecast_multipliers'])},
            'runtime_seconds':time.perf_counter()-started,
            'environment':{'python':sys.version,'platform':platform.platform(),'numpy':np.__version__},
            'limits':['One primary contrast; all remaining intervals are exploratory pointwise, not simultaneous.',
                      'Independent replicate-level inference includes calibration/selection/test Monte Carlo variability but only for specified generators.',
                      'The reference optimum uses a finite noisy sample and a finite strategy class, not a deployable oracle or a global optimum.',
                      'A signed reference gap for a budget-infeasible selected pair is not feasible constrained regret.',
                      'Shift cases intentionally mismatch validation and test laws; neither law is estimated from real option quotes.',
                      'Expected-shortfall validation with n=16 depends on only 1.6 tail observations; estimator instability is part of the study.',
                      'The Heston scheme has time-discretization bias; refinement figures are diagnostic, not an exact-simulation certificate.']}
    dump(out/'v2_selection_summary.json',result)
    write_csv(out/'v2_selection_candidates.csv',candidates)
    write_csv(out/'v2_selection_choices.csv',selected)
    write_csv(out/'v2_selection_aggregates.csv',aggregate)
    write_csv(out/'v2_selection_frequencies.csv',frequencies)
    write_csv(out/'v2_selection_comparisons.csv',comparisons)
    print(json.dumps({'output':str(out),'seconds':result['runtime_seconds'],'primary':result['primary_comparison']}),flush=True)


if __name__=='__main__':
    main()
