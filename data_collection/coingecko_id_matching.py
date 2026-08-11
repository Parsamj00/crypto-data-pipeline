"""
Matches your own asset names against CoinGecko's coin ID list, which
is a required step before fetching price history (CoinGecko's price
endpoints need the coin's internal ID, not its display name).

Matching strategy, applied in order:
  1. Exact match on lowercased name
  2. Fuzzy match (difflib, cutoff 0.70) as a fallback for naming
     differences ("Cream" vs "Cream Finance")

Originally three separate scripts at different stages of the same
idea (exact-only, exact+fuzzy, and a raw list export with no
matching); consolidated here since they were all solving the same
problem.

The /coins/list endpoint is public and does not require an API key.
"""

import os
from difflib import get_close_matches

import pandas as pd
import requests

COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
FUZZY_MATCH_CUTOFF = 0.70


def fetch_all_coins() -> dict[str, str]:
    """Return {lowercased coin name: coingecko id} for every listed coin."""
    response = requests.get(COINGECKO_LIST_URL, timeout=30)
    response.raise_for_status()
    coins = response.json()

    name_to_id = {}
    for coin in coins:
        name = coin.get("name", "").strip().lower()
        coin_id = coin.get("id", "").strip()
        if name and coin_id:
            name_to_id[name] = coin_id
    return name_to_id


def match_names(asset_names: list[str], name_to_id: dict[str, str]) -> list[str]:
    all_known_names = list(name_to_id.keys())
    matched_ids = []

    for original_name in asset_names:
        key = str(original_name).strip().lower()

        if key in name_to_id:
            matched_ids.append(name_to_id[key])
            continue

        fuzzy_matches = get_close_matches(key, all_known_names, n=1, cutoff=FUZZY_MATCH_CUTOFF)
        matched_ids.append(name_to_id[fuzzy_matches[0]] if fuzzy_matches else "Not available")

    return matched_ids


def main(input_path: str, output_path: str):
    df = pd.read_excel(input_path)
    if "name" not in df.columns:
        raise ValueError(f"Input file must contain a 'name' column. Found: {list(df.columns)}")

    print("Fetching coin list from CoinGecko...")
    name_to_id = fetch_all_coins()
    print(f"  Retrieved {len(name_to_id)} coins")

    df["matched_id"] = match_names(df["name"].tolist(), name_to_id)

    df.to_excel(output_path, index=False)
    unmatched = (df["matched_id"] == "Not available").sum()
    print(f"Wrote {output_path} ({unmatched} unmatched out of {len(df)})")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/assets.xlsx")
    parser.add_argument("--output", default="sample_data/assets_matched.xlsx")
    args = parser.parse_args()
    main(args.input, args.output)
