#!/usr/bin/env python
"""Calibrate Kelly criterion parameters from historical IC backtest data.

Runs Iron Condor simulations matching live config (USDC linear options)
and extracts win_rate, avg_win, avg_loss for the position sizer.

Tests multiple scenarios:
- Various entry conditions (strict vs relaxed)
- Individual DTEs
- Different profit targets

Output: Calibrated SizingConfig parameters for position_sizer.py

Usage:
    python scripts/calibrate_kelly_params.py
"""

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---- IC structure (from paper_trading.py ic_config) ----
SHORT_DELTA = 0.15
WING_DELTA = 0.05
BID_ASK_SPREAD_PCT = 0.03  # 3% per leg

# DTE range (calibrated Session 50)
DTE_MIN = 23
DTE_MAX = 55
TEST_DTES = [25, 28, 30, 35, 42, 45, 53]

# IV rank lookback
IV_RANK_LOOKBACK = 252
RV_LOOKBACK = 30

# Minimum gap between entries
MIN_GAP_DAYS = 7


# ---- Black-Scholes ----

def bs_put(S: float, K: float, T: float, sigma: float) -> float:
    """Put price as fraction of spot."""
    if T <= 0:
        return max(K - S, 0) / S
    d1 = (np.log(S / K) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return (K * norm.cdf(-d2) - S * norm.cdf(-d1)) / S


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    """Call price as fraction of spot."""
    if T <= 0:
        return max(S - K, 0) / S
    d1 = (np.log(S / K) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return (S * norm.cdf(d1) - K * norm.cdf(d2)) / S


def delta_to_strike(spot: float, delta: float, dte: int, iv: float, option_type: str) -> float:
    """Convert delta to strike price."""
    T = dte / 365
    sigma = iv / 100
    if option_type == "put":
        d1 = -norm.ppf(abs(delta))
    else:
        d1 = norm.ppf(delta)
    exponent = d1 * sigma * np.sqrt(T) - 0.5 * sigma**2 * T
    return spot / np.exp(exponent)


# ---- Data ----

def load_data(db_path: str = "data/trading.db") -> list[dict]:
    """Load historical ETH data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, btc_price, dvol
        FROM historical_data
        WHERE dvol IS NOT NULL
        ORDER BY timestamp
    """)
    data = []
    for row in cursor.fetchall():
        data.append({
            "timestamp": datetime.fromisoformat(row[0]),
            "price": row[1],
            "dvol": row[2],
        })
    conn.close()
    return data


def calc_iv_rank(data: list[dict], idx: int) -> Optional[float]:
    if idx < IV_RANK_LOOKBACK:
        return None
    cur = data[idx]["dvol"]
    hist = [data[i]["dvol"] for i in range(idx - IV_RANK_LOOKBACK, idx)]
    lo, hi = min(hist), max(hist)
    return (cur - lo) / (hi - lo) if hi != lo else 0.5


def calc_rv30(data: list[dict], idx: int) -> Optional[float]:
    if idx < RV_LOOKBACK:
        return None
    prices = [data[i]["price"] for i in range(idx - RV_LOOKBACK, idx + 1)]
    rets = [np.log(prices[i + 1] / prices[i]) for i in range(len(prices) - 1)]
    return float(np.std(rets) * np.sqrt(365) * 100) if len(rets) >= 2 else None


# ---- IC simulation ----

@dataclass
class ICTrade:
    entry_date: datetime
    exit_date: datetime
    dte: int
    entry_price: float
    dvol: float
    iv_rank: float
    iv_rv_spread: float
    net_credit: float
    max_loss: float
    pnl: float
    pnl_usd: float
    win: bool
    exit_reason: str


def simulate_ic(data, entry_idx, dte, iv_rank, iv_rv_spread, profit_target):
    if entry_idx + dte >= len(data):
        return None

    entry = data[entry_idx]
    S = entry["price"]
    iv = entry["dvol"]
    sigma = iv / 100
    T = dte / 365

    sp_K = delta_to_strike(S, -SHORT_DELTA, dte, iv, "put")
    lp_K = delta_to_strike(S, -WING_DELTA, dte, iv, "put")
    sc_K = delta_to_strike(S, SHORT_DELTA, dte, iv, "call")
    lc_K = delta_to_strike(S, WING_DELTA, dte, iv, "call")

    sp_p = bs_put(S, sp_K, T, sigma)
    lp_p = bs_put(S, lp_K, T, sigma)
    sc_p = bs_call(S, sc_K, T, sigma)
    lc_p = bs_call(S, lc_K, T, sigma)

    gross = (sp_p + sc_p) - (lp_p + lc_p)
    cost = 4 * BID_ASK_SPREAD_PCT * gross
    net = gross - cost
    if net <= 0:
        return None

    put_w = (sp_K - lp_K) / S
    call_w = (lc_K - sc_K) / S
    max_loss = max(put_w, call_w) - net

    exit_reason = None
    exit_idx = entry_idx

    for i in range(1, dte + 1):
        if entry_idx + i >= len(data):
            break
        cur = data[entry_idx + i]
        cp = cur["price"]
        ci = cur["dvol"]
        dr = dte - i

        if cp < sp_K:
            exit_reason = "breached_put"
            exit_idx = entry_idx + i
            break
        if cp > sc_K:
            exit_reason = "breached_call"
            exit_idx = entry_idx + i
            break

        if dr > 0:
            s = ci / 100
            t = dr / 365
            cv = (bs_put(cp, sp_K, t, s) + bs_call(cp, sc_K, t, s)
                  - bs_put(cp, lp_K, t, s) - bs_call(cp, lc_K, t, s))
        else:
            cv = (max(sp_K - cp, 0) / cp + max(cp - sc_K, 0) / cp
                  - max(lp_K - cp, 0) / cp - max(cp - lc_K, 0) / cp)

        if gross - cv >= gross * profit_target:
            exit_reason = "profit_target"
            exit_idx = entry_idx + i
            break
        exit_idx = entry_idx + i

    if exit_reason is None:
        ep = data[exit_idx]["price"]
        if sp_K <= ep <= sc_K:
            exit_reason = "expiry_win"
        elif ep < sp_K:
            exit_reason = "breached_put"
        else:
            exit_reason = "breached_call"

    ep = data[exit_idx]["price"]

    if exit_reason == "profit_target":
        exit_cost = 4 * BID_ASK_SPREAD_PCT * gross * 0.5
        pnl = net * profit_target - exit_cost
    elif exit_reason == "expiry_win":
        pnl = net
    elif exit_reason == "breached_put":
        intr = min((sp_K - ep) / S, put_w)
        pnl = net - intr
    elif exit_reason == "breached_call":
        intr = min((ep - sc_K) / S, call_w)
        pnl = net - intr
    else:
        pnl = 0

    return ICTrade(
        entry_date=entry["timestamp"],
        exit_date=data[exit_idx]["timestamp"],
        dte=dte,
        entry_price=S,
        dvol=iv,
        iv_rank=iv_rank,
        iv_rv_spread=iv_rv_spread,
        net_credit=net,
        max_loss=max_loss,
        pnl=pnl,
        pnl_usd=pnl * S,
        win=pnl > 0,
        exit_reason=exit_reason,
    )


# ---- Backtest runner ----

def run_backtest(data, min_iv_rank, min_spread, profit_target, target_dte=None):
    """Run IC backtest with given entry conditions.

    If target_dte is specified, only use that DTE.
    Otherwise, try all TEST_DTES and pick first valid.
    """
    trades = []
    last_entry_idx = -MIN_GAP_DAYS
    start_idx = max(IV_RANK_LOOKBACK, RV_LOOKBACK)

    for i in range(start_idx, len(data)):
        if i - last_entry_idx < MIN_GAP_DAYS:
            continue

        iv_rank = calc_iv_rank(data, i)
        if iv_rank is None:
            continue

        rv30 = calc_rv30(data, i)
        if rv30 is None:
            continue

        dvol = data[i]["dvol"]
        spread = dvol - rv30

        if iv_rank < min_iv_rank:
            continue
        if min_spread is not None and spread < min_spread:
            continue

        dtes = [target_dte] if target_dte else TEST_DTES
        for dte in dtes:
            if dte < DTE_MIN or dte > DTE_MAX:
                continue
            result = simulate_ic(data, i, dte, iv_rank, spread, profit_target)
            if result is not None:
                trades.append(result)
                last_entry_idx = i
                break

    return trades


def calc_kelly(trades):
    """Return dict with Kelly params, or None if insufficient data."""
    if len(trades) < 3:
        return None

    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]

    wr = len(wins) / len(trades)
    aw = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    al = float(np.mean([abs(t.pnl) for t in losses])) if losses else 0.0

    if al <= 0:
        al = 0.0001  # Avoid division by zero

    b = aw / al
    p = wr
    q = 1.0 - p
    kelly = p - (q / b) if b > 0 else -1.0
    half_kelly = kelly / 2.0

    pnls = [t.pnl for t in trades]
    avg_pnl = float(np.mean(pnls))
    std_pnl = float(np.std(pnls))

    days_span = (trades[-1].entry_date - trades[0].entry_date).days
    tpy = len(trades) * 365 / days_span if days_span > 0 else 12

    sharpe = 0.0
    if std_pnl > 0:
        sharpe = (avg_pnl / std_pnl) * np.sqrt(min(tpy, 52))

    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "n": len(trades),
        "wr": wr,
        "aw": aw,
        "al": al,
        "b": b,
        "kelly": kelly,
        "half_kelly": half_kelly,
        "sharpe": sharpe,
        "pf": pf,
        "avg_pnl": avg_pnl,
        "tpy": tpy,
        "avg_win_usd": float(np.mean([t.pnl_usd for t in wins])) if wins else 0,
        "avg_loss_usd": float(np.mean([abs(t.pnl_usd) for t in losses])) if losses else 0,
    }


# ---- Main ----

def main():
    print("=" * 75)
    print("KELLY PARAMETER CALIBRATION FOR IC (USDC LINEAR)")
    print("=" * 75)

    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")
    print(f"Range: {data[0]['timestamp'].date()} to {data[-1]['timestamp'].date()}")
    print(f"IC: {SHORT_DELTA:.0%}-delta shorts, {WING_DELTA:.0%}-delta wings")
    print(f"DTE range: {DTE_MIN}-{DTE_MAX}, Bid-ask: {BID_ASK_SPREAD_PCT:.0%}/leg")

    # ================================================================
    # SECTION 1: Sweep entry conditions x profit targets
    # ================================================================
    print(f"\n{'=' * 75}")
    print("SCENARIO SWEEP: Entry conditions x Profit targets")
    print(f"{'=' * 75}")

    entry_configs = [
        ("Strict (IVR>60% + Spread>16)", 0.60, 16.0),
        ("Medium (IVR>60% + Spread>10)", 0.60, 10.0),
        ("IV Rank only (IVR>60%)",       0.60, None),
        ("Relaxed (IVR>40%)",            0.40, None),
        ("Broad (IVR>30%)",              0.30, None),
        ("No filter",                     0.0,  None),
    ]

    profit_targets = [0.50, 0.65, 0.75]

    header = f"{'Entry Filter':<32} {'PT':>4} {'N':>4} {'Win%':>6} {'AvgW':>8} {'AvgL':>8} {'b':>6} {'Kelly':>8} {'HalfK':>8} {'Sharpe':>7} {'PF':>6}"
    print(f"\n{header}")
    print("-" * len(header))

    best_scenario = None
    best_half_kelly = -999

    for label, min_ivr, min_spread in entry_configs:
        for pt in profit_targets:
            trades = run_backtest(data, min_ivr, min_spread, pt)
            k = calc_kelly(trades)
            if k is None:
                print(f"{label:<32} {pt:>3.0%} {len(trades):>4}   (insufficient data)")
                continue

            pf_str = f"{k['pf']:.2f}" if k["pf"] != float("inf") else "inf"
            print(f"{label:<32} {pt:>3.0%} {k['n']:>4} {k['wr']:>5.1%} "
                  f"{k['aw']:>7.5f} {k['al']:>7.5f} {k['b']:>5.2f} "
                  f"{k['kelly']:>7.4f} {k['half_kelly']:>7.4f} "
                  f"{k['sharpe']:>6.2f} {pf_str:>6}")

            # Track best positive Kelly with >= 10 trades
            if k["half_kelly"] > best_half_kelly and k["n"] >= 10:
                best_half_kelly = k["half_kelly"]
                best_scenario = (label, pt, k, trades)

    # ================================================================
    # SECTION 2: DTE breakdown for most promising scenario
    # ================================================================
    if best_scenario:
        label, pt, best_k, best_trades = best_scenario
        print(f"\n{'=' * 75}")
        print(f"BEST SCENARIO: {label}, PT={pt:.0%}")
        print(f"{'=' * 75}")
        print(f"  Trades: {best_k['n']}, Win Rate: {best_k['wr']:.1%}")
        print(f"  Avg Win: {best_k['aw']:.6f} (${best_k['avg_win_usd']:.2f}/ETH)")
        print(f"  Avg Loss: {best_k['al']:.6f} (${best_k['avg_loss_usd']:.2f}/ETH)")
        print(f"  Kelly: {best_k['kelly']:.4f}, Half Kelly: {best_k['half_kelly']:.4f}")
        print(f"  Sharpe: {best_k['sharpe']:.2f}, PF: {best_k['pf']:.2f}")

        # Show trades
        print(f"\n  {'Date':>12} {'DTE':>4} {'ETH$':>7} {'DVOL':>5} {'IVRk':>5} "
              f"{'Sprd':>5} {'Credit':>8} {'P&L':>9} {'P&L$':>8} {'Exit':>15}")
        print(f"  {'-' * 90}")
        for t in best_trades:
            marker = " *" if not t.win else ""
            print(f"  {t.entry_date.strftime('%Y-%m-%d'):>12} {t.dte:>4} "
                  f"${t.entry_price:>6.0f} {t.dvol:>5.1f} {t.iv_rank:>4.0%} "
                  f"{t.iv_rv_spread:>5.1f} {t.net_credit:>7.5f} "
                  f"{t.pnl:>+8.5f} ${t.pnl_usd:>+7.2f} {t.exit_reason:>15}{marker}")

        # Exit reasons
        reasons = {}
        for t in best_trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        print(f"\n  Exit reasons:")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {r}: {c} ({c/len(best_trades):.0%})")

    # ================================================================
    # SECTION 3: DTE-specific Kelly for best entry conditions
    # ================================================================
    if best_scenario:
        _, pt, _, _ = best_scenario
        # Extract the entry config that matched
        for lbl, min_ivr, min_spread in entry_configs:
            if lbl == best_scenario[0]:
                break

        print(f"\n{'=' * 75}")
        print(f"DTE BREAKDOWN ({lbl}, PT={pt:.0%})")
        print(f"{'=' * 75}")

        print(f"\n  {'DTE':>4} {'N':>4} {'Win%':>6} {'AvgW':>8} {'AvgL':>8} {'Kelly':>8} {'HalfK':>8} {'Sharpe':>7}")
        print(f"  {'-' * 56}")

        for dte in TEST_DTES:
            trades_dte = run_backtest(data, min_ivr, min_spread, pt, target_dte=dte)
            k = calc_kelly(trades_dte)
            if k is None:
                print(f"  {dte:>4} {len(trades_dte):>4}   (insufficient)")
                continue
            print(f"  {dte:>4} {k['n']:>4} {k['wr']:>5.1%} {k['aw']:>7.5f} "
                  f"{k['al']:>7.5f} {k['kelly']:>7.4f} {k['half_kelly']:>7.4f} "
                  f"{k['sharpe']:>6.2f}")

    # ================================================================
    # SECTION 4: Recommended config
    # ================================================================
    print(f"\n{'=' * 75}")
    print("RECOMMENDED CONFIG")
    print(f"{'=' * 75}")

    if best_scenario and best_k["half_kelly"] > 0:
        suggested_max = min(best_k["half_kelly"], 0.30)
        suggested_max = max(suggested_max, 0.05)

        print(f"""
  Based on {best_k['n']} IC trades over {data[-1]['timestamp'].date() - data[0]['timestamp'].date()} days:
  Entry: {label}, Profit Target: {pt:.0%}
  Win Rate: {best_k['wr']:.1%}, Win/Loss ratio: {best_k['b']:.3f}
  Half Kelly: {best_k['half_kelly']:.4f} ({best_k['half_kelly']:.2%})

  # SizingConfig (in paper_trading.py or settings.yaml):
  sizing_config = SizingConfig(
      max_position_pct={suggested_max:.4f},  # Was 0.10
      max_total_exposure_pct=0.30,
      base_win_rate={best_k['wr']:.4f},  # Was 0.65
      base_avg_win={best_k['aw']:.6f},  # Was 0.02
      base_avg_loss={best_k['al']:.6f},  # Was 0.01
  )

  Position sizing with $10K capital, ETH ~$2500:
    1.0x regime: ${10000 * suggested_max:.0f} = {10000 * suggested_max / 2500:.1f} ETH
    0.5x regime: ${10000 * suggested_max * 0.5:.0f} = {10000 * suggested_max * 0.5 / 2500:.1f} ETH
""")
    else:
        print("""
  WARNING: No scenario found with positive Kelly edge and >= 10 trades.

  The IC strategy with current parameters (15d/5d, 25 DTE) may not have
  a positive edge in the historical data. Consider:
  1. Adjusting wing width (10-delta instead of 5-delta for tighter risk)
  2. Different DTE (longer = more theta decay before breach)
  3. Different profit target (earlier exit = less breach risk)
  4. Different entry conditions

  Using conservative defaults until more data available:
  sizing_config = SizingConfig(
      max_position_pct=0.05,   # Conservative 5%
      max_total_exposure_pct=0.30,
      base_win_rate=0.70,      # Approximate from limited data
      base_avg_win=0.008,      # ~$20/ETH on wins
      base_avg_loss=0.030,     # ~$75/ETH on losses
  )
""")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
