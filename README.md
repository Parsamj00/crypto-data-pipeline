# Crypto Data Pipeline

A data pipeline that pulls price and TVL (Total Value Locked) history for crypto assets and DeFi protocols from public APIs, cleans and matches asset names across sources, and loads everything into a relational database.

## Why I built this

This is the data gathering side of a project I worked on that never turned into a published paper. The underlying question was about crypto hacks and exploits: when a protocol gets hit, how much does it actually move the asset's price and TVL (Total Value Locked), and could that movement work as a way to measure how severe an incident really was, beyond just the headline dollar amount stolen. This repo covers that first half, pulling price and TVL history for the relevant assets and protocols from public APIs, cleaning it, and matching it to the right names across sources, the raw material any before/after comparison around an incident would need. The incident data itself and the actual severity analysis aren't part of this repo.

It's adjacent to my Student Research Assistant work at Goethe University, where I build similar Python data pipelines for econometric research on digital assets, but it's a separate project of my own, not part of that role, and no research data or findings from it are included here.

## What it does

- **Fetches price history** from CoinGecko (paid API) and DefiLlama (free alternative)
- **Fetches TVL history** at both the chain level and individual protocol level from DefiLlama
- **Fetches pool-level APY/TVL** for yield-farming pools from DefiLlama's yields API
- **Matches your own asset names to each source's internal IDs**, handling naming mismatches ("Cream" vs "cream-finance") with exact matching, suffix stripping, and fuzzy matching as a fallback
- **Checks data coverage**, which of your assets are actually tracked by DefiLlama, and how much price/TVL history you have for each

## Why this matters for data quality

Every source names things differently, and coin/protocol lists change constantly. A meaningful part of this project is the matching logic that reconciles your own naming with each API's naming, since a silent mismatch here means silently missing data, not an error you'd notice.

## Architecture

```
crypto-data-pipeline/
├── db_config.py              # database connection (SQLite or SQL Server)
├── db_schema.py              # table definitions
├── data_collection/          # one script per data source
└── data_processing/          # coverage checks and reporting
```

Originally built against Microsoft SQL Server. That database no longer exists (the machine it ran on was lost), so this repo defaults to SQLite so it can be cloned and run immediately with no setup. Set `DB_BACKEND=sqlserver` in `.env` to target SQL Server instead, the schema and upsert logic work against both.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your CoinGecko API key if using that source
python db_schema.py    # creates the local SQLite database
```

## Usage

```bash
# match your asset names to CoinGecko IDs first
python data_collection/coingecko_id_matching.py --input your_assets.xlsx

# fetch price history (pick one or both sources)
python data_collection/coingecko_price_history.py --input your_assets_matched.xlsx
python data_collection/defillama_coin_prices.py --input your_assets.xlsx

# fetch TVL history
python data_collection/defillama_chain_tvl.py --input your_chains.xlsx
python data_collection/defillama_protocol_tvl.py --input your_protocols.xlsx

# check coverage and generate a summary report
python data_processing/coverage_check.py --input your_assets.xlsx
python data_processing/reporting_summary.py
```

## Testing

`tests/test_pipeline.py` runs the pipeline logic end to end against a local SQLite database, with API responses mocked using payloads shaped like the real APIs (parsing, name matching, upserts, and reporting are all exercised against real code paths, only the network call itself is stubbed). Run with:

```bash
python tests/test_pipeline.py
```

## What's AI-assisted vs. my own work

The original data collection scripts, the API integration approach, the SQL schema, and the name-matching logic (suffix stripping, override lists, fuzzy fallback) are my own design from building this pipeline over time. Claude assisted with the cleanup pass for this public version: consolidating near-duplicate scripts, adding the SQLite backend, writing the automated tests, and drafting this README. Every change made during cleanup was reviewed and approved by me before publishing.

## Stack

Python, pandas, requests, SQLite / SQL Server (pyodbc)
