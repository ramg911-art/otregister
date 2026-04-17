-- Fix iol_master.id sequence when pg_get_serial_sequence returns NULL or inserts duplicate id.
-- Run as superuser or table owner if ALTER fails.
--
-- psql -U otuser -d otregister -f scripts/fix_iol_master_sequence.sql

BEGIN;

-- Drop old ownership links so OWNED BY can attach our sequence (safe if none exist)
DO $bd$
DECLARE r RECORD;
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
      AND t.relname = 'iol_master'
      AND a.attname = 'id'
  LOOP
    EXECUTE format('ALTER SEQUENCE %s OWNED BY NONE', r.seq_reg);
  END LOOP;
END
$bd$;

CREATE SEQUENCE IF NOT EXISTS public.iol_master_id_seq;

ALTER TABLE public.iol_master
  ALTER COLUMN id SET DEFAULT nextval('public.iol_master_id_seq'::regclass);

ALTER SEQUENCE public.iol_master_id_seq OWNED BY public.iol_master.id;

SELECT setval(
  'public.iol_master_id_seq'::regclass,
  (SELECT COALESCE(MAX(id), 0) FROM public.iol_master)
);

COMMIT;

-- Must return: public.iol_master_id_seq
SELECT pg_get_serial_sequence('public.iol_master', 'id');
SELECT pg_get_serial_sequence('iol_master', 'id');
