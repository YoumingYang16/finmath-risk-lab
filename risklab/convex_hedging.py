"""Finite-feature CVaR hedging as a sparse linear program.

With fixed causal features and no action clipping, gains are affine in theta,
and proportional costs are convex piecewise linear. An absolute-trade epigraph
and CVaR excess-loss epigraph therefore give an LP. This is a known convex
construction, not a claim of a new hedging algorithm or global policy optimum.
"""
from __future__ import annotations
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .pricing import bs_delta
from .advanced_hedging import account_positions,empirical_es


def causal_design(paths,strike=100.,horizon=21/252,vol=.2):
    paths=np.asarray(paths,float)
    if paths.ndim!=2 or not len(paths) or paths.shape[1]<2 or not np.isfinite(paths).all() or (paths<=0).any():raise ValueError('positive finite path matrix required')
    if not np.isfinite(strike) or strike<=0 or not np.isfinite(horizon) or horizon<=0 or not np.isfinite(vol) or vol<=0:raise ValueError('positive finite strike, horizon and vol required')
    n,columns=paths.shape;steps=columns-1;remaining=(steps-np.arange(steps))/steps
    base=bs_delta(paths[:,:-1],strike,horizon*remaining[None,:],0,vol)
    # Clipping a fixed observable feature preserves affinity in learned theta.
    phi=np.stack([np.ones_like(base),np.clip(np.log(paths[:,:-1]/strike)/.1,-3,3),np.broadcast_to(remaining,base.shape),4*base*(1-base)],axis=2)
    return base,phi


def learned_positions(paths,theta,strike=100.,horizon=21/252,vol=.2):
    base,phi=causal_design(paths,strike,horizon,vol);theta=np.asarray(theta,float)
    if theta.shape!=(phi.shape[-1],) or not np.isfinite(theta).all():raise ValueError('finite coefficient vector required')
    return base+np.einsum('ntp,p->nt',phi,theta)


def fit_cvar_hedge(paths,premium,strike=100.,horizon=21/252,vol=.2,cost_bps=5.,budget=.18,alpha=.9,penalty=.01,coefficient_bound=.25):
    """Fit on provided training paths. This API is restricted to zero rates.

    Position and mean-cost constraints are SAMPLE constraints. Coefficients
    are bounded but future positions need not stay inside [0,1]; callers must
    report violations and may not silently clip the optimized policy.
    """
    paths=np.asarray(paths,float);base,phi=causal_design(paths,strike,horizon,vol)
    n,steps=base.shape;p=phi.shape[-1]
    if n<10:raise ValueError('at least ten training paths required')
    for x in [cost_bps,budget,alpha,penalty,coefficient_bound]:
        if np.ndim(x)!=0 or not np.isfinite(x):raise ValueError('finite scalar objective parameters required')
    if cost_bps<=0 or budget<0 or not 0<alpha<1 or penalty<0 or coefficient_bound<=0:raise ValueError('invalid objective parameters')
    premium=np.broadcast_to(np.asarray(premium,float),(n,)).copy()
    if not np.isfinite(premium).all() or (premium<0).any():raise ValueError('finite nonnegative premium required')
    dbase=np.diff(np.pad(base,((0,0),(1,1))),axis=1)
    dphi=np.diff(np.pad(phi,((0,0),(1,1),(0,0))),axis=1)
    increments=np.diff(paths,axis=1);gbase=np.sum(base*increments,axis=1);gphi=np.einsum('ntp,nt->np',phi,increments)
    loss_base=np.maximum(paths[:,-1]-strike,0)-premium-gbase
    trades=n*(steps+1);state_rows=n*steps
    # Variables theta[p], abs(theta)[p], eta[1], tail excess[n], abs(trade)[trades].
    eta_index=2*p;excess_start=eta_index+1;trade_start=excess_start+n;dimension=trade_start+trades
    empty=lambda rows,cols:sparse.csr_matrix((rows,cols))
    trade_matrix=sparse.csr_matrix(dphi.reshape(trades,p));ident=sparse.eye(trades,format='csr')
    middle=empty(trades,p+1+n)
    absolute_a=sparse.hstack([trade_matrix,middle,-ident],format='csr')
    absolute_b=sparse.hstack([-trade_matrix,middle,-ident],format='csr')
    costs=(cost_bps/1e4*paths).ravel()
    path_cost=sparse.csr_matrix((costs,(np.repeat(np.arange(n),steps+1),np.arange(trades))),shape=(n,trades))
    tail=sparse.hstack([-sparse.csr_matrix(gphi),empty(n,p),-np.ones((n,1)),-sparse.eye(n),path_cost],format='csr')
    flat_phi=sparse.csr_matrix(phi.reshape(state_rows,p))
    position_a=sparse.hstack([flat_phi,empty(state_rows,dimension-p)],format='csr')
    position_b=sparse.hstack([-flat_phi,empty(state_rows,dimension-p)],format='csr')
    cost_row=sparse.hstack([empty(1,trade_start),sparse.csr_matrix(costs.reshape(1,-1)/n)],format='csr')
    norm_a=sparse.hstack([sparse.eye(p),-sparse.eye(p),empty(p,dimension-2*p)],format='csr')
    norm_b=sparse.hstack([-sparse.eye(p),-sparse.eye(p),empty(p,dimension-2*p)],format='csr')
    A=sparse.vstack([absolute_a,absolute_b,tail,position_a,position_b,cost_row,norm_a,norm_b],format='csr')
    b=np.concatenate([-dbase.ravel(),dbase.ravel(),-loss_base,1-base.ravel(),base.ravel(),[budget],np.zeros(2*p)])
    objective=np.zeros(dimension);objective[p:2*p]=penalty;objective[eta_index]=1;objective[excess_start:trade_start]=1/((1-alpha)*n)
    bounds=[(-coefficient_bound,coefficient_bound)]*p+[(0,None)]*p+[(None,None)]+[(0,None)]*(n+trades)
    res=linprog(objective,A_ub=A,b_ub=b,bounds=bounds,method='highs',options={'primal_feasibility_tolerance':1e-8,'dual_feasibility_tolerance':1e-8})
    common={'success':bool(res.success),'solver_status':int(res.status),'message':res.message,'n_train':n,'variables':dimension,'constraints':len(b),'alpha':alpha,'penalty':penalty,'budget':budget,'cost_bps':cost_bps,'iterations':int(res.nit),'feature_names':['intercept','clipped_log_moneyness','remaining_fraction','delta_curvature_proxy']}
    if not res.success:return common
    theta=res.x[:p];positions=base+np.einsum('ntp,p->nt',phi,theta)
    accounted=account_positions(paths,positions,strike,0,horizon,premium,cost_bps)
    exact=empirical_es(-accounted['pnl'],alpha)+penalty*np.sum(np.abs(theta))
    dual=float(b@res.ineqlin.marginals)
    for i,(low,high) in enumerate(bounds):
        if low is not None:dual+=low*res.lower.marginals[i]
        if high is not None:dual+=high*res.upper.marginals[i]
    stationarity=objective-A.T@res.ineqlin.marginals-res.lower.marginals-res.upper.marginals
    common.update(theta=theta.tolist(),objective=float(res.fun),independent_objective=float(exact),objective_reconciliation_gap=float(res.fun-exact),dual_objective=dual,duality_gap=float(res.fun-dual),max_primal_inequality_violation=float(max(0,np.max(A@res.x-b))),max_stationarity_residual=float(np.max(np.abs(stationarity))),train_mean_cost=float(accounted['cost'].mean()),train_position_min=float(positions.min()),train_position_max=float(positions.max()),train_es=float(empirical_es(-accounted['pnl'],alpha)),coefficient_l1=float(np.abs(theta).sum()))
    return common


def evaluate_cvar_hedge(paths,fit,premium,strike=100.,horizon=21/252,vol=.2,record_path=None):
    if not fit.get('success'):raise ValueError('cannot evaluate an unsuccessful fit')
    positions=learned_positions(paths,fit['theta'],strike,horizon,vol)
    run=account_positions(paths,positions,strike,0,horizon,premium,fit['cost_bps'],record_path)
    run['position_violation_fraction']=float(np.mean((positions < -1e-8)|(positions > 1+1e-8)))
    run['position_min']=float(positions.min());run['position_max']=float(positions.max())
    return run
