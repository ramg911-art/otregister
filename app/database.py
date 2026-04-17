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
    fq_seq = "public." + seq_name
    max_sub = "(SELECT COALESCE(MAX(" + id_column + "), 0) FROM public." + table_name + ")"

    def _do(conn):
        conn.execute(
            text("SELECT setval('" + fq_seq + "'::regclass, " + max_sub + ")"),
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
    fq_tbl = "public." + table_name
    fq_fb = "public." + seq_fallback
    max_sub = f"(SELECT COALESCE(MAX({id_column}), 0) FROM {fq_tbl})"

    def _do(conn):
        # Schema-qualified table name — required for pg_get_serial_sequence after our fixes
        conn.execute(
            text(
                f"""
                SELECT setval(
                    COALESCE(pg_get_serial_sequence(:tbl, :col)::regclass, :fb::regclass),
                    {max_sub}
                )
                """
            ),
            {"tbl": fq_tbl, "col": id_column, "fb": fq_fb},
        )
        try:
            conn.execute(
                text(f"SELECT setval(:fb::regclass, {max_sub})"),
                {"fb": fq_fb},
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

    Uses schema-qualified public.* names so pg_get_serial_sequence('public.tab','id') works.
    """
    if db.get_bind().url.drivername == "sqlite":
        return
    from sqlalchemy import text
    allowed = ("users", "ot_register", "iol_master", "intravitreal_drug_master")
    if table_name not in allowed:
        return
    seq_name = table_name + "_" + id_column + "_seq"
    sch = "public"
    fq_table = sch + "." + table_name
    fq_seq = sch + "." + seq_name
    fq_col = fq_table + "." + id_column

    def _do(conn):
        # Detach any old sequence still "owning" this column (pgloader leaves odd states)
        try:
            conn.execute(
                text(
                    """
                    DO $bd$
                    DECLARE
                      r RECORD;
                    BEGIN
                      FOR r IN
                        SELECT c.oid::regclass AS seq_reg
                        FROM pg_class c
                        JOIN pg_depend d ON d.objid = c.oid
                        JOIN pg_class t ON t.oid = d.refobjid
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                        JOIN pg_namespace n ON n.oid = t.relnamespace
                        WHERE c.relkind = 'S'
                          AND n.nspname = 'public'
                          AND t.relname = :tname
                          AND a.attname = :cname
                      LOOP
                        EXECUTE format('ALTER SEQUENCE %s OWNED BY NONE', r.seq_reg);
                      END LOOP;
                    END
                    $bd$
                    """
                ),
                {"tname": table_name, "cname": id_column},
            )
        except Exception:
            pass

        conn.execute(text("CREATE SEQUENCE IF NOT EXISTS " + fq_seq))
        conn.execute(
            text(
                "ALTER TABLE " + fq_table + " ALTER COLUMN " + id_column
                + " SET DEFAULT nextval('" + fq_seq + "'::regclass)"
            )
        )
        try:
            conn.execute(text("ALTER SEQUENCE " + fq_seq + " OWNED BY " + fq_col))
        except Exception:
            pass
        max_sub = "(SELECT COALESCE(MAX(" + id_column + "), 0) FROM " + fq_table + ")"
        conn.execute(text("SELECT setval('" + fq_seq + "'::regclass, " + max_sub + ")"))

    try:
        _pg_engine_run(db, _do)
    except Exception:
        pass