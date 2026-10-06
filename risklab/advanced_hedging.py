"""Boundary rebalancing and a general, independently auditable position ledger.

The band is an execution baseline, not a claimed optimal Whalley-Wilmott band.
Positions supplied to account_positions must already respect information time.
"""
from __future__ import annotations
import numpy as np
from .hedging import hedge_paths
from .pricing import bs_delta


def account_positions(paths, positions, strike, rate, horizon, premium, cost_bps=0., record_path=None):
    paths=np.asarray(paths,float);positions=np.asarray(positions,float)
    if paths.ndim!=2 or paths.shape[1]<2 or positions.shape!=(paths.shape[0],paths.shape[1]-1) or not len(paths):
        raise ValueError('positions must have one pre-return position for each path interval')
    if not np.isfinite(paths).all() or (paths<=0).any() or not np.isfinite(positions).all():
        raise ValueError('finite positions and positive finite prices required')
    for x in [strike,rate,horizon,cost_bps]:
        if np.ndim(x)!=0 or not np.isfinite(x):raise ValueError('finite scalar parameters required')
    if strike<=0 or horizon<=0 or cost_bps<0:raise ValueError('invalid strike, horizon or costs')
    n,columns=paths.shape;steps=columns-1
    premium=np.broadcast_to(np.asarray(premium,float),(n,)).copy()
    if not np.isfinite(premium).all() or (premium<0).any():raise ValueError('nonnegative finite premiums required')
    if record_path is not None and (isinstance(record_path,(bool,np.bool_)) or not isinstance(record_path,(int,np.integer)) or not 0<=record_path<n):raise ValueError('invalid record_path')
    dt=horizon/steps;cash=premium.copy();held=np.zeros(n);fees=np.zeros(n);turnover=np.zeros(n);trades=np.zeros(n,int);ledger=[]
    with np.errstate(over='raise'):
        interest_factor=np.expm1(rate*dt);terminal=np.exp(rate*(horizon-np.arange(columns)*dt))
    for j in range(columns):
        before=cash.copy() if record_path is not None else None
        interest=np.zeros(n) if j==0 else cash*interest_factor;cash+=interest
        target=positions[:,j] if j<steps else np.zeros(n)
        trade=target-held;notional=np.abs(trade)*paths[:,j];fee=notional*cost_bps/1e4
        payoff=np.maximum(paths[:,j]-strike,0) if j==steps else np.zeros(n)
        cash-=trade*paths[:,j]+fee+payoff;held=target.copy();fees+=fee*terminal[j];turnover+=notional;trades+=(trade!=0)
        if record_path is not None:
            i=record_path
            ledger.append({'step':j,'time':j*dt,'event':'entry' if j==0 else 'settlement' if j==steps else 'observation','spot':float(paths[i,j]),'position':float(held[i]),'trade':float(trade[i]),'cash_before':float(before[i]),'interest':float(interest[i]),'fee':float(fee[i]),'terminal_value_fee':float(fee[i]*terminal[j]),'payoff':float(payoff[i]),'cash_after':float(cash[i]),'wealth':float(cash[i]+held[i]*paths[i,j]),'cumulative_cost':float(fees[i]),'cumulative_turnover':float(turnover[i])})
    if not np.isfinite(cash).all() or not np.isfinite(fees).all():raise ValueError('nonfinite accounting output')
    return {'pnl':cash,'cost':fees,'turnover':turnover,'trades':trades,'ledger':ledger,'positions':positions}


def band_hedge(paths,strike,rate,horizon,hedge_vol,premium,policy=None,cost_bps=0.,record_path=0):
    policy={'kind':'fixed','every':1} if policy is None else dict(policy)
    if policy.get('kind') in {'fixed','threshold'}:
        return hedge_paths(paths,strike,rate,horizon,hedge_vol,premium,policy=policy,cost_bps=cost_bps,record_path=record_path)
    if policy.get('kind')!='band' or set(policy)-{'kind','width'}:raise ValueError('unsupported policy')
    width=policy.get('width',.05)
    if np.ndim(width)!=0 or not np.isfinite(width) or width<0:raise ValueError('nonnegative finite band width required')
    paths=np.asarray(paths,float)
    if paths.ndim!=2 or not len(paths) or paths.shape[1]<2:raise ValueError('invalid paths')
    n,columns=paths.shape;steps=columns-1
    vol=np.asarray(hedge_vol,float)
    if vol.ndim!=0 and vol.shape!=(n,steps):raise ValueError('vol shape must be scalar or path by decision')
    if horizon<=0:raise ValueError('positive horizon required')
    tau=horizon-np.arange(steps)*(horizon/steps)
    desired=np.asarray(bs_delta(paths[:,:-1],strike,tau[None,:],rate,vol),float)
    positions=np.empty_like(desired);positions[:,0]=desired[:,0]
    for j in range(1,steps):positions[:,j]=np.clip(positions[:,j-1],desired[:,j]-width,desired[:,j]+width)
    result=account_positions(paths,positions,strike,rate,horizon,premium,cost_bps,record_path)
    if record_path is not None:
        for j,row in enumerate(result['ledger']):row['desired_delta']=float(desired[record_path,j]) if j<steps else 0.
    return result


def empirical_es(loss,alpha=.90):
    loss=np.asarray(loss,float)
    if loss.ndim!=1 or not len(loss) or not np.isfinite(loss).all() or not 0<alpha<1:raise ValueError('finite nonempty losses and alpha in (0,1) required')
    values=np.sort(loss)[::-1];mass=(1-alpha)*len(values);whole=int(np.floor(mass));fraction=mass-whole
    return float((values[:whole].sum()+(fraction*values[whole] if fraction>0 else 0))/mass)


def risk_summary(pnl,cost=None,alpha=.9):
    pnl=np.asarray(pnl,float)
    if pnl.ndim!=1 or not len(pnl) or not np.isfinite(pnl).all():raise ValueError('finite nonempty one-dimensional pnl required')
    mean=float(pnl.mean());variance=float(pnl.var(ddof=0));mse=float(np.mean(pnl**2))
    result={'n':len(pnl),'mean_pnl':mean,'bias_squared':mean**2,'variance_pnl':variance,'mse':mse,'rmse':float(np.sqrt(mse)),'es90':empirical_es(-pnl,alpha),'es_alpha':alpha}
    if cost is not None:
        cost=np.asarray(cost,float)
        if cost.shape!=pnl.shape or not np.isfinite(cost).all() or (cost<0).any():raise ValueError('cost must be aligned nonnegative finite values')
        result.update(mean_cost=float(cost.mean()),gross_mse=float(np.mean((pnl+cost)**2)))
    return result
