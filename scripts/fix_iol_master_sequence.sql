-- Run once on PostgreSQL if IOL inserts fail with duplicate key on id, or if:
--   SELECT pg_get_serial_sequence('iol_master', 'id');
-- returns NULL (sequence not linked after pgloader/SQLite import).
--
-- psql: \i scripts/fix_iol_master_sequence.sql
-- or paste into pgAdmin.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS iol_master_id_seq;

ALTER TABLE iol_master
  ALTER COLUMN id SET DEFAULT nextval('iol_master_id_seq'::regclass);

ALTER SEQUENCE iol_master_id_seq OWNED BY iol_master.id;

SELECT setval(
  'iol_master_id_seq'::regclass,
  (SELECT COALESCE(MAX(id), 0) FROM iol_master)
);

COMMIT;

-- Verify:
-- SELECT pg_get_serial_sequence('iol_master', 'id');
-- should return: public.iol_master_id_seq
