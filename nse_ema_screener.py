#!/usr/bin/env python3
"""
NSE/BSE 20/50 EMA Crossover Screener - standalone (no TradingView required)
============================================================================
Same strategy/classification logic as the Pine Script v6 screener/indicator:

  BUY            -> 20 EMA just crossed above 50 EMA (fresh, on latest
                     completed daily candle)
  ABOUT TO CROSS -> 20 EMA still below 50 EMA, but rising, with the gap
                     narrowing vs. the previous candle (early warning only)
  HOLD/BULLISH   -> 20 EMA already above 50 EMA (no fresh cross)
  EXIT/SELL      -> 20 EMA just crossed below 50 EMA (fresh)

Data source : Yahoo Finance via `yfinance` (NSE tickers use a ".NS" suffix,
              e.g. RELIANCE.NS). Free, no API key needed.
Alerting    : Telegram bot (sendMessage). Set TELEGRAM_BOT_TOKEN and
              TELEGRAM_CHAT_ID as environment variables (see setup notes at
              the bottom of this file) before running.
Scheduling  : designed to be run once a day via cron, AFTER NSE market close
              (15:30 IST) and after Yahoo's EOD data has settled - 17:30-
              18:00 IST is a safe target.

Install:
    pip install yfinance pandas requests

Run manually:
    python3 nse_ema_screener.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# Config - edit this section
# ---------------------------------------------------------------------------

EMA_FAST = 20
EMA_SLOW = 50

# NSE symbols in Yahoo Finance format (".NS" suffix). BSE-only names use
# ".BO" instead. Edit freely - swap in a full NIFTY 100/200/500 list if you
# want broader coverage (no TradingView-style call cap here).
CORE_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "ASIANPAINT.NS",
    "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS",
    "ADANIENT.NS", "NTPC.NS", "POWERGRID.NS", "TATAMOTORS.NS", "TATASTEEL.NS",
    "JSWSTEEL.NS", "NESTLEIND.NS", "ONGC.NS", "COALINDIA.NS", "BAJAJFINSV.NS",
]

# MTF-eligible watchlist (partial snapshot from a broker's screener - not
# exhaustive, see chat notes).
MTF_WATCHLIST = [
    "ATHERENERG.NS", "TEJASNET.NS", "MASTEK.NS", "NETWEB.NS", "COFORGE.NS",
    "TVSMOTOR.NS", "HDFCBANK.NS", "HINDCOPPER.NS", "RELIANCE.NS", "IFCI.NS",
    "BSE.NS", "FMGOETZE.NS", "VBL.NS", "APARINDS.NS", "LAURUSLABS.NS",
    "RECLTD.NS", "MCX.NS", "OMAXE.NS", "JIOFIN.NS", "BHARTIARTL.NS",
    "ADANIPOWER.NS", "PREMIERENE.NS", "GODREJCP.NS", "NEWGEN.NS", "ITC.NS",
    "REDINGTON.NS", "WELCORP.NS", "TCS.NS", "RATNAVEER.NS", "VOLTAS.NS",
    "CGCL.NS", "MOREPENLAB.NS", "DATAPATTNS.NS", "NHPC.NS", "VEDL.NS",
    "BANKBARODA.NS", "IDEA.NS", "OFSS.NS", "HAPPSTMNDS.NS", "KAYNES.NS",
    "KALYANKJIL.NS", "NAZARA.NS", "VMM.NS", "GENUSPOWER.NS", "TATATECH.NS",
    "ZEEL.NS", "AEROFLEX.NS", "YESBANK.NS", "TATASTEEL.NS", "GESHIP.NS",
    "WOCKPHARMA.NS", "CROMPTON.NS", "EXIDEIND.NS", "BDL.NS", "SOLARINDS.NS",
    "PFC.NS", "COALINDIA.NS", "TATAMOTORS.NS", "HINDPETRO.NS", "BEL.NS",
    "HINDZINC.NS", "SAGILITY.NS", "DIXON.NS", "HAL.NS", "ADANIENSOL.NS",
    "HINDUNILVR.NS", "PARAS.NS", "SONACOMS.NS", "BBTC.NS", "INFY.NS",
    "CYIENT.NS", "ASIANPAINT.NS", "OLAELEC.NS", "SEQUENT.NS", "INOXINDIA.NS",
    "IKIO.NS", "MARUTI.NS", "TECHM.NS", "ANGELONE.NS", "ETERNAL.NS",
    "SHRIRAMFIN.NS", "BHEL.NS", "FORCEMOT.NS", "CHENNPETRO.NS", "WIPRO.NS",
]

# Fundamentally strong (high ROCE/ROE, low D/E) large + mid caps, from
# Screener.in / Equitymaster quality screens (see chat notes).
FUNDAMENTALLY_STRONG = [
    "TITAN.NS", "BEL.NS", "HAL.NS", "COALINDIA.NS", "NESTLEIND.NS",
    "EICHERMOT.NS", "VBL.NS", "DIVISLAB.NS", "CUMMINSIND.NS", "PIDILITIND.NS",
    "ABB.NS", "CGPOWER.NS", "TCS.NS", "INFY.NS", "HINDUNILVR.NS",
    "ITC.NS", "HCLTECH.NS", "ASIANPAINT.NS", "LTIM.NS", "HDFCAMC.NS",
    "HEROMOTOCO.NS", "BOSCHLTD.NS", "MARICO.NS", "PAGEIND.NS", "GLAXO.NS",
    "DIXON.NS", "IRCTC.NS", "ABBOTINDIA.NS", "NATIONALUM.NS", "SOLARINDS.NS",
    "PREMIERENE.NS", "PERSISTENT.NS", "LTTS.NS", "KALYANKJIL.NS", "MAZDOCK.NS",
    "BHARTIHEXA.NS",
]

# NIFTY 50 constituents (as of 8 Dec 2025 - NSE rebalances semi-annually, so
# re-check niftyindices.com if this drifts stale). BAJAJ-AUTO and M&M use
# NSE's actual symbol formatting; verify these two resolve on yfinance in
# your environment before relying on them.
NIFTY_50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "ETERNAL.NS",
    "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HINDALCO.NS",
    "HINDUNILVR.NS", "ICICIBANK.NS", "INDIGO.NS", "INFY.NS", "ITC.NS",
    "JIOFIN.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS",
    "MARUTI.NS", "MAXHEALTH.NS", "NESTLEIND.NS", "NTPC.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SHRIRAMFIN.NS", "SBIN.NS",
    "SUNPHARMA.NS", "TCS.NS", "TATACONSUM.NS", "TMPV.NS", "TATASTEEL.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]

# NIFTY NEXT 50 constituents (as of 30 Mar 2026, sourced from an index-fund
# factsheet - 48 of 50 captured, 2 missing from source extraction). Flagged
# entries below are recent listings/renames worth double-checking on
# nseindia.com before relying on them.
NIFTY_NEXT_50 = [
    "ABB.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS",
    "BAJAJHLDNG.NS", "BANKBARODA.NS", "BOSCHLTD.NS", "BPCL.NS", "BRITANNIA.NS",
    "CANBK.NS", "CGPOWER.NS", "CHOLAFIN.NS", "CUMMINSIND.NS", "DIVISLAB.NS",
    "DLF.NS", "DMART.NS", "GAIL.NS", "GODREJCP.NS", "HAL.NS",
    "HDFCAMC.NS", "HINDZINC.NS", "HYUNDAI.NS", "INDHOTEL.NS", "IOC.NS",
    "IRFC.NS", "JINDALSTEL.NS", "LODHA.NS", "LTIM.NS", "MAZDOCK.NS",
    "MOTHERSON.NS", "MUTHOOTFIN.NS", "PFC.NS", "PIDILITIND.NS", "PNB.NS",
    "RECLTD.NS", "SHREECEM.NS", "SIEMENS.NS", "SOLARINDS.NS", "TATAPOWER.NS",
    "TATAMOTORS.NS", "TORNTPHARM.NS", "TVSMOTOR.NS", "UNIONBANK.NS", "VBL.NS",
    "VEDL.NS", "ZYDUSLIFE.NS",
    # verify before relying on these three (recent listing/rename risk):
    # Siemens Energy India, Tata Capital, United Spirits
]

# Merge all watchlists and de-duplicate (preserving first-seen order) so the
# same symbol never gets scanned - and reported - more than once.
SYMBOLS = list(dict.fromkeys(FUNDAMENTALLY_STRONG + NIFTY_50 + NIFTY_NEXT_50))

LOOKBACK_PERIOD = "1y"     # enough history for a stable 50 EMA warm-up
MAX_ROWS_PER_CATEGORY = 15  # trim long lists in the Telegram message

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = dtime(15, 30)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

CAT_BUY, CAT_ATC, CAT_HOLD, CAT_EXIT, CAT_NONE = "BUY", "ABOUT TO CROSS", "HOLD / BULLISH", "EXIT / SELL", "NONE"


@dataclass
class Result:
    symbol: str
    price: float
    ema_fast: float
    ema_slow: float
    diff_pct: float
    category: str
    cross_date: str | None


# ---------------------------------------------------------------------------
# Core logic (mirrors the Pine Script exactly)
# ---------------------------------------------------------------------------

def classify(ef1: float, es1: float, ef2: float, es2: float) -> str:
    """ef1/es1 = latest completed bar's EMAs, ef2/es2 = the bar before that."""
    fresh_bull = ef2 <= es2 and ef1 > es1
    fresh_bear = ef2 >= es2 and ef1 < es1
    gap_now = es1 - ef1
    gap_prev = es2 - ef2
    rising = ef1 > ef2
    narrowing = gap_now < gap_prev

    if fresh_bull:
        return CAT_BUY
    if fresh_bear:
        return CAT_EXIT
    if ef1 > es1:
        return CAT_HOLD
    if ef1 < es1 and rising and narrowing and gap_now > 0:
        return CAT_ATC
    return CAT_NONE


def drop_incomplete_today_bar(df: pd.DataFrame) -> pd.DataFrame:
    """
    If the script happens to run mid-session and Yahoo has already appended
    a live, still-forming bar for today, drop it so we only ever score
    fully completed daily candles (no look-ahead / no repaint).
    """
    if df.empty:
        return df
    now_ist = datetime.now(IST)
    last_date = df.index[-1].date()
    if last_date == now_ist.date() and now_ist.time() < MARKET_CLOSE:
        return df.iloc[:-1]
    return df


def extract_close(df: pd.DataFrame) -> pd.Series:
    """
    Recent yfinance versions return a MultiIndex on columns (Price x Ticker),
    even for a single-symbol download - so df["Close"] can come back as a
    1-column DataFrame instead of a plain Series. Normalize to a Series
    regardless of yfinance version / column orientation.
    """
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close


def scan_symbol(symbol: str) -> Result | None:
    try:
        df = yf.download(symbol, period=LOOKBACK_PERIOD, interval="1d",
                          progress=False, auto_adjust=True)
    except Exception as exc:  # noqa: BLE001 - keep the screener running
        print(f"[warn] {symbol}: download failed ({exc})", file=sys.stderr)
        return None

    if df.empty or len(df) < EMA_SLOW + 3:
        print(f"[warn] {symbol}: not enough history, skipping", file=sys.stderr)
        return None

    df = drop_incomplete_today_bar(df)
    if len(df) < EMA_SLOW + 3:
        return None

    close = extract_close(df)
    ema_fast_series = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow_series = close.ewm(span=EMA_SLOW, adjust=False).mean()

    ef1, es1 = float(ema_fast_series.iloc[-1]), float(ema_slow_series.iloc[-1])
    ef2, es2 = float(ema_fast_series.iloc[-2]), float(ema_slow_series.iloc[-2])
    price = float(close.iloc[-1])

    category = classify(ef1, es1, ef2, es2)
    if category == CAT_NONE:
        return None

    diff_pct = (ef1 - es1) / es1 * 100 if es1 else 0.0
    cross_date = str(df.index[-1].date()) if category in (CAT_BUY, CAT_EXIT) else None

    return Result(symbol=symbol.replace(".NS", "").replace(".BO", ""),
                  price=price, ema_fast=ef1, ema_slow=es1,
                  diff_pct=diff_pct, category=category, cross_date=cross_date)


def run_screener() -> dict[str, list[Result]]:
    buckets: dict[str, list[Result]] = {CAT_BUY: [], CAT_ATC: [], CAT_HOLD: [], CAT_EXIT: []}
    for symbol in SYMBOLS:
        result = scan_symbol(symbol)
        if result is not None:
            buckets[result.category].append(result)

    buckets[CAT_BUY].sort(key=lambda r: r.cross_date or "", reverse=True)
    buckets[CAT_ATC].sort(key=lambda r: abs(r.diff_pct))
    buckets[CAT_HOLD].sort(key=lambda r: r.diff_pct, reverse=True)
    buckets[CAT_EXIT].sort(key=lambda r: r.cross_date or "", reverse=True)
    return buckets


# ---------------------------------------------------------------------------
# Formatting + Telegram delivery
# ---------------------------------------------------------------------------

def format_message(buckets: dict[str, list[Result]]) -> str:
    today = datetime.now(IST).strftime("%d %b %Y")
    lines = [f"*NSE EMA 20/50 Screener - {today}*"]

    section_titles = {
        CAT_BUY: "🟢 BUY (fresh crossover)",
        CAT_ATC: "🟡 ABOUT TO CROSS",
        CAT_HOLD: "🔵 HOLD / BULLISH",
        CAT_EXIT: "🔴 EXIT / SELL",
    }

    for cat, title in section_titles.items():
        rows = buckets[cat][:MAX_ROWS_PER_CATEGORY]
        lines.append(f"\n{title} ({len(buckets[cat])})")
        if not rows:
            lines.append("  none")
            continue
        for r in rows:
            lines.append(f"  {r.symbol}: ₹{r.price:.2f} | 20EMA {r.ema_fast:.2f} | "
                          f"50EMA {r.ema_slow:.2f} | gap {r.diff_pct:+.2f}%")

    return "\n".join(lines)


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[error] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - "
              "printing to console instead.\n")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram caps messages at 4096 chars - split if needed.
    chunks = [message[i:i + 3800] for i in range(0, len(message), 3800)] or [""]
    for chunk in chunks:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
        }, timeout=15)
        if resp.status_code != 200:
            print(f"[error] Telegram send failed: {resp.status_code} {resp.text}",
                  file=sys.stderr)


def main() -> None:
    buckets = run_screener()
    message = format_message(buckets)
    send_telegram(message)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# One-time setup notes
# ---------------------------------------------------------------------------
# 1. Create a bot:
#      - Message @BotFather on Telegram -> /newbot -> follow prompts
#      - Copy the token it gives you (looks like 123456789:AAExxxxxxxxxxxx)
#
# 2. Get your chat_id:
#      - Send any message to your new bot first
#      - Visit: https://api.telegram.org/bot<TOKEN>/getUpdates
#      - Find "chat":{"id": <NUMBER>, ...} in the JSON response
#
# 3. Set both as environment variables (e.g. in your crontab or a .env
#    loaded by your shell profile):
#      export TELEGRAM_BOT_TOKEN="123456789:AAExxxxxxxxxxxx"
#      export TELEGRAM_CHAT_ID="987654321"
#
# 4. Install dependencies:
#      pip install yfinance pandas requests
#
# 5. Add a cron job (edit with `crontab -e`) to run at 17:45 IST on
#    weekdays (adjust the hour/timezone for your server):
#      45 17 * * 1-5 /usr/bin/python3 /path/to/nse_ema_screener.py >> /path/to/screener.log 2>&1
#
#    If your server's system timezone isn't IST, prefix with TZ, e.g.:
#      45 17 * * 1-5 TZ=Asia/Kolkata /usr/bin/python3 /path/to/nse_ema_screener.py
