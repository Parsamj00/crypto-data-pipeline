"""
Fetches historical TVL for individual DeFi protocols (not whole
chains, see defillama_chain_tvl.py for that) from DefiLlama, and
upserts into tvl_history.

Protocol names from your own asset list rarely match DefiLlama's
slugs exactly ("Cream" vs "cream-finance"), so this applies, in
order: known one-off overrides, common suffix stripping (" Finance",
" Protocol", etc.), exact match, then a fuzzy fallback.

This consolidates two earlier scripts that both solved this same
matching problem at different levels of completeness; this version
keeps the more complete matching logic.
"""

import difflib
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402

YEARS_OF_HISTORY = 10
RATE_LIMIT_PER_SEC = 5
SLEEP_SEC = 1 / RATE_LIMIT_PER_SEC
FUZZY_MATCH_CUTOFF = 0.70

SUFFIXES_TO_STRIP = [
    r"\s+finance$", r"\s+bridge$", r"\s+protocol$", r"\s+dao$",
    r"\s+exchange$", r"\s+network$", r"\s+wallet$", r"\s+farm$",
]

# One-off name overrides where automatic matching fails or picks the
# wrong result. Add entries here as new mismatches are found.
NAME_OVERRIDES = {
    "cream": "cream-finance",
    "euler": "euler",
    "vulcanforged": "vulcan-forged",
}


def strip_suffix(name: str) -> str:
    for suffix in SUFFIXES_TO_STRIP:
        name = re.sub(suffix, "", name, flags=re.IGNORECASE)
    return name.strip()


def normalize(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch == "-")


def resolve_slug(raw_name: str, protocol_map: dict, chain_map: dict, all_keys: list) -> tuple[str | None, str | None]:
    """Return (slug, source) where source is 'protocol' or 'chain', or (None, None)."""
    key = normalize(strip_suffix(raw_name))

    override_slug = NAME_OVERRIDES.get(key)
    if override_slug:
        source = "protocol" if override_slug in protocol_map.values() else "chain"
        return override_slug, source

    if key in protocol_map:
        return protocol_map[key], "protocol"
    if key in chain_map:
        return chain_map[key], "chain"

    fuzzy = difflib.get_close_matches(key, all_keys, n=1, cutoff=FUZZY_MATCH_CUTOFF)
    if fuzzy:
        best = fuzzy[0]
        return (protocol_map[best], "protocol") if best in protocol_map else (chain_map[best], "chain")

    return None, None


def upsert_tvl(cursor, name: str, tvl_date: date, tvl: float | None, existing: set):
    key = (name, tvl_date)
    if key in existing:
        return False
    cursor.execute(
        "INSERT INTO tvl_history (name, tvl_date, tvl) VALUES (?, ?, ?)", (name, tvl_date, tvl)
    )
    existing.add(key)
    return True


def main(input_path: str):
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=YEARS_OF_HISTORY * 365)).timestamp())

    assets = pd.read_excel(input_path, usecols=[0], names=["asset"])["asset"].astype(str).tolist()

    chains_resp = requests.get("https://api.llama.fi/chains", timeout=30)
    chains_resp.raise_for_status()
    chain_map = {}
    for chain in chains_resp.json():
        slug = chain.get("chain") or chain.get("name") or chain.get("slug")
        if slug:
            chain_map[normalize(slug)] = slug

    protocols_resp = requests.get("https://api.llama.fi/protocols", timeout=30)
    protocols_resp.raise_for_status()
    protocol_map = {normalize(p["name"]): p["slug"] for p in protocols_resp.json()}

    all_keys = list(chain_map.keys()) + list(protocol_map.keys())

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, tvl_date FROM tvl_history")
    existing = {(row[0], row[1]) for row in cursor.fetchall()}

    for raw_name in assets:
        slug, source = resolve_slug(raw_name, protocol_map, chain_map, all_keys)
        if not slug:
            print(f"  skipping '{raw_name}': no match after cleaning and fuzzy matching")
            continue

        url = (
            f"https://api.llama.fi/protocol/{slug}"
            if source == "protocol"
            else f"https://api.llama.fi/api/v2/historicalChainTvl/{slug}"
        )
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"  fetch error for '{raw_name}' ({slug}): {e}")
            continue

        entries = data.get("tvl", []) if isinstance(data, dict) else data if isinstance(data, list) else []

        inserted = 0
        for point in entries:
            ts = point.get("date")
            if not ts or ts < cutoff_ts:
                continue
            tvl_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            tvl = point.get("totalLiquidityUSD") or point.get("tvl")
            if upsert_tvl(cursor, slug, tvl_date, tvl, existing):
                inserted += 1

        conn.commit()
        print(f"  '{raw_name}' -> {slug}: {inserted} new rows")
        time.sleep(SLEEP_SEC)

    cursor.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/protocol_names.xlsx")
    args = parser.parse_args()
    main(args.input)
