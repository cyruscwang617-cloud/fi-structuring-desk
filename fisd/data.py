"""Market data: US Treasury par yield curve (treasury.gov), SOFR (NY Fed) and
the MOVE rates volatility index (Yahoo Finance, delayed).

Both sources are free and need no API key. If a download fails, the app falls
back to a small ILLUSTRATIVE sample file so the demo still runs -- and says so.
"""
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import requests

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
SOFR_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json"
MOVE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE?range=5d&interval=1d"
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_curve.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (fi-structuring-desk; educational project)"}


def parse_treasury_csv(text):
    """Turn the Treasury CSV into a table: one row per date, one column per
    tenor in years (1.0, 2.0, ...), yields as decimals (0.04 = 4%)."""
    raw = pd.read_csv(io.StringIO(text))
    raw["Date"] = pd.to_datetime(raw["Date"], format="%m/%d/%Y")
    out = pd.DataFrame(index=raw["Date"])
    for col in raw.columns:
        match = re.fullmatch(r"(\d+) Yr", col.strip())   # keep "1 Yr", "2 Yr", ...
        if match:
            out[float(match.group(1))] = pd.to_numeric(raw[col], errors="coerce").values / 100
    return out.sort_index().dropna(how="all")


def load_treasury_curve():
    """Return (history_table, source_label). Tries this year, then last year."""
    this_year = date.today().year
    for year in (this_year, this_year - 1):
        try:
            resp = requests.get(TREASURY_URL.format(year=year), headers=HEADERS, timeout=15)
            resp.raise_for_status()
            table = parse_treasury_csv(resp.text)
            if len(table) > 0:
                return table, "LIVE: US Treasury daily par yield curve"
        except Exception:
            continue
    table = parse_treasury_csv(SAMPLE_FILE.read_text())
    return table, "SAMPLE: illustrative numbers, not market data (live download failed)"


def load_sofr():
    """Return (rate_as_decimal, effective_date) or (None, None) if unavailable."""
    try:
        resp = requests.get(SOFR_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        latest = resp.json()["refRates"][0]
        return latest["percentRate"] / 100, latest["effectiveDate"]
    except Exception:
        return None, None


def parse_yahoo_chart(payload):
    """Pull the latest level out of Yahoo's chart JSON."""
    result = payload["chart"]["result"][0]
    price = result["meta"].get("regularMarketPrice")
    if price is None:                       # fall back to the last daily close
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        price = closes[-1]
    return float(price)


def load_move():
    """MOVE index = implied vol of Treasury options, in bp per year.
    Used as a live PROXY for swaption normal vol. Returns None if unavailable."""
    try:
        resp = requests.get(MOVE_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return parse_yahoo_chart(resp.json())
    except Exception:
        return None
