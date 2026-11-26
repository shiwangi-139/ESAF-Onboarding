"""RM sign-in with Google (invite-only), server-side sessions, CSRF tokens and role checks."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

import activity
import config
from db import SYSTEM, Ctx, tx

bp = Blueprint("auth", __name__, url_prefix="/auth")
oauth = OAuth()
SESSION_COOKIE = "csp_rm"
ROLE_LABELS = {
    "org_admin": "Admin", "rm_manager": "RM manager", "rm": "RM", "compliance_viewer": "Compliance (read-only)",
}


def init_app(app):
    oauth.init_app(app)
    if config.GOOGLE_CLIENT_ID:
        oauth.register(
            "google",
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
        )
    app.register_blueprint(bp)
    app.jinja_env.globals.update(csrf_token=csrf_token, role_label=lambda r: ROLE_LABELS.get(r, r))


def _hash(token):
    return hashlib.sha256(token.encode()).digest()


def now():
    return datetime.now(timezone.utc)


# ── session handling ──────────────────────────────────────────

def load_user():
    """Sets g.user and g.ctx from the session cookie, or leaves them as None."""
    g.user, g.ctx, g.session_token = None, None, None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return
    with tx(SYSTEM) as cur:
        cur.execute(
            """SELECT s.id AS session_id, s.expires_at, s.last_seen_at, s.revoked_at,
                      u.id, u.org_id, u.team_id, u.email, u.name, u.role, u.status
               FROM user_sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = %s""",
            (_hash(token),),
        )
        row = cur.fetchone()
        if not row or row["revoked_at"] or row["status"] != "active":
            return
        t = now()
        if row["expires_at"] < t or row["last_seen_at"] < t - timedelta(minutes=config.SESSION_IDLE_MINUTES):
            cur.execute("UPDATE user_sessions SET revoked_at = now() WHERE id = %s", (row["session_id"],))
            return
        if row["last_seen_at"] < t - timedelta(minutes=1):
            cur.execute("UPDATE user_sessions SET last_seen_at = now() WHERE id = %s", (row["session_id"],))
    g.user = row
    g.ctx = Ctx(role=row["role"], org_id=str(row["org_id"]), user_id=str(row["id"]))
    g.session_token = token


def _start_session(user, response):
    token = secrets.token_urlsafe(32)
    with tx(SYSTEM) as cur:
        cur.execute(
            """INSERT INTO user_sessions (org_id, user_id, token_hash, ip, user_agent, expires_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (user["org_id"], user["id"], _hash(token), request.remote_addr,
             request.headers.get("User-Agent", "")[:300], now() + timedelta(hours=config.SESSION_HOURS)),
        )
        cur.execute(
            "UPDATE users SET status = 'active', last_login_at = now() WHERE id = %s", (user["id"],)
        )
        activity.audit(cur, user["org_id"], "login", "user", user["id"], user_id=user["id"])
    response.set_cookie(SESSION_COOKIE, token, max_age=config.SESSION_HOURS * 3600, httponly=True,
                        secure=not config.IS_DEV, samesite="Lax")
    return response


def csrf_token():
    if not getattr(g, "session_token", None):
        return ""
    return hmac.new(config.SECRET_KEY.encode(), b"csrf:" + _hash(g.session_token), "sha256").hexdigest()


def check_csrf():
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, csrf_token()):
        abort(400, "Invalid or missing CSRF token. Reload the page and try again.")


def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.get("user"):
                return redirect(url_for("auth.login", next=request.full_path))
            if roles and g.user["role"] not in roles:
                abort(403)
            if request.method == "POST":
                check_csrf()
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ── sign-in routes ────────────────────────────────────────────

def _find_invited_user(email):
    with tx(SYSTEM) as cur:
        cur.execute(
            """SELECT u.*, o.allowed_google_domain FROM users u JOIN organizations o ON o.id = u.org_id
               WHERE u.email = %s AND u.status <> 'disabled' AND o.status = 'active'""",
            (email.lower(),),
        )
        return cur.fetchone()


def _deny(email, reason):
    with tx(SYSTEM) as cur:
        cur.execute("SELECT id FROM organizations ORDER BY created_at LIMIT 1")
        org = cur.fetchone()
        if org:
            activity.audit(cur, org["id"], "login_denied", "email", email, {"reason": reason})
    activity.alert(f"⚠️ Sign-in refused for an uninvited/blocked account ({reason}).")
    return render_template("login.html", error="This Google account doesn't have access. Ask your admin to invite you."), 403


def _safe_next():
    target = request.args.get("next") or request.cookies.get("csp_next") or ""
    return target if target.startswith("/dashboard") else url_for("dashboard.index")


@bp.route("/login")
def login():
    return render_template("login.html", google_enabled=bool(config.GOOGLE_CLIENT_ID),
                           dev_login=config.DEV_LOGIN_ENABLED and request.remote_addr in ("127.0.0.1", "::1"),
                           next=request.args.get("next", ""))


@bp.route("/google")
def google_start():
    if not config.GOOGLE_CLIENT_ID:
        abort(404)
    resp = oauth.google.authorize_redirect(url_for("auth.google_callback", _external=True), prompt="select_account")
    nxt = request.args.get("next", "")
    if nxt.startswith("/dashboard"):
        resp.set_cookie("csp_next", nxt, max_age=600, httponly=True, secure=not config.IS_DEV, samesite="Lax")
    return resp


@bp.route("/google/callback")
def google_callback():
    if not config.GOOGLE_CLIENT_ID:
        abort(404)
    token = oauth.google.authorize_access_token()  # verifies state, nonce and the ID token signature
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        return _deny(email or "unknown", "email not verified")
    user = _find_invited_user(email)
    if not user:
        return _deny(email, "not invited")
    domain = user["allowed_google_domain"]
    if domain and info.get("hd") != domain:
        return _deny(email, "wrong Google Workspace domain")
    if user["google_sub"] and user["google_sub"] != info.get("sub"):
        return _deny(email, "Google account mismatch")
    if not user["google_sub"]:
        with tx(SYSTEM) as cur:
            cur.execute("UPDATE users SET google_sub = %s WHERE id = %s", (info["sub"], user["id"]))
    resp = redirect(_safe_next())
    resp.delete_cookie("csp_next")
    return _start_session(user, resp)


@bp.route("/dev-login", methods=["POST"])
def dev_login():
    """Local testing only: APP_ENV=development, DEV_LOGIN=1, and the request must come from this machine."""
    if not config.DEV_LOGIN_ENABLED or request.remote_addr not in ("127.0.0.1", "::1"):
        abort(404)
    user = _find_invited_user(request.form.get("email", ""))
    if not user:
        return _deny(request.form.get("email", ""), "not invited (dev login)")
    return _start_session(user, redirect(_safe_next()))


@bp.route("/logout", methods=["POST"])
def logout():
    if g.get("user"):
        check_csrf()
        with tx(SYSTEM) as cur:
            cur.execute("UPDATE user_sessions SET revoked_at = now() WHERE token_hash = %s", (_hash(g.session_token),))
            activity.audit(cur, g.user["org_id"], "logout", "user", g.user["id"])
    resp = redirect(url_for("auth.login"))
    resp.delete_cookie(SESSION_COOKIE)
    return resp
