#!/usr/bin/env python3
"""Admin commands. Run from the project folder with the venv's python, e.g. `venv/bin/python manage.py migrate`.

  genkeys                     print fresh SECRET_KEY / MASTER_KEY_V1 / INDEX_KEY values for .env
  migrate                     apply database migrations in migrations/
  init                        create the organisation, the ESAF programme and the first admin
  add-user EMAIL NAME ROLE    invite a user (roles: org_admin, rm_manager, rm, compliance_viewer)
  erase-lead LEAD_ID          DPDP erasure: destroy the lead's keys (crypto-shred) and delete its files
  purge-stale --days N        delete form sessions where no mobile was entered, older than N days
  verify-audit                check the audit log's hash chain hasn't been tampered with
"""
import argparse
import base64
import glob
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def genkeys(_):
    print("# Paste into the server's .env. Keep a copy in a password manager; losing MASTER_KEY_V1 means losing all data.")
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print("KEK_VERSION=1")
    print(f"MASTER_KEY_V1={base64.b64encode(os.urandom(32)).decode()}")
    print(f"INDEX_KEY={base64.b64encode(os.urandom(32)).decode()}")


def _db():
    sys.path.insert(0, os.path.join(ROOT, "webform"))
    import db
    return db


def migrate(_):
    import psycopg2
    sys.path.insert(0, os.path.join(ROOT, "webform"))
    import config
    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS app")
        cur.execute("CREATE TABLE IF NOT EXISTS app.schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        conn.commit()
        cur.execute("SELECT name FROM app.schema_migrations")
        done = {r[0] for r in cur.fetchall()}
        for path in sorted(glob.glob(os.path.join(ROOT, "migrations", "*.sql"))):
            name = os.path.basename(path)
            if name in done:
                continue
            print(f"applying {name}")
            with open(path) as f:
                cur.execute(f.read())
            cur.execute("INSERT INTO app.schema_migrations (name) VALUES (%s)", (name,))
            conn.commit()
    conn.close()
    print("migrations up to date")


def init(args):
    db = _db()
    with db.tx(db.SYSTEM) as cur:
        cur.execute("SELECT id FROM organizations WHERE slug = %s", (args.org_slug,))
        org = cur.fetchone()
        if not org:
            cur.execute("INSERT INTO organizations (name, slug, allowed_google_domain) VALUES (%s, %s, %s) RETURNING id",
                        (args.org_name, args.org_slug, args.google_domain or None))
            org = cur.fetchone()
            print(f"created organisation {args.org_name}")
        cur.execute("SELECT 1 FROM programs WHERE slug = %s", (args.program_slug,))
        if not cur.fetchone():
            cur.execute(
                """INSERT INTO programs (org_id, slug, name, bank_name, bc_name, submission_email)
                   VALUES (%s, %s, 'ESAF CSP onboarding', 'ESAF Small Finance Bank', 'Aceware Fintech Services Pvt Ltd', %s)""",
                (org["id"], args.program_slug, args.submission_email),
            )
            print(f"created programme {args.program_slug}")
        cur.execute("SELECT 1 FROM users WHERE email = %s", (args.admin_email.lower(),))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (org_id, email, name, role) VALUES (%s, %s, %s, 'org_admin')",
                        (org["id"], args.admin_email.lower(), args.admin_name))
            print(f"invited admin {args.admin_email}")


def add_user(args):
    db = _db()
    with db.tx(db.SYSTEM) as cur:
        cur.execute("SELECT id FROM organizations ORDER BY created_at LIMIT 1")
        org = cur.fetchone()
        cur.execute("INSERT INTO users (org_id, email, name, role) VALUES (%s, %s, %s, %s)",
                    (org["id"], args.email.lower(), args.name, args.role))
    print(f"invited {args.email} as {args.role}")


def erase_lead(args):
    db = _db()
    import activity
    import storage
    with db.tx(db.SYSTEM) as cur:
        cur.execute("SELECT org_id FROM leads WHERE id = %s", (args.lead_id,))
        lead = cur.fetchone()
        if not lead:
            sys.exit("no such lead")
        cur.execute("SELECT storage_key FROM uploaded_documents WHERE lead_id = %s UNION ALL "
                    "SELECT storage_key FROM generated_documents WHERE lead_id = %s", (args.lead_id, args.lead_id))
        keys = [r["storage_key"] for r in cur.fetchall()]
        cur.execute(
            """UPDATE data_keys SET wrapped = NULL, destroyed_at = now()
               WHERE owner_id = %s OR owner_id IN (SELECT id FROM form_sessions WHERE lead_id = %s)""",
            (args.lead_id, args.lead_id),
        )
        cur.execute("UPDATE leads SET deleted_at = now(), name_enc = NULL, email_enc = NULL WHERE id = %s", (args.lead_id,))
        activity.audit(cur, lead["org_id"], "erase_lead", "lead", args.lead_id, {"files": len(keys)})
    for k in keys:
        storage.delete(k)
    print(f"erased lead {args.lead_id}: keys destroyed, {len(keys)} files deleted")


def purge_stale(args):
    db = _db()
    with db.tx(db.SYSTEM) as cur:
        cur.execute("""DELETE FROM form_sessions WHERE lead_id IS NULL AND last_activity_at < now() - make_interval(days => %s)
                       RETURNING id""", (args.days,))
        ids = [r["id"] for r in cur.fetchall()]
        if ids:
            cur.execute("DELETE FROM data_keys WHERE owner_type = 'form_session' AND owner_id = ANY(%s::uuid[])",
                        ([str(i) for i in ids],))
    print(f"purged {len(ids)} stale anonymous form sessions")


def verify_audit(_):
    db = _db()
    import activity
    with db.tx(db.SYSTEM) as cur:
        cur.execute("SELECT id, name FROM organizations")
        for org in cur.fetchall():
            bad = activity.verify_audit_chain(cur, org["id"])
            print(f"{org['name']}: " + ("audit chain OK" if bad is None else f"TAMPERING DETECTED at audit_log id {bad}"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("genkeys").set_defaults(fn=genkeys)
    sub.add_parser("migrate").set_defaults(fn=migrate)
    s = sub.add_parser("init")
    s.add_argument("--org-name", required=True)
    s.add_argument("--org-slug", required=True)
    s.add_argument("--google-domain", help="only Google accounts from this Workspace domain can sign in")
    s.add_argument("--admin-email", required=True)
    s.add_argument("--admin-name", required=True)
    s.add_argument("--program-slug", default="esaf-csp")
    s.add_argument("--submission-email", default="Wasim@acemoney.in")
    s.set_defaults(fn=init)
    s = sub.add_parser("add-user")
    s.add_argument("email")
    s.add_argument("name")
    s.add_argument("role", choices=["org_admin", "rm_manager", "rm", "compliance_viewer"])
    s.set_defaults(fn=add_user)
    s = sub.add_parser("erase-lead")
    s.add_argument("lead_id")
    s.set_defaults(fn=erase_lead)
    s = sub.add_parser("purge-stale")
    s.add_argument("--days", type=int, default=30)
    s.set_defaults(fn=purge_stale)
    sub.add_parser("verify-audit").set_defaults(fn=verify_audit)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
