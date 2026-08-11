"""
Shared database connection layer.

This project was originally built against Microsoft SQL Server. That
database no longer exists (the machine it ran on was lost), so this
module adds a SQLite backend as the default so the pipeline can be run
and verified end to end without any external database setup.

Usage:
    from db_config import get_connection, get_backend

    conn = get_connection()
    cur = conn.cursor()
    ...

Backend selection (environment variable DB_BACKEND):
    "sqlite"     (default) - writes to a local file, no setup required
    "sqlserver"  - original production target, requires ODBC Driver 18
                   for SQL Server and a reachable instance

SQL Server connection details are read from environment variables
(see .env.example). Nothing is hardcoded here.
"""

import os
import sqlite3

DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
SQLITE_PATH = os.environ.get("SQLITE_PATH", "crypto_pipeline.db")


def get_backend() -> str:
    return DB_BACKEND


def get_connection():
    """Return a DB-API connection for the configured backend.

    Both sqlite3 and pyodbc use '?' as the parameter placeholder, so
    query strings written for one work unchanged against the other,
    as long as the SQL itself avoids backend-specific syntax (see
    db_schema.py, which branches on backend for table creation only).
    """
    if DB_BACKEND == "sqlite":
        conn = sqlite3.connect(SQLITE_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    if DB_BACKEND == "sqlserver":
        import pyodbc  # imported lazily so sqlite-only usage has no dependency on it

        server = os.environ.get("SQLSERVER_HOST", ".")
        database = os.environ.get("SQLSERVER_DATABASE", "CryptoPipelineDB")
        driver = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server")

        connection_string = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=Yes;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )
        return pyodbc.connect(connection_string)

    raise ValueError(f"Unknown DB_BACKEND '{DB_BACKEND}'. Use 'sqlite' or 'sqlserver'.")
