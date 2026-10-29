# Mainnet Go-Live Checklist — Small-Capital Validation Phase

**Purpose:** Move the bot from Deribit *testnet* (paper) to *mainnet* (real money) at a
deliberately small capital level, to validate the strategies that testnet can no longer
exercise — primarily **Calendar Spread** (dominant in NEUTRAL, ~99% of recent regime time,
only 1 clean paper cycle) and **Gamma Scalp** (0 live trades ever).

> ⚠️ `run_paper_trading.py` places **real orders** against whatever `base_url` it is pointed
> at. On `www.deribit.com` this trades real funds. The word "paper" in the script name is
> historical — there is no simulation layer.

---

## 0. Decisions to make first (do NOT skip)

- [ ] **Validation capital amount.** Config default is `$1,500` (see rationale in
  `config/settings.mainnet.yaml`). Minimum that can place a trade ≈ `0.5 × ETH_price`
  (~$810 now; ~$1,620 if DVOL is in the 73–82 reduce band). Confirm your number.
  - At `$1,500`, trades clear when DVOL < 73 (current regime). If DVOL enters 73–82,
    orders may be **rejected as "below minimum trade"** — that is expected, not a bug.
    Use ≥ ~$2,000 if you want the bot to keep trading through the reduce band.
- [ ] **IV-Rank override** (`src/execution/paper_trading.py:475–492`). This local
  recalculation was added *because testnet DVOL history has unrealistic extremes*. It runs
  unconditionally, so it will also override mainnet's real DVOL-derived IV rank and can
  skew regime detection. **Decide before go-live:** keep it, gate it to testnet only, or
  remove it. This is a code change requiring its own review — do not silently ship as-is.
- [ ] **Which currency.** Config is ETH (`ETH_USDC` linear). Confirm the mainnet account is
  funded in USDC for ETH linear options.

---

## 1. Deribit mainnet account

- [ ] Account created and funded with **USDC** (linear ETH options are USDC-margined).
- [ ] API key created with **trade** permission. **Disable withdraw** permission on this key.
- [ ] (Optional but recommended) IP-allowlist the key to the Pi's egress IP.
- [ ] Note the key/secret for the `.env` step below.

## 2. Credentials on the Pi

The live `.env` currently holds **testnet** credentials. Do not overwrite blindly.

- [ ] Back up the existing `.env`: `cp ~/options-trading-bot/.env ~/options-trading-bot/.env.testnet.bak`
- [ ] Set mainnet values in `.env`:
  - `DERIBIT_API_KEY=<mainnet key>`
  - `DERIBIT_API_SECRET=<mainnet secret>`
  - `TELEGRAM_BOT_TOKEN=<token>`
  - `TELEGRAM_CHAT_ID=<chat id>`
- [ ] Confirm the Pi's GitHub PAT is current (it has expired repeatedly — Sessions 76/78) so
  you can deploy fixes without the `git bundle`-over-`scp` workaround.

## 3. Deploy the mainnet-ready code

- [ ] Ensure Pi is on the intended commit (currently `988d4d2`):
  `cd ~/options-trading-bot && git log --oneline -1`
- [ ] Ensure the mainnet config with the validation capital is present:
  `git pull` (or bundle/scp) so `config/settings.mainnet.yaml` includes `initial_capital_usd: 1500.0`.

## 4. Systemd service — point at mainnet

Current `ExecStart` (testnet):
```
ExecStart=/home/pi/options-trading-bot/venv/bin/python scripts/run_paper_trading.py \
  --config config/settings.testnet.yaml --interval 60
```

Change to (mainnet validation):
```
ExecStart=/home/pi/options-trading-bot/venv/bin/python scripts/run_paper_trading.py \
  --config config/settings.mainnet.yaml \
  --db data/mainnet.db \
  --capital 1500 \
  --interval 60
```

- [ ] `--db data/mainnet.db` — separate DB so testnet history is preserved and mainnet
  starts clean.
- [ ] `--capital 1500` — **this is what actually seeds capital** on the fresh `mainnet.db`
  (the YAML value is ignored by this script). Must match your Decision-0 amount.
- [ ] Edit via `sudo systemctl edit --full options-bot.service` (or the service file directly),
  then `sudo systemctl daemon-reload`.

> On the **first** run against an empty `data/mainnet.db`, capital is seeded from `--capital`.
> On every restart afterward, capital is loaded from `paper_trading_state` in that DB and
> `--capital` is ignored. To re-seed, stop the service and start with `--fresh` (clears state).

## 5. Backups — repoint at mainnet DB

- [ ] Update the backup cron / `deploy/backup_db.py` target from `data/paper_trading.db` to
  `data/mainnet.db` (or add it), so the real-money DB is on the 7-day rotation.

## 6. Pre-flight dry run

- [ ] Validate config without trading:
  `venv/bin/python scripts/run_paper_trading.py --config config/settings.mainnet.yaml --dry-run`
  Confirm it prints `API: https://www.deribit.com`, `Currency: ETH`, DVOL thresholds 73/82.
- [ ] Send a Telegram test (entry/exit/circuit-breaker notifications enabled in mainnet.yaml).
- [ ] Confirm current `ETH_price` such that your chosen capital clears the `0.5 × ETH_price`
  floor. At ETH $1,620 and $1,500 capital: `1500 × 0.20 / 1620 = 0.185 ETH` ≥ 0.1 → OK.

## 7. Go live

- [ ] `sudo systemctl start options-bot.service`
- [ ] `journalctl -u options-bot.service -f` (or `tail -f logs/bot.log`) and watch:
  - authentication succeeds against `www.deribit.com`
  - regime detection + option-chain filter run each cycle
  - **first entry signal** fires (expect Calendar Spread in NEUTRAL, now that mainnet lists
    14–21 DTE weeklies)

## 8. First-cycle validation (the whole point)

- [ ] Watch the **first Calendar Spread** end-to-end: entry fill (both legs), `manage()`
  each cycle, and the eventual close (profit target, price-move exit, or short-leg expiry).
  Confirm the expired-leg-close path (Session 77 fix) behaves on mainnet.
- [ ] Reconcile the bot's DB position against the Deribit web UI after entry and after close.
- [ ] If **Gamma Scalp** ever triggers (LOW_IV / VOLATILE_FAIR), watch it especially closely —
  it has zero prior live validation and the 0.40 stop is from a conservative backtest proxy.
- [ ] Verify realized PnL in `paper_trading_state.capital` matches Deribit fills + fees.

## 9. Kill switch / rollback

- [ ] Stop trading immediately: `sudo systemctl stop options-bot.service`
- [ ] Manual position close is via the Deribit API/UI (see Session 77 memory for the exact
  API call pattern used to unstick a leg).
- [ ] Roll back to testnet: restore `.env.testnet.bak`, revert `ExecStart` to
  `--config config/settings.testnet.yaml` (drop `--db/--capital`), `daemon-reload`, restart.

---

## Known limitations going in (accept explicitly)

- **Calendar Spread validation is N=1 clean.** This phase exists to raise that number on
  mainnet with small capital. Treat early cycles as validation, not profit.
- **Gamma Scalp is unvalidated live.** Its stop is a backtest upper-bound, not a live figure.
- **Single-position mode.** Only one strategy holds a position at a time — capital efficiency
  is intentionally limited, but state-drift risk is contained.
- **Iron Condor** is the best-validated live strategy (2 clean wins) but only triggers in
  HIGH_IV_OVERPRICED (~0.7% of recent time), so it will rarely carry the bot.
