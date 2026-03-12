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


def fix_postgres_sequence(db, table_name: str, id_column: str = "id"):
    """Fix PostgreSQL sequence for table after migration (SQLite→PG). Safe to call for SQLite (no-op)."""
    if db.get_bind().url.drivername == "sqlite":
        return
    from sqlalchemy import text
    allowed = ("users", "ot_register", "iol_master", "intravitreal_drug_master")
    if table_name not in allowed:
        return
    try:
        sql = (
            "SELECT setval(pg_get_serial_sequence(:t, :c), "
            "(SELECT COALESCE(MAX(id), 0) + 1 FROM " + table_name + "))"
        )
        db.execute(text(sql), {"t": table_name, "c": id_column})
    except Exception:
        pass