# Code Review — Recent Commits (Deribit Strategy Routing Hardening)

**Reviewer:** Claude Opus 4.7 (1M)
**Date:** 2026-05-12
**Scope:** Commits since last verified-clean state on master.

## Commits Reviewed

| SHA | Message |
|-----|---------|
| `2b647d3` | fix: harden Deribit strategy routing |
| `0255973` | docs: extend Session 77 memory (review excluded) |
| `52ce395` | chore: mark deploy/backup_db.py and pi-control.sh executable (review excluded) |
| `7381b17` | fix(paper): record executed close contract |
| `5bf0ab0` | docs: Session 77 memory (review excluded) |
| `2a4b262` | fix: close only long leg when calendar spread short leg expires |

## Automated Checks

| Check | Result |
|-------|--------|
| `pytest` (full repo, 431 tests) | **PASS** in 25.16s |
| `ruff check src/ tests/` | **PASS** |
| `mypy` on changed src files | **PASS** |
| New test count | **+13** (covering: gamma DTE/profit/loss exits, gamma/vol_arb mismatched straddle rejection, executor multi-leg market reject, executor close-uses-market, paper config CLI overrides, backtest auto-neutral, backtest wheel rejection, mainnet/testnet limit-order config, calendar single-leg close, paper one-leg close recording) |

---

## Summary

The commits do four high-value things:

1. **Routes NEUTRAL regime to Calendar Spread instead of Wheel** (Wheel is mechanically broken for Deribit cash-settled options — assignment never happens, so the strategy cannot work).
2. **Hardens multi-leg execution** by refusing uncapped sequential market opens (Session 69 root cause) while keeping market closes for risk reduction.
3. **Fixes the Session 77 expired-leg loop**: calendar spread no longer submits buy-to-close orders for instruments that no longer exist on the exchange.
4. **Fixes the close-trade DB record** to persist the *executed* instrument when the close signal is single-leg.

All four changes are sound, well-tested, and the right direction. The blocking issues are zero. The findings below are non-blocking but worth addressing.

---

## Findings

### MEDIUM — `_find_matching_straddle` is duplicated verbatim across two strategies

**Files:** `src/strategies/gamma_scalp.py:181-218` and `src/strategies/vol_arb.py:177-214`

The two implementations are byte-for-byte identical — same filter constants (±0.10 from ±0.50), same scoring function, same iteration shape. This is a textbook DRY violation that will rot independently the moment one strategy needs a different delta tolerance.

**Recommendation:** Promote to `src/data/option_selector.py` as `OptionSelector.find_matching_straddle(target_put_delta=-0.50, target_call_delta=0.50, max_delta_diff=0.10)` — both `OptionSelector` and the two strategies already import each other's neighbourhood.

```python
# proposed signature
def find_matching_straddle(
    self,
    target_put_delta: float = -0.50,
    target_call_delta: float = 0.50,
    max_delta_diff: float = 0.10,
) -> Optional[tuple[OptionContract, OptionContract]]: ...
```

This also positions the helper next to `find_by_delta` which is the existing single-leg version it replaces.

---

### MEDIUM — Long-debit strategies inherit unreachable `loss_limit = 2.0`

**Files:** `src/strategies/base.py:33`, `src/strategies/factory.py:47-54`, `src/strategies/gamma_scalp.py:113-117`

`StrategyConfig.loss_limit` defaults to `2.0` (200% of premium). For **short-credit** strategies (Iron Condor, Wheel CSP), 200% means "loss is 2× the credit received" — reachable.

For the **long-debit** check added in gamma_scalp:

```python
loss_pct = (initial_debit - current_value) / initial_debit
if loss_pct >= self.config.loss_limit:  # 2.0
```

The maximum value of `loss_pct` is 1.0 (current_value=0, option worthless). The check **can never fire**. Vol Arb's buy-vol mode has the same shape if a loss check is ever added there.

**Recommendation:** Either:
- Override `loss_limit` in `GammaScalpConfig` to a calibrated value (CLAUDE.md → "Empirically derived from backtests"), or
- Add an explicit `long_debit_loss_limit: float` field on the long-debit strategies so the units are obvious (e.g., 0.50 = "exit at 50% drawdown of debit").

The current code passes tests because the failing test uses `gamma_config.loss_limit = 0.50` to force a trip — but no calibrated production value exists. This is also a direct CLAUDE.md NO-ASSUMPTIONS violation since `0.50` profit target on the same path is the inherited base default with no script-backed justification.

---

### MEDIUM — `order_executor.execute_signal` still `break`s on first failed CLOSE leg

**File:** `src/execution/order_executor.py:124-129`

```python
# Stop if a leg fails (don't leave partial positions)
if not result.success:
    logger.error(...)
    break
```

This is the original Session 77 root cause as named in `.claude/memory.md`: *"`order_executor.execute_signal()` `break`-on-first-leg-failure (correct for entries, wrong for closes), the long got stranded."*

The commit `2a4b262` avoids the **specific** case of an expired-short-leg by reshaping the signal to drop the expired contract. But the underlying executor behaviour — abort remaining legs on any CLOSE failure — is unchanged. Any future failure mode (illiquid leg, rate-limited fill, partial fill on leg 1) still strands the other legs.

For CLOSE, the safer policy is *try every leg* and let `paper_trading._execute_signal` (which already handles PARTIAL FILL detection at `paper_trading.py:870`) decide what to halt. Specifically, the comment "don't leave partial positions" is **inverted** for CLOSE: breaking *creates* the partial position rather than preventing it.

**Recommendation:**
```python
if not result.success:
    logger.error(...)
    if signal.action == SignalAction.OPEN:
        break
    # For CLOSE: continue with remaining legs to reduce risk
```

---

### LOW — Calendar `_generate_close_long_only_signal` has fragile ordering assumption

**File:** `src/strategies/calendar_spread.py:451-467`

```python
long_leg = self.state.contracts[1]  # index 1 = long leg
```

The ordering invariant `contracts = [short_leg, long_leg]` is established in `_generate_calendar_signal` at line 214, but only by convention — there is no type-level or runtime guarantee, and DB-restored state (via `_load_state` in `paper_trading.py`) reconstructs `state.contracts` from row order without an explicit "leg role" column.

**Recommendation:** Use a role-based lookup or explicit expiry comparison, e.g.

```python
long_leg = max(self.state.contracts, key=lambda c: c.expiry)
```

This makes the invariant self-evident at the call site and survives a row-order regression in the persistence layer.

Also: the fallback `if len(self.state.contracts) < 2: return self._generate_close_signal(reason)` will then construct a signal with hardcoded `legs_direction=["buy", "sell"]` (line 447) when only 1 contract is present — a length mismatch with `signal.contracts`. Unreachable in practice (`manage()` requires 2 legs) but reachable by future call sites.

---

### LOW — `_get_current_straddle_value` falls back to `mark_price` when bid is zero/None

**File:** `src/strategies/gamma_scalp.py:266-284`

```python
price = current.bid or current.mark_price or current.mid_price
```

This is the same pattern as `calendar_spread._get_current_spread_value`, but inverts the protection that commit `7cac658` (use execution prices for profit targets) was added to provide. On illiquid testnet legs, `bid == 0` is *truthful* — we cannot sell for any non-zero amount. Falling back to `mark_price` overstates the closeable value, which:

- triggers **false profit targets** (close attempt fails to fill at the implied price), and
- **understates loss_pct**, suppressing the loss-limit branch (compounding the MEDIUM finding above).

**Recommendation:** Decide whether `bid == 0` means "untradeable" (return `None` so the check is skipped) or "use the bid" (still 0). The current `or` chain treats `0.0` as missing data, which is the worst of both worlds.

---

### LOW — Fees not accounted for in gamma_scalp profit/loss checks

**File:** `src/strategies/gamma_scalp.py:104-117`

`initial_debit = abs(self.state.premium_received)` does not include `entry_fees`, and `current_value` is the gross bid sum without subtracting estimated close fees. `paper_trading._execute_signal` properly accounts for fees in *realized* PnL (line 1018), so positions can hit the strategy-side profit target while the realized PnL is still negative once fees clear.

**Recommendation:** Use `initial_debit = abs(premium_received) + entry_fees` and (optionally) subtract a small fee estimate from `current_value`. Calendar spread has the same gap. Out of scope for this commit but worth tracking.

---

### LOW — Inconsistent semantic in factory: `wheel_min_iv_rank` used for calendar `max_iv_rank`

**File:** `src/strategies/factory.py:60`

```python
max_iv_rank=0.20 if currency == "ETH" else wheel_min_iv_rank.get(currency, 0.30),
```

For BTC this routes Calendar Spread's *upper bound* through a dict literally named `wheel_min_iv_rank` (the wheel's *lower bound*). It works only because the numerical values happen to coincide today. If wheel's BTC threshold is recalibrated, calendar will silently move with it.

**Recommendation:** Either inline the BTC literal (`0.30`) or rename the dict (`neutral_iv_rank_threshold` covers both call sites). One-line change.

---

### LOW — Multi-leg market OPEN rejection has no retry/halt loop guard

**File:** `src/execution/order_executor.py:90-100`

When `use_market_orders=True` is configured (legacy/CLI override) and a multi-leg OPEN is generated, the executor returns a single failed `OrderResult`. The strategy state is not touched (`activate()` never called), so the same evaluation runs next cycle and produces the same signal → same rejection. Tight loop until someone changes config.

**Recommendation:** Optional — record the rejection in `circuit_breaker.record_api_error()` so the existing API-error breaker eventually trips, or short-circuit the regime-evaluation when this specific error has fired N times.

Risk is low because the default configs are all `use_market_orders=false` now (verified by `test_*_config_uses_limit_orders`), but a user passing `--market-orders` on the CLI hits this immediately.

---

### LOW — `use_market_order` parameter shadows the instance attribute name

**File:** `src/execution/order_executor.py:232,263`

The new parameter is `use_market_order` (singular), the instance attribute is `self.use_market_orders` (plural). The line:

```python
use_market_order = self.use_market_orders if use_market_order is None else use_market_order
```

is correct but confusing on a second read. Suggested rename: `use_market_order_override: Optional[bool]` to make the optional/override semantic explicit.

---

### NIT — Dead `or 0` in score computation

**Files:** `src/strategies/gamma_scalp.py:211` and `src/strategies/vol_arb.py:207`

```python
score = abs((put.delta or 0) - (-0.50)) + abs((call.delta or 0) - 0.50)
```

Both `put.delta` and `call.delta` are already filtered to `is not None` upstream in the same function, so the `or 0` defensive code is unreachable. Cosmetic but reads like there's an edge case to worry about.

---

### NIT — `(opt.expiry, opt.strike)` key collision possible

**Files:** `src/strategies/gamma_scalp.py:186-194` and `src/strategies/vol_arb.py:182-190`

Two puts at identical strike+expiry would collide in the dict-comprehension key; later wins. Deribit doesn't issue duplicates, but the same risk exists if test fixtures or the synthetic chain in `BacktestEngine` produces near-duplicates. Defensive coding would prefer the higher-delta candidate explicitly.

---

## Strengths

- **Test coverage is excellent.** Every behavioral change has at least one targeted test, plus integration coverage for the NEUTRAL→Calendar path. Multiple Session-77-style failure modes are now regression-locked (`test_calendar_expired_short_close_records_long_leg_trade`, `test_execute_signal_rejects_multi_leg_market_open`, `test_close_on_short_leg_expiry`).
- **Config consolidation** — `build_paper_config` extraction is a clean replacement for the previous inline `PaperTradingConfig(...)` construction in `run()` and is well-tested.
- **CLI mutually-exclusive group** is the right argparse primitive for `--market-orders` / `--limit-orders` — neither silently overrides the other.
- **Explicit ValueError in `BacktestEngine.__init__`** for `StrategyType.WHEEL` prevents silent no-op backtests, which is exactly the right failure mode.
- **`order_type="market"` for closes regardless of config** is the right risk-reduction policy: prioritize getting out over getting a tight price.
- **Strict zip in `execute_signal`** (`zip(..., strict=True)`) protects against the historical class of "legs and directions out of sync" bugs.

---

## Security

No new attack surface. All inputs are from YAML config, CLI args (parsed by `argparse`), or Deribit API responses (parsed via `.get()` with defaults). No SQL string interpolation. No subprocess invocation. No file path traversal risk in new code.

## Performance

The straddle finder runs O(N) over the option chain with one dict build + one linear scan — fine for chains of a few hundred contracts. The added `_get_current_straddle_value` is O(K) where K is the number of position legs (2). No hot path regressions.

---

## Recommended Follow-ups (in priority order)

1. **Fix `execute_signal` break-on-fail for CLOSE signals** — preserves the Session 77 fix even when failure modes other than expired-leg occur.
2. **Calibrate or override `loss_limit` for long-debit strategies** — currently dead code for gamma scalp.
3. **Hoist `_find_matching_straddle` to OptionSelector** — eliminate the byte-identical duplicate.
4. **Use `max(contracts, key=expiry)` for long-leg lookup in calendar** — kills the implicit-ordering footgun.
5. **Decide `bid==0` policy** in `_get_current_straddle_value` and `_get_current_spread_value` consistently.

None of these block the current commit batch. The shipped behaviour is strictly better than what it replaces.
