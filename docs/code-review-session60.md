# Code Review - Session 60 (2026-02-06)

6-agent parallel review across all subsystems. 34 issues found (10 critical, 16 high, 8 medium).
Previous reviews: Session 58 (109 issues), Sessions 59-60 fixed ~81 of those.

---

## CRITICAL (10 issues)

### C1: Trade direction defaults to "buy" when legs_direction is None
- **File:** `src/execution/paper_trading.py:913`
- **Confidence:** 90%
- **Impact:** Database contains incorrect trade direction for Vol Arb / Gamma Scalp CLOSE signals
- **Details:** Line 913 saves Trade records with direction defaulting to "buy":
  ```python
  direction = signal.legs_direction[i] if signal.legs_direction else "buy"
  ```
  But line 929 correctly defaults to `signal.direction`:
  ```python
  directions = signal.legs_direction or [signal.direction] * len(signal.contracts)
  ```
  When Vol Arb or Gamma Scalp generate CLOSE signals without `legs_direction` and `signal.direction="sell"`, the Trade record will be saved with side=BUY instead of SELL.
- **Fix:** Change line 913 to:
  ```python
  direction = signal.legs_direction[i] if signal.legs_direction else signal.direction
  ```

### C2: Calendar spread expiry check uses real time instead of simulation time
- **File:** `src/strategies/calendar_spread.py:359`
- **Confidence:** 95%
- **Impact:** In backtesting, expiry checks use actual current time instead of simulation time. Short legs appear expired/not expired based on real time, not backtest time.
- **Details:**
  ```python
  def _short_leg_expired(self) -> bool:
      now = datetime.now(timezone.utc)  # WRONG in backtest context
      return now >= short_leg.expiry
  ```
  But line 174 correctly uses `metrics.timestamp`.
- **Fix:** Pass `metrics` (or timestamp) to `_short_leg_expired()` and use `metrics.timestamp or datetime.now(timezone.utc)`.

### C3: Emergency manager not called from paper trading loop [NEEDS VERIFICATION]
- **File:** `src/execution/paper_trading.py`
- **Confidence:** ~85%
- **Impact:** If true, DVOL > 100 emergency conditions never trigger position closes.
- **Details:** Agent claims emergency manager is imported but never instantiated or called in the paper trading loop. Needs verification - the DVOL halt logic in `_run_iteration()` may handle this differently.
- **Fix:** Verify and integrate if missing.

### C4: Unbounded DVOL API fetch (no time range constraint)
- **File:** `src/data/market_analyzer.py:120-123`
- **Confidence:** 90%
- **Impact:** Fetches unlimited DVOL history from Deribit API. Could return years of data, cause slow responses, trigger rate limits, waste bandwidth.
- **Details:**
  ```python
  dvol_data = await self.client.get_volatility_index(
      currency=self.currency,
      resolution=86400,  # Daily - no start/end timestamp
  )
  ```
- **Fix:** Add time range constraint:
  ```python
  end_ms = int(time.time() * 1000)
  start_ms = end_ms - (365 * 86400000)  # 365 days back
  dvol_data = await self.client.get_volatility_index(
      currency=self.currency,
      resolution=86400,
      start_timestamp=start_ms,
      end_timestamp=end_ms,
  )
  ```

### C5: IV Rank lookback not enforced at 252 days
- **File:** `src/data/market_analyzer.py` / `src/data/volatility.py:70-76`
- **Confidence:** 80%
- **Impact:** Documentation says "252-day (1 year) lookback" with calibration rationale, but code uses all available history. Threshold calibrations (40%, 60%) may be wrong for the actual data window used.
- **Details:** `volatility.py` documents the 252-day window but `market_analyzer.py` fetches unlimited data and passes it all to `calculate_iv_rank()`.
- **Fix:** Either constrain the fetch (see C4) or slice to last 252 values:
  ```python
  if len(dvol_data) > 252:
      dvol_data = dvol_data[-252:]
  ```

### C6: PRAGMA foreign_keys = ON set in initialize() but lost on reconnect
- **File:** `src/persistence/database.py:213`
- **Confidence:** 90%
- **Impact:** Foreign key constraints won't be enforced after reconnection, allowing orphaned records.
- **Details:** SQLite PRAGMA settings are per-connection, not persistent. The Session 59 fix put it in `initialize()` which only runs once. If connection closes and reopens, FK constraints are OFF.
- **Fix:** Move to connection property:
  ```python
  @property
  def connection(self) -> sqlite3.Connection:
      with self._lock:
          if self._connection is None:
              self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
              self._connection.row_factory = sqlite3.Row
              self._connection.execute("PRAGMA foreign_keys = ON")
          return self._connection
  ```

### C7: Backtest entry commission never deducted
- **File:** `src/backtest/position_tracker.py:140-148`
- **Confidence:** 100%
- **Impact:** Positions appear more profitable than they actually are. Over hundreds of trades, significantly inflates backtest returns.
- **Details:** Commission calculation at close includes both entry and exit premiums, but entry commission was never deducted when the position was opened. Only exit-time commission is subtracted from P&L.
- **Fix:** Either deduct entry commission in `open_position()` or store it on the position and include in final P&L at close.

### C8: Backtest RV calculation uses close prices (look-ahead bias)
- **File:** `src/backtest/data_fetcher.py:218`
- **Confidence:** 95%
- **Impact:** RV at bar[i] includes bar[i].close which isn't known at decision time (bar[i].open). IV-RV spread calculations become inconsistent.
- **Details:**
  ```python
  closes = np.array([bar.close for bar in price_bars])  # Line 218
  log_returns = np.diff(np.log(closes))
  ```
  Engine uses `bar.open` for all other decisions.
- **Fix:** Use open prices:
  ```python
  opens = np.array([bar.open for bar in price_bars])
  log_returns = np.diff(np.log(opens))
  ```

### C9: Synthetic contracts still use Brenner-Subrahmanyam, not Black-Scholes
- **File:** `src/backtest/engine.py:583-593`
- **Confidence:** 90%
- **Impact:** When positions' strikes fall outside the generated chain (due to spot price movement), contracts get repriced with the wrong formula. Creates pricing discontinuity affecting mark-to-market P&L.
- **Details:** `_create_synthetic_contract()` still uses `time_value = iv * sqrt(t) * spot * 0.4` while `option_chain_generator.py` was updated to Black-Scholes in Session 59.
- **Fix:** Replace with Black-Scholes implementation (import `_norm_cdf` from option_chain_generator and use identical pricing logic).

### C10: Dashboard SQLite race condition - no threading lock
- **File:** `dashboard/backend/services/db_service.py:28-33`
- **Confidence:** 95%
- **Impact:** Concurrent FastAPI requests can cause "database is locked" errors or corruption. Unlike main bot's database (which has threading.Lock per Session 59 fix), dashboard has no protection.
- **Details:**
  ```python
  @contextmanager
  def get_connection(self):
      conn = sqlite3.connect(self.db_path)  # No lock, new connection each time
      conn.row_factory = sqlite3.Row
      try:
          yield conn
      finally:
          conn.close()
  ```
- **Fix:** Add `threading.Lock` around connection creation.

---

## HIGH (16 issues)

### H1: Vol Arb / Gamma Scalp CLOSE signals missing legs_direction
- **File:** `src/strategies/vol_arb.py:207`, `src/strategies/gamma_scalp.py:186`
- **Confidence:** 80%
- **Impact:** Inconsistent with IC and Calendar which specify `legs_direction` in CLOSE signals. Triggers C1 above (trade direction saved as "buy" instead of actual direction).
- **Fix:** Add `legs_direction` to CLOSE signals in both strategies.

### H2: base.py activate() uses real time, not simulation time
- **File:** `src/strategies/base.py:141`
- **Confidence:** 80%
- **Impact:** In backtesting, entry_time reflects when backtest ran, not simulation time.
- **Fix:** Add optional `entry_time` parameter defaulting to `datetime.now()`.

### H3: Halted strategies state not persisted across restarts
- **File:** `src/execution/paper_trading.py:245-331`
- **Confidence:** 88%
- **Impact:** If bot crashes after partial fill halt, halt state is lost on restart and strategy resumes (potentially creating duplicate orders).
- **Fix:** Save `_halted_strategies` set to database and restore in `_load_state()`.

### H4: Peak capital not persisted immediately, lost on crash
- **File:** `src/execution/paper_trading.py:1001, 343`
- **Confidence:** 85%
- **Impact:** If bot crashes between close and save, peak capital is lost. Drawdown calculations become inaccurate, potentially allowing trades that should be blocked.
- **Fix:** Save state immediately after capital mutations.

### H5: Strategies can try to close illiquid contracts not in current chain
- **File:** `src/execution/paper_trading.py:666-672`
- **Confidence:** 85%
- **Impact:** After market crash, options may become illiquid (bid=0, ask=0), filtered out of chain. Strategy generates CLOSE signal with stale contracts, order fails, position stuck open.
- **Fix:** Validate contracts still exist in chain with liquidity before generating CLOSE signals.

### H6: Silent DB errors hide schema changes
- **File:** `src/data/market_analyzer.py:192-194`
- **Confidence:** 82%
- **Impact:** Schema errors (table/column missing) logged at debug level, not warning. RV calculation silently fails, IV-RV spread = None, regime detection breaks.
- **Fix:** Log schema errors at warning/error level, keep OSError at debug.

### H7: rv_7d can be None from bad data, unchecked
- **File:** `src/data/market_analyzer.py:70`
- **Confidence:** 88%
- **Impact:** If last 7 prices contain zero/negative values, `calculate_realized_volatility()` returns None but it's still assigned to `MarketMetrics.rv_7d`. Later code may assume valid float.
- **Fix:** Check return value and log warning if None.

### H8: transaction() context manager exists but never used by repositories
- **File:** `src/persistence/repositories.py` (all save/update methods)
- **Confidence:** 85%
- **Impact:** No automatic rollback on exceptions. Multi-step operations aren't atomic. The entire `transaction()` feature from Session 59 is dead code.
- **Fix:** Replace manual `cursor = self.db.connection.cursor()` + `commit()` with `with self.db.transaction() as cursor:`.

### H9: Missing timezone validation on repository datetime inputs
- **File:** `src/persistence/repositories.py`
- **Confidence:** 82%
- **Impact:** Naive datetimes silently stored, causing incorrect comparisons with timezone-aware datetimes in WHERE clauses.
- **Fix:** Add Pydantic validators to models enforcing timezone-aware datetimes, or add `_ensure_utc()` calls to save methods.

### H10: DailyPerformance.date typed as datetime, should be date
- **File:** `src/persistence/models.py:96`
- **Confidence:** 85%
- **Impact:** Type mismatch with SQL DATE column. Full timestamps stored instead of dates, causing comparison and grouping issues.
- **Fix:** Change type to `date` from `datetime.date`.

### H11: Backtest capital can go negative, breaking risk checks
- **File:** `src/backtest/engine.py:469`
- **Confidence:** 90%
- **Impact:** A single large losing trade can make capital negative. Subsequent calculations (exposure, margin, risk checks) break or produce wrong results.
- **Fix:** Clamp capital to 0 and halt new position opening when depleted.

### H12: No capital check when backtest margin tracking disabled
- **File:** `src/backtest/engine.py:399-416`
- **Confidence:** 85%
- **Impact:** Without margin checking (default in tests), positions can be opened without verifying sufficient capital. Backtest shows unrealistic returns.
- **Fix:** Add basic capital check even when margin tracking disabled.

### H13: Expired options valued at stale price, not intrinsic
- **File:** `src/backtest/position_tracker.py:234-261`
- **Confidence:** 85%
- **Impact:** Positions held through expiry are mis-valued. Expired options should be at intrinsic value but fallback uses old mark price.
- **Fix:** Check if contract expired and calculate intrinsic value instead.

### H14: Dashboard connection leak in positions router
- **File:** `dashboard/backend/routers/positions.py:96-128`
- **Confidence:** 90%
- **Impact:** If exception occurs during cursor execution, connection is never closed.
- **Fix:** Use `with sqlite3.connect(...) as conn:` context manager.

### H15: Dashboard connection leaks in live_data_service (2 methods)
- **File:** `dashboard/backend/services/live_data_service.py:200-212, 230-246`
- **Confidence:** 90%
- **Impact:** `_calculate_iv_rank` and `_calculate_realized_vol` manually create connections, only close on success path. Early returns and exceptions leak connections.
- **Fix:** Use context managers for both methods.

### H16: Dashboard cache race condition
- **File:** `dashboard/backend/services/live_data_service.py:107-123`
- **Confidence:** 85%
- **Impact:** Concurrent requests both see expired cache, both fetch from Deribit, wastes API quota, could trigger rate limits.
- **Fix:** Add `asyncio.Lock` around cache check + fetch.

---

## MEDIUM (8 issues)

### M1: DTE calculation can be -1 on expiry day
- **File:** `src/data/option_selector.py:130`
- **Confidence:** 85%
- **Impact:** On expiry day after midnight UTC, `.days` returns -1. Options still tradeable but filtered out.
- **Fix:** Use `total_seconds() / 86400` or `max(0, dte)`.

### M2: Non-deterministic delta selection on ties
- **File:** `src/data/option_selector.py:44-47`
- **Confidence:** 70%
- **Impact:** If two options have identical delta distance, sort order is undefined. Could cause non-reproducible backtest results.
- **Fix:** Add secondary sort by strike: `key=lambda o: (abs(delta_diff), o.strike)`.

### M3: Backtest IV rank uses close price (minor look-ahead)
- **File:** `src/backtest/data_fetcher.py:187-188`
- **Confidence:** 85%
- **Impact:** Current DVOL uses `bar.close` but decisions happen at `bar.open`. Minor look-ahead bias in IV rank calculation.
- **Fix:** Use `dvol_bars[i].open` for current_dvol.

### M4: Backtest position tracker allows zero/negative quantity
- **File:** `src/backtest/position_tracker.py:68-107`
- **Confidence:** 85%
- **Impact:** If quantity is 0 or negative, P&L and commission calculations break silently.
- **Fix:** Add `if signal.quantity <= 0: raise ValueError(...)` guard.

### M5: Missing capital validation in PaperTradingState model
- **File:** `src/persistence/models.py:163-164`
- **Confidence:** 72%
- **Impact:** Negative capital can be persisted to database.
- **Fix:** Add `Field(ge=0)` validator to capital and peak_capital.

### M6: RiskEvent severity not validated (no enum)
- **File:** `src/persistence/models.py:116`
- **Confidence:** 70%
- **Impact:** Typos in severity strings accepted silently.
- **Fix:** Use `Literal["info", "warning", "critical"]` or enum.

### M7: Dashboard broadcast loop swallows CancelledError
- **File:** `dashboard/backend/main.py:155-210`
- **Confidence:** 82%
- **Impact:** Shutdown may hang waiting for broadcast task to finish.
- **Fix:** Re-raise `asyncio.CancelledError` before generic `except Exception`.

### M8: No date range validation on dashboard historical endpoint
- **File:** `dashboard/backend/routers/historical.py:22-33`
- **Confidence:** 85%
- **Impact:** Clients can request unbounded date ranges, causing large DB scans.
- **Fix:** Add max range validation (e.g., 365 days).

---

## Issues Needing Verification

- **C3**: Emergency manager integration - needs manual check of paper_trading.py to confirm
- **C4/C5**: DVOL fetch bounds - need to check if Deribit API has default limits

## False Positives / Already Fixed

- IC max loss calculation (agent retracted - division by spot is correct)
- Vol Arb phase never set (already fixed in Session 59, set by paper_trading.py)

## Statistics

| Severity | Count |
|----------|-------|
| Critical | 10 |
| High | 16 |
| Medium | 8 |
| **Total** | **34** |

| Area | Critical | High | Medium |
|------|----------|------|--------|
| Strategy | 2 | 2 | 0 |
| Execution/Risk | 1 | 3 | 0 |
| Data | 2 | 2 | 2 |
| Persistence | 1 | 3 | 2 |
| Backtest | 3 | 3 | 2 |
| Dashboard | 1 | 3 | 2 |
