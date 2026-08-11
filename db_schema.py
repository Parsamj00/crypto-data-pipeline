"""
Creates the two tables this pipeline writes to: price_history and
tvl_history. Originally two separate scripts (one per table, SQL
Server only); consolidated here with SQLite DDL added.

Run directly to set up a fresh database:
    python db_schema.py
"""

from db_config import get_connection, get_backend

SQLITE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        token_id TEXT,
        price_date DATE,
        price REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tvl_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        tvl_date DATE,
        tvl REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS apy_tvl_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        pool_id TEXT,
        pool_date DATE,
        apy REAL,
        tvl_usd REAL
    )
    """,
]

SQLSERVER_DDL = [
    """
    IF OBJECT_ID('price_history', 'U') IS NULL
    BEGIN
        CREATE TABLE price_history (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255),
            token_id NVARCHAR(255),
            price_date DATE,
            price FLOAT
        )
    END
    """,
    """
    IF OBJECT_ID('tvl_history', 'U') IS NULL
    BEGIN
        CREATE TABLE tvl_history (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255),
            tvl_date DATE,
            tvl FLOAT
        )
    END
    """,
    """
    IF OBJECT_ID('apy_tvl_pool', 'U') IS NULL
    BEGIN
        CREATE TABLE apy_tvl_pool (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255),
            pool_id NVARCHAR(400),
            pool_date DATE,
            apy FLOAT,
            tvl_usd FLOAT
        )
    END
    """,
]


def create_tables():
    conn = get_connection()
    cur = conn.cursor()
    ddl_statements = SQLITE_DDL if get_backend() == "sqlite" else SQLSERVER_DDL
    for statement in ddl_statements:
        cur.execute(statement)
    conn.commit()
    conn.close()
    print(f"Tables created successfully (backend: {get_backend()}).")


if __name__ == "__main__":
    create_tables()
