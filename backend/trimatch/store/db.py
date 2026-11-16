"""Connection to the review store and its setup.

The store is a database `trimatch_review` in the Postgres 16 container that already runs Odoo
(odoo/docker-compose.yml), owned by its own login role `trimatch`. `trimatch db init`
creates role and database with the container's local superuser, writes a generated
password to `.env` (never printed) and runs the migrations.

Settings (environment or .env):
- TRIMATCH_DB_URL       full SQLAlchemy URL; overrides everything below
- TRIMATCH_DB_PASSWORD  password of the `trimatch` role (written by `db init`)
- TRIMATCH_PG_PORT      host port of the Postgres container (default 5442)
- TRIMATCH_DB_ADMIN_URL superuser URL used by `db init` only (default: the compose superuser)
"""

from __future__ import annotations

import os
import secrets
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from trimatch.config import REPO_ROOT
from trimatch.odoo_adapter import load_dotenv

ROLE = "trimatch"
DEFAULT_ODOO_DB = "trimatch"  # Odoo's database (odoo_adapter.DEFAULT_DB): never ours
DEFAULT_PORT = 5442
MIGRATIONS = Path(__file__).parent / "migrations"
ENV_FILE = REPO_ROOT / ".env"


class StoreNotConfigured(RuntimeError):
    pass


def _port() -> int:
    return int(os.environ.get("TRIMATCH_PG_PORT", DEFAULT_PORT))


def database_url(database: str = "trimatch_review") -> URL:
    load_dotenv()
    if raw := os.environ.get("TRIMATCH_DB_URL"):
        url = make_url(raw)
        return url if database == "trimatch_review" else url.set(database=database)
    password = os.environ.get("TRIMATCH_DB_PASSWORD")
    if not password:
        raise StoreNotConfigured(
            "TRIMATCH_DB_PASSWORD is not set. Create the review store with: "
            "uv run --project backend trimatch db init"
        )
    return URL.create(
        "postgresql+psycopg",
        username=ROLE,
        password=password,
        host="127.0.0.1",  # not "localhost": see OdooClient (IPv6 delay on Windows)
        port=_port(),
        database=database,
    )


def admin_url() -> URL:
    load_dotenv()
    if raw := os.environ.get("TRIMATCH_DB_ADMIN_URL"):
        return make_url(raw)
    # The compose file's local-only superuser (odoo/docker-compose.yml, bound to 127.0.0.1).
    return URL.create(
        "postgresql+psycopg",
        username="odoo",
        password="odoo",
        host="127.0.0.1",
        port=_port(),
        database="postgres",
    )


@cache
def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def engine(url: URL | None = None) -> Engine:
    return _engine((url or database_url()).render_as_string(hide_password=False))


def session_factory(url: URL | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine(url), expire_on_commit=False)


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def upgrade(url: URL | None = None) -> None:
    """Apply all migrations (idempotent). Refuses Odoo's own database."""
    url = url or database_url()
    if url.database == os.environ.get("ODOO_DB", DEFAULT_ODOO_DB):
        raise StoreNotConfigured(f"refusing to migrate Odoo's database {url.database!r}")
    cfg = alembic_config()
    with engine(url).begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def _ensure_password() -> str:
    load_dotenv()
    if pw := os.environ.get("TRIMATCH_DB_PASSWORD"):
        return pw
    pw = secrets.token_urlsafe(24)
    existing = ENV_FILE.read_text(encoding="utf-8-sig") if ENV_FILE.is_file() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    with ENV_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{sep}# Review store role password, written by `trimatch db init`\n")
        f.write(f"TRIMATCH_DB_PASSWORD={pw}\n")
    os.environ["TRIMATCH_DB_PASSWORD"] = pw
    return pw


def init(databases: tuple[str, ...] = ("trimatch_review",)) -> list[str]:
    """Create the `trimatch` role and databases if missing, then migrate `trimatch`.

    Returns what was done, for the CLI. The role's password is (re)set from .env, so .env
    stays the single source of truth.
    """
    done: list[str] = []
    password = _ensure_password()
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            raw = conn.connection.driver_connection  # psycopg connection, for sql composition
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)
            ).scalar()
            verb = "ALTER" if exists else "CREATE"
            stmt = sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(ROLE), sql.Literal(password)
            )
            raw.execute(stmt)
            done.append(f"role {ROLE} {'updated' if exists else 'created'}")
            for db in databases:
                if conn.exec_driver_sql(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (db,)
                ).scalar():
                    done.append(f"database {db} exists")
                    continue
                raw.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(db), sql.Identifier(ROLE)
                    )
                )
                done.append(f"database {db} created")
    finally:
        admin.dispose()
    upgrade(database_url("trimatch_review"))
    done.append("migrations applied to trimatch_review")
    return done
