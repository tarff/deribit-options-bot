# Review Findings Fix Design

## Scope

Implement the concrete, code-backed findings from `CODE_REVIEW.md` that improve execution safety or remove brittle duplication.

## Decisions

- `OrderExecutor.execute_signal()` keeps stop-on-failure behavior for `OPEN`, but for `CLOSE` it attempts every leg so one close failure does not strand later legs.
- Calendar spread identifies short and long legs by expiry rather than list index. The short leg is the earliest expiry; the long leg is the latest expiry.
- ATM straddle selection moves to `OptionSelector.find_matching_straddle()` so Gamma Scalp and Vol Arb share one implementation.
- Execution-value checks treat `0.0` bid/ask values as real prices. They do not fall through to mark price just because zero is falsy.
- Mechanical cleanup renames ambiguous threshold and market-order override variables without changing behavior.

## Out Of Scope

- Gamma Scalp long-debit `loss_limit` calibration. This requires a backtest-backed parameter, not an arbitrary default.
- Fee-adjusted unrealized strategy PnL checks. This is an accounting policy change and should be handled separately.
- Circuit-breaker loop guard for rejected multi-leg market opens. This needs a retry/halt policy decision.

## Tests

Add targeted regression tests for:

- CLOSE signals continue after a failed leg.
- OPEN signals still stop after a failed leg.
- Calendar long-only close uses the contract with the latest expiry even if restored out of order.
- Shared straddle selection rejects mismatched legs and selects a same-strike, same-expiry liquid pair.
- Zero bid is treated as zero closeable value for Gamma Scalp instead of falling back to mark.
