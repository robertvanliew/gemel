# Phase 1: Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test the `core/` package — data adapters (yfinance + Alpaca) with parquet caching, indicators, Black-Scholes + IV proxy, regime classifier, event calendar, and the SQLite schema — that the journal, backtester, scanner, and dashboard (Phases 2–5) all sit on.

**Architecture:** Only `core/data/` touches the network; everything downstream consumes pandas DataFrames so all logic is unit-testable offline. Adapters implement one `DataAdapter` interface and are selected via `DATA_SOURCE` in `.env`. SQLite (SQLModel) stores decisions/results only; price bars live in a parquet cache.

**Tech Stack:** Python 3.14 (venv at `.venv`), pandas 3.x, numpy 2.x, pyarrow, SQLModel, yfinance 1.4.x, alpaca-py 0.43.x, python-dotenv, pytest.

**Conventions for every task:**
- Run commands from the repo root: `c:\Users\12124\Documents\Scanner, Back Tester`
- Python is always the venv interpreter: `.venv\Scripts\python.exe`; pytest via `.venv\Scripts\python.exe -m pytest`
- The spec is `docs/superpowers/specs/2026-06-12-trading-tools-design.md`
- **No network calls in tests.** Anything that would hit the network gets monkeypatched.

---

### Task 1: Project scaffold + test harness

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `core/__init__.py`, `core/data/__init__.py`, `core/options/__init__.py`, `tests/__init__.py`
- Create: `tests/test_scaffold.py`

- [ ] **Step 1: Write requirements.txt**

```
# data
yfinance>=1.4
alpaca-py>=0.43
pandas>=3.0
numpy>=2.4
pyarrow>=17
# storage
sqlmodel>=0.0.22
# web (used from Phase 2 on, pinned now so the env is stable)
fastapi>=0.115
uvicorn[standard]>=0.32
jinja2>=3.1
python-multipart>=0.0.12
httpx>=0.27
# config
python-dotenv>=1.0
# test
pytest>=8.3
```

- [ ] **Step 2: Write pytest.ini**

```ini
[pytest]
testpaths = tests
addopts = -q
```

- [ ] **Step 3: Create empty package markers**

Create these four files, each containing only a newline: `core/__init__.py`, `core/data/__init__.py`, `core/options/__init__.py`, `tests/__init__.py`

- [ ] **Step 4: Write the failing scaffold test**

`tests/test_scaffold.py`:
```python
def test_core_imports():
    import core
    import core.data
    import core.options
```

- [ ] **Step 5: Install dependencies and run the test**

Run: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Then: `.venv\Scripts\python.exe -m pytest tests/test_scaffold.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini core tests
git commit -m "chore: scaffold core package and test harness"
```

---

### Task 2: Indicators — EMA

**Files:**
- Create: `core/indicators.py`
- Create: `tests/test_indicators.py`

- [ ] **Step 1: Write the failing test**

`tests/test_indicators.py`:
```python
import pandas as pd
import pytest

from core.indicators import ema


def test_ema_hand_computed_span3():
    # span=3 -> k = 2/(3+1) = 0.5
    # e0=1; e1 = 2*0.5 + 1*0.5 = 1.5; e2 = 3*0.5 + 1.5*0.5 = 2.25
    s = pd.Series([1.0, 2.0, 3.0])
    out = ema(s, 3)
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(1.5)
    assert out.iloc[2] == pytest.approx(2.25)


def test_ema_returns_series_same_index():
    s = pd.Series([10.0, 11.0, 12.0], index=pd.date_range("2026-01-01", periods=3))
    out = ema(s, 2)
    assert (out.index == s.index).all()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name 'ema'`

- [ ] **Step 3: Implement**

`core/indicators.py`:
```python
"""Pure technical-indicator functions. No look-ahead: every value at index i
is computed from data up to and including i."""
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (adjust=False -> recursive, no look-ahead)."""
    return series.ewm(span=span, adjust=False).mean()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/indicators.py tests/test_indicators.py
git commit -m "feat(core): ema indicator"
```

---

### Task 3: Indicators — RSI (Wilder)

**Files:**
- Modify: `core/indicators.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_indicators.py`)

```python
from core.indicators import rsi


def test_rsi_all_gains_is_100():
    s = pd.Series([float(x) for x in range(1, 40)])
    assert rsi(s, 14).iloc[-1] == pytest.approx(100.0)


def test_rsi_hand_computed_period2():
    # closes [10,11,10,11] -> deltas [1,-1,1]
    # Wilder smoothing alpha=1/2, adjust=False:
    #   gains  [1,0,1] -> 1, .5, .75 ; losses [0,1,0] -> 0, .5, .25
    # RS = .75/.25 = 3 -> RSI = 100 - 100/(1+3) = 75
    s = pd.Series([10.0, 11.0, 10.0, 11.0])
    assert rsi(s, 2).iloc[-1] == pytest.approx(75.0)


def test_rsi_bounded_0_100():
    s = pd.Series([100.0, 99.0, 101.0, 98.0, 102.0, 97.0, 103.0, 100.0] * 5)
    out = rsi(s, 14).dropna()
    assert ((out >= 0) & (out <= 100)).all()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name 'rsi'`

- [ ] **Step 3: Implement** (append to `core/indicators.py`)

```python
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index with Wilder's smoothing (ewm alpha=1/period)."""
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # where avg_loss == 0 (pure uptrend) RSI is 100 by definition
    out = out.where(avg_loss != 0, 100.0)
    out.iloc[0] = float("nan")  # no delta on the first bar
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/indicators.py tests/test_indicators.py
git commit -m "feat(core): rsi indicator (Wilder smoothing)"
```

---

### Task 4: Indicators — support detection (swing-low clustering)

**Files:**
- Modify: `core/indicators.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_indicators.py`)

```python
import numpy as np

from core.indicators import detect_support


def _bars_with_double_bottom() -> pd.DataFrame:
    # price drifts 110 -> dips to ~100 (bar 10) -> recovers -> dips to ~100.5 (bar 25) -> ends 107
    lows = np.array(
        [110, 108, 106, 104, 103, 102, 101.5, 101, 100.5, 100.2,
         100.0, 100.8, 102, 103.5, 105, 106, 105.5, 104, 103, 102,
         101.5, 101.2, 100.9, 100.7, 100.6, 100.5, 101.5, 103, 105, 107],
        dtype=float,
    )
    return pd.DataFrame({"low": lows, "close": lows + 0.5})


def test_detect_support_finds_double_bottom_level():
    bars = _bars_with_double_bottom()
    level = detect_support(bars, lookback=30)
    assert level is not None
    assert 99.5 <= level <= 101.0  # the ~100 cluster


def test_detect_support_none_when_no_swing_lows():
    # strictly rising lows -> a single swing low at best, below min_touches
    bars = pd.DataFrame({"low": np.linspace(100, 130, 30), "close": np.linspace(100.5, 130.5, 30)})
    assert detect_support(bars, lookback=30) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_support'`

- [ ] **Step 3: Implement** (append to `core/indicators.py`)

```python
def detect_support(
    bars: pd.DataFrame,
    lookback: int = 60,
    wing: int = 2,
    cluster_tol: float = 0.015,
    min_touches: int = 2,
) -> float | None:
    """Find the strongest support level below the current close.

    Method: swing lows (a low strictly lower than `wing` bars on each side)
    within the last `lookback` bars are clustered when within `cluster_tol`
    (fractional) of each other. The cluster with the most touches (ties -> the
    higher level) wins, if it has >= min_touches and sits below the last close.
    Returns the cluster's mean level, or None.
    """
    window = bars.tail(lookback)
    lows = window["low"].to_numpy()
    last_close = float(window["close"].iloc[-1])

    swings: list[float] = []
    for i in range(wing, len(lows) - wing):
        left = lows[i - wing : i]
        right = lows[i + 1 : i + 1 + wing]
        if (lows[i] < left).all() and (lows[i] < right).all():
            swings.append(float(lows[i]))
    if not swings:
        return None

    swings.sort()
    clusters: list[list[float]] = [[swings[0]]]
    for level in swings[1:]:
        if level <= clusters[-1][0] * (1.0 + cluster_tol):
            clusters[-1].append(level)
        else:
            clusters.append([level])

    candidates = [
        (len(c), sum(c) / len(c))
        for c in clusters
        if len(c) >= min_touches and (sum(c) / len(c)) < last_close
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))  # most touches, then highest level
    return candidates[-1][1]
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_indicators.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add core/indicators.py tests/test_indicators.py
git commit -m "feat(core): support detection via swing-low clustering"
```

---

### Task 5: Regime classifier

**Files:**
- Create: `core/regime.py`
- Create: `tests/test_regime.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_regime.py`:
```python
import numpy as np
import pandas as pd

from core.regime import Regime, classify_regime


def _closes(values) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_rising_market_is_trending_up():
    closes = _closes(np.linspace(100, 150, 120))
    assert classify_regime(closes) == Regime.TRENDING_UP


def test_falling_market_is_declining():
    closes = _closes(np.linspace(150, 100, 120))
    assert classify_regime(closes) == Regime.DECLINING


def test_flat_market_is_choppy():
    base = np.full(120, 100.0)
    base[::2] += 0.5  # tiny alternation around a flat line
    assert classify_regime(_closes(base)) == Regime.CHOPPY
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_regime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.regime'`

- [ ] **Step 3: Implement**

`core/regime.py`:
```python
"""Market-regime classification: SPY (or any benchmark) vs its 50-day EMA + slope.

Used by the scanner's master gate / playbook and the backtester's
regime-segmented reporting (the 'bull-market trap' check).
"""
from enum import Enum

import pandas as pd

from core.indicators import ema


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    CHOPPY = "choppy"
    DECLINING = "declining"


def classify_regime(closes: pd.Series, slope_bars: int = 10, slope_tol: float = 0.005) -> Regime:
    """Classify using the last close vs the 50-EMA and the EMA's recent slope.

    - above the 50-EMA with the EMA rising  > slope_tol over slope_bars -> TRENDING_UP
    - below the 50-EMA with the EMA falling < -slope_tol               -> DECLINING
    - everything else                                                   -> CHOPPY
    """
    e50 = ema(closes, 50)
    last_close = float(closes.iloc[-1])
    ema_now = float(e50.iloc[-1])
    ema_then = float(e50.iloc[-1 - slope_bars])
    slope = ema_now / ema_then - 1.0

    if last_close > ema_now and slope > slope_tol:
        return Regime.TRENDING_UP
    if last_close < ema_now and slope < -slope_tol:
        return Regime.DECLINING
    return Regime.CHOPPY
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_regime.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/regime.py tests/test_regime.py
git commit -m "feat(core): market regime classifier"
```

---

### Task 6: Black-Scholes pricing + greeks

**Files:**
- Create: `core/options/black_scholes.py`
- Create: `tests/test_black_scholes.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_black_scholes.py`:
```python
import pytest

from core.options.black_scholes import bs_call, bs_put, put_delta


# Classic textbook reference values: S=100, K=100, T=1y, r=5%, sigma=20%
S, K, T, R, SIG = 100.0, 100.0, 1.0, 0.05, 0.20


def test_bs_call_reference_value():
    assert bs_call(S, K, T, SIG, R) == pytest.approx(10.4506, abs=1e-3)


def test_bs_put_reference_value():
    assert bs_put(S, K, T, SIG, R) == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    import math
    call, put = bs_call(S, K, T, SIG, R), bs_put(S, K, T, SIG, R)
    assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_put_delta_reference_value():
    # d1 = 0.35 -> N(d1) = 0.63683 -> put delta = N(d1) - 1 = -0.36317
    assert put_delta(S, K, T, SIG, R) == pytest.approx(-0.36317, abs=1e-4)


def test_expiry_is_intrinsic():
    assert bs_put(90.0, 100.0, 0.0, SIG, R) == pytest.approx(10.0)
    assert bs_call(110.0, 100.0, 0.0, SIG, R) == pytest.approx(10.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_black_scholes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.options.black_scholes'`

- [ ] **Step 3: Implement**

`core/options/black_scholes.py`:
```python
"""Black-Scholes pricing for European options.

One pricing path feeds the scanner's candidate math, the backtester's leg
valuation, and the dashboard's T+0 curves / P&L matrix — keep it pure.
"""
import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(s: float, k: float, t: float, sigma: float, r: float) -> float:
    return (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def bs_call(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return max(s - k, 0.0)
    d1 = _d1(s, k, t, sigma, r)
    d2 = d1 - sigma * math.sqrt(t)
    return s * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)


def bs_put(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return max(k - s, 0.0)
    d1 = _d1(s, k, t, sigma, r)
    d2 = d1 - sigma * math.sqrt(t)
    return k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def call_delta(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return 1.0 if s > k else 0.0
    return _norm_cdf(_d1(s, k, t, sigma, r))


def put_delta(s: float, k: float, t: float, sigma: float, r: float = 0.04) -> float:
    if t <= 0:
        return -1.0 if s < k else 0.0
    return _norm_cdf(_d1(s, k, t, sigma, r)) - 1.0
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_black_scholes.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/options/black_scholes.py tests/test_black_scholes.py
git commit -m "feat(core): black-scholes pricing and deltas"
```

---

### Task 7: IV proxy + IV rank

**Files:**
- Create: `core/options/iv_proxy.py`
- Create: `tests/test_iv_proxy.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_iv_proxy.py`:
```python
import numpy as np
import pandas as pd
import pytest

from core.options.iv_proxy import iv_rank, realized_vol, vol_index_symbol


def test_vol_index_mapping():
    assert vol_index_symbol("SPY") == "^VIX"
    assert vol_index_symbol("QQQ") == "^VXN"
    assert vol_index_symbol("IWM") == "^RVX"
    assert vol_index_symbol("GLD") is None  # no index -> realized-vol fallback


def test_realized_vol_constant_series_is_zero():
    closes = pd.Series(np.full(60, 100.0))
    assert realized_vol(closes) == pytest.approx(0.0)


def test_realized_vol_is_annualized_std_of_log_returns():
    closes = pd.Series([100.0, 101.0, 100.0, 101.0] * 20)
    lr = np.log(closes / closes.shift(1)).dropna()
    expected = float(lr.std(ddof=1) * np.sqrt(252))
    assert realized_vol(closes) == pytest.approx(expected)


def test_iv_rank_endpoints_and_midpoint():
    year = pd.Series(np.linspace(10.0, 30.0, 252))  # 52wk range 10..30
    assert iv_rank(year, current=10.0) == pytest.approx(0.0)
    assert iv_rank(year, current=30.0) == pytest.approx(100.0)
    assert iv_rank(year, current=20.0) == pytest.approx(50.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_iv_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.options.iv_proxy'`

- [ ] **Step 3: Implement**

`core/options/iv_proxy.py`:
```python
"""Implied-volatility proxy for free-data mode (spec 'path b').

Tickers with a free CBOE volatility index use it directly (VIX family);
everything else falls back to annualized realized volatility. IV rank
locates today's IV within its trailing 52-week range (the scanner's
IVR >= 25 gate).
"""
import numpy as np
import pandas as pd

_VOL_INDEX = {"SPY": "^VIX", "QQQ": "^VXN", "IWM": "^RVX"}

TRADING_DAYS = 252


def vol_index_symbol(ticker: str) -> str | None:
    """The matching volatility-index symbol, or None -> use realized_vol."""
    return _VOL_INDEX.get(ticker.upper())


def realized_vol(closes: pd.Series, window: int | None = None) -> float:
    """Annualized std-dev of daily log returns (optionally over a tail window)."""
    if window is not None:
        closes = closes.tail(window + 1)
    log_returns = np.log(closes / closes.shift(1)).dropna()
    if log_returns.empty:
        return 0.0
    return float(log_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def iv_rank(year_of_iv: pd.Series, current: float) -> float:
    """Where `current` sits in the past year's IV range, 0..100."""
    lo, hi = float(year_of_iv.min()), float(year_of_iv.max())
    if hi == lo:
        return 50.0
    return max(0.0, min(100.0, (current - lo) / (hi - lo) * 100.0))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_iv_proxy.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/options/iv_proxy.py tests/test_iv_proxy.py
git commit -m "feat(core): IV proxy (VIX-family + realized vol) and IV rank"
```

---

### Task 8: DataAdapter interface + yfinance adapter

**Files:**
- Create: `core/data/base.py`
- Create: `core/data/yfinance_adapter.py`
- Create: `tests/test_yfinance_adapter.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_yfinance_adapter.py`:
```python
import pandas as pd
import pytest

import core.data.yfinance_adapter as yfa
from core.data.yfinance_adapter import YFinanceAdapter


class _FakeTicker:
    """Stands in for yfinance.Ticker — tests never touch the network."""

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period=None, interval=None, auto_adjust=True):
        idx = pd.date_range("2026-01-05", periods=3, freq="B", tz="America/New_York")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.5, 101.5, 102.5],
                "Volume": [1_000, 1_100, 1_200],
                "Dividends": [0.0, 0.0, 0.0],     # yfinance includes extras; adapter must drop them
                "Stock Splits": [0.0, 0.0, 0.0],
            },
            index=idx,
        )


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(yfa.yf, "Ticker", _FakeTicker)
    return YFinanceAdapter()


def test_get_daily_bars_normalized_schema(adapter):
    bars = adapter.get_daily_bars("SPY", lookback_days=120)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert bars.index.tz is None  # normalized to tz-naive dates
    assert bars["close"].iloc[-1] == pytest.approx(102.5)


def test_get_quote_is_last_close(adapter):
    assert adapter.get_quote("SPY") == pytest.approx(102.5)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_yfinance_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.data.yfinance_adapter'`

- [ ] **Step 3: Implement the interface**

`core/data/base.py`:
```python
"""DataAdapter: the only seam in the system that touches the network.

Everything downstream consumes the normalized DataFrame schema returned here:
columns [open, high, low, close, volume], tz-naive DatetimeIndex, float prices.
"""
from abc import ABC, abstractmethod

import pandas as pd


class DataAdapter(ABC):
    @abstractmethod
    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        """Daily OHLCV, normalized schema, oldest row first."""

    @abstractmethod
    def get_quote(self, ticker: str) -> float:
        """Most recent price the source can provide (delayed is acceptable)."""


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Map any source frame with OHLCV-ish columns onto the canonical schema."""
    out = df.rename(columns={c: c.lower() for c in df.columns})
    out = out[["open", "high", "low", "close", "volume"]].astype(
        {"open": float, "high": float, "low": float, "close": float}
    )
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    return out.sort_index()
```

- [ ] **Step 4: Implement the yfinance adapter**

`core/data/yfinance_adapter.py`:
```python
"""Default zero-config adapter. Free, ~15-min-delayed quotes, daily bars,
volatility indices (^VIX family) — sufficient for the whole phase-1 system."""
import pandas as pd
import yfinance as yf

from core.data.base import DataAdapter, normalize_bars


class YFinanceAdapter(DataAdapter):
    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        # yfinance periods are coarse; round up to cover lookback_days calendar-wise
        days = max(lookback_days, 5)
        raw = yf.Ticker(ticker).history(period=f"{days * 2}d", interval="1d", auto_adjust=True)
        if raw.empty:
            raise RuntimeError(f"yfinance returned no data for {ticker!r}")
        return normalize_bars(raw).tail(lookback_days)

    def get_quote(self, ticker: str) -> float:
        return float(self.get_daily_bars(ticker, lookback_days=5)["close"].iloc[-1])
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_yfinance_adapter.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add core/data/base.py core/data/yfinance_adapter.py tests/test_yfinance_adapter.py
git commit -m "feat(core): DataAdapter interface + yfinance adapter"
```

---

### Task 9: Parquet bar cache

**Files:**
- Create: `core/data/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`:
```python
import pandas as pd

from core.data.base import DataAdapter
from core.data.cache import CachedAdapter


class _CountingAdapter(DataAdapter):
    """Fake source that counts fetches so tests can prove cache hits."""

    def __init__(self):
        self.fetches = 0

    def get_daily_bars(self, ticker, lookback_days=120):
        self.fetches += 1
        idx = pd.date_range("2026-01-05", periods=lookback_days, freq="B")
        return pd.DataFrame(
            {
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.5, "volume": 1_000,
            },
            index=idx,
        )

    def get_quote(self, ticker):
        return 100.5


def test_second_read_hits_cache(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path, max_age_days=999)
    a = cached.get_daily_bars("SPY", lookback_days=30)
    b = cached.get_daily_bars("SPY", lookback_days=30)
    assert src.fetches == 1
    # check_freq=False: parquet round-trips drop the index freq attribute
    pd.testing.assert_frame_equal(a, b, check_freq=False)
    assert (tmp_path / "SPY.parquet").exists()


def test_stale_cache_refetches(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path, max_age_days=0)  # everything is stale
    cached.get_daily_bars("SPY", lookback_days=30)
    cached.get_daily_bars("SPY", lookback_days=30)
    assert src.fetches == 2


def test_quote_passes_through(tmp_path):
    src = _CountingAdapter()
    cached = CachedAdapter(src, cache_dir=tmp_path)
    assert cached.get_quote("SPY") == 100.5
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.data.cache'`

- [ ] **Step 3: Implement**

`core/data/cache.py`:
```python
"""Parquet-backed read-through cache wrapping any DataAdapter.

Bars are bulk columnar data: they live as one parquet file per ticker in
data/cache/, NOT in SQLite (which stores decisions and results only).
"""
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core.data.base import DataAdapter


class CachedAdapter(DataAdapter):
    def __init__(self, source: DataAdapter, cache_dir: str | Path = "data/cache", max_age_days: int = 1):
        self.source = source
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days

    def _path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.parquet"

    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        path = self._path(ticker)
        if path.exists():
            cached = pd.read_parquet(path)
            fresh_enough = cached.index[-1] >= pd.Timestamp(datetime.now().date()) - timedelta(days=self.max_age_days)
            if fresh_enough and len(cached) >= lookback_days:
                return cached.tail(lookback_days)
        bars = self.source.get_daily_bars(ticker, lookback_days=lookback_days)
        bars.to_parquet(path)
        return bars

    def get_quote(self, ticker: str) -> float:
        return self.source.get_quote(ticker)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cache.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/data/cache.py tests/test_cache.py
git commit -m "feat(core): parquet read-through cache for daily bars"
```

---

### Task 10: Alpaca adapter

**Files:**
- Create: `core/data/alpaca_adapter.py`
- Create: `tests/test_alpaca_adapter.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_alpaca_adapter.py`:
```python
import pandas as pd
import pytest

from core.data.alpaca_adapter import AlpacaAdapter


class _FakeBarsResponse:
    @property
    def df(self):
        idx = pd.MultiIndex.from_product(
            [["SPY"], pd.date_range("2026-01-05", periods=3, freq="B", tz="UTC")],
            names=["symbol", "timestamp"],
        )
        return pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1_000, 1_100, 1_200],
                "trade_count": [10, 11, 12],    # alpaca extras; adapter must drop
                "vwap": [100.4, 101.4, 102.4],
            },
            index=idx,
        )


class _FakeClient:
    def __init__(self, *a, **kw):
        pass

    def get_stock_bars(self, request):
        return _FakeBarsResponse()


@pytest.fixture
def adapter(monkeypatch):
    import core.data.alpaca_adapter as aa
    monkeypatch.setattr(aa, "StockHistoricalDataClient", _FakeClient)
    return AlpacaAdapter(api_key="test-key", secret_key="test-secret")


def test_missing_keys_raise():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaAdapter(api_key="", secret_key="")


def test_get_daily_bars_normalized_schema(adapter):
    bars = adapter.get_daily_bars("SPY", lookback_days=3)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(bars.index, pd.DatetimeIndex)
    assert bars.index.tz is None
    assert bars["close"].iloc[-1] == pytest.approx(102.5)


def test_get_quote_is_last_close(adapter):
    assert adapter.get_quote("SPY") == pytest.approx(102.5)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alpaca_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.data.alpaca_adapter'`

- [ ] **Step 3: Implement**

`core/data/alpaca_adapter.py`:
```python
"""Keyed adapter for Alpaca Market Data (free tier = IEX feed).

MARKET DATA ONLY: this module imports the historical-data client exclusively.
No trading client, no order endpoints — that is a hard project guardrail.
"""
import os
from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from core.data.base import DataAdapter, normalize_bars


class AlpacaAdapter(DataAdapter):
    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        api_key = api_key if api_key is not None else os.getenv("ALPACA_API_KEY", "")
        secret_key = secret_key if secret_key is not None else os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            raise ValueError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing — set them in .env")
        self.client = StockHistoricalDataClient(api_key, secret_key)

    def get_daily_bars(self, ticker: str, lookback_days: int = 120) -> pd.DataFrame:
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=lookback_days * 2),
        )
        raw = self.client.get_stock_bars(req).df
        if raw.empty:
            raise RuntimeError(f"alpaca returned no data for {ticker!r}")
        raw = raw.xs(ticker, level="symbol")
        return normalize_bars(raw).tail(lookback_days)

    def get_quote(self, ticker: str) -> float:
        return float(self.get_daily_bars(ticker, lookback_days=5)["close"].iloc[-1])
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alpaca_adapter.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/data/alpaca_adapter.py tests/test_alpaca_adapter.py
git commit -m "feat(core): alpaca market-data adapter (read-only)"
```

---

### Task 11: Adapter factory (env-driven selection)

**Files:**
- Create: `core/data/factory.py`
- Create: `tests/test_factory.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_factory.py`:
```python
import pytest

from core.data.cache import CachedAdapter
from core.data.factory import make_adapter
from core.data.yfinance_adapter import YFinanceAdapter


def test_default_is_cached_yfinance(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    adapter = make_adapter(cache_dir=tmp_path)
    assert isinstance(adapter, CachedAdapter)
    assert isinstance(adapter.source, YFinanceAdapter)


def test_alpaca_selected_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_SOURCE", "alpaca")
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")

    import core.data.alpaca_adapter as aa

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

    monkeypatch.setattr(aa, "StockHistoricalDataClient", _FakeClient)
    adapter = make_adapter(cache_dir=tmp_path)
    assert isinstance(adapter, CachedAdapter)
    assert isinstance(adapter.source, aa.AlpacaAdapter)


def test_unknown_source_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_SOURCE", "robinhood")
    with pytest.raises(ValueError, match="DATA_SOURCE"):
        make_adapter(cache_dir=tmp_path)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.data.factory'`

- [ ] **Step 3: Implement**

`core/data/factory.py`:
```python
"""Build the configured adapter: DATA_SOURCE in .env -> yfinance (default) | alpaca.

Everything that needs market data calls make_adapter() and stays
source-agnostic. Always wrapped in the parquet cache.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from core.data.base import DataAdapter
from core.data.cache import CachedAdapter


def make_adapter(cache_dir: str | Path = "data/cache") -> CachedAdapter:
    load_dotenv()
    source_name = os.getenv("DATA_SOURCE", "yfinance").lower()
    source: DataAdapter
    if source_name == "yfinance":
        from core.data.yfinance_adapter import YFinanceAdapter
        source = YFinanceAdapter()
    elif source_name == "alpaca":
        from core.data.alpaca_adapter import AlpacaAdapter
        source = AlpacaAdapter()
    else:
        raise ValueError(f"DATA_SOURCE={source_name!r} is not supported (yfinance | alpaca)")
    return CachedAdapter(source, cache_dir=cache_dir)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_factory.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/data/factory.py tests/test_factory.py
git commit -m "feat(core): env-driven adapter factory with cache wrapping"
```

---

### Task 12: Event calendar (FOMC + earnings gate)

**Files:**
- Create: `core/calendar.py`
- Create: `tests/test_calendar.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_calendar.py`:
```python
from datetime import date

from core.calendar import FOMC_DATES, has_event_risk


def test_fomc_dates_present_for_2026():
    assert any(d.year == 2026 for d in FOMC_DATES)


def test_fomc_inside_window_is_event_risk():
    fomc = sorted(d for d in FOMC_DATES if d.year == 2026)[0]
    assert has_event_risk(start=fomc, expiry=fomc, earnings_date=None) is True


def test_no_events_means_no_risk():
    assert has_event_risk(start=date(2026, 1, 2), expiry=date(2026, 1, 3), earnings_date=None) is False


def test_earnings_inside_window_is_event_risk():
    assert (
        has_event_risk(start=date(2026, 7, 1), expiry=date(2026, 8, 15), earnings_date=date(2026, 7, 30))
        is True
    )


def test_earnings_after_expiry_is_fine():
    assert (
        has_event_risk(start=date(2026, 7, 1), expiry=date(2026, 7, 10), earnings_date=date(2026, 7, 30))
        is False
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.calendar'`

- [ ] **Step 3: Implement**

`core/calendar.py`:
```python
"""Event-risk filter: scheduled events that can gap price through both strikes.

FOMC meeting dates are a static list (8/year, published years ahead by the Fed)
— update annually. Earnings dates come from the data adapter at scan time and
are passed in; ETFs in the core universe have no earnings, but XLK/XLV-style
sector screens treat top-holding earnings clusters as the earnings_date.
"""
from datetime import date

# Second day of each two-day FOMC meeting (the announcement day), 2026.
# Source: federalreserve.gov FOMC calendar. Update each December.
FOMC_DATES: list[date] = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


def has_event_risk(start: date, expiry: date, earnings_date: date | None) -> bool:
    """True if an FOMC meeting or the given earnings date falls in [start, expiry]."""
    if any(start <= d <= expiry for d in FOMC_DATES):
        return True
    if earnings_date is not None and start <= earnings_date <= expiry:
        return True
    return False
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_calendar.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/calendar.py tests/test_calendar.py
git commit -m "feat(core): FOMC/earnings event-risk filter"
```

---

### Task 13: SQLite schema (SQLModel)

**Files:**
- Create: `core/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:
```python
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.db import Campaign, Trade, TradeRule, make_engine, init_db


@pytest.fixture
def session():
    engine = make_engine("sqlite://")  # in-memory
    init_db(engine)
    with Session(engine) as s:
        yield s


def _valid_trade(**overrides):
    base = dict(
        ticker="SPY",
        strategy="bull_put_spread",
        opened_at=datetime(2026, 6, 1, 10, 0),
        is_paper=True,
        qty=1,
        short_strike=575.0,
        long_strike=570.0,
        credit_debit=1.42,
        delta_at_entry=0.18,
        dte_at_entry=38,
        reason_for_entry="above 20/50 EMA, RSI 58",
        profit_target="buy back at 50% (0.71)",
        stop="2x credit (2.84)",
        time_stop="close or roll at 21 DTE",
        status="open",
    )
    base.update(overrides)
    return Trade(**base)


def test_round_trip_trade_with_rules(session):
    trade = _valid_trade()
    session.add(trade)
    session.commit()
    session.add(TradeRule(trade_id=trade.id, rule_key="above_emas", rule_label="Above 20/50 EMA", followed=True))
    session.commit()

    loaded = session.exec(select(Trade)).one()
    assert loaded.short_strike == 575.0
    rules = session.exec(select(TradeRule)).all()
    assert len(rules) == 1 and rules[0].followed is True


def test_exit_plan_is_required_at_schema_level(session):
    # profit_target / stop / time_stop are NOT NULL: the journal's
    # "won't save without an exit plan" rule is enforced by the schema.
    session.add(_valid_trade(profit_target=None))
    with pytest.raises(IntegrityError):
        session.commit()


def test_campaign_links_rolled_trades(session):
    camp = Campaign(ticker="QQQ", strategy="bull_put_spread", opened_at=datetime(2026, 4, 14), status="closed")
    session.add(camp)
    session.commit()
    session.add(_valid_trade(ticker="QQQ", campaign_id=camp.id, status="closed", pnl=-54.0))
    session.add(_valid_trade(ticker="QQQ", campaign_id=camp.id, status="closed", pnl=118.0))
    session.commit()

    legs = session.exec(select(Trade).where(Trade.campaign_id == camp.id)).all()
    assert sum(t.pnl for t in legs) == pytest.approx(64.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.db'`

- [ ] **Step 3: Implement**

`core/db.py`:
```python
"""SQLite schema via SQLModel. Holds decisions and results only — price bars
live in the parquet cache. The exit-plan fields on Trade are NOT NULL by
design: 'the plan is written when you're calm' is enforced by the schema.
"""
from datetime import datetime

from sqlmodel import Field, SQLModel, create_engine


class Campaign(SQLModel, table=True):
    """A chain of rolled positions judged as one trade idea."""
    id: int | None = Field(default=None, primary_key=True)
    ticker: str
    strategy: str
    opened_at: datetime
    closed_at: datetime | None = None
    status: str = "open"  # open | closed


class Trade(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaign.id")
    ticker: str
    strategy: str  # bull_put_spread | cash_secured_put | long_option
    opened_at: datetime
    closed_at: datetime | None = None
    is_paper: bool = True
    qty: int = 1
    short_strike: float | None = None
    long_strike: float | None = None   # None for single-leg strategies
    credit_debit: float                # +credit collected / -debit paid, per share
    delta_at_entry: float | None = None
    dte_at_entry: int | None = None
    reason_for_entry: str
    # exit plan — required, not optional (journal hard rule)
    profit_target: str = Field(nullable=False)
    stop: str = Field(nullable=False)
    time_stop: str = Field(nullable=False)
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None           # realized, dollars, set at close
    status: str = "open"               # open | closed


class TradeRule(SQLModel, table=True):
    """One checklist row per rule per trade -> adherence scoring."""
    id: int | None = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trade.id")
    rule_key: str
    rule_label: str
    followed: bool


class BacktestRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)
    strategy: str
    ticker: str
    params_json: str          # JSON: delta band, DTE, frictions...
    date_start: datetime
    date_end: datetime
    oos_start: datetime       # in-sample/out-of-sample boundary
    stats_json: str           # JSON: win rate, PF, drawdown... (IS and OOS)
    regime_stats_json: str    # JSON: per-regime breakdown
    sensitivity_json: str     # JSON: delta x DTE grid


class BacktestTrade(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="backtestrun.id")
    opened_at: datetime
    closed_at: datetime
    short_strike: float | None = None
    long_strike: float | None = None
    credit_debit: float
    exit_reason: str
    pnl: float
    regime: str               # trending_up | choppy | declining
    in_sample: bool


class ScanReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ran_at: datetime = Field(default_factory=datetime.now)
    master_gate_pass: bool
    regime: str
    playbook: str
    summary_md: str = ""


class ScanResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="scanreport.id")
    ticker: str
    passes_json: str          # JSON: {criterion: bool}
    rsi: float | None = None
    ivr: float | None = None
    metrics_json: str = "{}"
    qualifies: bool = False
    rank: int | None = None
    candidate_json: str | None = None  # strikes/credit/max-loss/BE/target/stop for the top pick


def make_engine(url: str = "sqlite:///data/trading.sqlite"):
    return create_engine(url, connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_db.py
git commit -m "feat(core): sqlite schema — trades, campaigns, backtests, scans"
```

---

### Task 14: Full-suite green + live smoke (manual, not in suite)

**Files:**
- Modify: `check_data.py` (extend to exercise the new core)

- [ ] **Step 1: Run the entire offline test suite**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: PASS — all tests from Tasks 1–13 (≈31 tests), zero network calls

- [ ] **Step 2: Rewrite check_data.py to exercise the real core end-to-end**

```python
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
```

- [ ] **Step 3: Run the live smoke test**

Run: `.venv\Scripts\python.exe check_data.py`
Expected: real SPY numbers for every line — close, EMAs, RSI, support level (or none), regime, VIX + IV rank

- [ ] **Step 4: Commit**

```bash
git add check_data.py
git commit -m "feat(core): end-to-end live smoke test over the real core"
```

---

## What Phase 1 deliberately does NOT include

Option-chain fetching (Phase 4 scanner needs it; design the call then), the **ADX indicator**
(spec lists it in `core/indicators.py`, but only the Phase-4 regime-playbook display consumes it —
implement it in the Phase 4 plan alongside its consumer), the backtest engine and strategies
(Phase 3), FastAPI/web (Phase 2), Task Scheduler registration (Phase 4), Claude summary layer
(Phase 5). Each later phase gets its own plan once the previous one lands.
