"""One-time migration: add the battery charge-limit columns to the `devices` table.

The app uses SQLAlchemy `create_all`, which creates missing TABLES but never adds columns to a
table that already exists. So a database created before the charge-limit feature (e.g. the
Render Postgres) is missing `charge_limit_enabled` / `charge_stop` / `charge_resume`. This
script adds whichever are missing, with the same defaults as the model. Idempotent and safe to
re-run; works on both Postgres and SQLite.

Run against the live DB:
    DATABASE_URL=postgres://...  python tools/migrate_charge_columns.py
Local SQLite needs no migration (a fresh phonedesk.db already has the columns), but running this
against it is harmless.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root on path

from sqlalchemy import inspect, text

from app.db import engine

# column name -> SQL type + default (matches app/models.py Device)
COLUMNS = {
    "charge_limit_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
    "charge_stop": "INTEGER NOT NULL DEFAULT 80",
    "charge_resume": "INTEGER NOT NULL DEFAULT 25",
}


def main() -> None:
    insp = inspect(engine)
    if "devices" not in insp.get_table_names():
        print("no `devices` table yet — nothing to migrate (create_all will build it fresh)")
        return
    existing = {c["name"] for c in insp.get_columns("devices")}
    # SQLite spells the boolean default differently; normalise per dialect.
    is_sqlite = engine.dialect.name == "sqlite"
    added = []
    with engine.begin() as conn:
        for name, ddl in COLUMNS.items():
            if name in existing:
                continue
            sql = ddl.replace("DEFAULT TRUE", "DEFAULT 1") if is_sqlite else ddl
            conn.execute(text(f"ALTER TABLE devices ADD COLUMN {name} {sql}"))
            added.append(name)
    print(f"migration done — added: {added or 'nothing (already up to date)'}")


if __name__ == "__main__":
    main()
