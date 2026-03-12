# OT Register — PostgreSQL Migration Guide (Ubuntu)

This document describes how to migrate the OT Register application from SQLite to PostgreSQL on **Ubuntu Linux**, preserve all data, and run the application against PostgreSQL.

**Important:** This server may also run **Optical POS** or other applications. The steps below only create a **dedicated** database and user for OT Register. They do **not** modify, stop, or reconfigure any existing PostgreSQL databases or system services.

---

## Project analysis (reference)

- **Connection:** The app connects via `app/database.py`. When `DATABASE_URL` is not set, it uses SQLite at `otregister.db` (project root) or `data/ot.db`.
- **ORM:** SQLAlchemy (synchronous). Driver for PostgreSQL: `psycopg2-binary` (in `requirements.txt`).
- **Config:** Database URL is read from the environment (or `.env` via `python-dotenv`). No SQLite-specific code paths when `DATABASE_URL` is set to PostgreSQL.

---

## 1. Prerequisites

- Ubuntu server with Python 3 and the project deployed.
- PostgreSQL server (often already installed for Optical POS). We will only **add** a new database and user; existing databases are left untouched.

---

## 2. Install PostgreSQL (if not already installed)

If PostgreSQL is not installed (e.g. Optical POS uses a different stack), install it without disrupting other services:

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
# Optional: enable on boot (only if you want PostgreSQL to start automatically)
# sudo systemctl enable postgresql
```

If PostgreSQL is already running (e.g. for other applications), **do not** reinstall or restart it. Proceed to creating only the OT Register database and user.

---

## 3. Create the PostgreSQL database and user (OT Register only)

Create **only** the database and user for OT Register. This does **not** affect existing databases (e.g. Optical POS).

Connect as the PostgreSQL superuser and run:

```sql
CREATE USER otuser WITH PASSWORD 'password';
CREATE DATABASE otregister OWNER otuser;
GRANT ALL PRIVILEGES ON DATABASE otregister TO otuser;
\c otregister
GRANT ALL ON SCHEMA public TO otuser;
-- Required for sequences (SERIAL columns)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO otuser;
```

Or from the shell on Ubuntu:

```bash
sudo -u postgres psql -c "CREATE USER otuser WITH PASSWORD 'password';"
sudo -u postgres psql -c "CREATE DATABASE otregister OWNER otuser;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE otregister TO otuser;"
sudo -u postgres psql -d otregister -c "GRANT ALL ON SCHEMA public TO otuser;"
sudo -u postgres psql -d otregister -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO otuser;"
```

Change `password` to a strong password in production. Do **not** alter or drop any other users or databases.

---

## 4. Migrate data from SQLite to PostgreSQL

The SQLite database file is **`otregister.db`** (project root). The migration scripts look for `otregister.db` first, then `data/ot.db`.

### Option A: pgloader (recommended on Ubuntu)

On Ubuntu, install pgloader and run the migration. This only reads from `otregister.db` and writes to the `otregister` database; it does not touch other databases or the SQLite file.

```bash
# Install pgloader (Ubuntu)
sudo apt install pgloader

# From project root (ensure otregister.db is in the current directory or use full path)
pgloader sqlite:///otregister.db postgresql://otuser:password@localhost/otregister
```

Or use the helper script (prefers `otregister.db`, then `data/ot.db`):

```bash
./scripts/pgloader_migrate.sh
```

### Option B: Python migration script (no pgloader required)

From the project root:

```bash
# Default: SQLite from otregister.db or data/ot.db, PostgreSQL from DATABASE_URL or default
python3 scripts/migrate_sqlite_to_postgres.py

# Explicit paths (Ubuntu: otregister.db in project root)
python3 scripts/migrate_sqlite_to_postgres.py --sqlite-path otregister.db --pg-url "postgresql://otuser:password@localhost/otregister"

# If PostgreSQL already has tables and you want to replace them (destructive)
python3 scripts/migrate_sqlite_to_postgres.py --drop-tables
```

This script:

1. Creates all tables in PostgreSQL from the application’s SQLAlchemy models.
2. Copies data in FK-safe order: `users`, `iol_master`, `intravitreal_drug_master`, `ot_register`.
3. Resets sequences so new rows get correct IDs.
4. Does **not** modify or delete the SQLite database.

---

## 5. Verify the migration

Run the verification script from the project root:

```bash
python3 scripts/verify_migration.py
```

With explicit paths (e.g. `otregister.db` in project root):

```bash
python3 scripts/verify_migration.py --sqlite-path otregister.db --pg-url "postgresql://otuser:password@localhost/otregister"
```

The script compares row counts per table and runs a simple query on PostgreSQL. Confirm all tables exist, row counts match, and fix any mismatches before switching the app to PostgreSQL.

---

## 6. Run the application with PostgreSQL

1. Set the database URL (choose one):

   - **Environment variable (Ubuntu)**

     ```bash
     export DATABASE_URL=postgresql://otuser:password@localhost/otregister
     python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
     ```

   - **`.env` file (recommended)**

     Copy the example and set the URL:

     ```bash
     cp .env.example .env
     ```

     Edit `.env` and set:

     ```
     DATABASE_URL=postgresql://otuser:password@localhost/otregister
     ```

     Then start the app (the app loads `.env` via `python-dotenv`):

     ```bash
     python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
     ```

2. Open the app in the browser and confirm login, dashboard, and OT register behaviour.

The app uses the same code for SQLite and PostgreSQL; only `DATABASE_URL` changes. No SQLite dependency when `DATABASE_URL` points to PostgreSQL.

---

## 7. Backup (PostgreSQL)

After migration, back up **only** the `otregister` database regularly. This does not backup or affect other databases (e.g. Optical POS).

**Plain SQL (human-readable, good for version control or manual restore):**

```bash
pg_dump -U otuser -d otregister -f otregister_backup.sql
```

With a date in the filename:

```bash
pg_dump -U otuser -d otregister -f otregister_backup_$(date +%Y%m%d).sql
```

**Custom format (smaller, good for full restore):**

```bash
pg_dump -U otuser -d otregister -Fc -f otregister_backup_$(date +%Y%m%d).dump
```

**Restore from plain SQL:**

```bash
psql -U otuser -d otregister -f otregister_backup.sql
```

**Restore from custom format:**

```bash
pg_restore -U otuser -d otregister -c otregister_backup_YYYYMMDD.dump
```

---

## 8. Rollback to SQLite

If you need to revert to SQLite (e.g. migration issues or temporary rollback):

1. **Stop the OT Register application only.** Do not stop PostgreSQL or other services (e.g. Optical POS).
2. **Remove or unset `DATABASE_URL`:**
   - Delete or comment out the `DATABASE_URL` line in `.env`, or
   - Unset the variable: `unset DATABASE_URL`
3. **Restart the OT Register application.**

The app will use the default SQLite database (`data/ot.db` or `otregister.db` if configured). The original SQLite file is **never** deleted or overwritten by the migration scripts.

---

## 9. Safety and shared server (Optical POS)

- **OT Register only:** We create only the database `otregister` and user `otuser`. No existing PostgreSQL databases or users are modified.
- **No service disruption:** Do not restart PostgreSQL or change its configuration for this migration. Existing applications (e.g. Optical POS) keep using their own databases.
- **SQLite preserved:** The migration scripts **do not delete or alter** `otregister.db`. Keep it as a backup until you are satisfied with PostgreSQL.
- **Testing:** Prefer testing the migration on a copy of `otregister.db` or on a staging server before changing production.
- **Backups:** Use `pg_dump` only for the `otregister` database; other databases are unchanged.

---

## 10. Schema compatibility (SQLite → PostgreSQL)

The application uses SQLAlchemy; the same models work with both backends. Handled automatically:

- **AUTOINCREMENT** → PostgreSQL `SERIAL` / identity columns (via SQLAlchemy).
- **BOOLEAN** → PostgreSQL `boolean` (SQLite 0/1 converted where needed in the Python migration script).
- **DATETIME / DATE** → PostgreSQL `date` / `timestamp` (SQLAlchemy types).
- **Indexes, unique constraints, foreign keys** → Created from models when using the Python migration script; pgloader maps SQLite schema to PostgreSQL.

No application code changes are required for these.

**Fix sequences after migration:** If you used pgloader or imported data with explicit IDs, PostgreSQL sequences (e.g. `users_id_seq`) may not be updated. New inserts can then hit "duplicate key" on the **primary key** (not username), and new rows never appear. The app now auto-fixes the `users` sequence when this happens. To fix all table sequences once, run in `psql`:

```sql
SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT COALESCE(MAX(id), 0) + 1 FROM users));
SELECT setval(pg_get_serial_sequence('iol_master', 'id'), (SELECT COALESCE(MAX(id), 0) + 1 FROM iol_master));
SELECT setval(pg_get_serial_sequence('intravitreal_drug_master', 'id'), (SELECT COALESCE(MAX(id), 0) + 1 FROM intravitreal_drug_master));
SELECT setval(pg_get_serial_sequence('ot_register', 'id'), (SELECT COALESCE(MAX(id), 0) + 1 FROM ot_register));
```

---

## 11. Summary (Ubuntu)

| Step | Action |
|------|--------|
| 1 | Install PostgreSQL if needed; do not disrupt existing services or databases. |
| 2 | Create **only** user `otuser` and database `otregister`. |
| 3 | Run `pgloader sqlite:///otregister.db postgresql://otuser:password@localhost/otregister` or `python3 scripts/migrate_sqlite_to_postgres.py`. |
| 4 | Run `python3 scripts/verify_migration.py`. |
| 5 | Set `DATABASE_URL=postgresql://otuser:password@localhost/otregister` (e.g. in `.env`). |
| 6 | Start the app with `uvicorn app.main:app`. |
| 7 | Back up with `pg_dump -U otuser -d otregister -f otregister_backup.sql`. |
| 8 | To roll back, unset `DATABASE_URL` and restart the app; keep `otregister.db` intact. |
