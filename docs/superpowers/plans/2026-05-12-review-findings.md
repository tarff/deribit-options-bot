# Review Findings Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix concrete execution-safety and maintainability findings from `CODE_REVIEW.md`.

**Architecture:** Keep behavior local to existing modules. Execution policy stays in `OrderExecutor`, option-pair selection moves into `OptionSelector`, and strategies call shared helpers while retaining strategy-specific signal construction.

**Tech Stack:** Python, pytest, asyncio, existing dataclass strategy models.

---

### Task 1: Executor CLOSE Continuation

**Files:**
- Modify: `tests/unit/test_order_executor.py`
- Modify: `src/execution/order_executor.py`

- [ ] Add a failing test that a two-leg CLOSE still attempts leg 2 when leg 1 fails.
- [ ] Add or adjust a test that a three-leg OPEN stops before leg 3 when leg 2 fails.
- [ ] Run the targeted tests and confirm the CLOSE continuation test fails.
- [ ] Change `execute_signal()` so failed OPEN legs break, failed CLOSE legs continue.
- [ ] Run targeted order-executor tests.

### Task 2: Calendar Leg Role Lookup

**Files:**
- Modify: `tests/unit/test_calendar_spread.py`
- Modify: `src/strategies/calendar_spread.py`

- [ ] Add a failing test where `state.contracts` is restored as `[long, short]` and expired-short management closes only the long leg.
- [ ] Add helper methods that return short and long legs by expiry.
- [ ] Update `_short_leg_expired()`, `_get_current_spread_value()`, and `_generate_close_long_only_signal()` to use role helpers.
- [ ] Run targeted calendar tests.

### Task 3: Shared Straddle Selector

**Files:**
- Modify: `tests/unit/test_option_selector.py`
- Modify: `tests/unit/test_gamma_scalp_strategy.py`
- Modify: `tests/unit/test_vol_arb_strategy.py`
- Modify: `src/data/option_selector.py`
- Modify: `src/strategies/gamma_scalp.py`
- Modify: `src/strategies/vol_arb.py`

- [ ] Add failing selector tests for same strike/expiry selection, mismatch rejection, and duplicate-key scoring.
- [ ] Implement `OptionSelector.find_matching_straddle()`.
- [ ] Replace duplicated strategy methods with calls to the selector helper.
- [ ] Run targeted selector and strategy tests.

### Task 4: Zero Bid Pricing And Cleanup

**Files:**
- Modify: `tests/unit/test_gamma_scalp_strategy.py`
- Modify: `tests/unit/test_calendar_spread.py`
- Modify: `src/strategies/gamma_scalp.py`
- Modify: `src/strategies/calendar_spread.py`
- Modify: `src/strategies/factory.py`
- Modify: `src/execution/order_executor.py`

- [ ] Add failing tests that `bid=0.0` does not fall back to mark price in closeable-value calculations.
- [ ] Replace falsy price chains with explicit `is not None` fallback helpers.
- [ ] Rename `wheel_min_iv_rank` to a neutral threshold name.
- [ ] Rename `_execute_leg(..., use_market_order=...)` to `use_market_order_override`.
- [ ] Run targeted tests.

### Task 5: Final Verification

**Files:**
- No code changes.

- [ ] Run `pytest`.
- [ ] Run `ruff check src/ tests/`.
- [ ] Run `git diff --check`.
- [ ] Review `git diff` for accidental unrelated changes.
