# Live smoke test (NOT part of the pytest suite — hits the network on purpose).
# Proves the phase-1 core works end to end on real data.
# Run:  .venv\Scripts\python.exe check_data.py
from core.data.factory import make_adapter
from core.indicators import detect_support, ema, rsi
from core.options.iv_proxy import iv_rank, vol_index_symbol
from core.regime import classify_regime

adapter = make_adapter()
bars = adapter.get_daily_bars("SPY", lookback_days=120)
close = bars["close"]

print(f"SPY as of {bars.index[-1].date()}  (source: {type(adapter.source).__name__})")
print(f"  last close : ${close.iloc[-1]:,.2f}")
print(f"  20-day EMA : ${ema(close, 20).iloc[-1]:,.2f}")
print(f"  50-day EMA : ${ema(close, 50).iloc[-1]:,.2f}")
print(f"  RSI(14)    : {rsi(close, 14).iloc[-1]:.1f}")
support = detect_support(bars, lookback=60)
print(f"  support    : {'$' + format(support, ',.2f') if support else 'none detected'}")
print(f"  regime     : {classify_regime(close).value}")

vix_symbol = vol_index_symbol("SPY")
vix = adapter.get_daily_bars(vix_symbol, lookback_days=252)["close"]
print(f"  IV (VIX)   : {vix.iloc[-1]:.1f}  ->  IV rank {iv_rank(vix, float(vix.iloc[-1])):.0f}")
