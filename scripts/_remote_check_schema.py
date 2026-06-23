import os
import sys
sys.path.insert(0, "/home/ram/otregister")
os.chdir("/home/ram/otregister")
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text, inspect
from app.database import engine, ensure_iol_order_schema

print("Running ensure_iol_order_schema...")
ensure_iol_order_schema(engine)
print("Done.")

insp = inspect(engine)
tables = set(insp.get_table_names())
needed = ["iol_supplier", "iol_order", "iol_order_status_log"]
print("\n=== TABLES ===")
for t in needed:
    print(f"  {t}: {'OK' if t in tables else 'MISSING'}")

if "iol_master" in tables:
    cols = {c["name"] for c in insp.get_columns("iol_master")}
    print("\n=== iol_master.supplier_id ===")
    print("  supplier_id:", "OK" if "supplier_id" in cols else "MISSING")

print("\n=== ROW COUNTS ===")
with engine.connect() as conn:
    for t in needed:
        if t in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t}: {n}")
