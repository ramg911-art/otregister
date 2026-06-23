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


def ensure_ot_register_patient_contact_columns(engine):
    """
    Add patient_phone / patient_emr_id to ot_register if missing (SQLite + PostgreSQL).
    Safe to call on every app startup.
    """
    from sqlalchemy import text

    table = "ot_register"
    with engine.begin() as conn:
        if engine.url.drivername == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            col_names = {row[1] for row in rows}
            if "patient_phone" not in col_names:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN patient_phone VARCHAR(32)")
                )
            if "patient_emr_id" not in col_names:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN patient_emr_id VARCHAR(50)")
                )
            return

        def _has_col(column_name: str) -> bool:
            n = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
                    """
                ),
                {"t": table, "c": column_name},
            ).scalar()
            return int(n or 0) > 0

        if not _has_col("patient_phone"):
            conn.execute(
                text(f"ALTER TABLE public.{table} ADD COLUMN patient_phone VARCHAR(32)")
            )
        if not _has_col("patient_emr_id"):
            conn.execute(
                text(f"ALTER TABLE public.{table} ADD COLUMN patient_emr_id VARCHAR(50)")
            )


def migrate_legacy_user_roles(engine):
    """Rename legacy role values to canonical administrator / optometrist."""
    from sqlalchemy import text

    with engine.begin() as conn:
        try:
            conn.execute(
                text("UPDATE users SET role = 'administrator' WHERE role = 'admin'")
            )
        except Exception:
            pass
        try:
            conn.execute(
                text("UPDATE users SET role = 'optometrist' WHERE role = 'staff'")
            )
        except Exception:
            pass


def ensure_patient_feedback_medicine_column(engine):
    """Add medicine_administration to patient_feedback if missing."""
    from sqlalchemy import text

    table = "patient_feedback"
    with engine.begin() as conn:
        if engine.url.drivername == "sqlite":
            try:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            except Exception:
                return
            if not rows:
                return
            col_names = {row[1] for row in rows}
            if "medicine_administration" not in col_names:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN medicine_administration VARCHAR(16)"
                    )
                )
            return

        def _has_col(column_name: str) -> bool:
            n = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
                    """
                ),
                {"t": table, "c": column_name},
            ).scalar()
            return int(n or 0) > 0

        try:
            if not _has_col("medicine_administration"):
                conn.execute(
                    text(
                        f"ALTER TABLE public.{table} ADD COLUMN medicine_administration VARCHAR(16)"
                    )
                )
        except Exception:
            pass


def ensure_patient_feedback_updated_by_column(engine):
    """Add updated_by_user_id to patient_feedback if missing."""
    from sqlalchemy import text

    table = "patient_feedback"
    with engine.begin() as conn:
        if engine.url.drivername == "sqlite":
            try:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            except Exception:
                return
            if not rows:
                return
            col_names = {row[1] for row in rows}
            if "updated_by_user_id" not in col_names:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN updated_by_user_id INTEGER")
                )
            return

        def _has_col(column_name: str) -> bool:
            n = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
                    """
                ),
                {"t": table, "c": column_name},
            ).scalar()
            return int(n or 0) > 0

        try:
            if not _has_col("updated_by_user_id"):
                conn.execute(
                    text(
                        f"ALTER TABLE public.{table} ADD COLUMN updated_by_user_id INTEGER"
                    )
                )
        except Exception:
            pass


def ensure_iol_order_schema(engine):
    """IOL supplier, order tables, and iol_master.supplier_id (SQLite + PostgreSQL)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        is_sqlite = engine.url.drivername == "sqlite"

        if is_sqlite:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS iol_supplier (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        supplier_name VARCHAR(200) NOT NULL,
                        supplier_phone VARCHAR(32) NOT NULL,
                        contact_person_name VARCHAR(120) NOT NULL,
                        contact_person_phone VARCHAR(32) NOT NULL
                    )
                    """
                )
            )
            rows = conn.execute(text("PRAGMA table_info(iol_master)")).fetchall()
            col_names = {row[1] for row in rows}
            if "supplier_id" not in col_names:
                conn.execute(
                    text("ALTER TABLE iol_master ADD COLUMN supplier_id INTEGER")
                )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS iol_order (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ot_register_id INTEGER NOT NULL,
                        iol_id INTEGER NOT NULL,
                        iol_power VARCHAR(16) NOT NULL,
                        status VARCHAR(32) NOT NULL DEFAULT 'ordered',
                        ordered_at DATETIME NOT NULL,
                        ordered_by_user_id INTEGER NOT NULL,
                        order_no VARCHAR(16),
                        order_jpg_path VARCHAR(512),
                        received_at DATETIME,
                        received_by_user_id INTEGER,
                        mismatch_kind VARCHAR(16),
                        resolution_action VARCHAR(32),
                        resolution_notes TEXT,
                        superseded_by_order_id INTEGER,
                        FOREIGN KEY(ot_register_id) REFERENCES ot_register(id) ON DELETE CASCADE,
                        FOREIGN KEY(iol_id) REFERENCES iol_master(id),
                        FOREIGN KEY(ordered_by_user_id) REFERENCES users(id),
                        FOREIGN KEY(received_by_user_id) REFERENCES users(id),
                        FOREIGN KEY(superseded_by_order_id) REFERENCES iol_order(id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS iol_order_status_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        iol_order_id INTEGER NOT NULL,
                        action VARCHAR(64) NOT NULL,
                        from_status VARCHAR(32),
                        to_status VARCHAR(32) NOT NULL,
                        user_id INTEGER NOT NULL,
                        notes TEXT,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(iol_order_id) REFERENCES iol_order(id) ON DELETE CASCADE,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                    """
                )
            )
            rows = conn.execute(text("PRAGMA table_info(iol_order)")).fetchall()
            iol_order_cols = {row[1] for row in rows} if rows else set()
            if "order_no" not in iol_order_cols:
                conn.execute(text("ALTER TABLE iol_order ADD COLUMN order_no VARCHAR(16)"))
            return

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS public.iol_supplier (
                    id SERIAL PRIMARY KEY,
                    supplier_name VARCHAR(200) NOT NULL,
                    supplier_phone VARCHAR(32) NOT NULL,
                    contact_person_name VARCHAR(120) NOT NULL,
                    contact_person_phone VARCHAR(32) NOT NULL
                )
                """
            )
        )

        def _has_col(table: str, column: str) -> bool:
            n = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
                    """
                ),
                {"t": table, "c": column},
            ).scalar()
            return int(n or 0) > 0

        if not _has_col("iol_master", "supplier_id"):
            conn.execute(
                text(
                    "ALTER TABLE public.iol_master ADD COLUMN supplier_id INTEGER "
                    "REFERENCES public.iol_supplier(id)"
                )
            )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS public.iol_order (
                    id SERIAL PRIMARY KEY,
                    ot_register_id INTEGER NOT NULL REFERENCES public.ot_register(id) ON DELETE CASCADE,
                    iol_id INTEGER NOT NULL REFERENCES public.iol_master(id),
                    iol_power VARCHAR(16) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'ordered',
                    ordered_at TIMESTAMP NOT NULL,
                    ordered_by_user_id INTEGER NOT NULL REFERENCES public.users(id),
                    order_no VARCHAR(16),
                    order_jpg_path VARCHAR(512),
                    received_at TIMESTAMP,
                    received_by_user_id INTEGER REFERENCES public.users(id),
                    mismatch_kind VARCHAR(16),
                    resolution_action VARCHAR(32),
                    resolution_notes TEXT,
                    superseded_by_order_id INTEGER REFERENCES public.iol_order(id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS public.iol_order_status_log (
                    id SERIAL PRIMARY KEY,
                    iol_order_id INTEGER NOT NULL REFERENCES public.iol_order(id) ON DELETE CASCADE,
                    action VARCHAR(64) NOT NULL,
                    from_status VARCHAR(32),
                    to_status VARCHAR(32) NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES public.users(id),
                    notes TEXT,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        if not _has_col("iol_order", "order_no"):
            conn.execute(
                text("ALTER TABLE public.iol_order ADD COLUMN order_no VARCHAR(16)")
            )