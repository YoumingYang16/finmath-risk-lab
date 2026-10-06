"""Publication figures drawn solely from executed V2 evidence."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'figures';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','svg.fonttype':'none'})
COLORS=['#176B87','#D47D33','#77559A']
SELECTORS=['forecast_first','joint_mse','joint_es90']
LABELS=['Forecast first','Joint MSE','Joint ES90']

def load(name):return json.loads((ROOT/'results'/f'{name}.json').read_text(encoding='utf-8'))
def save(fig,name):
    fig.savefig(OUT/f'{name}.png',dpi=180,bbox_inches='tight',facecolor='white')
    fig.savefig(OUT/f'{name}.svg',bbox_inches='tight',facecolor='white');plt.close(fig)

def main():
    hist=load('v2_historical_summary');sim=load('v2_selection_summary');convex=load('v2_convex_summary');dis=load('v2_discretization')
    for period,label in [('retrospective','2015-2025 retrospective'),('additional_2026','2026 Jan-Sep additional')]:
        fig,axes=plt.subplots(2,3,figsize=(9.2,4.2),layout='constrained')
        for ax,ccy in zip(axes.ravel(),['USD','JPY','GBP','CHF','CAD','AUD']):
            rows=[r for r in hist['primary_comparisons'] if r['currency']==ccy and r['period']==period]
            for i,r in enumerate(rows):
                ax.errorbar(r['difference'],i,xerr=[[r['difference']-r['ci_low']],[r['ci_high']-r['difference']]],fmt='o',color=COLORS[i],capsize=3)
            ax.axvline(0,color='#999999',lw=.8);ax.set_yticks(range(3),['Block 1','Block 3','Block 6']);ax.set_ylim(-.4,2.4);ax.set_title(f'{ccy}  n={rows[0]["n"]}')
            ax.ticklabel_format(axis='x',style='sci',scilimits=(-2,2));ax.grid(axis='x',alpha=.15)
        fig.supxlabel('Term minus flat: mean squared loss difference (negative favors term)')
        fig.suptitle(label+' | pointwise 95% moving-block intervals',fontsize=12)
        save(fig,'v2_history_'+period)
    fig,axes=plt.subplots(2,2,figsize=(9.2,5.8),layout='constrained')
    for ax,scenario in zip(axes.ravel(),['matched_gbm','heston','heston_shift','jump_shift']):
        for selector,color,label in zip(SELECTORS,COLORS,LABELS):
            rows=sorted([r for r in sim['aggregates'] if r['scenario']==scenario and r['selector']==selector and r['fee_bps']==5],key=lambda r:r['validation_n'])
            ax.plot([r['validation_n'] for r in rows],[r['mean_test_mse'] for r in rows],'-o',color=color,label=label)
        ax.set_xscale('log',base=2);ax.set_xticks([16,64,256],['16','64','256']);ax.set_title(scenario.replace('_',' ').title());ax.set_ylabel('Mean test MSE');ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8);fig.supxlabel('Validation paths | 24 independent full-procedure repetitions, 5 bps')
    save(fig,'v2_selection_size')
    fig,axes=plt.subplots(1,2,figsize=(9.2,3.7),layout='constrained')
    rows=[r for r in sim['aggregates'] if r['scenario']=='heston' and r['validation_n']==64 and r['fee_bps']==5]
    rows=sorted(rows,key=lambda r:SELECTORS.index(r['selector']));x=np.arange(3)
    axes[0].bar(x,[r['mean_test_variance'] for r in rows],color=COLORS[0],label='Variance')
    axes[0].bar(x,[r['mean_test_bias_squared'] for r in rows],bottom=[r['mean_test_variance'] for r in rows],color=COLORS[1],label='Squared bias')
    axes[0].set_xticks(x,LABELS,rotation=12);axes[0].set_ylabel('Net MSE decomposition');axes[0].legend(fontsize=8)
    for selector,color,label in zip(SELECTORS,COLORS,LABELS):
        r=next(r for r in rows if r['selector']==selector);axes[1].scatter(r['mean_test_cost'],r['mean_test_es90'],s=75,color=color,label=label)
    axes[1].set_xlabel('Mean cost');axes[1].set_ylabel('Mean test ES90');axes[1].legend(fontsize=8);axes[1].grid(alpha=.2)
    fig.suptitle('Matched Heston | 64 validation paths | 5 bps',fontsize=12)
    save(fig,'v2_selection_tradeoff')
    fig,axes=plt.subplots(1,3,figsize=(9.2,3.3),layout='constrained')
    for ax,metric,title in zip(axes,['es90','mse','mean_cost'],['ES90 difference','MSE difference','Mean cost difference']):
        rows=[r for r in convex['contrasts'] if r['metric']==metric]
        for i,r in enumerate(rows):
            ax.errorbar(r['difference'],i,xerr=[[r['difference']-r['ci_low']],[r['ci_high']-r['difference']]],fmt='o',capsize=4,color=COLORS[i])
        ax.axvline(0,color='#888888',lw=.8);ax.set_yticks([0,1],['Matched','Shifted']);ax.set_ylim(-.5,1.5);ax.set_title(title,fontsize=11);ax.grid(axis='x',alpha=.2)
    fig.supxlabel('CVaR learner minus validation-selected band | 8 independent repetitions | pointwise 95% t intervals')
    save(fig,'v2_convex_contrasts')
    fig,axes=plt.subplots(1,2,figsize=(9.2,3.7),layout='constrained')
    for ax,scenario in zip(axes,['matched_heston','shifted_heston']):
        for name,color,label in zip(['convex_cvar','validation_selected_band','daily'],COLORS,['CVaR learner','Selected band','Daily delta']):
            rows=[r for r in convex['test_rows'] if r['scenario']==scenario and r['method']==name]
            ax.scatter([r['mean_cost'] for r in rows],[r['es90'] for r in rows],color=color,s=35,alpha=.85,label=label)
        ax.set_title(scenario.replace('_',' ').title());ax.set_xlabel('Mean test cost');ax.set_ylabel('Test ES90');ax.grid(alpha=.2)
    axes[0].legend(fontsize=8);fig.suptitle('Each point is one complete training and validation repetition',fontsize=12)
    save(fig,'v2_convex_tradeoff')
    fig,axes=plt.subplots(1,2,figsize=(9.2,3.6),layout='constrained')
    for scenario,color in zip(['heston','heston_shift'],COLORS):
        rows=[r for r in dis['rows'] if r['scenario']==scenario]
        axes[0].errorbar([r['substeps'] for r in rows],[r['terminal_variance_mean'] for r in rows],yerr=[1.96*r['variance_mean_se'] for r in rows],fmt='-o',color=color,label=scenario)
        axes[0].axhline(rows[0]['variance_exact_mean'],ls=':',color=color)
        axes[1].errorbar([r['substeps'] for r in rows],[r['band05_mse'] for r in rows],yerr=[1.96*r['band05_mse_se'] for r in rows],fmt='-o',color=color,label=scenario)
    for ax in axes:ax.set_xscale('log',base=2);ax.set_xticks([1,2,4,8,16],['1','2','4','8','16']);ax.set_xlabel('Substeps per observation');ax.grid(alpha=.2)
    axes[0].set_ylabel('Mean terminal variance');axes[0].legend(fontsize=8);axes[1].set_ylabel('Band05 mean squared loss')
    fig.suptitle('Independent ensembles, 32,768 paths each | bars show Monte Carlo uncertainty',fontsize=12)
    save(fig,'v2_discretization')
    print(json.dumps({'figures':7,'formats':['png','svg'],'source':'executed V2 JSON'},ensure_ascii=False))

if __name__=='__main__':main()
