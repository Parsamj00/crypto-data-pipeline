"""
Fetches full daily price history from the CoinGecko Pro API for a list
of assets and writes it into the price_history table.

Input: an Excel/CSV file with columns 'name' and 'token_id' (CoinGecko
coin IDs). See coingecko_id_matching.py to generate this mapping.

Requires a CoinGecko Pro API key set as the COINGECKO_API_KEY
environment variable (see .env.example).
"""

import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402

API_KEY = os.environ.get("COINGECKO_API_KEY", "YOUR_API_KEY_HERE")
VS_CURRENCY = "usd"
RATE_LIMIT_DELAY_SEC = 1.2


def get_daily_prices(coin_id: str) -> list[tuple]:
    """Fetch (date, price) pairs for a coin's full available history."""
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    headers = {"x-cg-pro-api-key": API_KEY}
    params = {"vs_currency": VS_CURRENCY, "days": "max", "interval": "daily"}

    response = requests.get(url, headers=headers, params=params, timeout=30)
    if not response.ok:
        return []

    prices = response.json().get("prices", [])
    return [
        (datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc).date(), p[1])
        for p in prices
    ]


def load_asset_list(input_path: str) -> pd.DataFrame:
    df = pd.read_excel(input_path)
    required = {"name", "token_id"}
    if not required.issubset(df.columns):
        raise ValueError(f"Input file must contain columns {required}. Found: {list(df.columns)}")
    return df.drop_duplicates(subset="name").reset_index(drop=True)


def main(input_path: str):
    df = load_asset_list(input_path)
    conn = get_connection()
    cursor = conn.cursor()

    missing_ids = []

    for _, row in df.iterrows():
        name = row["name"]
        token_id = row.get("token_id")

        if pd.isna(token_id) or str(token_id).strip().lower() in ("", "not available", "nan"):
            missing_ids.append(name)
            continue

        print(f"Fetching {name} ({token_id})...")
        try:
            daily_prices = get_daily_prices(token_id)
        except requests.RequestException as e:
            print(f"  Failed to fetch data for {name}: {e}")
            continue

        for price_date, price in daily_prices:
            try:
                cursor.execute(
                    "INSERT INTO price_history (name, token_id, price_date, price) VALUES (?, ?, ?, ?)",
                    (name, token_id, price_date, price),
                )
            except Exception as e:
                print(f"  Insert failed for {name} on {price_date}: {e}")

        conn.commit()
        print(f"  {name}: {len(daily_prices)} days of data")
        time.sleep(RATE_LIMIT_DELAY_SEC)

    cursor.close()
    conn.close()

    if missing_ids:
        print("\nMissing token IDs (skipped):")
        for name in missing_ids:
            print(f"  - {name}")
    else:
        print("\nAll token IDs were available.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="sample_data/assets.xlsx",
        help="Path to Excel file with 'name' and 'token_id' columns",
    )
    args = parser.parse_args()
    main(args.input)
