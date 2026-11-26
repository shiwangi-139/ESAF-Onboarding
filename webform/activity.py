"""Event timeline, tamper-evident audit log, and RM alerts."""
import hashlib
import json
import logging
import threading
import urllib.parse
import urllib.request

from flask import g, has_request_context, request

import config
from db import Json

log = logging.getLogger(__name__)


def event(cur, org_id, lead_id, type_, actor_type="system", actor_id=None, payload=None):
    cur.execute(
        """INSERT INTO events (org_id, lead_id, actor_type, actor_id, type, payload)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (org_id, lead_id, actor_type, actor_id, type_, Json(payload or {})),
    )


def audit(cur, org_id, action, target_type=None, target_id=None, details=None, user_id=None):
    """Each row stores the hash of the previous row in its organisation, so edits or deletions break the chain."""
    if user_id is None and has_request_context():
        user = getattr(g, "user", None)
        user_id = user["id"] if user else None
    ip = request.remote_addr if has_request_context() else None
    ua = request.headers.get("User-Agent", "")[:300] if has_request_context() else None

    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"audit:{org_id}",))
    cur.execute("SELECT hash FROM audit_log WHERE org_id = %s ORDER BY id DESC LIMIT 1", (org_id,))
    row = cur.fetchone()
    prev = row["hash"] if row else ""
    body = json.dumps(
        [str(org_id), str(user_id or ""), action, target_type or "", str(target_id or ""), details or {}],
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = hashlib.sha256((prev + body).encode()).hexdigest()
    cur.execute(
        """INSERT INTO audit_log (org_id, user_id, action, target_type, target_id, ip, user_agent, details,
                                  prev_hash, hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (org_id, user_id, action, target_type, str(target_id) if target_id else None, ip, ua,
         Json(details or {}), prev or None, digest),
    )


def verify_audit_chain(cur, org_id):
    cur.execute(
        "SELECT * FROM audit_log WHERE org_id = %s ORDER BY id", (org_id,)
    )
    prev = ""
    for row in cur.fetchall():
        body = json.dumps(
            [str(row["org_id"]), str(row["user_id"] or ""), row["action"], row["target_type"] or "",
             str(row["target_id"] or ""), row["details"] or {}],
            sort_keys=True, ensure_ascii=False, default=str,
        )
        if (row["prev_hash"] or "") != prev or hashlib.sha256((prev + body).encode()).hexdigest() != row["hash"]:
            return row["id"]
        prev = row["hash"]
    return None


def alert(text):
    """Telegram alert to the RM/admin group. Never include names, numbers or documents, only IDs and statuses."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return
    threading.Thread(target=_send_telegram, args=(text,), daemon=True).start()


def _send_telegram(text):
    data = urllib.parse.urlencode(
        {"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage", data=data, timeout=10
        ).read()
    except Exception as exc:
        log.warning("Telegram alert failed: %s", exc)
