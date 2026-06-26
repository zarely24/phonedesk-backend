"""Database engine + session. SQLite locally, Postgres on Render — same code."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

# Render gives DATABASE_URL as postgres://… ; SQLAlchemy + psycopg3 wants postgresql+psycopg://…
url = settings.DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://") and "+psycopg" not in url:
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


# Columns added after the first release. create_all() makes missing TABLES but never adds
# columns to a table that already exists, so an older Postgres (e.g. Render) is missing these.
# We add whichever are absent on every startup — idempotent, so it self-heals after a deploy
# without anyone running a manual migration in the shell.
_LATER_COLUMNS = {
    "devices": {
        "charge_limit_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
        "charge_stop": "INTEGER NOT NULL DEFAULT 80",
        "charge_resume": "INTEGER NOT NULL DEFAULT 25",
    },
}


def _ensure_columns() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    is_sqlite = engine.dialect.name == "sqlite"
    with engine.begin() as conn:
        for table, cols in _LATER_COLUMNS.items():
            if table not in tables:
                continue  # create_all will build it fresh, with these columns already on it
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name in existing:
                    continue
                sql = ddl.replace("DEFAULT TRUE", "DEFAULT 1") if is_sqlite else ddl
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql}"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_columns()


def get_db():
    """FastAPI dependency: one Session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
