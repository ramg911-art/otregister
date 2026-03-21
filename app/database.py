from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Load .env from project root so DATABASE_URL and TELEGRAM_* are available
from dotenv import load_dotenv
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_base_dir, ".env"))

# --------------------------------------------------
# Database URL
# --------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://otuser:password@localhost/otregister"
)

# --------------------------------------------------
# Engine configuration
# --------------------------------------------------

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

# --------------------------------------------------
# Session
# --------------------------------------------------

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# --------------------------------------------------
# Base class for models
# --------------------------------------------------

Base = declarative_base()

# --------------------------------------------------
# Dependency for FastAPI
# --------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _rollback_if_postgres(db):
    """PostgreSQL aborts the whole transaction on any error; must rollback before reuse."""
    try:
        if db.get_bind().url.drivername != "sqlite":
            db.rollback()
    except Exception:
        pass


def _pg_engine_run(db, fn):
    """
    Run fn(connection) inside its own committed transaction on the engine.
    Does NOT use the ORM session — avoids InFailedSqlTransaction poisoning the session
    when setval/DDL fails or after errors.
    """
    bind = db.get_bind()
    if bind.url.drivername == "sqlite":
        return
    with bind.begin() as conn:
        fn(conn)


def fix_postgres_sequence(db, table_name: str, id_column: str = "id"):
    """Fix PostgreSQL sequence for table after migration (SQLite→PG). Safe to call for SQLite (no-op)."""
    if db.get_bind().url.drivername == "sqlite":
        return
    from sqlalchemy import text
    allowed = ("users", "ot_register", "iol_master", "intravitreal_drug_master")
    if table_name not in allowed:
        return
    seq_name = table_name + "_" + id_column + "_seq"
    # setval(seq, v): next nextval() returns v+1 — use MAX(id), not MAX(id)+1
    max_sub = "(SELECT COALESCE(MAX(" + id_column + "), 0) FROM " + table_name + ")"

    def _do(conn):
        conn.execute(
            text("SELECT setval(:seq::regclass, " + max_sub + ")"),
            {"seq": seq_name},
        )

    try:
        _pg_engine_run(db, _do)
    except Exception:
        pass


def reset_id_sequence(db, table_name: str, id_column: str = "id"):
    """
    Reset id sequence so the next generated id is MAX(id)+1.
    Syncs BOTH pg_get_serial_sequence(...) and the conventional {table}_id_seq — pgloader/migrations
    sometimes leave the column using a different sequence than our fallback.
    Runs on a separate engine transaction so the ORM session stays valid.
    """
    if db.get_bind().url.drivername == "sqlite":
        return
    from sqlalchemy import text
    allowed = ("users", "ot_register", "iol_master", "intravitreal_drug_master")
    if table_name not in allowed:
        return
    seq_fallback = f"{table_name}_{id_column}_seq"
    max_sub = f"(SELECT COALESCE(MAX({id_column}), 0) FROM {table_name})"

    def _do(conn):
        # Primary: sequence PostgreSQL links to this column, else conventional name
        conn.execute(
            text(
                f"""
                SELECT setval(
                    COALESCE(pg_get_serial_sequence(:tbl, :col)::regclass, :fb::regclass),
                    {max_sub}
                )
                """
            ),
            {"tbl": table_name, "col": id_column, "fb": seq_fallback},
        )
        # Secondary: always bump conventional name too (may differ from linked seq after migration)
        try:
            conn.execute(
                text(f"SELECT setval(:fb::regclass, {max_sub})"),
                {"fb": seq_fallback},
            )
        except Exception:
            pass

    try:
        _pg_engine_run(db, _do)
    except Exception:
        pass


def reset_ot_register_sequence(db):
    """Reset ot_register.id sequence (see reset_id_sequence)."""
    reset_id_sequence(db, "ot_register")


def ensure_postgres_id_default(db, table_name: str, id_column: str = "id"):
    """
    Ensure the id column has DEFAULT nextval(...) so INSERTs get an id.
    Fixes 'null value in column "id" violates not-null constraint' after pgloader migration.
    Uses a separate engine transaction so failed DDL cannot abort the ORM session.

    After SQLite/pgloader imports, pg_get_serial_sequence() is often NULL until we:
    SET DEFAULT + ALTER SEQUENCE ... OWNED BY — that links the sequence so resets apply correctly.
    """
    if db.get_bind().url.drivername == "sqlite":
        return
    from sqlalchemy import text
    allowed = ("users", "ot_register", "iol_master", "intravitreal_drug_master")
    if table_name not in allowed:
        return
    seq_name = table_name + "_" + id_column + "_seq"
    # qualified ref for OWNED BY / regclass (public schema)
    tbl_col = table_name + "." + id_column

    def _do(conn):
        conn.execute(text("CREATE SEQUENCE IF NOT EXISTS " + seq_name))
        conn.execute(
            text(
                "ALTER TABLE " + table_name + " ALTER COLUMN " + id_column
                + " SET DEFAULT nextval('" + seq_name + "'::regclass)"
            )
        )
        # Link sequence ↔ column so pg_get_serial_sequence() is non-NULL (fixes pgloader imports)
        try:
            conn.execute(text("ALTER SEQUENCE " + seq_name + " OWNED BY " + tbl_col))
        except Exception:
            pass
        max_sub = "(SELECT COALESCE(MAX(" + id_column + "), 0) FROM " + table_name + ")"
        conn.execute(
            text("SELECT setval(:seq::regclass, " + max_sub + ")"),
            {"seq": seq_name},
        )

    try:
        _pg_engine_run(db, _do)
    except Exception:
        pass