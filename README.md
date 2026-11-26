# CSP Agent Onboarding Platform

Onboards CSP (Customer Service Point) agents for ESAF Small Finance Bank. It covers the whole path from lead → bilingual mobile form → document upload → field visit → auto-filled official documents, and an RM dashboard tracks every lead along the way.

- **Public form:** `/apply`, one permanent link. Progress saves on every step.
- **RM dashboard:** `/dashboard`. Google sign-in, roles (admin / RM manager / RM / compliance), lead assignment.
- **Security:** encrypted fields and files (a key per lead), Postgres row-level security, a secure upload pipeline, a hash-chained audit log. See [docs/SECURITY.md](docs/SECURITY.md).

**Uploaded documents never go into this repository.** They are stored encrypted on the server (`STORAGE_DIR`, default `/srv/csp-onboarding/data/objects`). Locally they go to `data/`, which git ignores.

## Docs

| | |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Server setup, where data is stored, backups, updates |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Database design |
| [docs/SECURITY.md](docs/SECURITY.md) | Security design and go-live checklist |
| [docs/PLAN.md](docs/PLAN.md) | Roadmap |

## Local development

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env
venv/bin/python manage.py genkeys        # paste into .env; also set APP_ENV=development, DEV_LOGIN=1, DATABASE_URL
venv/bin/python manage.py migrate
venv/bin/python manage.py init --org-name "Eko" --org-slug eko --admin-email you@example.com --admin-name "You"
venv/bin/python webform/app.py           # http://localhost:5000/dashboard
```

Never commit `.env`. It holds the encryption keys.
