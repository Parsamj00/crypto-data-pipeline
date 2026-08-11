"""
Checks which names in your own asset list actually exist as tracked
protocols in DefiLlama, useful for catching naming mismatches before
running the TVL/APY fetchers (a name that's not in DefiLlama's list
will silently return zero rows there otherwise).
"""

import pandas as pd
import requests


def check_coverage(input_path: str, output_path: str):
    df = pd.read_excel(input_path)
    if "name" not in df.columns:
        raise ValueError(f"Input file must contain a 'name' column. Found: {list(df.columns)}")

    df["normalized_name"] = df["name"].str.lower().str.strip()

    response = requests.get("https://api.llama.fi/protocols", timeout=30)
    response.raise_for_status()
    protocol_names = {p["name"].lower().strip() for p in response.json()}

    df["in_defillama"] = df["normalized_name"].apply(lambda n: n in protocol_names)

    df[["name", "in_defillama"]].to_excel(output_path, index=False)
    covered = df["in_defillama"].sum()
    print(f"{covered}/{len(df)} names matched a DefiLlama protocol. Wrote {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample_data/assets.xlsx")
    parser.add_argument("--output", default="sample_data/coverage_report.xlsx")
    args = parser.parse_args()
    check_coverage(args.input, args.output)
