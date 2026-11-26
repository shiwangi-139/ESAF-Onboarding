"""RM dashboard: track every lead, review what they filled, do the field visit, generate the official documents.

Every query runs with the signed-in user's context, so Postgres row-level security decides which leads they
can see (RMs: their own; managers: their team + unassigned; admins/compliance: everything in the org).
"""
import io
import os
import re
import socket
import tempfile
import uuid
import zipfile
from datetime import date
from urllib.parse import quote

from flask import Blueprint, abort, g, redirect, render_template, request, send_file, url_for

import activity
import config
import crypto
import documents
import storage
from auth import ROLE_LABELS, login_required
from db import SYSTEM, Json, tx
from fields import DECLARATION_TYPES, DOC_FIELDS, FIELDS, FVR_FIELDS, REQUIRED_KEYS, STEPS, TOTAL_STEPS

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

ALL = ("org_admin", "rm_manager", "rm", "compliance_viewer")
WORKERS = ("org_admin", "rm_manager", "rm")
MANAGERS = ("org_admin", "rm_manager")
DOC_KIND_LABELS = {
    "application_form": "Aggregator Application Form",
    "field_verification_report": "Field Verification Report (FVR)",
    "declaration": "Customer Declaration Form",
    "agreement": "Agent Banking Agreement",
}
MASKED_FOR_COMPLIANCE = {"pan_number", "bank_account_number", "micr"}
AUTO_MISMATCH_LABELS = {"shop_address": "No shop address proof", "local_address": "Lives away from Aadhaar address"}

# A lead's most useful form session: a submitted one if any, else the most recently active.
LATEST_FORM = """
    SELECT * FROM form_sessions fs WHERE fs.lead_id = {lead}
    ORDER BY (fs.status = 'submitted') DESC, fs.last_activity_at DESC LIMIT 1
"""


# ── helpers ───────────────────────────────────────────────────

def is_compliance():
    return g.user["role"] == "compliance_viewer"


def mask(value, keep=4):
    return ("•" * max(len(value) - keep, 0) + value[-keep:]) if value else value


def base_url():
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL
    host = request.host
    if host.startswith(("127.0.0.1", "localhost")):
        port = host.split(":", 1)[1] if ":" in host else "80"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host = f"{s.getsockname()[0]}:{port}"
            s.close()
        except OSError:
            pass
    return f"{request.scheme}://{host}"


def apply_link(lead_id=None):
    link = base_url() + "/apply"
    return f"{link}?ref={lead_id}" if lead_id else link


def whatsapp_url(mobile, link):
    message = ("नमस्ते! ESAF Small Finance Bank में CSP बनने के लिए इस लिंक पर अपने दस्तावेज़ "
               f"अपलोड करें और फॉर्म भरें:\n{link}")
    digits = re.sub(r"\D", "", mobile or "")
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(message)}" if digits else f"https://wa.me/?text={quote(message)}"


def progress(form):
    status = (form or {}).get("status")
    info = {"filled": (form or {}).get("answered_count", 0), "total_fields": len(REQUIRED_KEYS),
            "total_docs": len(DOC_FIELDS)}
    if status == "submitted":
        info.update(label="Submitted", color="green", note=fmt_time(form["submitted_at"]))
    elif status == "in_progress":
        info.update(label="Filling in", color="amber",
                    note=f"Step {form['current_step']} of {TOTAL_STEPS} · last active {fmt_time(form['last_activity_at'])}")
    elif status == "opened":
        info.update(label="Opened", color="amber", note=f"Opened {fmt_time(form['opened_at'])}, nothing filled yet")
    else:
        info.update(label="Not opened yet", color="blue", note=None)
    return info


@bp.app_template_filter("fmt")
def fmt_time(value):
    return value.astimezone().strftime("%d %b, %I:%M %p") if value else ""


def decrypt_lead(keys, row):
    key = keys.get(row["key_id"])
    mobile = crypto.dec_text(key, row["mobile_enc"])
    return {
        "name": crypto.dec_text(key, row["name_enc"]),
        "mobile": mask(mobile) if is_compliance() else mobile,
        "email": crypto.dec_text(key, row["email_enc"]),
    }


def get_lead(cur, lead_id):
    cur.execute("SELECT * FROM leads WHERE id = %s AND deleted_at IS NULL", (str(lead_id),))
    lead = cur.fetchone()
    if not lead:
        abort(404)  # also what RLS gives an RM for someone else's lead
    return lead


def back(lead_id, msg, anchor=""):
    return redirect(url_for("dashboard.lead", lead_id=lead_id, msg=msg) + (f"#{anchor}" if anchor else ""))


# ── lead list ─────────────────────────────────────────────────

@bp.route("/")
@login_required(*ALL)
def index():
    view = request.args.get("view", "all")
    with tx(g.ctx) as cur:
        cur.execute(
            f"""SELECT l.id, l.key_id, l.name_enc, l.mobile_enc, l.email_enc, l.source, l.status, l.created_at,
                       l.assigned_rm_id, u.name AS rm_name,
                       f.status AS form_status, f.current_step, f.opened_at, f.last_activity_at, f.submitted_at,
                       f.answered_count,
                       (SELECT count(*) FROM uploaded_documents d
                         WHERE d.form_session_id = f.id AND d.superseded_at IS NULL) AS docs,
                       (SELECT count(*) FROM mismatches m WHERE m.lead_id = l.id AND NOT m.resolved) AS mismatches
                FROM leads l
                LEFT JOIN users u ON u.id = l.assigned_rm_id
                LEFT JOIN LATERAL ({LATEST_FORM.format(lead="l.id")}) f ON true
                WHERE l.deleted_at IS NULL
                ORDER BY COALESCE(f.last_activity_at, l.created_at) DESC"""
        )
        rows = cur.fetchall()
        cur.execute("SELECT count(*) AS n FROM form_sessions WHERE lead_id IS NULL AND opened_at > now() - interval '30 days'")
        anonymous = cur.fetchone()["n"]
        keys = crypto.KeyRing(cur)
        leads = []
        for r in rows:
            form = {"status": r["form_status"], "current_step": r["current_step"], "opened_at": r["opened_at"],
                    "last_activity_at": r["last_activity_at"], "submitted_at": r["submitted_at"],
                    "answered_count": r["answered_count"] or 0} if r["form_status"] else None
            lead = {**decrypt_lead(keys, r), "id": r["id"], "source": r["source"], "created_at": r["created_at"],
                    "rm_name": r["rm_name"], "assigned": r["assigned_rm_id"], "docs": r["docs"],
                    "mismatches": r["mismatches"], "progress": progress(form), "mine": str(r["assigned_rm_id"]) == g.ctx.user_id}
            lead["wa"] = whatsapp_url(None if is_compliance() else lead["mobile"], apply_link(r["id"]))
            leads.append(lead)

    labels = [l["progress"]["label"] for l in leads]
    stats = [
        {"label": "Total leads", "n": len(leads)},
        {"label": "Not opened yet", "n": labels.count("Not opened yet")},
        {"label": "Opened / filling in", "n": labels.count("Opened") + labels.count("Filling in")},
        {"label": "Submitted", "n": labels.count("Submitted")},
        {"label": "Opened, no mobile entered (30 days)", "n": anonymous},
    ]
    if g.user["role"] in MANAGERS:
        stats.append({"label": "Unassigned", "n": sum(1 for l in leads if not l["assigned"])})
    if view == "mine":
        leads = [l for l in leads if l["mine"]]
    elif view == "unassigned":
        leads = [l for l in leads if not l["assigned"]]

    new_lead = next((l for l in leads if str(l["id"]) == request.args.get("new")), None)
    link = apply_link()
    return render_template("dashboard.html", leads=leads, stats=stats, link=link, share_wa=whatsapp_url(None, link),
                           new_lead=new_lead, view=view, error=request.args.get("error"),
                           can_add=g.user["role"] in WORKERS, is_manager=g.user["role"] in MANAGERS)


@bp.route("/leads", methods=["POST"])
@login_required(*WORKERS)
def create():
    name = request.form.get("name", "").strip()[:200]
    mobile = re.sub(r"\D", "", request.form.get("mobile", ""))[-10:]
    email = request.form.get("email", "").strip()[:200]
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        return redirect(url_for("dashboard.index", error="Enter a valid 10-digit mobile number."))
    with tx(SYSTEM) as cur:
        cur.execute("SELECT * FROM programs WHERE org_id = %s AND slug = %s", (g.ctx.org_id, config.DEFAULT_PROGRAM_SLUG))
        program = cur.fetchone()
        cur.execute("SELECT id, assigned_rm_id FROM leads WHERE program_id = %s AND mobile_hash = %s AND deleted_at IS NULL",
                    (program["id"], crypto.blind_index(mobile)))
        existing = cur.fetchone()
    if existing:
        with tx(g.ctx) as cur:
            cur.execute("SELECT 1 FROM leads WHERE id = %s", (existing["id"],))
            visible = cur.fetchone()
        if visible:
            return redirect(url_for("dashboard.index", new=existing["id"]))
        return redirect(url_for("dashboard.index",
                                error="A lead with this mobile already exists and is assigned to another RM. Ask your manager."))

    with tx(g.ctx) as cur:
        lead_id = uuid.uuid4()
        key_id, key = crypto.create_data_key(cur, g.ctx.org_id, "lead", lead_id)
        cur.execute(
            """INSERT INTO leads (id, org_id, program_id, assigned_rm_id, source, key_id, name_enc, mobile_enc,
                                  mobile_hash, mobile_last4, email_enc, status, created_by)
               VALUES (%s, %s, %s, %s, 'manual', %s, %s, %s, %s, %s, %s, 'new', %s)""",
            (str(lead_id), g.ctx.org_id, program["id"], g.ctx.user_id, key_id, crypto.enc_text(key, name),
             crypto.enc_text(key, mobile), crypto.blind_index(mobile), mobile[-4:], crypto.enc_text(key, email),
             g.ctx.user_id),
        )
        activity.event(cur, g.ctx.org_id, str(lead_id), "lead.created", "user", g.ctx.user_id, {"source": "manual"})
        activity.audit(cur, g.ctx.org_id, "create_lead", "lead", lead_id)
    return redirect(url_for("dashboard.index", new=lead_id))


# ── one lead ──────────────────────────────────────────────────

@bp.route("/lead/<uuid:lead_id>")
@login_required(*ALL)
def lead(lead_id):
    with tx(g.ctx) as cur:
        row = get_lead(cur, lead_id)
        keys = crypto.KeyRing(cur)
        lead_key = keys.get(row["key_id"])
        info = decrypt_lead(keys, row)
        cur.execute(LATEST_FORM.format(lead="%s"), (str(lead_id),))
        form = cur.fetchone()
        answers = crypto.dec_json(keys.get(form["key_id"]), form["answers_enc"]) if form else {}
        if is_compliance():
            answers = {k: (mask(v) if k in MASKED_FOR_COMPLIANCE else v) for k, v in answers.items()}
        docs = []
        if form:
            cur.execute("""SELECT id, doc_type, created_at, exif_lat, exif_lng, scan_status FROM uploaded_documents
                           WHERE form_session_id = %s AND superseded_at IS NULL""", (form["id"],))
            docs = cur.fetchall()
        cur.execute("SELECT * FROM field_visits WHERE lead_id = %s", (str(lead_id),))
        visit_row = cur.fetchone()
        cur.execute("SELECT * FROM mismatches WHERE lead_id = %s AND NOT resolved ORDER BY created_at", (str(lead_id),))
        mismatches = cur.fetchall()
        for m in mismatches:
            m["label"] = dict(DECLARATION_TYPES).get(m["field_name"]) or AUTO_MISMATCH_LABELS.get(m["field_name"])
            m["value_a"] = crypto.dec_text(lead_key, m["value_a_enc"])
            m["value_b"] = crypto.dec_text(lead_key, m["value_b_enc"])
        generated = latest_generated(cur, lead_id)
        cur.execute("SELECT type, payload, created_at FROM events WHERE lead_id = %s ORDER BY id", (str(lead_id),))
        history = cur.fetchall()
        rms = []
        if g.user["role"] in MANAGERS:
            cur.execute("SELECT id, name, role FROM users WHERE status <> 'disabled' AND role IN ('rm', 'rm_manager', 'org_admin') "
                        "ORDER BY name")
            rms = cur.fetchall()
        cur.execute("SELECT name FROM users WHERE id = %s", (row["assigned_rm_id"],))
        rm = cur.fetchone()
        activity.audit(cur, g.ctx.org_id, "view_lead", "lead", lead_id)

    started = bool(form)
    groups = [{"title": s["en"], "items": [(f.en, answers.get(f.key)) for f in s["fields"]]}
              for s in STEPS if s["fields"] and s["n"] != 1] if started else []
    docs_by_type = {d["doc_type"]: d for d in docs}
    shop = docs_by_type.get("shop_photo")
    location = None
    if shop and shop["exif_lat"]:
        location = (round(shop["exif_lat"], 6), round(shop["exif_lng"], 6), "photo GPS")
    elif answers.get("shop_lat"):
        location = (answers["shop_lat"], answers["shop_lng"], "phone location")
    missing = []
    if form and form["status"] != "submitted":
        missing = [FIELDS[k].en for k in REQUIRED_KEYS if not answers.get(k)]
        missing += [en for key, _, en in DOC_FIELDS if key not in docs_by_type]

    visit = (visit_row or {}).get("answers") or {"visit_date": date.today().isoformat(), "state": answers.get("state", "")}
    return render_template(
        "lead.html", lead={**row, **info}, rm_name=rm and rm["name"], form=form, info=progress(form),
        total_steps=TOTAL_STEPS, groups=groups, missing=missing, location=location,
        doc_tiles=[(en, docs_by_type.get(key)) for key, _, en in DOC_FIELDS],
        mismatches=mismatches, history=history, submitted=bool(form and form["status"] == "submitted"),
        fvr_fields=FVR_FIELDS, visit=visit, visit_saved_at=visit_row and visit_row["updated_at"],
        declaration_types=DECLARATION_TYPES, generated=generated, doc_kind_labels=DOC_KIND_LABELS,
        wa=whatsapp_url(info["mobile"], apply_link(row["id"])), rms=rms, msg=request.args.get("msg"),
        can_edit=g.user["role"] in WORKERS, is_manager=g.user["role"] in MANAGERS, compliance=is_compliance(),
    )


def latest_generated(cur, lead_id):
    cur.execute(
        """SELECT * FROM generated_documents
           WHERE lead_id = %s AND version = (SELECT max(version) FROM generated_documents WHERE lead_id = %s)
           ORDER BY doc_type, filename""",
        (str(lead_id), str(lead_id)),
    )
    return cur.fetchall()


@bp.route("/file/<uuid:doc_id>")
@login_required(*WORKERS)
def file(doc_id):
    with tx(g.ctx) as cur:
        cur.execute("SELECT * FROM uploaded_documents WHERE id = %s", (str(doc_id),))
        doc = cur.fetchone()
        if not doc:
            abort(404)
        data = storage.get(doc["storage_key"], crypto.KeyRing(cur).get(doc["key_id"]))
        activity.audit(cur, g.ctx.org_id, "view_document", "uploaded_document", doc_id,
                       {"doc_type": doc["doc_type"], "lead_id": str(doc["lead_id"])})
    resp = send_file(io.BytesIO(data), mimetype="image/jpeg")
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/lead/<uuid:lead_id>/assign", methods=["POST"])
@login_required(*MANAGERS)
def assign(lead_id):
    to_user = request.form.get("user_id") or None
    with tx(g.ctx) as cur:
        row = get_lead(cur, lead_id)
        if to_user:
            cur.execute("SELECT id FROM users WHERE id = %s AND status <> 'disabled'", (to_user,))
            if not cur.fetchone():
                abort(400)
        cur.execute("UPDATE leads SET assigned_rm_id = %s WHERE id = %s", (to_user, str(lead_id)))
        cur.execute("INSERT INTO lead_assignments (org_id, lead_id, from_user_id, to_user_id, assigned_by) "
                    "VALUES (%s, %s, %s, %s, %s)", (g.ctx.org_id, str(lead_id), row["assigned_rm_id"], to_user, g.ctx.user_id))
        activity.event(cur, g.ctx.org_id, str(lead_id), "lead.assigned", "user", g.ctx.user_id, {"to": str(to_user)})
        activity.audit(cur, g.ctx.org_id, "assign_lead", "lead", lead_id, {"to": str(to_user)})
    return back(lead_id, "Assignment updated.")


@bp.route("/lead/<uuid:lead_id>/visit", methods=["POST"])
@login_required(*WORKERS)
def save_visit(lead_id):
    answers = {f.key: request.form.get(f.key, "").strip()[:1000] for f in FVR_FIELDS}
    with tx(g.ctx) as cur:
        get_lead(cur, lead_id)
        cur.execute(
            """INSERT INTO field_visits (org_id, lead_id, answers, recommendation, updated_by)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (lead_id) DO UPDATE SET answers = EXCLUDED.answers, recommendation = EXCLUDED.recommendation,
                                                   updated_by = EXCLUDED.updated_by, updated_at = now()""",
            (g.ctx.org_id, str(lead_id), Json(answers), answers.get("recommendation") or None, g.ctx.user_id),
        )
        activity.event(cur, g.ctx.org_id, str(lead_id), "field_visit.saved", "user", g.ctx.user_id,
                       {"recommendation": answers.get("recommendation")})
        activity.audit(cur, g.ctx.org_id, "save_field_visit", "lead", lead_id)
    return back(lead_id, "Field visit saved.", "fvr")


@bp.route("/lead/<uuid:lead_id>/mismatch", methods=["POST"])
@login_required(*WORKERS)
def add_mismatch(lead_id):
    kind = request.form.get("field_name")
    if kind not in dict(DECLARATION_TYPES):
        abort(400)
    with tx(g.ctx) as cur:
        row = get_lead(cur, lead_id)
        key = crypto.KeyRing(cur).get(row["key_id"])
        f = {k: request.form.get(k, "").strip()[:300] for k in ("source_a", "value_a", "source_b", "value_b")}
        cur.execute(
            """INSERT INTO mismatches (org_id, lead_id, field_name, source_a, value_a_enc, source_b, value_b_enc, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (g.ctx.org_id, str(lead_id), kind, f["source_a"] or None, crypto.enc_text(key, f["value_a"]),
             f["source_b"] or None, crypto.enc_text(key, f["value_b"]), g.ctx.user_id),
        )
        activity.audit(cur, g.ctx.org_id, "add_declaration_item", "lead", lead_id, {"type": kind})
    return back(lead_id, "Declaration item added.", "declaration")


@bp.route("/lead/<uuid:lead_id>/mismatch/<uuid:mismatch_id>/delete", methods=["POST"])
@login_required(*WORKERS)
def delete_mismatch(lead_id, mismatch_id):
    with tx(g.ctx) as cur:
        get_lead(cur, lead_id)
        cur.execute("DELETE FROM mismatches WHERE id = %s AND lead_id = %s", (str(mismatch_id), str(lead_id)))
        activity.audit(cur, g.ctx.org_id, "remove_declaration_item", "lead", lead_id)
    return back(lead_id, "Declaration item removed.", "declaration")


# ── official documents ────────────────────────────────────────

@bp.route("/lead/<uuid:lead_id>/generate", methods=["POST"])
@login_required(*WORKERS)
def generate(lead_id):
    with tx(g.ctx) as cur:
        row = get_lead(cur, lead_id)
        keys = crypto.KeyRing(cur)
        lead_key = keys.get(row["key_id"])
        cur.execute("SELECT * FROM form_sessions WHERE lead_id = %s AND status = 'submitted' "
                    "ORDER BY submitted_at DESC LIMIT 1", (str(lead_id),))
        form = cur.fetchone()
        if not form:
            return back(lead_id, "The lead hasn't submitted the form yet.", "documents")
        answers = crypto.dec_json(keys.get(form["key_id"]), form["answers_enc"])
        lead_info = {"mobile_number": crypto.dec_text(lead_key, row["mobile_enc"]),
                     "email": crypto.dec_text(lead_key, row["email_enc"]), "name": crypto.dec_text(lead_key, row["name_enc"])}
        cur.execute("SELECT answers FROM field_visits WHERE lead_id = %s", (str(lead_id),))
        visit = (cur.fetchone() or {}).get("answers")
        cur.execute("SELECT * FROM mismatches WHERE lead_id = %s AND NOT resolved", (str(lead_id),))
        mismatches = [{**m, "value_a": crypto.dec_text(lead_key, m["value_a_enc"]),
                       "value_b": crypto.dec_text(lead_key, m["value_b_enc"])} for m in cur.fetchall()]
        cur.execute("SELECT storage_key, key_id FROM uploaded_documents WHERE form_session_id = %s "
                    "AND doc_type = 'photo' AND superseded_at IS NULL", (form["id"],))
        photo = cur.fetchone()
        photo_bytes = storage.get(photo["storage_key"], keys.get(photo["key_id"])) if photo else None
        cur.execute("SELECT COALESCE(max(version), 0) + 1 AS v FROM generated_documents WHERE lead_id = %s", (str(lead_id),))
        version = cur.fetchone()["v"]

    prefix = f"{str(lead_id)[:8]}_v{version}"
    made = []
    with tempfile.TemporaryDirectory(prefix="csp-gen-") as tmp:
        os.chmod(tmp, 0o700)
        photo_path = None
        if photo_bytes:
            photo_path = os.path.join(tmp, "photo.jpg")
            with open(photo_path, "wb") as f:
                f.write(photo_bytes)

        def out(kind, ext):
            return os.path.join(tmp, f"{prefix}_{kind}.{ext}")
        try:
            documents.fill_application_form(answers, lead_info, photo_path, out("application_form", "pdf"))
            made.append(("application_form", out("application_form", "pdf")))
            documents.fill_fvr(answers, lead_info, visit, out("field_verification_report", "pdf"))
            made.append(("field_verification_report", out("field_verification_report", "pdf")))
            if mismatches:
                documents.fill_declaration(answers, lead_info, mismatches, out("declaration", "pdf"))
                made.append(("declaration", out("declaration", "pdf")))
            documents.fill_agreement(answers, lead_info, out("agreement", "docx"))
            made.append(("agreement", out("agreement", "docx")))
            if documents.soffice_available():
                made.append(("agreement", documents.docx_to_pdf(out("agreement", "docx"))))
        except Exception as exc:
            return back(lead_id, f"Couldn't generate documents: {exc}", "documents")

        with tx(g.ctx) as cur:
            for kind, path in made:
                with open(path, "rb") as f:
                    storage_key, sha = storage.put(f.read(), lead_key)
                cur.execute(
                    """INSERT INTO generated_documents (org_id, lead_id, doc_type, version, filename, storage_key,
                                                        key_id, sha256, generated_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (g.ctx.org_id, str(lead_id), kind, version, os.path.basename(path), storage_key, row["key_id"],
                     sha, g.ctx.user_id),
                )
            cur.execute("UPDATE leads SET status = 'documents_generated' WHERE id = %s", (str(lead_id),))
            activity.event(cur, g.ctx.org_id, str(lead_id), "documents.generated", "user", g.ctx.user_id, {"version": version})
            activity.audit(cur, g.ctx.org_id, "generate_documents", "lead", lead_id, {"version": version})

    note = "" if visit else " The FVR's field-visit part is blank: save the field visit and generate again."
    return back(lead_id, f"Documents generated (version {version}).{note}", "documents")


@bp.route("/generated/<uuid:doc_id>")
@login_required(*WORKERS)
def generated_file(doc_id):
    with tx(g.ctx) as cur:
        cur.execute("SELECT * FROM generated_documents WHERE id = %s", (str(doc_id),))
        doc = cur.fetchone()
        if not doc:
            abort(404)
        data = storage.get(doc["storage_key"], crypto.KeyRing(cur).get(doc["key_id"]))
        activity.audit(cur, g.ctx.org_id, "download_document", "generated_document", doc_id, {"file": doc["filename"]})
    return send_file(io.BytesIO(data), as_attachment=True, download_name=doc["filename"])


@bp.route("/lead/<uuid:lead_id>/packet")
@login_required(*WORKERS)
def packet(lead_id):
    with tx(g.ctx) as cur:
        get_lead(cur, lead_id)
        keys = crypto.KeyRing(cur)
        generated = latest_generated(cur, lead_id)
        cur.execute("SELECT id FROM form_sessions WHERE lead_id = %s AND status = 'submitted' "
                    "ORDER BY submitted_at DESC LIMIT 1", (str(lead_id),))
        form = cur.fetchone()
        if not generated or not form:
            abort(404)
        cur.execute("SELECT doc_type, storage_key, key_id FROM uploaded_documents "
                    "WHERE form_session_id = %s AND superseded_at IS NULL", (form["id"],))
        uploaded = cur.fetchall()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for d in generated:
                z.writestr(f"forms/{d['filename']}", storage.get(d["storage_key"], keys.get(d["key_id"])))
            for u in uploaded:
                z.writestr(f"documents/{u['doc_type']}.jpg", storage.get(u["storage_key"], keys.get(u["key_id"])))
        activity.audit(cur, g.ctx.org_id, "download_packet", "lead", lead_id, {"version": generated[0]["version"]})
    buf.seek(0)
    name = f"{str(lead_id)[:8]}_ESAF_KYC_packet_v{generated[0]['version']}_{date.today():%Y%m%d}.zip"
    return send_file(buf, as_attachment=True, download_name=name, mimetype="application/zip")


# ── team & users (admin) ──────────────────────────────────────

@bp.route("/users")
@login_required("org_admin")
def users():
    with tx(g.ctx) as cur:
        cur.execute("""SELECT u.*, t.name AS team_name FROM users u LEFT JOIN teams t ON t.id = u.team_id
                       ORDER BY u.status = 'disabled', u.name""")
        rows = cur.fetchall()
        cur.execute("SELECT * FROM teams ORDER BY name")
        teams = cur.fetchall()
    return render_template("users.html", users=rows, teams=teams, roles=ROLE_LABELS, msg=request.args.get("msg"))


@bp.route("/users", methods=["POST"])
@login_required("org_admin")
def save_user():
    email = request.form.get("email", "").strip().lower()
    name = request.form.get("name", "").strip()[:200]
    role = request.form.get("role")
    team_id = request.form.get("team_id") or None
    status = request.form.get("status") or None
    user_id = request.form.get("user_id")
    if role not in ROLE_LABELS:
        abort(400)
    with tx(g.ctx) as cur:
        if user_id:
            if user_id == g.ctx.user_id and (role != "org_admin" or status == "disabled"):
                return redirect(url_for("dashboard.users", msg="You can't remove your own admin access."))
            cur.execute("UPDATE users SET role = %s, team_id = %s, status = COALESCE(%s, status) WHERE id = %s",
                        (role, team_id, status, user_id))
            if status == "disabled":
                cur.execute("UPDATE user_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (user_id,))
            activity.audit(cur, g.ctx.org_id, "update_user", "user", user_id, {"role": role, "status": status or ""})
            msg = "User updated."
        else:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not name:
                return redirect(url_for("dashboard.users", msg="Enter a name and a valid Google email."))
            cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return redirect(url_for("dashboard.users", msg="That email is already on the team."))
            cur.execute("INSERT INTO users (org_id, team_id, email, name, role, invited_by) VALUES (%s, %s, %s, %s, %s, %s)",
                        (g.ctx.org_id, team_id, email, name, role, g.ctx.user_id))
            activity.audit(cur, g.ctx.org_id, "invite_user", "user", email, {"role": role})
            msg = f"Invited {email}. They can now sign in with Google."
    return redirect(url_for("dashboard.users", msg=msg))


@bp.route("/teams", methods=["POST"])
@login_required("org_admin")
def add_team():
    name = request.form.get("name", "").strip()[:100]
    if name:
        with tx(g.ctx) as cur:
            cur.execute("INSERT INTO teams (org_id, name, region) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (g.ctx.org_id, name, request.form.get("region", "").strip()[:100] or None))
            activity.audit(cur, g.ctx.org_id, "create_team", "team", name)
    return redirect(url_for("dashboard.users", msg="Team saved."))
