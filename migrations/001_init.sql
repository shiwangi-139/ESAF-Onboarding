-- Production schema for the CSP onboarding platform. See docs/ARCHITECTURE.md and docs/SECURITY.md.
-- Personal data is stored encrypted by the app (…_enc columns); the database never sees plaintext.
-- Row-level security: every query runs with app.org_id / app.user_id / app.role set by the app.

CREATE SCHEMA IF NOT EXISTS app;
SET search_path = app;

-- ── Tenancy & access ──────────────────────────────────────────

CREATE TABLE organizations (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                  text NOT NULL,
  slug                  text NOT NULL UNIQUE,
  allowed_google_domain text,
  status                text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  settings              jsonb NOT NULL DEFAULT '{}',
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE programs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id),
  slug             text NOT NULL UNIQUE,
  name             text NOT NULL,
  bank_name        text NOT NULL,
  bc_name          text NOT NULL,
  registration_fee text NOT NULL DEFAULT '1,999',
  submission_email text,
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'closed')),
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE teams (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id     uuid NOT NULL REFERENCES organizations(id),
  name       text NOT NULL,
  region     text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organizations(id),
  team_id       uuid REFERENCES teams(id),
  email         text NOT NULL,
  google_sub    text UNIQUE,
  name          text NOT NULL,
  role          text NOT NULL CHECK (role IN ('org_admin', 'rm_manager', 'rm', 'compliance_viewer')),
  status        text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'active', 'disabled')),
  invited_by    uuid REFERENCES users(id),
  last_login_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, email),
  CHECK (email = lower(email))
);

CREATE TABLE user_sessions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organizations(id),
  user_id      uuid NOT NULL REFERENCES users(id),
  token_hash   bytea NOT NULL UNIQUE,
  ip           inet,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz
);

-- One data key per lead and per form session (envelope encryption). Destroying the keys of a lead
-- makes all of its encrypted fields and files unreadable (crypto-shredding).
CREATE TABLE data_keys (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organizations(id),
  owner_type   text NOT NULL CHECK (owner_type IN ('lead', 'form_session')),
  owner_id     uuid NOT NULL,
  wrapped      bytea,
  kek_version  int NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  destroyed_at timestamptz
);
CREATE INDEX ON data_keys (owner_id);

-- ── Leads ─────────────────────────────────────────────────────

CREATE TABLE leads (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id         uuid NOT NULL REFERENCES organizations(id),
  program_id     uuid NOT NULL REFERENCES programs(id),
  assigned_rm_id uuid REFERENCES users(id),
  source         text NOT NULL CHECK (source IN ('manual', 'form_link', 'website', 'referral')),
  key_id         uuid NOT NULL REFERENCES data_keys(id),
  name_enc       bytea,
  mobile_enc     bytea NOT NULL,
  mobile_hash    bytea NOT NULL,
  mobile_last4   text NOT NULL,
  email_enc      bytea,
  state          text,
  pincode        text,
  status         text NOT NULL DEFAULT 'new',
  created_by     uuid REFERENCES users(id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz
);
CREATE UNIQUE INDEX leads_mobile_per_program ON leads (program_id, mobile_hash) WHERE deleted_at IS NULL;
CREATE INDEX ON leads (org_id, assigned_rm_id);

CREATE TABLE lead_assignments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organizations(id),
  lead_id      uuid NOT NULL REFERENCES leads(id),
  from_user_id uuid REFERENCES users(id),
  to_user_id   uuid REFERENCES users(id),
  assigned_by  uuid REFERENCES users(id),
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ── Onboarding data ───────────────────────────────────────────

CREATE TABLE form_sessions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id),
  program_id       uuid NOT NULL REFERENCES programs(id),
  lead_id          uuid REFERENCES leads(id),
  ref_lead_id      uuid REFERENCES leads(id),
  token_hash       bytea NOT NULL UNIQUE,
  key_id           uuid NOT NULL REFERENCES data_keys(id),
  answers_enc      bytea,
  answered_count   int NOT NULL DEFAULT 0,
  current_step     int NOT NULL DEFAULT 1,
  status           text NOT NULL DEFAULT 'opened' CHECK (status IN ('opened', 'in_progress', 'submitted')),
  opened_at        timestamptz NOT NULL DEFAULT now(),
  last_activity_at timestamptz NOT NULL DEFAULT now(),
  submitted_at     timestamptz,
  otp_verified_at  timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON form_sessions (lead_id);

CREATE TABLE consents (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id),
  lead_id         uuid REFERENCES leads(id),
  form_session_id uuid REFERENCES form_sessions(id),
  purpose         text NOT NULL CHECK (purpose IN ('data_processing', 'contact', 'call_recording', 'whatsapp')),
  notice_version  text NOT NULL,
  method          text NOT NULL CHECK (method IN ('form_checkbox', 'verbal_on_call', 'otp')),
  granted_at      timestamptz NOT NULL DEFAULT now(),
  withdrawn_at    timestamptz
);

CREATE TABLE uploaded_documents (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id),
  lead_id         uuid REFERENCES leads(id),
  form_session_id uuid NOT NULL REFERENCES form_sessions(id),
  doc_type        text NOT NULL,
  storage_key     text NOT NULL UNIQUE,
  key_id          uuid NOT NULL REFERENCES data_keys(id),
  sha256          text NOT NULL,
  mime_type       text NOT NULL,
  size_bytes      int NOT NULL,
  width           int,
  height          int,
  scan_status     text NOT NULL CHECK (scan_status IN ('clean', 'skipped')),
  exif_lat        double precision,
  exif_lng        double precision,
  created_at      timestamptz NOT NULL DEFAULT now(),
  superseded_at   timestamptz
);
CREATE INDEX ON uploaded_documents (form_session_id);

CREATE TABLE field_visits (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id         uuid NOT NULL REFERENCES organizations(id),
  lead_id        uuid NOT NULL UNIQUE REFERENCES leads(id),
  answers        jsonb NOT NULL,
  recommendation text,
  updated_by     uuid REFERENCES users(id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mismatches (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id),
  lead_id     uuid NOT NULL REFERENCES leads(id),
  field_name  text NOT NULL CHECK (field_name IN ('name', 'dob', 'father_name', 'signature', 'shop_address', 'local_address')),
  source_a    text,
  value_a_enc bytea,
  source_b    text,
  value_b_enc bytea,
  auto        boolean NOT NULL DEFAULT false,
  resolved    boolean NOT NULL DEFAULT false,
  created_by  uuid REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE generated_documents (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organizations(id),
  lead_id      uuid NOT NULL REFERENCES leads(id),
  doc_type     text NOT NULL CHECK (doc_type IN ('application_form', 'field_verification_report', 'declaration', 'agreement')),
  version      int NOT NULL,
  filename     text NOT NULL,
  storage_key  text NOT NULL UNIQUE,
  key_id       uuid NOT NULL REFERENCES data_keys(id),
  sha256       text NOT NULL,
  generated_by uuid REFERENCES users(id),
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ── Automation & audit ────────────────────────────────────────

CREATE TABLE events (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id     uuid NOT NULL REFERENCES organizations(id),
  lead_id    uuid REFERENCES leads(id),
  actor_type text NOT NULL CHECK (actor_type IN ('system', 'user', 'lead', 'webhook')),
  actor_id   uuid,
  type       text NOT NULL,
  payload    jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON events (lead_id, id);

CREATE TABLE audit_log (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id      uuid NOT NULL REFERENCES organizations(id),
  user_id     uuid REFERENCES users(id),
  action      text NOT NULL,
  target_type text,
  target_id   text,
  ip          inet,
  user_agent  text,
  details     jsonb NOT NULL DEFAULT '{}',
  prev_hash   text,
  hash        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (org_id, id);

CREATE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER leads_touch BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ── Row-level security ────────────────────────────────────────
-- app.role = 'system' is used only by server-side code paths (public form, background work).

CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT coalesce(current_setting('app.role', true), '') $$;
CREATE FUNCTION app_org() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$;
CREATE FUNCTION app_user() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['programs', 'teams', 'users', 'user_sessions', 'data_keys', 'leads', 'lead_assignments',
                           'form_sessions', 'consents', 'uploaded_documents', 'field_visits', 'mismatches',
                           'generated_documents', 'events', 'audit_log']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY org_isolation ON %I USING (app_role() = ''system'' OR org_id = app_org())
                    WITH CHECK (app_role() = ''system'' OR org_id = app_org())', t);
  END LOOP;
END $$;

-- RMs see only leads assigned to them; managers see their team's leads and unassigned ones.
CREATE POLICY lead_visibility ON leads AS RESTRICTIVE
  USING (
    app_role() IN ('system', 'org_admin', 'compliance_viewer')
    OR (app_role() = 'rm' AND assigned_rm_id = app_user())
    OR (app_role() = 'rm_manager' AND (
          assigned_rm_id IS NULL
          OR assigned_rm_id = app_user()
          OR assigned_rm_id IN (SELECT u.id FROM users u
                                WHERE u.team_id IS NOT NULL
                                  AND u.team_id = (SELECT me.team_id FROM users me WHERE me.id = app_user()))))
  );

-- Everything hanging off a lead is visible only if the lead itself is visible.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['lead_assignments', 'form_sessions', 'consents', 'uploaded_documents', 'field_visits',
                           'mismatches', 'generated_documents', 'events']
  LOOP
    EXECUTE format('CREATE POLICY via_lead ON %I AS RESTRICTIVE
                    USING (app_role() = ''system'' OR lead_id IS NULL
                           OR EXISTS (SELECT 1 FROM leads l WHERE l.id = lead_id))', t);
  END LOOP;
END $$;

-- Compliance viewers can read but never change anything.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['leads', 'lead_assignments', 'form_sessions', 'uploaded_documents', 'field_visits',
                           'mismatches', 'generated_documents', 'users', 'teams']
  LOOP
    EXECUTE format('CREATE POLICY read_only_compliance_ins ON %I AS RESTRICTIVE FOR INSERT
                    WITH CHECK (app_role() <> ''compliance_viewer'')', t);
    EXECUTE format('CREATE POLICY read_only_compliance_upd ON %I AS RESTRICTIVE FOR UPDATE
                    USING (app_role() <> ''compliance_viewer'')', t);
    EXECUTE format('CREATE POLICY read_only_compliance_del ON %I AS RESTRICTIVE FOR DELETE
                    USING (app_role() <> ''compliance_viewer'')', t);
  END LOOP;
END $$;
