# Deploying the CSP Onboarding Platform

*For whoever sets up the company server (Ubuntu 22.04/24.04 LTS assumed, in an Indian region). Takes about an hour.*

---

## 1. What runs where

```
Internet ──443──▶ nginx (TLS, rate limits, security headers)
                    │  only nginx is reachable from outside
                    ▼
               gunicorn on 127.0.0.1:8000  ──▶  PostgreSQL on 127.0.0.1:5432 (not exposed)
               (systemd service "csp-onboarding", user "csp")
                    │
                    ▼
               /srv/csp-onboarding/data/objects   ← encrypted uploads + generated documents
```

## 2. Where everything is stored

| What | Where | How it's protected |
|---|---|---|
| Code | `/srv/csp-onboarding/app` (from the company git repo) | owned by root, read-only to the app |
| Python environment | `/srv/csp-onboarding/venv` | |
| Settings and secrets | `/srv/csp-onboarding/app/.env` | `chmod 600`, owner `csp`. Never in git. |
| Lead records, answers, timeline, audit log | PostgreSQL database `csp_onboarding`, schema `app` | Names, mobiles, emails and all form answers are **encrypted by the app** before they reach the database (AES-256-GCM, a separate key per lead). Row-level security limits each RM to their own leads. |
| Uploaded photos (Aadhaar, PAN, passbook…) | `/srv/csp-onboarding/data/objects/ab/<random>.bin` | Re-encoded to clean JPEG, then **encrypted** with the lead's key. Random file names, no personal data in paths. `chmod 600`. |
| Generated forms (application, FVR, declaration, agreement) | Same object store | Encrypted the same way. Versioned (v1, v2…), never overwritten. |
| Backups | `/srv/csp-onboarding/backups/*.gpg` + a second location | GPG AES-256 encrypted. |
| Logs | `journalctl -u csp-onboarding` and nginx logs | No personal data is logged by the app. |

**When someone uploads a photo:**
1. The upload arrives over HTTPS.
2. nginx checks the size (max 16 MB) and the rate limit.
3. The app confirms it's really an image by reading its contents, not its name.
4. The photo is decoded and saved as a fresh JPEG. This strips all metadata and anything hidden in the file. GPS is read first, for the shop photo.
5. ClamAV scans it, if enabled.
6. The photo is encrypted with the lead's key.
7. It's written to `data/objects/` under a random name.
8. A row in `app.uploaded_documents` records its type, size, checksum and scan result.

**Encryption keys:**
- `MASTER_KEY_V1` in `.env` wraps every lead's data key. **If you lose it, every lead's data becomes unreadable.** Keep a copy in the company password manager or vault, separate from the backups.
- `INDEX_KEY` lets the app look up mobile numbers without storing them in plain text.
- To rotate, add `MASTER_KEY_V2`, set `KEK_VERSION=2`, and keep V1 so existing data still opens.

---

## 3. One-time server setup

```bash
# Packages
sudo apt update
sudo apt install -y python3 python3-venv postgresql nginx certbot python3-certbot-nginx \
                    libreoffice-writer-nogui fonts-noto-core gnupg ufw
sudo apt install -y clamav-daemon     # optional virus scanning (then set CLAMAV_ENABLED=1)

# Firewall: only SSH and HTTPS
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable

# App user and folders
sudo useradd --system --home /srv/csp-onboarding --shell /usr/sbin/nologin csp
sudo mkdir -p /srv/csp-onboarding/{data/objects,backups,.config,.cache}
sudo chown -R csp:csp /srv/csp-onboarding && sudo chmod 700 /srv/csp-onboarding/data /srv/csp-onboarding/backups

# Code (from the company's private git repo)
sudo git clone <company-repo-url> /srv/csp-onboarding/app
sudo python3 -m venv /srv/csp-onboarding/venv
sudo /srv/csp-onboarding/venv/bin/pip install -r /srv/csp-onboarding/app/requirements.txt

# Database (local only, its own user, not a superuser)
sudo -u postgres psql -c "CREATE USER csp_app WITH PASSWORD '<strong-password>';"
sudo -u postgres psql -c "CREATE DATABASE csp_onboarding OWNER csp_app;"
```

### Settings

```bash
cd /srv/csp-onboarding/app
sudo cp .env.example .env
sudo /srv/csp-onboarding/venv/bin/python manage.py genkeys     # paste the output into .env
sudo nano .env      # DATABASE_URL, PUBLIC_BASE_URL, STORAGE_DIR, GOOGLE_CLIENT_ID/SECRET, Telegram...
sudo chown csp:csp .env && sudo chmod 600 .env
```

### Google sign-in

In Google Cloud Console:
1. Open **APIs & Services → OAuth consent screen** and choose **Internal**, so only your Workspace accounts can sign in.
2. Open **Credentials → Create credentials → OAuth client ID**:
   - Type: **Web application**
   - Authorised redirect URI: `https://csp.yourcompany.in/auth/google/callback`
3. Copy the client ID and secret into `.env`.
4. In the Workspace admin console, enforce **2-Step Verification** for everyone who uses the dashboard.

### Database and first admin

```bash
cd /srv/csp-onboarding/app
sudo -u csp /srv/csp-onboarding/venv/bin/python manage.py migrate
sudo -u csp /srv/csp-onboarding/venv/bin/python manage.py init \
     --org-name "Your Company" --org-slug yourco --google-domain yourcompany.in \
     --admin-email you@yourcompany.in --admin-name "Your Name"
```

The admin then invites RMs from **Team** in the dashboard.

### Start it

```bash
sudo cp deploy/csp-onboarding.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now csp-onboarding
sudo cp deploy/nginx.conf /etc/nginx/sites-available/csp-onboarding    # edit the domain first
sudo ln -s /etc/nginx/sites-available/csp-onboarding /etc/nginx/sites-enabled/
sudo certbot --nginx -d csp.yourcompany.in
sudo nginx -t && sudo systemctl reload nginx
```

Open `https://csp.yourcompany.in/dashboard` and sign in with Google. The form link is `https://csp.yourcompany.in/apply`.

### Backups

```bash
sudo sh -c 'head -c 48 /dev/urandom | base64 > /etc/csp-backup.pass && chmod 600 /etc/csp-backup.pass'
sudo cp deploy/backup.sh /usr/local/bin/csp-backup && sudo chmod 700 /usr/local/bin/csp-backup
echo "30 2 * * * root /usr/local/bin/csp-backup" | sudo tee /etc/cron.d/csp-backup
```

**Test a restore once a month.** Store the backup passphrase and `MASTER_KEY_V1` safely, separately from each other.

### Housekeeping (cron)

```bash
# Delete anonymous form sessions (no mobile entered) older than 30 days
0 3 * * * csp cd /srv/csp-onboarding/app && /srv/csp-onboarding/venv/bin/python manage.py purge-stale --days 30
# Check the audit log hasn't been tampered with
0 4 * * 1 csp cd /srv/csp-onboarding/app && /srv/csp-onboarding/venv/bin/python manage.py verify-audit
```

---

## 4. Updating to a new version

```bash
cd /srv/csp-onboarding/app && sudo git pull
sudo /srv/csp-onboarding/venv/bin/pip install -r requirements.txt
sudo -u csp /srv/csp-onboarding/venv/bin/python manage.py migrate
sudo systemctl restart csp-onboarding
```

## 5. Erasure request (DPDP)

```bash
sudo -u csp /srv/csp-onboarding/venv/bin/python manage.py erase-lead <lead-id>
```

This destroys the lead's encryption keys, so their data can never be read again, deletes their files, and records the erasure in the audit log.

---

## 6. Running it on a laptop for testing

```bash
cd csp-onboarding-agent
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py genkeys          # paste into .env, plus the lines below
#   APP_ENV=development
#   DEV_LOGIN=1
#   DATABASE_URL=postgresql://esaf_app:<password>@localhost:5432/esaf_onboarding
venv/bin/python manage.py migrate
venv/bin/python manage.py init --org-name "Eko" --org-slug eko --admin-email you@example.com --admin-name "You"
venv/bin/python webform/app.py
```

Open http://localhost:5000/dashboard, sign in with **Dev sign-in** using the admin email, and share the form link shown on the dashboard.

---

## 7. Not included yet (each needs an outside account)

| Feature | What's needed | Where it plugs in |
|---|---|---|
| SMS OTP on the form | SMS provider with TRAI DLT template | `form_sessions.otp_verified_at` is ready; add a step-1 check in `app.save_step` |
| Automatic WhatsApp after "Interested" | Meta WhatsApp Cloud API + approved utility template | the dashboard's "Send form" button |
| Automatic email | Amazon SES (Mumbai) or Zoho ZeptoMail + DNS records | same place |
| Call recording → transcript | Exotel + Sarvam STT | new `calls` table + webhook |
| Aadhaar QR / OCR prefill | UIDAI certificate; PaddleOCR | upload pipeline (`uploads.py`) |
| Aadhaar image masking | OCR to locate digits | upload pipeline |
| Penetration test | CERT-In empanelled auditor | before real leads |
