"""Self-financing, zero-dividend discrete hedge ledger for a short option.

At t=0 receive premium and buy the delta hedge. Cash then accrues at r; at each
interior observation rebalance using only the current spot and supplied current
volatility, before the NEXT price change. At expiry liquidate stock, pay its
transaction fee and pay the option payoff. Borrowing/lending share rate r.
There is no default/margin constraint or artificial insolvency stop. No cash
injections are allowed. Cost is accumulated to maturity at the cash rate, while
turnover is raw absolute traded currency notional. No dividends are supported.
"""

from __future__ import annotations

import numpy as np

from .pricing import bs_delta


def _scalar(value, name):
    if np.ndim(value) != 0 or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite scalar")
    return float(value)


def hedge_paths(paths, strike, rate, horizon, hedge_vol, premium, policy=None,
                cost_bps=0.0, kind="call", record_path=0):
    """Vectorized path ensemble with one fully auditable sample ledger.

    ``premium`` can be scalar or an (n_paths,) vector. ``hedge_vol`` is scalar
    or an (n_paths, steps) matrix; column j must be information available at
    observation j. No estimator is fitted inside this routine. A fixed policy
    trades at j divisible by every; a threshold policy trades when absolute
    desired-versus-held delta >= threshold. Both always establish the initial
    desired position. record_path=None disables ledger construction.

    Ledger records include cash_before (before that observation's interest),
    interest, trade, fee, cash_after, stock position and post-trade wealth.
    At maturity cash_after and wealth also deduct payoff. The sum of fees
    grown at r equals the returned cost, not the sum of nominal fee entries.
    """
    paths = np.asarray(paths, dtype=float)
    if paths.ndim != 2 or paths.shape[0] < 1 or paths.shape[1] < 2:
        raise ValueError("paths must have shape (n_paths, steps+1), with steps>=1")
    if not np.all(np.isfinite(paths)) or np.any(paths <= 0):
        raise ValueError("all path prices must be finite and strictly positive")
    n, columns = paths.shape
    steps = columns - 1
    strike, rate, horizon, cost_bps = [_scalar(v, name) for v, name in
                                     [(strike, "strike"), (rate, "rate"), (horizon, "horizon"), (cost_bps, "cost_bps")]]
    if strike <= 0 or horizon <= 0 or cost_bps < 0:
        raise ValueError("strike/horizon must be positive and cost_bps nonnegative")
    if kind not in {"call", "put"}:
        raise ValueError("kind must be call or put")
    volatility = np.asarray(hedge_vol, dtype=float)
    if volatility.ndim != 0 and volatility.shape != (n, steps):
        raise ValueError("hedge_vol must be scalar or have shape (n_paths,steps)")
    if not np.all(np.isfinite(volatility)) or np.any(volatility < 0):
        raise ValueError("hedge_vol must be finite and nonnegative")
    prem = np.asarray(premium, dtype=float)
    if prem.ndim == 0:
        prem = np.full(n, float(prem))
    if prem.shape != (n,) or not np.all(np.isfinite(prem)) or np.any(prem < 0):
        raise ValueError("premium must be nonnegative finite scalar or path vector")
    policy = {"kind": "fixed", "every": 1} if policy is None else dict(policy)
    policy_kind = policy.get("kind")
    if policy_kind == "fixed":
        if set(policy) - {"kind", "every"}:
            raise ValueError("unsupported fixed-policy key")
        every = policy.get("every", 1)
        if isinstance(every, (bool, np.bool_)) or not isinstance(every, (int, np.integer)) or every < 1:
            raise ValueError("every must be a positive integer")
    elif policy_kind == "threshold":
        if set(policy) - {"kind", "threshold"}:
            raise ValueError("unsupported threshold-policy key")
        threshold = _scalar(policy.get("threshold", 0.05), "threshold")
        if threshold < 0:
            raise ValueError("threshold must be nonnegative")
    else:
        raise ValueError("policy kind must be fixed or threshold")
    if record_path is not None and (isinstance(record_path, (bool, np.bool_)) or
                                   not isinstance(record_path, (int, np.integer)) or not 0 <= record_path < n):
        raise ValueError("record_path must be None or a valid integer path index")
    dt = horizon / steps
    with np.errstate(over="ignore", invalid="ignore"):
        accrual = np.exp(rate * dt)
        interest_factor = np.expm1(rate * dt)
        terminal_factors = np.exp(rate * (horizon - np.arange(steps + 1) * dt))
    if not np.isfinite(accrual) or not np.isfinite(interest_factor) or not np.all(np.isfinite(terminal_factors)):
        raise ValueError("rate/horizon cause nonfinite cash accrual")
    cash = prem.copy()
    position = np.zeros(n)
    cost = np.zeros(n)
    turnover = np.zeros(n)
    trades = np.zeros(n, dtype=np.int64)
    ledger = []
    fee_rate = cost_bps / 10000.0
    for j in range(steps + 1):
        before = cash.copy() if record_path is not None else None
        interest = np.zeros(n) if j == 0 else cash * interest_factor
        cash = cash + interest
        spot = paths[:, j]
        terminal = j == steps
        if terminal:
            desired = np.zeros(n)
            do_trade = np.ones(n, dtype=bool)
        else:
            vol_j = volatility if volatility.ndim == 0 else volatility[:, j]
            desired = bs_delta(spot, strike, horizon - j * dt, rate, vol_j, kind)
            if j == 0:
                do_trade = np.ones(n, dtype=bool)
            elif policy_kind == "fixed":
                do_trade = np.full(n, j % every == 0)
            else:
                do_trade = np.abs(desired - position) >= threshold
        trade = np.where(do_trade, desired - position, 0.0)
        notional = np.abs(trade) * spot
        fee = fee_rate * notional
        cash -= trade * spot + fee
        position = position + trade
        cost += fee * terminal_factors[j]
        turnover += notional
        trades += (trade != 0).astype(np.int64)
        payoff = np.maximum((1.0 if kind == "call" else -1.0) * (spot - strike), 0.0) if terminal else np.zeros(n)
        cash -= payoff
        if record_path is not None:
            i = record_path
            record = {"step": j, "time": float(j * dt),
                      "event": "entry" if j == 0 else ("settlement" if terminal else "observation"),
                      "spot": float(spot[i]), "hedge_vol": None if terminal else float(vol_j if np.ndim(vol_j) == 0 else vol_j[i]),
                      "desired_delta": float(desired[i]), "trade": float(trade[i]),
                      "position": float(position[i]), "cash_before": float(before[i]),
                      "interest": float(interest[i]), "fee": float(fee[i]),
                      "terminal_value_fee": float(fee[i] * terminal_factors[j]),
                      "payoff": float(payoff[i]), "cash_after": float(cash[i]),
                      "wealth": float(cash[i] + position[i] * spot[i]),
                      "cumulative_cost": float(cost[i]), "cumulative_turnover": float(turnover[i])}
            if not all(np.isfinite(value) for key, value in record.items() if key not in {"event", "hedge_vol"}):
                raise ValueError("parameters cause nonfinite ledger value")
            ledger.append(record)
    if not all(np.all(np.isfinite(x)) for x in (cash, cost, turnover)):
        raise ValueError("parameters cause nonfinite hedge output")
    return {"pnl": cash, "cost": cost, "turnover": turnover, "trades": trades, "ledger": ledger}
