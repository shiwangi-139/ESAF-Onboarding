#!/usr/bin/env python3
"""CSP onboarding platform: the public form (/apply) and the RM dashboard (/dashboard).

Each visitor gets a form session (cookie). Every step and photo is saved as they go, encrypted with that
session's data key, so RMs can track who opened the form, how far they got and what they filled.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import uuid

from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import activity
import auth
import config
import crypto
import storage
import uploads
from db import SYSTEM, tx
from fields import DOC_FIELDS, DOC_KEYS, FIELDS, REQUIRED_KEYS, STEP_FIELD_KEYS, STEPS, TOTAL_STEPS, UPPERCASE_KEYS

logging.basicConfig(level=logging.INFO)

APPLY_COOKIE = "csp_apply"
APPLY_COOKIE_DAYS = 30
# Link previews (WhatsApp, Facebook) fetch the page too: they must not count as someone opening it.
PREVIEW_BOTS = re.compile(r"bot|crawler|spider|whatsapp|facebookexternalhit|preview|slurp", re.I)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(
    MAX_CONTENT_LENGTH=(config.MAX_UPLOAD_MB + 1) * 1024 * 1024,
    SESSION_COOKIE_SECURE=not config.IS_DEV,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
if not config.IS_DEV:
    # Behind nginx on the server. (Never trust forwarded headers when the app is reachable directly.)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

auth.init_app(app)
from dashboard import bp as dashboard_bp  # noqa: E402
app.register_blueprint(dashboard_bp)


@app.before_request
def _load_user():
    auth.load_user()


@app.after_request
def _security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; "
        "object-src 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
    if not config.IS_DEV:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith(("/dashboard", "/apply", "/auth")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ── helpers ───────────────────────────────────────────────────

def _hash(token):
    return hashlib.sha256(token.encode()).digest()


def is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def normalize_mobile(value):
    digits = re.sub(r"\D", "", value or "")[-10:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


def apply_csrf(token):
    return hmac.new(config.SECRET_KEY.encode(), b"apply:" + _hash(token), "sha256").hexdigest()


def check_apply_csrf():
    token = request.cookies.get(APPLY_COOKIE, "")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not token or not hmac.compare_digest(sent, apply_csrf(token)):
        abort(400)


def default_program(cur):
    cur.execute("SELECT * FROM programs WHERE slug = %s AND status = 'active'", (config.DEFAULT_PROGRAM_SLUG,))
    program = cur.fetchone()
    if not program:
        abort(503, "The onboarding programme isn't set up yet (run: python manage.py init).")
    return program


def get_session_form(cur):
    token = request.cookies.get(APPLY_COOKIE)
    if not token:
        return None
    cur.execute("SELECT * FROM form_sessions WHERE token_hash = %s AND status <> 'submitted'", (_hash(token),))
    return cur.fetchone()


def find_or_create_lead(cur, form, mobile, email):
    """The form link is shared by everyone, so the mobile number ties a session to a lead."""
    mobile_hash = crypto.blind_index(mobile)
    cur.execute(
        "SELECT id FROM leads WHERE program_id = %s AND mobile_hash = %s AND deleted_at IS NULL",
        (form["program_id"], mobile_hash),
    )
    row = cur.fetchone()
    if row:
        return row["id"], False
    lead_id = uuid.uuid4()
    key_id, key = crypto.create_data_key(cur, form["org_id"], "lead", lead_id)
    cur.execute(
        """INSERT INTO leads (id, org_id, program_id, source, key_id, mobile_enc, mobile_hash, mobile_last4,
                              email_enc, status)
           VALUES (%s, %s, %s, 'form_link', %s, %s, %s, %s, %s, 'form_in_progress')""",
        (str(lead_id), form["org_id"], form["program_id"], key_id, crypto.enc_text(key, mobile), mobile_hash,
         mobile[-4:], crypto.enc_text(key, email)),
    )
    activity.event(cur, form["org_id"], str(lead_id), "lead.created", "lead", payload={"source": "form_link"})
    return str(lead_id), True


def answered(answers):
    return sum(1 for k in REQUIRED_KEYS if answers.get(k))


# ── public form ───────────────────────────────────────────────

@app.route("/")
def home():
    return redirect(url_for("dashboard.index"))


@app.route("/form/<token>")
def old_per_lead_link(token):
    return redirect(url_for("apply"))


@app.route("/apply/new")
def start_over():
    resp = make_response(redirect(url_for("apply")))
    resp.delete_cookie(APPLY_COOKIE, path="/apply")
    return resp


@app.route("/apply")
def apply():
    page = dict(steps=STEPS, total_steps=TOTAL_STEPS, doc_fields=DOC_FIELDS, saved={}, uploaded=[], start_step=1,
                csrf="", doc_keys=DOC_KEYS, notice_version=config.CONSENT_NOTICE_VERSION)
    if PREVIEW_BOTS.search(request.headers.get("User-Agent", "")):
        return render_template("apply.html", **page)

    token = request.cookies.get(APPLY_COOKIE)
    ref = request.args.get("ref")
    with tx(SYSTEM) as cur:
        program = default_program(cur)
        form = get_session_form(cur)
        if not form:
            token = secrets.token_urlsafe(32)
            form_id = uuid.uuid4()
            key_id, _ = crypto.create_data_key(cur, program["org_id"], "form_session", form_id)
            lead_id = None
            if is_uuid(ref):
                cur.execute("SELECT id FROM leads WHERE id = %s AND program_id = %s AND deleted_at IS NULL",
                            (ref, program["id"]))
                row = cur.fetchone()
                lead_id = row["id"] if row else None
            cur.execute(
                """INSERT INTO form_sessions (id, org_id, program_id, lead_id, ref_lead_id, token_hash, key_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (str(form_id), program["org_id"], program["id"], lead_id, lead_id, _hash(token), key_id),
            )
            form = cur.fetchone()
            if lead_id:
                cur.execute("UPDATE leads SET status = 'form_opened' WHERE id = %s AND status IN ('new', 'contacted', 'interested')",
                            (lead_id,))
                activity.event(cur, program["org_id"], lead_id, "form.opened", "lead")

        keys = crypto.KeyRing(cur)
        saved = crypto.dec_json(keys.get(form["key_id"]), form["answers_enc"])
        if form["lead_id"] and not saved.get("mobile"):
            cur.execute("SELECT key_id, mobile_enc FROM leads WHERE id = %s", (form["lead_id"],))
            lead = cur.fetchone()
            saved["mobile"] = crypto.dec_text(keys.get(lead["key_id"]), lead["mobile_enc"])
        cur.execute(
            "SELECT doc_type FROM uploaded_documents WHERE form_session_id = %s AND superseded_at IS NULL",
            (form["id"],),
        )
        uploaded = [r["doc_type"] for r in cur.fetchall()]

    page.update(saved=saved, uploaded=uploaded, start_step=min(form["current_step"], TOTAL_STEPS),
                csrf=apply_csrf(token))
    resp = make_response(render_template("apply.html", **page))
    resp.set_cookie(APPLY_COOKIE, token, max_age=APPLY_COOKIE_DAYS * 86400, path="/apply", httponly=True,
                    secure=not config.IS_DEV, samesite="Lax")
    return resp


@app.route("/apply/save", methods=["POST"])
def save_step():
    check_apply_csrf()
    step = request.form.get("step", type=int)
    if step not in STEP_FIELD_KEYS:
        return jsonify(ok=False, error="bad_step"), 400
    data = {k: request.form[k].strip()[:500] for k in STEP_FIELD_KEYS[step] if k in request.form}
    for key in UPPERCASE_KEYS & data.keys():
        data[key] = data[key].upper()

    new_unassigned = None
    with tx(SYSTEM) as cur:
        form = get_session_form(cur)
        if not form:
            return jsonify(ok=False, error="session_expired"), 409
        lead_id = form["lead_id"]
        if step == 1:
            mobile = normalize_mobile(data.get("mobile"))
            if not mobile:
                return jsonify(ok=False, error="invalid_mobile"), 400
            if request.form.get("consent") != "yes":
                return jsonify(ok=False, error="consent_required"), 400
            data["mobile"] = mobile
            if lead_id:
                cur.execute("SELECT mobile_hash FROM leads WHERE id = %s", (lead_id,))
                if bytes(cur.fetchone()["mobile_hash"]) != crypto.blind_index(mobile):
                    lead_id = None
            if not lead_id:
                lead_id, created = find_or_create_lead(cur, form, mobile, data.get("email"))
                cur.execute("UPDATE form_sessions SET lead_id = %s WHERE id = %s", (lead_id, form["id"]))
                cur.execute("UPDATE uploaded_documents SET lead_id = %s WHERE form_session_id = %s", (lead_id, form["id"]))
                cur.execute("SELECT assigned_rm_id FROM leads WHERE id = %s", (lead_id,))
                if created or not cur.fetchone()["assigned_rm_id"]:
                    new_unassigned = lead_id
            cur.execute("SELECT 1 FROM consents WHERE form_session_id = %s", (form["id"],))
            if not cur.fetchone():
                for purpose in ("data_processing", "contact"):
                    cur.execute(
                        """INSERT INTO consents (org_id, lead_id, form_session_id, purpose, notice_version, method)
                           VALUES (%s, %s, %s, %s, %s, 'form_checkbox')""",
                        (form["org_id"], lead_id, form["id"], purpose, config.CONSENT_NOTICE_VERSION),
                    )
            cur.execute("UPDATE leads SET status = 'form_in_progress' WHERE id = %s AND status NOT IN ('form_submitted')",
                        (lead_id,))
        elif not lead_id:
            return jsonify(ok=False, error="mobile_first"), 400

        keys = crypto.KeyRing(cur)
        key = keys.get(form["key_id"])
        answers = crypto.dec_json(key, form["answers_enc"])
        answers.update(data)
        cur.execute(
            """UPDATE form_sessions SET answers_enc = %s, answered_count = %s, current_step = GREATEST(current_step, %s),
                                        status = 'in_progress', last_activity_at = now()
               WHERE id = %s""",
            (crypto.enc_json(key, answers), answered(answers), min(step + 1, TOTAL_STEPS), form["id"]),
        )
        if step == 4:
            cur.execute("UPDATE leads SET state = %s, pincode = %s WHERE id = %s",
                        (answers.get("state"), answers.get("pincode"), lead_id))
        activity.event(cur, form["org_id"], lead_id, "form.step_saved", "lead", payload={"step": step})
    if new_unassigned:
        activity.alert(f"🆕 New lead {str(new_unassigned)[:8]} started the form (not assigned to an RM yet).\n"
                       f"{config.PUBLIC_BASE_URL}/dashboard/lead/{new_unassigned}")
    return jsonify(ok=True)


@app.route("/apply/upload", methods=["POST"])
def upload_doc():
    check_apply_csrf()
    doc_type = request.form.get("doc_type")
    file = request.files.get("file")
    if doc_type not in DOC_KEYS or not file:
        return jsonify(ok=False, error="bad_upload"), 400
    try:
        image = uploads.process_image(file.read())
    except uploads.UploadRejected as exc:
        return jsonify(ok=False, error=exc.code), 400

    with tx(SYSTEM) as cur:
        form = get_session_form(cur)
        if not form:
            return jsonify(ok=False, error="session_expired"), 409
        if not form["lead_id"]:
            return jsonify(ok=False, error="mobile_first"), 400
        key = crypto.KeyRing(cur).get(form["key_id"])
        storage_key, sha = storage.put(image["data"], key)
        cur.execute(
            """UPDATE uploaded_documents SET superseded_at = now()
               WHERE form_session_id = %s AND doc_type = %s AND superseded_at IS NULL RETURNING storage_key""",
            (form["id"], doc_type),
        )
        old = [r["storage_key"] for r in cur.fetchall()]
        gps = image["gps"]
        cur.execute(
            """INSERT INTO uploaded_documents (org_id, lead_id, form_session_id, doc_type, storage_key, key_id, sha256,
                                              mime_type, size_bytes, width, height, scan_status, exif_lat, exif_lng)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s)""",
            (form["org_id"], form["lead_id"], form["id"], doc_type, storage_key, form["key_id"], sha,
             len(image["data"]), image["width"], image["height"], image["scan_status"],
             gps[0] if gps else None, gps[1] if gps else None),
        )
        cur.execute("UPDATE form_sessions SET status = 'in_progress', last_activity_at = now() WHERE id = %s",
                    (form["id"],))
        activity.event(cur, form["org_id"], form["lead_id"], "document.uploaded", "lead", payload={"doc_type": doc_type})
    for storage_key in old:
        storage.delete(storage_key)
    return jsonify(ok=True)


def render_message(title, body, status=200):
    return render_template("message.html", title=title, body=body, back=status == 400), status


@app.route("/apply/submit", methods=["POST"])
def submit():
    check_apply_csrf()
    with tx(SYSTEM) as cur:
        form = get_session_form(cur)
        if not form:
            return render_message("सत्र समाप्त / Session expired",
                                  ["कृपया फॉर्म दोबारा खोलें। / Please open the form again."], 409)
        keys = crypto.KeyRing(cur)
        answers = crypto.dec_json(keys.get(form["key_id"]), form["answers_enc"])
        cur.execute(
            "SELECT doc_type FROM uploaded_documents WHERE form_session_id = %s AND superseded_at IS NULL", (form["id"],)
        )
        uploaded = {r["doc_type"] for r in cur.fetchall()}
        missing = [f"{FIELDS[k].hi} / {FIELDS[k].en}" for k in REQUIRED_KEYS if not answers.get(k)]
        if answers.get("lives_at_aadhaar_address") == "no" and not answers.get("local_address"):
            missing.append(f"{FIELDS['local_address'].hi} / {FIELDS['local_address'].en}")
        missing += [f"{hi} / {en}" for key, hi, en in DOC_FIELDS if key not in uploaded]
        if not form["lead_id"]:
            missing.insert(0, "मोबाइल नंबर / Mobile number")
        if missing:
            return render_message("कुछ जानकारी बाकी है / Some details are missing", missing, 400)

        lead_id = form["lead_id"]
        cur.execute("SELECT key_id, assigned_rm_id FROM leads WHERE id = %s", (lead_id,))
        lead = cur.fetchone()
        lead_key = keys.get(lead["key_id"])
        cur.execute("UPDATE form_sessions SET status = 'submitted', submitted_at = now(), last_activity_at = now() "
                    "WHERE id = %s", (form["id"],))
        cur.execute(
            """UPDATE leads SET status = 'form_submitted', name_enc = %s,
                                email_enc = COALESCE(%s, email_enc) WHERE id = %s""",
            (crypto.enc_text(lead_key, answers.get("full_name")), crypto.enc_text(lead_key, answers.get("email")), lead_id),
        )
        cur.execute("DELETE FROM mismatches WHERE lead_id = %s AND auto AND NOT resolved", (lead_id,))
        if answers.get("lives_at_aadhaar_address") == "no":
            cur.execute(
                """INSERT INTO mismatches (org_id, lead_id, field_name, source_a, source_b, value_b_enc, auto)
                   VALUES (%s, %s, 'local_address', 'Aadhaar', 'current residence', %s, true)""",
                (form["org_id"], lead_id, crypto.enc_text(lead_key, answers.get("local_address"))),
            )
        if answers.get("has_shop_proof") == "no":
            cur.execute(
                """INSERT INTO mismatches (org_id, lead_id, field_name, source_a, source_b, value_b_enc, auto)
                   VALUES (%s, %s, 'shop_address', 'no shop address proof', 'form', %s, true)""",
                (form["org_id"], lead_id, crypto.enc_text(lead_key, answers.get("shop_address"))),
            )
        activity.event(cur, form["org_id"], lead_id, "form.submitted", "lead")
    activity.alert(f"✅ Lead {str(lead_id)[:8]} submitted the onboarding form"
                   f"{'' if lead['assigned_rm_id'] else ' (not assigned to an RM yet)'}.\n"
                   f"{config.PUBLIC_BASE_URL}/dashboard/lead/{lead_id}")

    html, status = render_message(
        "धन्यवाद / Thank you",
        ["आपकी जानकारी सफलतापूर्वक जमा हो गई है। आपका RM जल्द संपर्क करेगा।",
         "Your details were submitted successfully. Your RM will follow up shortly."],
    )
    resp = make_response(html, status)
    resp.delete_cookie(APPLY_COOKIE, path="/apply")
    return resp


@app.errorhandler(413)
def too_large(_):
    return jsonify(ok=False, error="too_large"), 413


if __name__ == "__main__":
    # Local development only. On the server the app runs under gunicorn (see deploy/).
    app.run(host="0.0.0.0" if config.IS_DEV else "127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
