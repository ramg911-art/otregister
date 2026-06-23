"""Verify IOL order schema on remote PostgreSQL."""
import paramiko
import sys

HOST = "192.168.10.216"
USER = "deploy"
PASSWORD = "cursor123"
APP_ROOT = "/home/ram/otregister"


def p(s):
    sys.stdout.buffer.write(s.encode("utf-8", errors="replace"))
    if not s.endswith("\n"):
        sys.stdout.buffer.write(b"\n")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )

    check_py = r"""
import os
os.chdir(%r)
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text, inspect
from app.database import engine, ensure_iol_order_schema

ensure_iol_order_schema(engine)

insp = inspect(engine)
tables = set(insp.get_table_names())
needed = ["iol_supplier", "iol_order", "iol_order_status_log"]
print("=== TABLES ===")
for t in needed:
    print(f"  {t}: {'OK' if t in tables else 'MISSING'}")

cols = {c["name"] for c in insp.get_columns("iol_master")} if "iol_master" in tables else set()
print("=== iol_master.supplier_id ===")
print("  supplier_id:", "OK" if "supplier_id" in cols else "MISSING")

with engine.connect() as conn:
    for t in needed:
        if t in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t} rows: {n}")
""" % APP_ROOT

    cmd = f"cd {APP_ROOT} && . venv/bin/activate && python -c {check_py!r}"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    p(out)
    if err.strip():
        p("STDERR:\n" + err)
    p(f"exit {code}")
    client.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
