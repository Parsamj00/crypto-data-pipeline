"""
End-to-end test of the pipeline logic against SQLite, with external
API calls mocked using response payloads shaped like the real APIs.

Run with: python tests/test_pipeline.py
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data_collection"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data_processing"))

os.environ["DB_BACKEND"] = "sqlite"
test_db_fd, TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(test_db_fd)
os.environ["SQLITE_PATH"] = TEST_DB_PATH

import db_config  # noqa: E402
import db_schema  # noqa: E402

FAILURES = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def test_schema_creation():
    print("\n1. Schema creation")
    db_schema.create_tables()
    conn = db_config.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    check("price_history table exists", "price_history" in tables)
    check("tvl_history table exists", "tvl_history" in tables)
    check("apy_tvl_pool table exists", "apy_tvl_pool" in tables)


def test_coingecko_id_matching():
    print("\n2. coingecko_id_matching.py (exact + fuzzy matching)")
    import coingecko_id_matching as mod

    mock_name_to_id = {"bitcoin": "bitcoin", "ethereum": "ethereum", "bitcoin cash": "bitcoin-cash"}
    results = mod.match_names(["Bitcoin", "Bitcoin Csah", "Totally Unknown Coin XYZ"], mock_name_to_id)
    check("exact match works", results[0] == "bitcoin")
    check("fuzzy match works (typo 'Bitcoin Csah' -> 'bitcoin cash')", results[1] == "bitcoin-cash")
    check("unmatched falls back correctly", results[2] == "Not available")


def test_coingecko_price_history():
    print("\n3. coingecko_price_history.py (parsing + DB write)")
    import coingecko_price_history as mod

    fake_response = MagicMock()
    fake_response.ok = True
    fake_response.json.return_value = {
        "prices": [
            [1704067200000, 42000.5],  # 2024-01-01
            [1704153600000, 42500.0],  # 2024-01-02
        ]
    }
    with patch("requests.get", return_value=fake_response):
        prices = mod.get_daily_prices("bitcoin")
    check("parses 2 price points", len(prices) == 2)
    check("date parsed correctly", prices[0][0] == datetime(2024, 1, 1, tzinfo=timezone.utc).date())

    # write path: build a synthetic input file and run main() with the DB write, API mocked
    tmp_input = tempfile.mktemp(suffix=".xlsx")
    pd.DataFrame({"name": ["Bitcoin"], "token_id": ["bitcoin"]}).to_excel(tmp_input, index=False)
    with patch("requests.get", return_value=fake_response), patch("time.sleep"):
        mod.main(tmp_input)

    conn = db_config.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM price_history WHERE name='Bitcoin'").fetchone()[0]
    conn.close()
    check("2 rows written to price_history", count == 2)
    os.remove(tmp_input)


def test_defillama_chain_tvl():
    print("\n4. defillama_chain_tvl.py (parsing + upsert)")
    import defillama_chain_tvl as mod

    fake_chains = [
        {
            "name": "Ethereum",
            "tvl": [
                {"date": 1704067200, "tvl": 50_000_000_000},
                {"date": 1704153600, "tvl": 51_000_000_000},
            ],
        }
    ]
    tmp_input = tempfile.mktemp(suffix=".xlsx")
    pd.DataFrame({"chain": ["Ethereum"]}).to_excel(tmp_input, index=False)

    with patch.object(mod, "fetch_all_chain_tvl", return_value=fake_chains):
        mod.main(tmp_input)

    conn = db_config.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM tvl_history WHERE name='Ethereum'").fetchone()[0]
    conn.close()
    check("2 rows written to tvl_history", count == 2)

    # run again to confirm upsert doesn't duplicate
    with patch.object(mod, "fetch_all_chain_tvl", return_value=fake_chains):
        mod.main(tmp_input)
    conn = db_config.get_connection()
    count_after = conn.execute("SELECT COUNT(*) FROM tvl_history WHERE name='Ethereum'").fetchone()[0]
    conn.close()
    check("re-running does not duplicate rows (upsert works)", count_after == 2)
    os.remove(tmp_input)


def test_reporting_summary():
    print("\n5. reporting_summary.py (reads what was actually written)")
    import reporting_summary as mod

    summary, detail = mod.build_report()
    bitcoin_row = detail[detail["name"] == "Bitcoin"]
    check("summary reflects the Bitcoin price rows written earlier", not bitcoin_row.empty)
    if not bitcoin_row.empty:
        check("price_rows count matches", int(bitcoin_row.iloc[0]["price_rows"]) == 2)


def main():
    test_schema_creation()
    test_coingecko_id_matching()
    test_coingecko_price_history()
    test_defillama_chain_tvl()
    test_reporting_summary()

    print("\n" + "=" * 50)
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")

    os.remove(TEST_DB_PATH)


if __name__ == "__main__":
    main()
