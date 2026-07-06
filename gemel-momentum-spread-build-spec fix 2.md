# Gemel Build Spec — Momentum Debit Spread Module

*Requested by Julie · July 2026. Priority order is intentional: nothing gets traded live until items 1–4 exist and a paper cycle has run. If the first pass is already built: do §8 (bug fixes from the 7/6 live run) before anything else.*

---

## 0. The decision that gates everything: risk cap configuration

**Problem.** The current "Fits 2% cap?" logic makes the momentum spread strategy impossible on a $4k account: 2% = $80/trade, and the planned debit spreads cost $450–550 (11–14% of account each).

**Required change.** Make the per-trade risk cap **configurable per playbook**, not global:
- Credit spread playbook: keep existing cap (2% or current setting)
- Momentum debit spread playbook: separate cap derived from the diversification target, not the reverse. Arithmetic: $3,500–4,000 deployed ÷ 7 positions = $500–570 per spread = 12.5–14% of a $4k account. **Set per-position cap at 15%** — above the target so normal spreads pass, tight enough to block concentration (a $750+ spread forces a 5-position book). PLUS a **total deployment cap** (suggested: max 85–90% of account in open spreads; always ≥ $400 cash free)
- Sizing principle: position count follows qualifying opportunities, never the reverse. If only 5 names pass all gates this month, run 5 positions at ~$500 — do not upsize to $700 to deploy leftover capital. Cash is a position.
- Display the active cap on each playbook's page so it's never ambiguous which rule is in force

**Decision to record before building:** Julie + fiancé explicitly sign off that the momentum book runs at ~12% per-position risk. Write it in the journal as a standing decision. If that sizing is not acceptable, the strategy does not run at $4k — there is no configuration that satisfies both a 2% cap and $450 spreads.

---

## 1. Separate the two playbooks in navigation

**Problem.** The Scanner page currently stacks the credit-spread system (ETF screen, opportunity map, regime playbook) and the momentum table on one page. Reads as one scanner; it's two unrelated systems with different universes, different vehicles, different schedules.

**Required change.**
- Sidebar: split "Scanner" into two entries — **"Credit spreads (weekly)"** and **"Momentum spreads (monthly)"** — or one Scanner entry with two clearly labeled tabs
- Each page states its own: universe (6 ETFs vs. 21-name watchlist), vehicle (bull put credit spread vs. call debit spread), cadence (weekly Sunday screen vs. monthly re-rank), and active risk cap
- Positions and Journal pages: tag every position/entry with its playbook; filterable

---

## 2. Momentum page: replace LEAP columns with spread columns

**Problem.** The momentum table is built for buying naked LEAPs (Est. LEAP cost, 2% cap check, "long calls risk 100% of premium" banner). The chosen vehicle is now call debit spreads.

**Required table columns (per ranked name):**
1. Rank (by 1-yr ROC)
2. Ticker · Last price
3. 1-yr ROC % (the signal)
4. 3-mo ROC % (leadership health check)
5. **Est. spread cost** — model spread: buy ~5% OTM call, sell ~15–20% higher, nearest monthly expiry in the 6–12 month window; show net debit at mid
6. **Max value / max profit** of that model spread
7. **Liquidity gate** (see §3) — pass/fail with detail on hover
8. **Fits playbook cap?** — spread cost vs. the momentum playbook's per-position cap (§0)
9. **Theme tag** (AI hardware / software / energy / financials / etc.) — needed to enforce the max-2-per-theme rule; manual tags on the watchlist are fine v1

All columns click-sortable for exploration; **default and reset sort is 1-yr ROC descending** — that ranking is the signal, and the candidates card always assembles from it regardless of the table's current sort.

**Keep** the Rank now button and 21-name watchlist model. **Add:**
- **Ticker lookup box**: type any symbol → compute its 1-yr / 3-mo ROC → show where it *would* rank against the current watchlist, without adding it. (Answers "does META earn a spot?" in one search.)
- **"This month's qualifying candidates" card** (mirrors the credit side's shortlist): after Rank now, apply all gates automatically — top of ranking, liquidity pass, fits playbook cap, respects 2-per-theme against current holdings, **and reward-to-risk floor: modeled spread's max profit ≥ 1.5× its debit** (a pass/fail structure check only — max profit must never be used to rank or reorder candidates; selection order is always momentum rank) — and display the resulting shortlist of ≤7 with proposed strikes, est. debit, max profit, and theme. Labeled "suggested for review, not execution." One click on a candidate pre-fills the paper-entry form. Flag data-suspect rows (ROC > 1,000%, or < 300 trading days of history — spinoffs/splits/recent IPOs) with a "verify on chart" warning rather than silently including them.
- Watchlist editor: add/remove names, with a warning that the universe definition should be rules-based and stable, not vibes

---

## 3. Liquidity gate (new, required)

**Why.** Momentum in the stock ≠ liquid options, especially 6–12 months out. Wide LEAP markets can eat 15–20% of a small spread round-trip.

**Gate definition (per name, measured on the model spread's two strikes):**
- Bid/ask width of the spread (net) ≤ **10% of mid** → pass
- Open interest ≥ **100 contracts** on each leg → pass
- Both required. Fail either → name shows in the ranking but is flagged "illiquid — watchlist only"

Pull from yfinance option chains; if OI unavailable intraday, use previous close.

---

## 4. Paper trading book for momentum spreads

**Purpose.** Run at least one full monthly cycle (ideally two) on paper before live. Must exercise the *entire* loop: rank → enter → mark → exit-alert → close → review.

**Features:**
- **Paper entry** from the ranking table: pick name → app proposes the model spread (strikes, expiry, est. debit at mid) → user can adjust strikes → confirm → position opens at the *ask-side* fill (pessimistic fills on entry, bid-side on exit — mirror real friction, don't flatter the paper results)
- **Cap enforcement:** max 7 simultaneous paper positions; blocks entry over per-position or total deployment cap; blocks a 3rd position in the same theme
- **Theme exposure meter:** live readout per theme — position count, dollars, and % of deployed capital (e.g. "AI hardware: 2 positions · $980 · 26% of deployed"). Displayed on the paper book page and at the moment of entry, so a proposed trade shows what it does to concentration before it's confirmed
- **Live marks:** each open paper spread marked daily (or on page load) from live option quotes; show current value, P&L, and **% of max value reached** — this is the number the profit exit keys on
- **Exit alerts, two rules, shown on the position card:**
  1. Spread ≥ **75% of max value** → "Profit exit triggered" (75% is the standing default, chosen in advance; revisit only via backtest results in §6, never mid-trade)
  2. Monthly re-rank: name no longer in top N of ranking → "Signal exit triggered"
  Plus a passive warning at **< 45 DTE**: "Close before expiry week — pin risk"
- **Paper close:** one click, fills at bid-side mid, logs realized P&L
- **Scorecard:** running total P&L, win rate, avg win/avg loss, and — most important — **rule adherence %**: of exits taken, how many matched a triggered rule vs. discretionary. Same adherence philosophy already in the credit playbook. Adherence is the metric that decides readiness for live, not P&L.
- Journal auto-entry on every paper open/close with the rule state at that moment

---

## 5. Re-rank alert (small but essential)

At each monthly Rank now: compare current holdings (paper or live) against the new top ranks → banner listing any held name that fell out: "Signal exit: close X." Without this, the exit half of the strategy lives in Julie's memory.

---

## 6. Backtester: add call debit spreads

Currently supports bull put spreads / CSPs / long options; glossary marks debit spreads "not in playbook yet."

- Add call-debit-spread simulation: configurable long strike offset (% OTM), width (%), DTE window (150–365), profit exit (% of max value), monthly re-rank exit
- Run the momentum strategy end-to-end on the watchlist: monthly rank by 252-day ROC → hold top N as spreads → both exit rules
- Model fills at bid/ask, not mid — the original strategy's own backtest did this and it matters at these widths
- **Known limitation to display on results:** any backtest on the current 21-name watchlist inherits hindsight bias (names were chosen knowing they performed). Results are for tuning exits/sizing, not for projecting returns.

---

## 7. Explicitly out of scope (do not build yet)

- Auto-execution of any kind — read-only stays read-only
- Daily re-ranking or intraday momentum signals (noise; the strategy acts monthly)
- Additional playbooks before the paper cycle completes

---

## 8. Bug fixes from first live run (7/6/2026) — do these before the paper book

**8.1 Spread builder: solve width from budget, not price %.**
Current model (buy ~5% OTM, sell 15–20% higher) scales width with stock price — on high-priced names it produces $1,200–7,000 spreads and everything fails the cap. Spec error, not implementation error. Fix: for each name, find the widest available spread (real strike increments) whose **ask-side debit ≤ ~$550**. Show that spread's cost and max profit in the table. Only mark "over cap" if even the *minimum* available width exceeds $600 — that name is genuinely untradeable at this account size.

**8.2 yfinance rate limiting (YFRateLimitError skips, blank liquidity column).**
- Fetch option chains only for the top ~10 ranked names — ranking itself needs only stock prices
- Throttle: 2–3s between chain requests; retry with exponential backoff on failure
- Cache chains per session so re-clicks don't re-fetch
- Keep the current fail-closed behavior (skipped names excluded from candidates, skip reason displayed) — that part is correct

**8.3 Sort handling of missing data.**
n/a ROC values currently sort to the top (NaN treated as largest). Fix: rows with missing signal sink to the bottom of the table AND are ineligible as candidates regardless of other gates — no signal means nothing to rank (e.g., SPCX showed ✓ fits-cap while having no ROC at all; affordability without signal must never qualify).

**8.4 Spread builder: add a moneyness ceiling (found 7/6 second run).**
Budget-solved width with no moneyness limit produces lottery structures on cheap stocks — e.g., OSCR at $32 got a 32.5-wide spread (short strike ≈ 2× spot, max profit 5× debit = very low probability). Fix: two constraints together — ask-side debit ≤ ~$550 AND **short strike ≤ 15–20% above current price**. Solve for the widest width satisfying both. On cheap stocks this yields narrow, sane spreads (OSCR ≈ buy ~$33 / sell ~$38). Sanity display: flag any row whose max-profit-to-debit ratio exceeds ~3× — outsized payout means the strikes drifted too far OTM.

**8.5 Candidates must read from cached chains, not re-fetch.**
Second run showed every cap-fitting name skipped with YFRateLimitError on Find Candidates while the ranking table already had spread estimates — i.e., chains were fetched for ranking, then re-fetched for candidates and throttled. Fix: fetch chains once per Rank Now, persist for the session, and have Find Candidates (and paper-entry prefill) read only from that store. If throttling persists even with caching: increase inter-request delay to 5–10s and/or add an alternate chain source as fallback.

**8.6 Expandable ranking rows — show the modeled contract.**
Ranking table currently shows only net cost ("~$768 25w") and max profit; the legs are invisible, so numbers can't be verified against a broker. Fix: click/expand any row to reveal the modeled trade — long strike, short strike, expiration date, est. long price (ask), est. short credit (bid), net debit, and the max-profit arithmetic (width × 100 − debit). Goal: any row verifiable against thinkorswim in under a minute.

---

## Acceptance walkthrough (Julie's monthly session, ~30 min)

1. Open **Momentum spreads** page → click **Rank now**
2. Read top of list; illiquid and over-cap names already flagged; themes visible
3. Enter/adjust paper spreads on qualifying leaders (≤7 total, ≤2 per theme)
4. Any held name flagged by re-rank alert → close it
5. Weekly between sessions: 5-minute glance at position cards; close anything showing "Profit exit triggered"
6. After the cycle: review scorecard — adherence % first, P&L second
