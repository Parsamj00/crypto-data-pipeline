"""
Fetches historical TVL (Total Value Locked) for entire blockchains
from DefiLlama's historicalChainTvl endpoint, and upserts into
tvl_history. Input is an Excel/CSV file whose first column holds
chain names to match against DefiLlama's chain list.
"""

import os
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402

API_URL = "https://api.llama.fi/v2/historicalChainTvl"
YEARS_OF_HISTORY = 8
MAX_RETRIES = 5
INITIAL_BACKOFF_SEC = 1.5
MAX_BACKOFF_SEC = 30.0
HEADERS = {"User-Agent": "crypto-data-pipeline/1.0", "Accept": "application/json"}


def years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29 on a non-leap year
        return d.replace(month=2, day=28, year=d.year - years)


def parse_timestamp(ts_val) -> datetime | None:
    """Accept ISO strings, epoch seconds, or epoch milliseconds."""
    if ts_val is None:
        return None
    try:
        if isinstance(ts_val, str):
            dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        ts = int(ts_val)
        if ts > 10**11:  # milliseconds -> seconds
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def fetch_all_chain_tvl(session: requests.Session) -> list[dict]:
    backoff = INITIAL_BACKOFF_SEC
    for attempt in range(1, MAX_RETRIES + 1):
        response = session.get(API_URL, headers=HEADERS, timeout=60)
        if response.status_code == 200:
            payload = response.json()
            return payload if isinstance(payload, list) else payload.get("data", [])
        if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            wait = min(backoff, MAX_BACKOFF_SEC) + random.uniform(0, 0.75)
            print(f"HTTP {response.status_code}, retry {attempt}/{MAX_RETRIES} in {wait:.1f}s")
            time.sleep(wait)
            backoff *= 2
            continue
        response.raise_for_status()
    raise RuntimeError(f"Failed to fetch {API_URL} after {MAX_RETRIES} attempts")


def read_chain_names(input_path: str) -> list[str]:
    df = pd.read_excel(input_path, header=0)
    col0 = df.columns[0]
    seen, names = set(), []
    for value in df[col0].dropna().astype(str):
        cleaned = value.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            names.append(cleaned)
    return names


def upsert_tvl(cursor, name: str, tvl_date: date, tvl: float | None):
    cursor.execute("SELECT 1 FROM tvl_history WHERE name=? AND tvl_date=?", (name, tvl_date))
    if cursor.fetchone():
        cursor.execute("UPDATE tvl_history SET tvl=? WHERE name=? AND tvl_date=?", (tvl, name, tvl_date))
    else:
        cursor.execute(
            "INSERT INTO tvl_history (name, tvl_date, tvl) VALUES (?, ?, ?)", (name, tvl_date, tvl)
        )


def main(input_path: str):
    cutoff = years_ago(date.today(), YEARS_OF_HISTORY)
    chain_names = read_chain_names(input_path)
    print(f"Loaded {len(chain_names)} chain names from {input_path}")

    session = build_session()
    chains = fetch_all_chain_tvl(session)
    print(f"Fetched {len(chains)} chains from DefiLlama")

    name_to_chain = {}
    for chain in chains:
        name = str(chain.get("name", "")).strip()
        if name and name.lower() not in name_to_chain:
            name_to_chain[name.lower()] = chain

    conn = get_connection()
    cursor = conn.cursor()
    total_rows = 0

    for name in chain_names:
        chain = name_to_chain.get(name.lower())
        if chain is None:
            print(f"  not found: {name}")
            continue

        series = chain.get("tvl") or []
        kept = 0
        for point in series:
            ts = point.get("date") or point.get("timestamp")
            parsed = parse_timestamp(ts)
            if parsed is None or parsed.date() < cutoff:
                continue
            tvl = point.get("tvl")
            try:
                tvl = float(tvl) if tvl is not None else None
            except (TypeError, ValueError):
                tvl = None
            upsert_tvl(cursor, name[:255], parsed.date(), tvl)
            kept += 1

        conn.commit()
        print(f"  {name}: {kept} rows (since {cutoff})")
        total_rows += kept

    cursor.close()
    conn.close()
    print(f"Done. Upserted ~{total_rows} rows.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/chain_names.xlsx")
    args = parser.parse_args()
    main(args.input)
