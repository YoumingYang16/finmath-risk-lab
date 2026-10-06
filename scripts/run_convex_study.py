"""Executed direct-risk-learning extension under a source-frozen protocol."""
from __future__ import annotations
import csv,hashlib,json,sys,time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from risklab.stochastic_volatility import heston_paths
from risklab.pricing import bs_price
from risklab.convex_hedging import fit_cvar_hedge,evaluate_cvar_hedge,causal_design
from risklab.advanced_hedging import band_hedge,risk_summary
from risklab.statistics import paired_mean_ci


def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def csvout(path,rows):
    if not rows:return
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    started=time.perf_counter();protocol=json.loads((ROOT/'docs/v2_protocol.json').read_text(encoding='utf-8'));p=protocol['convex_extension'];s=protocol['simulation'];T=s['horizon'];premium=float(bs_price(100,100,T,0,.2))
    details={'protocol_sha256':hashlib.sha256((ROOT/'docs/v2_protocol.json').read_bytes()).hexdigest(),'training_scenario':'matched_heston','validation_scenario':'matched_heston','test_scenarios':['matched_heston','shifted_heston'],'base_delta_vol':.2,'coefficient_bound':.25,'selection':'Minimum validation ES90 among successful regularization fits with validation mean cost <=0.18; if none feasible pick smallest validation cost and flag fallback','baseline_selection':'Same validation cost budget; select ES90 between band05 and band10; fallback minimum cost','all_results_exploratory':True}
    dump(ROOT/'docs/v2_convex_design.json',details)
    fits=[];choices=[];rows=[];ledgers=[]
    for replicate,seed in enumerate(p['seeds']):
        train=heston_paths(p['training_paths'],21,T,seed=seed,**s['heston'])['prices']
        validation=heston_paths(p['validation_paths'],21,T,seed=seed+100000,**s['heston'])['prices']
        options=[]
        for penalty in p['coefficient_l1_penalties']:
            fit=fit_cvar_hedge(train,premium,budget=p['budget'],cost_bps=p['cost_bps'],alpha=p['alpha'],penalty=penalty)
            entry={'replicate':replicate,'seed':seed,**fit}
            if fit['success']:
                v=evaluate_cvar_hedge(validation,fit,premium);metrics=risk_summary(v['pnl'],v['cost']);entry['validation']=metrics
                options.append((fit,metrics))
                if abs(fit['duality_gap'])>1e-6 or abs(fit['objective_reconciliation_gap'])>1e-6 or fit['max_primal_inequality_violation']>1e-6:raise RuntimeError('LP audit failed')
            fits.append(entry)
        if not options:raise RuntimeError('All LP candidates failed; retain fits and inspect before proceeding')
        feasible=[x for x in options if x[1]['mean_cost']<=p['budget']]
        selected=min(feasible,key=lambda x:(x[1]['es90'],x[0]['penalty'])) if feasible else min(options,key=lambda x:(x[1]['mean_cost'],x[1]['es90']))
        baselines=[]
        for width in [.05,.10]:
            v=band_hedge(validation,100,0,T,.2,premium,{'kind':'band','width':width},p['cost_bps'],None)
            baselines.append((width,risk_summary(v['pnl'],v['cost'])))
        bf=[x for x in baselines if x[1]['mean_cost']<=p['budget']]
        baseline=min(bf,key=lambda x:(x[1]['es90'],x[0])) if bf else min(baselines,key=lambda x:x[1]['mean_cost'])
        choices.append({'replicate':replicate,'seed':seed,'selected_penalty':selected[0]['penalty'],'lp_validation_feasible':bool(feasible),'baseline_width':baseline[0],'baseline_validation_feasible':bool(bf)})
        for scenario,parameters in [('matched_heston',s['heston']),('shifted_heston',s['heston_shift'])]:
            paths=heston_paths(p['test_paths'],21,T,seed=seed+200000,**parameters)['prices']
            learned=evaluate_cvar_hedge(paths,selected[0],premium,record_path=0 if replicate==0 else None)
            band=band_hedge(paths,100,0,T,.2,premium,{'kind':'band','width':baseline[0]},p['cost_bps'],0 if replicate==0 else None)
            daily=band_hedge(paths,100,0,T,.2,premium,{'kind':'fixed','every':1},p['cost_bps'],None)
            # The baseline ledger omits its full position matrix. Reconstruct its
            # exact causal daily delta instead of recording theoretical extrema.
            daily['positions']=causal_design(paths,100,T,.2)[0]
            for name,run in [('convex_cvar',learned),('validation_selected_band',band),('daily',daily)]:
                rows.append({'replicate':replicate,'seed':seed,'scenario':scenario,'method':name,**risk_summary(run['pnl'],run['cost']),
                             'test_budget_exceeded':float(run['cost'].mean())>p['budget'],'position_violation_fraction':run.get('position_violation_fraction',0.),
                             'position_min':run.get('position_min',float(np.min(run.get('positions',[0.])))),'position_max':run.get('position_max',float(np.max(run.get('positions',[1.]))))})
                if replicate==0 and run.get('ledger'):
                    for item in run['ledger']:ledgers.append({'scenario':scenario,'method':name,**item})
        print(f"CVaR replicate {replicate+1}/8 penalty={selected[0]['penalty']} train ES={selected[0]['train_es']:.6f}",flush=True)
    contrasts=[]
    for scenario in ['matched_heston','shifted_heston']:
        for metric in ['es90','mse','mean_cost']:
            a=np.array([r[metric] for r in rows if r['scenario']==scenario and r['method']=='convex_cvar']);b=np.array([r[metric] for r in rows if r['scenario']==scenario and r['method']=='validation_selected_band'])
            contrasts.append({'scenario':scenario,'metric':metric,'contrast':'convex_cvar minus validation_selected_band','unit':'independent training/validation/test repetition','interpretation':'Exploratory pointwise t interval over only eight repetitions; no universal superiority claim',**paired_mean_ci(a,b)})
    sources=['risklab/advanced_hedging.py','risklab/convex_hedging.py','risklab/stochastic_volatility.py','scripts/run_convex_study.py']
    summary={'status':'executed','version':'2.0.0','design':details,'protocol':p,'fits':fits,'choices':choices,'test_rows':rows,'contrasts':contrasts,
             'audit':{'all_fits_successful':all(f['success'] for f in fits),'fits':len(fits),'max_abs_duality_gap':max(abs(f['duality_gap']) for f in fits if f['success']),
                      'max_objective_reconciliation_gap':max(abs(f['objective_reconciliation_gap']) for f in fits if f['success']),'max_constraint_violation':max(f['max_primal_inequality_violation'] for f in fits if f['success'])},
             'limitations':['Finite feature class, not a globally optimal hedging policy or a new optimization theorem.','Training position constraints do not guarantee unseen-state constraints; no action clipping used.','Calibration is synthetic; no real option quotes or market execution.','No neural deep-hedging competitor has been trained; this gap prevents broad state-of-the-art claims.'],
             'runtime_seconds':time.perf_counter()-started,'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}}
    dump(ROOT/'results/v2_convex_summary.json',summary);csvout(ROOT/'results/v2_convex_metrics.csv',rows);csvout(ROOT/'results/v2_convex_choices.csv',choices)
    # Both ledgers use the same bookkeeping fields; the band has an extra desired delta.
    keys=sorted({key for row in ledgers for key in row});csvout(ROOT/'results/v2_convex_ledger.csv',[{key:row.get(key) for key in keys} for row in ledgers])
    print(json.dumps({'seconds':summary['runtime_seconds'],'audit':summary['audit']}))


if __name__=='__main__':main()
