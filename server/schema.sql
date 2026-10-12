-- Fleet server, phase 1. Run as the database owner (see app/manage.py init). Safe to run again.
--
-- Separation between organisations is enforced HERE, not only in the application: every table with customer
-- data has org_id and row-level security, forced even for the table owner. The API connects as fleet_app,
-- which cannot bypass it, and sets app.org_id for each transaction. The only code that looks across
-- organisations is the three SECURITY DEFINER functions at the end, which turn a presented secret into an
-- organisation. Secrets (tokens, keys) are stored as SHA-256 hashes only.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_app') THEN
    CREATE ROLE fleet_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
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

-- ---------------------------------------------------------------- row-level security
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['admin_keys', 'enrolment_tokens', 'devices', 'snapshots', 'audit_log'] LOOP
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
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fleet_app;

-- ---------------------------------------------------------------- the three doors across organisations
-- Each takes the SHA-256 of a presented secret and answers with the organisation it belongs to, nothing else.
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
