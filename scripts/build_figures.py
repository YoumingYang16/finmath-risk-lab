"""Publication figures generated exclusively from saved executed experiments."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'figures'
OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','figure.dpi':140,'savefig.dpi':220,'svg.fonttype':'none'})
COLORS=['#147d80','#dc8436','#253e62','#8b69a8','#809085','#bf5360']


def save(fig,name):
    fig.savefig(OUT/f'{name}.png',bbox_inches='tight',facecolor='white')
    fig.savefig(OUT/f'{name}.svg',bbox_inches='tight',facecolor='white')
    plt.close(fig)


def main():
    sim=json.loads((ROOT/'results/simulation_summary.json').read_text(encoding='utf-8'))
    df=pd.DataFrame(sim['rows']);test=df[df.split=='test']
    numeric=pd.DataFrame(sim['numerical']['rows'])
    fig,ax=plt.subplots(1,2,figsize=(10,3.5))
    c=numeric[numeric.method=='CRR'];ax[0].loglog(c['size'],c.absolute_error,'o-',color=COLORS[0]);ax[0].set(xlabel='Tree steps',ylabel='Absolute price error',title='CRR convergence to analytic price')
    for i,m in enumerate(['MC plain','MC antithetic']):
        a=numeric[numeric.method==m];ax[1].loglog(a['size'],a.standard_error,'o-',label=m,color=COLORS[i])
    ax[1].set(xlabel='Total terminal draws',ylabel='Estimated standard error',title='Monte Carlo uncertainty');ax[1].legend(frameon=False)
    fig.tight_layout();save(fig,'01_numerical')
    fig,axs=plt.subplots(1,3,figsize=(11,4),sharey=True)
    for ax,fee in zip(axs,[0,5,20]):
        pivot=test[test.fee_bps==fee].pivot(index='scenario',columns='policy',values='rmse').reindex(columns=['daily','every5','every21','band02','band05','band10'])
        im=ax.imshow(pivot.to_numpy(),vmin=0,vmax=float(test.rmse.max()),cmap='YlGnBu',aspect='auto')
        ax.set_xticks(range(6),pivot.columns,rotation=60,ha='right');ax.set_yticks(range(7),pivot.index);ax.set_title(f'{fee} bps')
        for i in range(7):
            for j in range(6):
                val=pivot.iloc[i,j];ax.text(j,i,f'{val:.2f}',ha='center',va='center',fontsize=8,color='white' if val>test.rmse.max()*.57 else '#152d42')
    fig.subplots_adjust(left=.06,right=.88,bottom=.23,wspace=.12);bar=fig.add_axes([.90,.24,.018,.65]);fig.colorbar(im,cax=bar,label='Test net P&L RMSE');save(fig,'02_scenario_risk')
    fig,axs=plt.subplots(1,3,figsize=(10.5,3.4),sharey=True)
    for ax,fee in zip(axs,[0,5,20]):
        for i,(name,g) in enumerate(test[(test.scenario=='S1')&(test.fee_bps==fee)].groupby('policy',sort=False)):
            ax.scatter(g.mean_cost,g.rmse,s=65,color=COLORS[i],label=name)
        ax.axvline(.5,color='#697782',ls='--',lw=1);ax.set(xlabel='Mean terminal-value cost',title=f'Matched GBM / {fee} bps');ax.grid(alpha=.15)
    axs[0].set_ylabel('Test net P&L RMSE');axs[2].legend(frameon=False,fontsize=8);fig.tight_layout();save(fig,'03_cost_risk')
    comparisons=pd.DataFrame(sim['paired_comparisons']);a=comparisons[comparisons.fee_bps==5].iloc[::-1]
    fig,ax=plt.subplots(figsize=(9,3.7));x=a.difference.to_numpy();y=np.arange(len(a));ax.errorbar(x,y,xerr=np.vstack([x-a.ci_low.to_numpy(),a.ci_high.to_numpy()-x]),fmt='o',color=COLORS[0],capsize=3)
    ax.axvline(0,color='#888',lw=1);ax.set_yticks(y,[f'{s}: {p}' for s,p in zip(a.scenario,a.selected_policy)]);ax.set(xlabel='Mean squared loss difference vs every5 (negative favors selected)',title='5 bps / independent paired test paths');ax.text(.01,-.25,'S1 is primary. Other intervals are exploratory and pointwise.',transform=ax.transAxes,fontsize=9);fig.tight_layout();save(fig,'04_paired_comparisons')
    hist=json.loads((ROOT/'results/historical_summary.json').read_text(encoding='utf-8'))
    forecasts=pd.read_csv(ROOT/'results/historical_forecasts.csv');episodes=pd.read_csv(ROOT/'results/historical_episodes.csv')
    fig,axs=plt.subplots(2,1,figsize=(10,5.5),sharex=True)
    for ax,currency in zip(axs,['USD','JPY']):
        g=forecasts[(forecasts.currency==currency)&(forecasts.split=='test')].copy();dates=pd.to_datetime(g.target_date)
        for i,col in enumerate(['rolling63','ewma','ridge']):
            ax.plot(dates,np.sqrt(252*g[col]),label=col,color=COLORS[i],lw=1,alpha=.9)
        ax.set_ylabel(f'{currency}/EUR\nAnnualized volatility');ax.grid(alpha=.15)
    axs[0].legend(ncol=3,frameon=False,loc='upper left');axs[0].set_title('Causal forecasts on held-out observations / 2021–2025');fig.tight_layout();save(fig,'05_historical_volatility')
    fig,axs=plt.subplots(1,2,figsize=(10,3.7))
    for ax,currency in zip(axs,['USD','JPY']):
        metrics=hist['currencies'][currency]['forecast_evaluation']['test']['metrics'];base=metrics['rolling63']['qlike']
        models=list(metrics);values=[metrics[m]['qlike']-base for m in models]
        ax.barh(models,values,color=[COLORS[2],COLORS[4],COLORS[0],COLORS[1]]);ax.axvline(0,color='#777',lw=1);ax.set(title=currency+' per EUR',xlabel='Test QLIKE difference vs rolling63');ax.invert_yaxis()
    fig.tight_layout();save(fig,'06_forecast_comparison')
    fig,axs=plt.subplots(1,2,figsize=(10.5,4),sharey=True)
    names=['frozen_rolling63_daily','rolling63_daily','ewma_daily','ridge_daily','selected_every5','selected_threshold']
    for ax,currency in zip(axs,['USD','JPY']):
        g=episodes[(episodes.currency==currency)&(episodes.split=='test')&(episodes.cost_bps==5)]
        for i,strategy in enumerate(names):
            a=g[g.strategy==strategy];ax.scatter(a.cost.mean(),np.sqrt(np.mean(a.pnl**2)),s=75,color=COLORS[i],label=strategy)
        ax.axvline(.12,color='#888',ls='--',lw=1);ax.set(title=currency+' per EUR / 5 bps',xlabel='Mean transaction cost');ax.grid(alpha=.15)
    axs[0].set_ylabel('Test net P&L RMSE');fig.legend(*axs[0].get_legend_handles_labels(),loc='lower center',ncol=3,fontsize=8,frameon=False);fig.subplots_adjust(bottom=.30,wspace=.20);save(fig,'07_historical_hedging')
    fig,axs=plt.subplots(1,2,figsize=(10.5,3.6))
    for ax,currency in zip(axs,['USD','JPY']):
        intervals=hist['currencies'][currency]['forecast_evaluation']['test_loss_difference_intervals'];rows=[r for r in intervals if r['candidate']=='ridge' and r['metric']=='qlike']
        for i,r in enumerate(rows):
            ax.errorbar(r['mean'],i,xerr=[[r['mean']-r['ci_low']],[r['ci_high']-r['mean']]],fmt='o',capsize=4,color=COLORS[0])
        ax.axvline(0,color='#888',lw=1);ax.set_yticks(range(len(rows)),[f"Block {r['block_length']}" for r in rows]);ax.set(title=currency+' per EUR',xlabel='Ridge minus rolling63 QLIKE');ax.set_ylim(-.5,len(rows)-.5)
    fig.suptitle('95% moving-block intervals / pointwise, conditional on selection',fontsize=11);fig.tight_layout();save(fig,'08_block_sensitivity')
    print(json.dumps({'figures':len(list(OUT.glob('*.png'))),'directory':str(OUT)}))


if __name__=='__main__':
    main()
