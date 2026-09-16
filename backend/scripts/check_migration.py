"""Validate exported SQL in a disposable PostgreSQL schema, rolled back after inspection."""

from pathlib import Path
from sqlalchemy import text
from app.db import engine

sql = (Path(__file__).parents[1] / "migrations/001_initial.sql").read_text()
with engine.connect() as conn:
    tx = conn.begin()
    try:
        conn.exec_driver_sql("CREATE SCHEMA electra_migration_check")
        conn.exec_driver_sql("SET LOCAL search_path TO electra_migration_check")
        conn.exec_driver_sql(sql)
        tables = conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='electra_migration_check' AND table_type='BASE TABLE'"
            )
        )
        assert tables == 33, tables
        print(
            f"Exported migration creates {tables} tables successfully; verification transaction rolled back."
        )
    finally:
        tx.rollback()
