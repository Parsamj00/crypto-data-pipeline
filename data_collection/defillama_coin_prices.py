"""
Fetches daily price history from DefiLlama's coins.llama.fi endpoint,
as a free/no-key alternative to coingecko_price_history.py. Useful
when an asset isn't covered well by CoinGecko or a paid key isn't
available.

Requests are chunked (default 365 days per request) since the API
times out on very long single-shot ranges.

Input: an Excel/CSV file with columns 'name' and 'token_id'.
"""

import calendar
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402

BASE_URL = "https://coins.llama.fi"
YEARS_OF_HISTORY = 10
CHUNK_DAYS = 365
RATE_LIMIT_DELAY_SEC = 2.0


def fetch_chunk(token_id: str, chunk_start_ts: int, chunk_span_days: int) -> list[tuple]:
    url = f"{BASE_URL}/chart/{token_id}?start={chunk_start_ts}&span={chunk_span_days}&period=1d"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"  Chunk request failed for {token_id}: {e}")
        return []

    if isinstance(data, dict) and "coins" in data:
        raw = data["coins"].get(token_id, {}).get("prices", [])
    elif isinstance(data, list):
        raw = data
    else:
        return []

    series = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp") or item.get("date")
        price = item.get("price") or item.get("value")
        if ts is None or price is None:
            continue
        series.append((datetime.fromtimestamp(ts, timezone.utc).date(), price))
    return series


def get_daily_prices(token_id: str, start_ts: int, span_days: int, chunk_days: int = CHUNK_DAYS) -> list[tuple]:
    all_series = {}
    seconds_per_day = 86400
    num_full_chunks = span_days // chunk_days
    remainder_days = span_days % chunk_days

    for i in range(num_full_chunks):
        chunk_start_ts = start_ts + i * chunk_days * seconds_per_day
        for date_, price in fetch_chunk(token_id, chunk_start_ts, chunk_days):
            all_series[date_] = price

    if remainder_days:
        chunk_start_ts = start_ts + num_full_chunks * chunk_days * seconds_per_day
        for date_, price in fetch_chunk(token_id, chunk_start_ts, remainder_days):
            all_series[date_] = price

    return sorted(all_series.items())


def main(input_path: str):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365 * YEARS_OF_HISTORY)
    from_ts = calendar.timegm(start_date.utctimetuple())
    span_days = (end_date.date() - start_date.date()).days + 1

    df = pd.read_excel(input_path)
    if not {"name", "token_id"}.issubset(df.columns):
        raise ValueError("Input file must contain 'name' and 'token_id' columns")
    df = df.drop_duplicates(subset="name").reset_index(drop=True)

    conn = get_connection()
    cursor = conn.cursor()
    missing_ids = []

    for _, row in df.iterrows():
        name = str(row["name"]).strip()
        token_id = str(row["token_id"]).strip()
        if not token_id or token_id.lower() in ("nan", "not available"):
            missing_ids.append(name)
            continue

        print(f"Fetching {name} ({token_id})...")
        daily = get_daily_prices(token_id, start_ts=from_ts, span_days=span_days)
        print(f"  {name}: {len(daily)} days of data")

        for price_date, price in daily:
            cursor.execute(
                "SELECT 1 FROM price_history WHERE name=? AND token_id=? AND price_date=?",
                (name, token_id, price_date),
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO price_history (name, token_id, price_date, price) VALUES (?, ?, ?, ?)",
                    (name, token_id, price_date, price),
                )

        conn.commit()
        time.sleep(RATE_LIMIT_DELAY_SEC)

    cursor.close()
    conn.close()

    if missing_ids:
        print("\nMissing token IDs (skipped):")
        for name in missing_ids:
            print(f"  - {name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/assets.xlsx")
    args = parser.parse_args()
    main(args.input)
