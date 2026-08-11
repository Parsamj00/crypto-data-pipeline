"""
Summarizes data coverage across the price_history and tvl_history
tables: how many assets have price data, how many have TVL data, and
the date range covered for each.

Originally this compared two separate Excel exports; adapted here to
query the database directly, which is both simpler and stays correct
as new data is collected.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db_config import get_connection  # noqa: E402


def build_report() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = get_connection()

    price_df = pd.read_sql_query(
        "SELECT name, COUNT(*) AS price_rows, MIN(price_date) AS price_start, MAX(price_date) AS price_end "
        "FROM price_history GROUP BY name",
        conn,
    )
    tvl_df = pd.read_sql_query(
        "SELECT name, COUNT(*) AS tvl_rows, MIN(tvl_date) AS tvl_start, MAX(tvl_date) AS tvl_end "
        "FROM tvl_history GROUP BY name",
        conn,
    )
    conn.close()

    detail = pd.merge(price_df, tvl_df, on="name", how="outer").fillna({"price_rows": 0, "tvl_rows": 0})

    total_assets = len(detail)
    with_price = (detail["price_rows"] > 0).sum()
    with_tvl = (detail["tvl_rows"] > 0).sum()

    summary = pd.DataFrame({
        "metric": [
            "Total assets with any data",
            "Assets with price data",
            "Assets without price data",
            "Assets with TVL data",
            "Assets without TVL data",
        ],
        "value": [total_assets, with_price, total_assets - with_price, with_tvl, total_assets - with_tvl],
    })

    return summary, detail


def main(output_path: str):
    summary, detail = build_report()
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        detail.to_excel(writer, sheet_name="Details", index=False)
    print(f"Report written to {output_path}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="sample_data/coverage_summary.xlsx")
    args = parser.parse_args()
    main(args.output)
