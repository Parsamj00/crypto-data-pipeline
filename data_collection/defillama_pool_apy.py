"""
Fetches historical APY and TVL for specific yield-farming pools from
DefiLlama's yields endpoint, and upserts into apy_tvl_pool.

Input: Excel file, column A = your own label for the asset, columns
B onward = one or more DefiLlama pool IDs to fetch for that asset.
"""

import os
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402

API_BASE = "https://yields.llama.fi/chart/"
YEARS_OF_HISTORY = 8
MAX_RETRIES = 8
INITIAL_BACKOFF_SEC = 2.0
MAX_BACKOFF_SEC = 60.0
POLITE_DELAY_SEC = 1.5
HEADERS = {"User-Agent": "crypto-data-pipeline/1.0", "Accept": "application/json"}


def years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year - years)


def read_unique_pools(input_path: str) -> tuple[list[str], dict[str, str]]:
    df = pd.read_excel(input_path, header=0)
    if df.shape[1] < 2:
        raise ValueError("Input file must have at least 2 columns (A: label, B+: pool IDs)")

    name_col = df.columns[0]
    seen, ordered_ids, id_to_name = set(), [], {}

    for _, row in df.iterrows():
        name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
        if not name:
            continue
        for col in df.columns[1:]:
            value = row[col]
            if pd.isna(value):
                continue
            pool_id = str(value).strip()
            if not pool_id or pool_id.lower() == "not available" or pool_id in seen:
                continue
            seen.add(pool_id)
            ordered_ids.append(pool_id)
            id_to_name[pool_id] = name

    return ordered_ids, id_to_name


def fetch_chart_points(session: requests.Session, pool_id: str) -> list[dict]:
    url = API_BASE + quote_plus(pool_id)
    backoff = INITIAL_BACKOFF_SEC

    for attempt in range(1, MAX_RETRIES + 1):
        response = session.get(url, headers=HEADERS, timeout=60)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return payload.get("data") or payload.get("chart") or []
            return []
        if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            wait = min(backoff, MAX_BACKOFF_SEC) + random.uniform(0, 0.75)
            time.sleep(wait)
            backoff *= 2
            continue
        response.raise_for_status()
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries (pool {pool_id})")


def parse_timestamp(ts_val) -> datetime | None:
    if ts_val is None:
        return None
    try:
        if isinstance(ts_val, str):
            dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        ts = int(ts_val)
        if ts > 10**11:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def point_to_row(name: str, pool_id: str, point: dict) -> tuple | None:
    parsed = parse_timestamp(point.get("timestamp") or point.get("time"))
    if parsed is None:
        return None

    apy = point.get("apy")
    if apy is None:
        base, reward = point.get("apyBase"), point.get("apyReward")
        try:
            apy = (float(base) if base is not None else 0.0) + (float(reward) if reward is not None else 0.0)
        except (TypeError, ValueError):
            apy = None
    else:
        try:
            apy = float(apy)
        except (TypeError, ValueError):
            apy = None

    tvl = point.get("tvlUsd", point.get("tvl"))
    try:
        tvl = float(tvl) if tvl is not None else None
    except (TypeError, ValueError):
        tvl = None

    return name[:255], pool_id[:400], parsed.date(), apy, tvl


def main(input_path: str):
    cutoff = years_ago(date.today(), YEARS_OF_HISTORY)
    pool_ids, id_to_name = read_unique_pools(input_path)
    print(f"Processing {len(pool_ids)} unique pool IDs...")

    conn = get_connection()
    cursor = conn.cursor()
    session = requests.Session()
    total_rows = 0

    for i, pool_id in enumerate(pool_ids, 1):
        name = id_to_name.get(pool_id, "")
        print(f"[{i}/{len(pool_ids)}] {pool_id}")

        try:
            points = fetch_chart_points(session, pool_id)
        except requests.RequestException as e:
            print(f"  error: {e}, skipping")
            time.sleep(POLITE_DELAY_SEC)
            continue

        rows = [point_to_row(name, pool_id, p) for p in points]
        rows = [r for r in rows if r and r[2] >= cutoff]

        for row in rows:
            cursor.execute(
                "INSERT INTO apy_tvl_pool (name, pool_id, pool_date, apy, tvl_usd) VALUES (?, ?, ?, ?, ?)",
                row,
            )
        conn.commit()
        print(f"  inserted {len(rows)} rows (of {len(points)} total points)")
        total_rows += len(rows)
        time.sleep(POLITE_DELAY_SEC + random.uniform(0.5, 1.0))

    cursor.close()
    conn.close()
    print(f"Done. Inserted ~{total_rows} rows.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/pool_ids.xlsx")
    args = parser.parse_args()
    main(args.input)
