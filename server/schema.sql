-- Fleet server, phases 1 and 2. Run as the database owner (see app/manage.py init). Safe to run again.
--
-- Separation between organisations is enforced HERE, not only in the application: every table with customer
-- data has org_id and row-level security, forced even for the table owner. The API connects as fleet_app,
-- which cannot bypass it, and sets app.org_id for each transaction. The only code that looks across
-- organisations is the SECURITY DEFINER functions at the end: three turn a presented secret into an
-- organisation, one tells the worker which devices are waiting to be judged (ids only). Secrets (tokens, keys) are stored as SHA-256 hashes only.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_app') THEN
    CREATE ROLE fleet_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
  -- the worker judges devices; it is under the same row-level security as the API, one organisation at a time
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_worker') THEN
    CREATE ROLE fleet_worker LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS organisations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  key_hash text NOT NULL UNIQUE,
  label text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used timestamptz
);

CREATE TABLE IF NOT EXISTS enrolment_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  label text NOT NULL DEFAULT '',
  max_uses int NOT NULL DEFAULT 1 CHECK (max_uses > 0),
  uses int NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  name text NOT NULL,
  key_hash text NOT NULL UNIQUE,
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz,
  agent_version text NOT NULL DEFAULT '',
  summary jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS devices_org ON devices (org_id, name);

-- What a device reported, per kind. A row is added only when the content changed (sha256), so this is also
-- the history.
CREATE TABLE IF NOT EXISTS snapshots (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  device_id uuid NOT NULL REFERENCES devices ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('device', 'apps', 'services', 'network', 'posture')),
  received_at timestamptz NOT NULL DEFAULT now(),
  sha256 text NOT NULL,
  payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_latest ON snapshots (device_id, kind, received_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_org ON audit_log (org_id, at DESC);

-- ---------------------------------------------------------------- phase 2: judging
-- facts_at moves whenever a check-in stored something new; the worker notes which facts, which reference
-- lists and which day its judgement was made for, and a device is judged again when any of the three moved.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS facts_at timestamptz;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS judged_facts_at timestamptz;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS judged_ref text;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS judged_day date;
UPDATE devices d SET facts_at = COALESCE(d.last_seen, d.enrolled_at)
 WHERE d.facts_at IS NULL AND EXISTS (SELECT 1 FROM snapshots s WHERE s.device_id = d.id);

-- The latest judgement of a device: known flaws, end of support, and the compliance checks.
CREATE TABLE IF NOT EXISTS judgements (
  device_id uuid PRIMARY KEY REFERENCES devices ON DELETE CASCADE,
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  judged_at timestamptz NOT NULL DEFAULT now(),
  ref text NOT NULL DEFAULT '',
  summary jsonb NOT NULL DEFAULT '{}',
  security jsonb NOT NULL DEFAULT '{}',
  compliance jsonb NOT NULL DEFAULT '{}'
);

-- One line per device per day with each check's result, so a past month can be shown.
CREATE TABLE IF NOT EXISTS compliance_history (
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  device_id uuid NOT NULL REFERENCES devices ON DELETE CASCADE,
  day date NOT NULL,
  line jsonb NOT NULL,
  PRIMARY KEY (device_id, day)
);
CREATE INDEX IF NOT EXISTS compliance_history_org ON compliance_history (org_id, day);

-- What the organisation states about things no program can measure. Always shown as declared.
CREATE TABLE IF NOT EXISTS declarations (
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  key text NOT NULL,
  answer text NOT NULL CHECK (answer IN ('yes', 'no', 'na')),
  note text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL DEFAULT '',
  PRIMARY KEY (org_id, key)
);

-- A failing check on one device that was accepted, with the reason. It keeps its failing mark.
CREATE TABLE IF NOT EXISTS exceptions (
  org_id uuid NOT NULL REFERENCES organisations ON DELETE CASCADE,
  device_id uuid NOT NULL REFERENCES devices ON DELETE CASCADE,
  check_id text NOT NULL,
  reason text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL DEFAULT '',
  PRIMARY KEY (device_id, check_id)
);

-- How fresh the public reference lists are (CVE, known exploited, end of life). No customer data: shared.
CREATE TABLE IF NOT EXISTS reference_status (
  k text PRIMARY KEY,
  v text NOT NULL,
  at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- row-level security
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['admin_keys', 'enrolment_tokens', 'devices', 'snapshots', 'audit_log',
                           'judgements', 'compliance_history', 'declarations', 'exceptions'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS own_org ON %I', t);
    -- no organisation set -> current_setting gives NULL -> no row matches: closed by default
    EXECUTE format($p$CREATE POLICY own_org ON %I USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
                       WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_org ON organisations;
CREATE POLICY own_org ON organisations USING (id = nullif(current_setting('app.org_id', true), '')::uuid);

GRANT USAGE ON SCHEMA public TO fleet_app;
GRANT SELECT ON organisations TO fleet_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON admin_keys, enrolment_tokens, devices, snapshots TO fleet_app;
GRANT SELECT, INSERT ON audit_log TO fleet_app;          -- the audit log is append-only for the application
GRANT SELECT, INSERT, UPDATE, DELETE ON declarations, exceptions TO fleet_app;
GRANT SELECT, UPDATE ON judgements TO fleet_app;          -- the API re-applies exceptions; only the worker judges
GRANT SELECT, INSERT, UPDATE ON compliance_history TO fleet_app;
GRANT SELECT ON reference_status TO fleet_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fleet_app;

GRANT USAGE ON SCHEMA public TO fleet_worker;
GRANT SELECT ON organisations, snapshots, exceptions, declarations TO fleet_worker;
GRANT SELECT, UPDATE ON devices TO fleet_worker;
GRANT SELECT, INSERT, UPDATE ON judgements, compliance_history TO fleet_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON reference_status TO fleet_worker;

-- ---------------------------------------------------------------- the doors across organisations
-- The first three each take the SHA-256 of a presented secret and answer with the organisation it belongs
-- to, nothing else.
-- They run as their owner, who must be able to bypass row-level security (a superuser, or a role with
-- BYPASSRLS): that is the only reason they can see past the policies.

CREATE OR REPLACE FUNCTION auth_device(p_hash text) RETURNS TABLE (device_id uuid, org_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT d.id, d.org_id FROM devices d WHERE d.key_hash = p_hash
$$;

CREATE OR REPLACE FUNCTION auth_admin(p_hash text) RETURNS TABLE (key_id uuid, org_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE admin_keys SET last_used = now() WHERE key_hash = p_hash RETURNING id, admin_keys.org_id
$$;

-- Uses up one use of a token if it is still valid; answers nothing otherwise. Atomic: two agents racing for
-- the last use cannot both win.
CREATE OR REPLACE FUNCTION redeem_token(p_hash text) RETURNS TABLE (token_id uuid, org_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE enrolment_tokens SET uses = uses + 1
   WHERE token_hash = p_hash AND uses < max_uses AND expires_at > now()
  RETURNING id, enrolment_tokens.org_id
$$;

REVOKE ALL ON FUNCTION auth_device(text), auth_admin(text), redeem_token(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_device(text), auth_admin(text), redeem_token(text) TO fleet_app;

-- The worker's door: which devices are waiting to be judged. Ids only; to read or write anything about a
-- device the worker then sets that organisation, like the API does.
CREATE OR REPLACE FUNCTION judge_queue(p_ref text, p_day date, p_limit int) RETURNS TABLE (device_id uuid, org_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT d.id, d.org_id FROM devices d
   WHERE d.facts_at IS NOT NULL
     AND (d.judged_facts_at IS DISTINCT FROM d.facts_at OR d.judged_ref IS DISTINCT FROM p_ref OR d.judged_day IS DISTINCT FROM p_day)
   ORDER BY d.judged_facts_at NULLS FIRST LIMIT p_limit
$$;
REVOKE ALL ON FUNCTION judge_queue(text, date, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION judge_queue(text, date, int) TO fleet_worker;
