"""Local static server with clean Bible routes.

Serves the BiblicalInspiration/ folder and adds simple URL rewrites:
- /Book/            -> /Book/index.html
- /Book/<n>         -> /Book/Book<n>.html
- /Book/<n>/        -> same

Examples:
- http://localhost:8000/Mark/1
- http://localhost:8000/Matthew/21
- http://localhost:8000/Mark/ (book index)

Run:
  D:/Webdesign/neocities/.venv/Scripts/python.exe BiblicalInspiration/serve_biblical_inspiration.py

Optional:
  ... serve_biblical_inspiration.py --port 8080
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import socket
import posixpath
import re
import sqlite3
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from html import escape as html_escape
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR  # serve BiblicalInspiration/
TIMINGS_DIR = ROOT_DIR / ".timings"  # local-only persistence for verse start-times
APP_STATE_DIR = ROOT_DIR / ".app"  # local-only persistence for auth/admin
APP_DB_PATH = APP_STATE_DIR / "app.sqlite3"


_BOOK_CHAPTER_RE = re.compile(r"^/([A-Za-z0-9]+)/([0-9]+)(?:/)?$")


_DB_INIT_LOCK = threading.Lock()
_DB_INIT_DONE = False


def _utc_now_ts() -> int:
    return int(time.time())


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _is_emailish(s: str) -> bool:
    s = (s or "").strip()
    return "@" in s and "." in s.split("@", 1)[-1]


def _password_hash(password: str, *, salt: bytes) -> bytes:
    # NOTE: This is a local/dev server; parameters chosen for reasonable security.
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )


def _sha256_bytes(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _ensure_db() -> None:
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return

    with _DB_INIT_LOCK:
        if _DB_INIT_DONE:
            return
        APP_STATE_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(APP_DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL,
                  email_norm TEXT NOT NULL UNIQUE,
                  pass_salt BLOB NOT NULL,
                  pass_hash BLOB NOT NULL,
                  is_admin INTEGER NOT NULL DEFAULT 0,
                  disabled INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  token_hash BLOB NOT NULL UNIQUE,
                  created_at INTEGER NOT NULL,
                  last_seen_at INTEGER NOT NULL,
                  expires_at INTEGER NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  selector TEXT NOT NULL UNIQUE,
                  verifier_hash BLOB NOT NULL,
                  created_at INTEGER NOT NULL,
                  expires_at INTEGER NOT NULL,
                  used_at INTEGER,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
        _DB_INIT_DONE = True


def _db_connect() -> sqlite3.Connection:
    _ensure_db()
    conn = sqlite3.connect(APP_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _parse_cookies(header_value: str | None) -> dict[str, str]:
    if not header_value:
        return {}
    out: dict[str, str] = {}
    for part in header_value.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_form_urlencoded(raw: bytes) -> dict[str, str]:
    try:
        decoded = raw.decode("utf-8", errors="replace")
    except Exception:
        return {}
    pairs = urllib.parse.parse_qsl(decoded, keep_blank_values=True)
    out: dict[str, str] = {}
    for k, v in pairs:
        if k not in out:
            out[k] = v
    return out


def _same_origin_post(handler: "RewritingHandler") -> bool:
    # Basic CSRF mitigation: require Origin (or Referer) to match host.
    host = (handler.headers.get("Host") or "").strip()
    if not host:
        return False

    origin = (handler.headers.get("Origin") or "").strip()
    referer = (handler.headers.get("Referer") or "").strip()
    candidate = origin or referer
    if not candidate:
        # Some clients omit these; keep permissive for local dev.
        return True
    try:
        u = urllib.parse.urlparse(candidate)
    except Exception:
        return False
    return u.netloc == host


def _html_page(*, title: str, body_html: str) -> bytes:
    # Intentionally minimal styling; keep local + dependency-free.
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html_escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
    main {{ max-width: 720px; }}
    header {{ display: flex; gap: 12px; align-items: baseline; justify-content: space-between; }}
    a {{ color: inherit; }}
    form {{ display: grid; gap: 10px; margin: 14px 0; }}
    label {{ display: grid; gap: 6px; }}
    input[type=text], input[type=password] {{ padding: 8px 10px; font-size: 16px; }}
    button {{ padding: 10px 12px; font-size: 16px; cursor: pointer; }}
    .row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .muted {{ opacity: 0.8; }}
        .error {{ font-weight: 600; }}
        .ok {{ font-weight: 600; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid rgba(127,127,127,0.35); padding: 8px; text-align: left; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <main>
    {body_html}
  </main>
</body>
</html>"""
    return html.encode("utf-8")


def _session_cookie_header(token: str, *, max_age_seconds: int) -> str:
    # Secure isn't set because this is a local HTTP server.
    return f"bi_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age_seconds}"


def _clear_session_cookie_header() -> str:
    return "bi_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def _create_session(conn: sqlite3.Connection, *, user_id: int) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    now = _utc_now_ts()
    expires_at = now + 60 * 60 * 24 * 14  # 14 days
    conn.execute(
        "INSERT INTO sessions(user_id, token_hash, created_at, last_seen_at, expires_at) VALUES (?,?,?,?,?)",
        (user_id, _sha256_bytes(token), now, now, expires_at),
    )
    return token, expires_at


def _get_current_user(conn: sqlite3.Connection, *, handler: "RewritingHandler") -> sqlite3.Row | None:
    cookies = _parse_cookies(handler.headers.get("Cookie"))
    token = cookies.get("bi_session")
    if not token:
        return None
    now = _utc_now_ts()
    token_hash = _sha256_bytes(token)
    row = conn.execute(
        """
        SELECT s.id AS session_id, s.user_id, u.email, u.is_admin, u.disabled
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (token_hash, now),
    ).fetchone()
    if row is None:
        return None
    # Touch session for active users.
    conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (now, row["session_id"]))
    return row


def _redirect(handler: "RewritingHandler", location: str, *, status: int = 303) -> None:
    handler.send_response(status)
    handler.send_header("Location", location)
    handler.end_headers()


def _send_html(handler: "RewritingHandler", *, title: str, body_html: str, status: int = 200, extra_headers: list[tuple[str, str]] | None = None) -> None:
    raw = _html_page(title=title, body_html=body_html)
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    if extra_headers:
        for k, v in extra_headers:
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(raw)


def _app_nav(*, user: sqlite3.Row | None) -> str:
    if user is None:
        return "<div class='row'><a href='/'>Bible</a><span class='muted'>/</span><a href='/app/login'>Login</a><a href='/app/register'>Register</a></div>"
    admin_link = "" if not int(user["is_admin"]) else "<a href='/app/admin'>Admin</a>"
    return (
        "<div class='row'>"
        "<a href='/'>Bible</a>"
        "<span class='muted'>/</span>"
        "<a href='/app/account'>Account</a>"
        f"{admin_link}"
        "<a href='/app/logout'>Logout</a>"
        "</div>"
    )


class RewritingHandler(SimpleHTTPRequestHandler):
    # Python's handler serves from current working directory; we instead serve from ROOT_DIR.

    def _timing_cors_headers(self) -> list[tuple[str, str]]:
        # Allow phone tooling (and other origins) to call the timing API.
        origin = (self.headers.get("Origin") or "").strip()
        allow_origin = origin if origin else "*"
        headers: list[tuple[str, str]] = [
            ("Access-Control-Allow-Origin", allow_origin),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
        ]
        if origin:
            headers.append(("Vary", "Origin"))
        return headers

    def _send_json(self, obj: dict, *, status: int = 200, extra_headers: list[tuple[str, str]] | None = None) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/timing":
            self.send_response(204)
            for k, v in self._timing_cors_headers():
                self.send_header(k, v)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b"{}"
        try:
            decoded = body.decode("utf-8")
        except Exception:
            return None
        try:
            data = json.loads(decoded)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _timing_file_path(self, *, book_order: int, chapter: int) -> Path:
        return TIMINGS_DIR / f"{book_order:02d}" / f"{chapter:03d}.json"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/app" or parsed.path.startswith("/app/"):
            self._handle_app_get(parsed)
            return
        if parsed.path == "/api/timing":
            qs = urllib.parse.parse_qs(parsed.query or "")
            try:
                book_order = int((qs.get("bookOrder") or qs.get("book_order") or [""])[0])
                chapter = int((qs.get("chapter") or [""])[0])
            except Exception:
                self._send_json({"error": "bookOrder and chapter are required"}, status=400, extra_headers=self._timing_cors_headers())
                return

            if book_order < 1 or book_order > 66 or chapter < 1:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400, extra_headers=self._timing_cors_headers())
                return

            p = self._timing_file_path(book_order=book_order, chapter=chapter)
            if not p.exists():
                self._send_json({"ok": True, "times": None}, extra_headers=self._timing_cors_headers())
                return
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._send_json({"error": "timing file unreadable"}, status=500, extra_headers=self._timing_cors_headers())
                return

            if not isinstance(data, dict):
                self._send_json({"error": "timing file invalid"}, status=500, extra_headers=self._timing_cors_headers())
                return

            self._send_json({"ok": True, **data}, extra_headers=self._timing_cors_headers())
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/app/"):
            self._handle_app_post(parsed)
            return
        if parsed.path == "/api/timing":
            data = self._read_json_body()
            if data is None:
                self._send_json({"error": "invalid json"}, status=400, extra_headers=self._timing_cors_headers())
                return

            try:
                book_order = int(data.get("bookOrder") or data.get("book_order") or 0)
                chapter = int(data.get("chapter") or 0)
            except Exception:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400, extra_headers=self._timing_cors_headers())
                return

            times = data.get("times")
            if not isinstance(times, list) or not times:
                self._send_json({"error": "times must be a non-empty array"}, status=400, extra_headers=self._timing_cors_headers())
                return

            # Validate times are finite >= 0.
            cleaned: list[float] = []
            for t in times:
                try:
                    x = float(t)
                except Exception:
                    self._send_json({"error": "times must be numbers"}, status=400, extra_headers=self._timing_cors_headers())
                    return
                if not (x >= 0.0):
                    self._send_json({"error": "times must be >= 0"}, status=400, extra_headers=self._timing_cors_headers())
                    return
                cleaned.append(round(x, 3))

            if book_order < 1 or book_order > 66 or chapter < 1:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400, extra_headers=self._timing_cors_headers())
                return

            payload = {
                "bookOrder": book_order,
                "chapter": chapter,
                "verseCount": int(data.get("verseCount") or len(cleaned)),
                "audioDuration": data.get("audioDuration"),
                "times": cleaned,
            }

            # Optional derived ranges (client-derived). Keep if present.
            ranges = data.get("ranges")
            if isinstance(ranges, list):
                payload["ranges"] = ranges

            p = self._timing_file_path(book_order=book_order, chapter=chapter)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json({"ok": True, "saved": True}, extra_headers=self._timing_cors_headers())
            return

        self.send_error(404)
        return

    def _handle_app_get(self, parsed: urllib.parse.ParseResult) -> None:
        path = parsed.path
        with _db_connect() as conn:
            user = _get_current_user(conn, handler=self)
            if path == "/app":
                if user is None:
                    _redirect(self, "/app/login")
                else:
                    _redirect(self, "/app/account")
                return

            if path == "/app/login":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                body = (
                    "<header><h1>Login</h1>" + _app_nav(user=None) + "</header>"
                    "<form method='post' action='/app/login'>"
                    "<label>Email<input name='email' type='text' autocomplete='email' required></label>"
                    "<label>Password<input name='password' type='password' autocomplete='current-password' required></label>"
                    "<button type='submit'>Login</button>"
                    "</form>"
                    "<p class='muted'><a href='/app/reset'>Forgot password?</a></p>"
                )
                _send_html(self, title="Login", body_html=body)
                return

            if path == "/app/register":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                body = (
                    "<header><h1>Register</h1>" + _app_nav(user=None) + "</header>"
                    "<form method='post' action='/app/register'>"
                    "<label>Email<input name='email' type='text' autocomplete='email' required></label>"
                    "<label>Password<input name='password' type='password' autocomplete='new-password' required></label>"
                    "<button type='submit'>Create account</button>"
                    "</form>"
                    "<p class='muted'>This runs only on your local server.</p>"
                )
                _send_html(self, title="Register", body_html=body)
                return

            if path == "/app/logout":
                if user is not None:
                    cookies = _parse_cookies(self.headers.get("Cookie"))
                    token = cookies.get("bi_session")
                    if token:
                        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_sha256_bytes(token),))
                        conn.commit()
                self.send_response(303)
                self.send_header("Location", "/app/login")
                self.send_header("Set-Cookie", _clear_session_cookie_header())
                self.end_headers()
                return

            if path == "/app/account":
                if user is None:
                    _redirect(self, "/app/login")
                    return
                if int(user["disabled"]):
                    body = (
                        "<header><h1>Account disabled</h1>" + _app_nav(user=user) + "</header>"
                        "<p class='error'>This account is disabled. Contact an admin.</p>"
                    )
                    _send_html(self, title="Account", body_html=body)
                    return

                body = (
                    "<header><h1>Account</h1>" + _app_nav(user=user) + "</header>"
                    f"<p>Email: <strong>{html_escape(str(user['email']))}</strong></p>"
                    "<h2>Change password</h2>"
                    "<form method='post' action='/app/account/change-password'>"
                    "<label>Current password<input name='current_password' type='password' autocomplete='current-password' required></label>"
                    "<label>New password<input name='new_password' type='password' autocomplete='new-password' required></label>"
                    "<button type='submit'>Change password</button>"
                    "</form>"
                    "<h2>Delete account</h2>"
                    "<form method='post' action='/app/account/delete' onsubmit=\"return confirm('Delete your account? This cannot be undone.')\">"
                    "<label>Password<input name='password' type='password' autocomplete='current-password' required></label>"
                    "<button type='submit'>Delete my account</button>"
                    "</form>"
                )
                _send_html(self, title="Account", body_html=body)
                return

            if path == "/app/reset":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                body = (
                    "<header><h1>Reset password</h1>" + _app_nav(user=None) + "</header>"
                    "<form method='post' action='/app/reset'>"
                    "<label>Email<input name='email' type='text' autocomplete='email' required></label>"
                    "<button type='submit'>Create reset link (dev)</button>"
                    "</form>"
                    "<p class='muted'>In dev mode, the reset link is shown after submission.</p>"
                )
                _send_html(self, title="Reset password", body_html=body)
                return

            if path == "/app/reset/confirm":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                qs = urllib.parse.parse_qs(parsed.query or "")
                token = (qs.get("token") or [""])[0]
                body = (
                    "<header><h1>Set new password</h1>" + _app_nav(user=None) + "</header>"
                    "<form method='post' action='/app/reset/confirm'>"
                    f"<input type='hidden' name='token' value='{html_escape(token)}'>"
                    "<label>New password<input name='new_password' type='password' autocomplete='new-password' required></label>"
                    "<button type='submit'>Set password</button>"
                    "</form>"
                )
                _send_html(self, title="Confirm reset", body_html=body)
                return

            if path == "/app/admin":
                if user is None:
                    _redirect(self, "/app/login")
                    return
                if not int(user["is_admin"]):
                    _send_html(
                        self,
                        title="Admin",
                        status=403,
                        body_html="<header><h1>Forbidden</h1>" + _app_nav(user=user) + "</header><p class='error'>Admin access required.</p>",
                    )
                    return

                users = conn.execute(
                    "SELECT id, email, is_admin, disabled, created_at FROM users ORDER BY id ASC"
                ).fetchall()

                rows = []
                for u in users:
                    actions = (
                        f"<form method='post' action='/app/admin/toggle-disabled' style='margin:0'>"
                        f"<input type='hidden' name='user_id' value='{u['id']}'>"
                        f"<input type='hidden' name='disabled' value='{0 if int(u['disabled']) else 1}'>"
                        f"<button type='submit'>{'Enable' if int(u['disabled']) else 'Disable'}</button>"
                        "</form>"
                        f"<form method='post' action='/app/admin/toggle-admin' style='margin:0'>"
                        f"<input type='hidden' name='user_id' value='{u['id']}'>"
                        f"<input type='hidden' name='is_admin' value='{0 if int(u['is_admin']) else 1}'>"
                        f"<button type='submit'>{'Revoke admin' if int(u['is_admin']) else 'Make admin'}</button>"
                        "</form>"
                        f"<form method='post' action='/app/admin/create-reset' style='margin:0'>"
                        f"<input type='hidden' name='user_id' value='{u['id']}'>"
                        "<button type='submit'>Create reset link</button>"
                        "</form>"
                        f"<form method='post' action='/app/admin/delete-user' style='margin:0' onsubmit=\"return confirm('Delete this user?')\">"
                        f"<input type='hidden' name='user_id' value='{u['id']}'>"
                        "<button type='submit'>Delete</button>"
                        "</form>"
                    )
                    rows.append(
                        "<tr>"
                        f"<td>{u['id']}</td>"
                        f"<td>{html_escape(str(u['email']))}</td>"
                        f"<td>{'yes' if int(u['is_admin']) else 'no'}</td>"
                        f"<td>{'yes' if int(u['disabled']) else 'no'}</td>"
                        f"<td><div class='row'>{actions}</div></td>"
                        "</tr>"
                    )

                msg = ""
                qs = urllib.parse.parse_qs(parsed.query or "")
                flash = (qs.get("msg") or [""])[0]
                if flash:
                    msg = f"<p class='ok'>{html_escape(flash)}</p>"

                body = (
                    "<header><h1>Admin</h1>" + _app_nav(user=user) + "</header>"
                    + msg
                    + "<h2>Create user</h2>"
                    + "<form method='post' action='/app/admin/create-user'>"
                    + "<label>Email<input name='email' type='text' autocomplete='off' required></label>"
                    + "<label>Temporary password<input name='password' type='password' autocomplete='new-password' required></label>"
                    + "<label><input name='is_admin' type='checkbox' value='1'> Make admin</label>"
                    + "<button type='submit'>Create</button>"
                    + "</form>"
                    + "<h2>Users</h2>"
                    + "<table><thead><tr><th>ID</th><th>Email</th><th>Admin</th><th>Disabled</th><th>Actions</th></tr></thead>"
                    + "<tbody>"
                    + "".join(rows)
                    + "</tbody></table>"
                )
                _send_html(self, title="Admin", body_html=body)
                return

        _send_html(self, title="Not Found", status=404, body_html="<h1>Not Found</h1><p class='muted'>Unknown /app route.</p>")

    def _handle_app_post(self, parsed: urllib.parse.ParseResult) -> None:
        if not _same_origin_post(self):
            _send_html(self, title="Bad Request", status=400, body_html="<h1>Bad Request</h1><p class='error'>Origin check failed.</p>")
            return

        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        form = _parse_form_urlencoded(raw)

        with _db_connect() as conn:
            user = _get_current_user(conn, handler=self)
            path = parsed.path
            now = _utc_now_ts()

            if path == "/app/login":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                email = _normalize_email(form.get("email") or "")
                password = form.get("password") or ""
                if not _is_emailish(email) or not password:
                    _send_html(self, title="Login", status=400, body_html="<h1>Login</h1><p class='error'>Invalid email or password.</p><p><a href='/app/login'>Back</a></p>")
                    return

                row = conn.execute(
                    "SELECT id, email, pass_salt, pass_hash, disabled FROM users WHERE email_norm=?",
                    (email,),
                ).fetchone()
                if row is None:
                    _send_html(self, title="Login", status=400, body_html="<h1>Login</h1><p class='error'>Invalid email or password.</p><p><a href='/app/login'>Back</a></p>")
                    return
                if int(row["disabled"]):
                    _send_html(self, title="Login", status=403, body_html="<h1>Login</h1><p class='error'>This account is disabled.</p><p><a href='/app/login'>Back</a></p>")
                    return

                calc = _password_hash(password, salt=bytes(row["pass_salt"]))
                if not hmac.compare_digest(calc, bytes(row["pass_hash"])):
                    _send_html(self, title="Login", status=400, body_html="<h1>Login</h1><p class='error'>Invalid email or password.</p><p><a href='/app/login'>Back</a></p>")
                    return

                token, expires_at = _create_session(conn, user_id=int(row["id"]))
                conn.commit()
                self.send_response(303)
                self.send_header("Location", "/app/account")
                self.send_header("Set-Cookie", _session_cookie_header(token, max_age_seconds=expires_at - now))
                self.end_headers()
                return

            if path == "/app/register":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                email = _normalize_email(form.get("email") or "")
                password = form.get("password") or ""
                if not _is_emailish(email) or len(password) < 8:
                    _send_html(self, title="Register", status=400, body_html="<h1>Register</h1><p class='error'>Use a valid email and a password of at least 8 characters.</p><p><a href='/app/register'>Back</a></p>")
                    return

                # Bootstrap: first user becomes admin.
                existing = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
                is_admin = 1 if int(existing) == 0 else 0
                salt = secrets.token_bytes(16)
                pwh = _password_hash(password, salt=salt)
                try:
                    conn.execute(
                        "INSERT INTO users(email, email_norm, pass_salt, pass_hash, is_admin, disabled, created_at) VALUES (?,?,?,?,?,?,?)",
                        (email, email, salt, pwh, is_admin, 0, now),
                    )
                except sqlite3.IntegrityError:
                    _send_html(self, title="Register", status=400, body_html="<h1>Register</h1><p class='error'>That email is already registered.</p><p><a href='/app/register'>Back</a></p>")
                    return

                user_id = int(conn.execute("SELECT id FROM users WHERE email_norm=?", (email,)).fetchone()["id"])
                token, expires_at = _create_session(conn, user_id=user_id)
                conn.commit()
                self.send_response(303)
                self.send_header("Location", "/app/account")
                self.send_header("Set-Cookie", _session_cookie_header(token, max_age_seconds=expires_at - now))
                self.end_headers()
                return

            if path == "/app/account/change-password":
                if user is None:
                    _redirect(self, "/app/login")
                    return
                if int(user["disabled"]):
                    _send_html(self, title="Account", status=403, body_html="<h1>Account</h1><p class='error'>Account disabled.</p>")
                    return
                current_password = form.get("current_password") or ""
                new_password = form.get("new_password") or ""
                if len(new_password) < 8:
                    _send_html(self, title="Account", status=400, body_html="<h1>Account</h1><p class='error'>New password must be at least 8 characters.</p><p><a href='/app/account'>Back</a></p>")
                    return
                row = conn.execute(
                    "SELECT pass_salt, pass_hash FROM users WHERE id=?",
                    (int(user["user_id"]),),
                ).fetchone()
                if row is None:
                    _redirect(self, "/app/logout")
                    return
                calc = _password_hash(current_password, salt=bytes(row["pass_salt"]))
                if not hmac.compare_digest(calc, bytes(row["pass_hash"])):
                    _send_html(self, title="Account", status=400, body_html="<h1>Account</h1><p class='error'>Current password is incorrect.</p><p><a href='/app/account'>Back</a></p>")
                    return
                salt = secrets.token_bytes(16)
                pwh = _password_hash(new_password, salt=salt)
                conn.execute(
                    "UPDATE users SET pass_salt=?, pass_hash=? WHERE id=?",
                    (salt, pwh, int(user["user_id"])),
                )
                conn.commit()
                _redirect(self, "/app/account")
                return

            if path == "/app/account/delete":
                if user is None:
                    _redirect(self, "/app/login")
                    return
                password = form.get("password") or ""
                row = conn.execute(
                    "SELECT pass_salt, pass_hash FROM users WHERE id=?",
                    (int(user["user_id"]),),
                ).fetchone()
                if row is None:
                    _redirect(self, "/app/logout")
                    return
                calc = _password_hash(password, salt=bytes(row["pass_salt"]))
                if not hmac.compare_digest(calc, bytes(row["pass_hash"])):
                    _send_html(self, title="Account", status=400, body_html="<h1>Account</h1><p class='error'>Password is incorrect.</p><p><a href='/app/account'>Back</a></p>")
                    return
                # Hard delete user + cascades.
                conn.execute("DELETE FROM users WHERE id=?", (int(user["user_id"]),))
                conn.commit()
                self.send_response(303)
                self.send_header("Location", "/app/register")
                self.send_header("Set-Cookie", _clear_session_cookie_header())
                self.end_headers()
                return

            if path == "/app/reset":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                email = _normalize_email(form.get("email") or "")
                # Avoid leaking existence; message is generic either way.
                row = conn.execute("SELECT id FROM users WHERE email_norm=? AND disabled=0", (email,)).fetchone()
                if row is None:
                    _send_html(
                        self,
                        title="Reset password",
                        body_html="<h1>Reset password</h1><p class='ok'>If the account exists, a reset link has been created.</p><p><a href='/app/login'>Back to login</a></p>",
                    )
                    return
                user_id = int(row["id"])
                selector = secrets.token_urlsafe(9)
                verifier = secrets.token_urlsafe(24)
                verifier_hash = _sha256_bytes(verifier)
                expires_at = now + 60 * 60  # 1 hour
                conn.execute(
                    "INSERT INTO password_reset_tokens(user_id, selector, verifier_hash, created_at, expires_at, used_at) VALUES (?,?,?,?,?,NULL)",
                    (user_id, selector, verifier_hash, now, expires_at),
                )
                conn.commit()
                token = f"{selector}.{verifier}"
                link = f"/app/reset/confirm?token={urllib.parse.quote(token)}"
                _send_html(
                    self,
                    title="Reset password",
                    body_html=(
                        "<h1>Reset password</h1>"
                        "<p class='ok'>Reset link created (dev).</p>"
                        f"<p><a href='{html_escape(link)}'>Click here to reset your password</a></p>"
                        f"<p class='muted'>Token: <code>{html_escape(token)}</code></p>"
                        "<p><a href='/app/login'>Back to login</a></p>"
                    ),
                )
                return

            if path == "/app/reset/confirm":
                if user is not None:
                    _redirect(self, "/app/account")
                    return
                token = (form.get("token") or "").strip()
                new_password = form.get("new_password") or ""
                if len(new_password) < 8:
                    _send_html(self, title="Confirm reset", status=400, body_html="<h1>Set new password</h1><p class='error'>Password must be at least 8 characters.</p>")
                    return
                if "." not in token:
                    _send_html(self, title="Confirm reset", status=400, body_html="<h1>Set new password</h1><p class='error'>Invalid token.</p>")
                    return
                selector, verifier = token.split(".", 1)
                row = conn.execute(
                    "SELECT id, user_id, verifier_hash, expires_at, used_at FROM password_reset_tokens WHERE selector=?",
                    (selector,),
                ).fetchone()
                if row is None or row["used_at"] is not None or int(row["expires_at"]) <= now:
                    _send_html(self, title="Confirm reset", status=400, body_html="<h1>Set new password</h1><p class='error'>Token expired or already used.</p>")
                    return
                if not hmac.compare_digest(_sha256_bytes(verifier), bytes(row["verifier_hash"])):
                    _send_html(self, title="Confirm reset", status=400, body_html="<h1>Set new password</h1><p class='error'>Invalid token.</p>")
                    return
                salt = secrets.token_bytes(16)
                pwh = _password_hash(new_password, salt=salt)
                conn.execute(
                    "UPDATE users SET pass_salt=?, pass_hash=? WHERE id=?",
                    (salt, pwh, int(row["user_id"])),
                )
                conn.execute(
                    "UPDATE password_reset_tokens SET used_at=? WHERE id=?",
                    (now, int(row["id"])),
                )
                # Revoke all sessions for that user.
                conn.execute("DELETE FROM sessions WHERE user_id=?", (int(row["user_id"]),))
                conn.commit()
                _send_html(
                    self,
                    title="Password reset",
                    body_html="<h1>Password updated</h1><p class='ok'>You can now log in with your new password.</p><p><a href='/app/login'>Login</a></p>",
                )
                return

            if path.startswith("/app/admin/"):
                if user is None:
                    _redirect(self, "/app/login")
                    return
                if not int(user["is_admin"]):
                    _send_html(self, title="Admin", status=403, body_html="<h1>Forbidden</h1><p class='error'>Admin access required.</p>")
                    return

                if path == "/app/admin/create-user":
                    email = _normalize_email(form.get("email") or "")
                    password = form.get("password") or ""
                    is_admin = 1 if (form.get("is_admin") == "1") else 0
                    if not _is_emailish(email) or len(password) < 8:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Invalid email or password too short"))
                        return
                    salt = secrets.token_bytes(16)
                    pwh = _password_hash(password, salt=salt)
                    try:
                        conn.execute(
                            "INSERT INTO users(email, email_norm, pass_salt, pass_hash, is_admin, disabled, created_at) VALUES (?,?,?,?,?,?,?)",
                            (email, email, salt, pwh, is_admin, 0, now),
                        )
                        conn.commit()
                    except sqlite3.IntegrityError:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Email already exists"))
                        return
                    _redirect(self, "/app/admin?msg=" + urllib.parse.quote("User created"))
                    return

                if path == "/app/admin/toggle-disabled":
                    try:
                        user_id = int(form.get("user_id") or "0")
                        disabled = 1 if int(form.get("disabled") or "0") else 0
                    except Exception:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Invalid request"))
                        return
                    conn.execute("UPDATE users SET disabled=? WHERE id=?", (disabled, user_id))
                    conn.commit()
                    _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Updated"))
                    return

                if path == "/app/admin/toggle-admin":
                    try:
                        user_id = int(form.get("user_id") or "0")
                        is_admin = 1 if int(form.get("is_admin") or "0") else 0
                    except Exception:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Invalid request"))
                        return
                    # Prevent removing admin from the last admin account.
                    if is_admin == 0:
                        n_admin = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin=1").fetchone()["n"]
                        is_current_admin = conn.execute(
                            "SELECT is_admin FROM users WHERE id=?",
                            (user_id,),
                        ).fetchone()
                        if is_current_admin is not None and int(is_current_admin["is_admin"]) == 1 and int(n_admin) <= 1:
                            _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Cannot remove the last admin"))
                            return
                    conn.execute("UPDATE users SET is_admin=? WHERE id=?", (is_admin, user_id))
                    conn.commit()
                    _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Updated"))
                    return

                if path == "/app/admin/create-reset":
                    try:
                        target_user_id = int(form.get("user_id") or "0")
                    except Exception:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Invalid request"))
                        return
                    row = conn.execute("SELECT id FROM users WHERE id=?", (target_user_id,)).fetchone()
                    if row is None:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("User not found"))
                        return
                    selector = secrets.token_urlsafe(9)
                    verifier = secrets.token_urlsafe(24)
                    verifier_hash = _sha256_bytes(verifier)
                    expires_at = now + 60 * 60
                    conn.execute(
                        "INSERT INTO password_reset_tokens(user_id, selector, verifier_hash, created_at, expires_at, used_at) VALUES (?,?,?,?,?,NULL)",
                        (target_user_id, selector, verifier_hash, now, expires_at),
                    )
                    conn.commit()
                    token = f"{selector}.{verifier}"
                    _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Reset token (dev): " + token))
                    return

                if path == "/app/admin/delete-user":
                    try:
                        target_user_id = int(form.get("user_id") or "0")
                    except Exception:
                        _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Invalid request"))
                        return
                    # Prevent deleting the last admin.
                    target = conn.execute(
                        "SELECT is_admin FROM users WHERE id=?",
                        (target_user_id,),
                    ).fetchone()
                    if target is not None and int(target["is_admin"]) == 1:
                        n_admin = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin=1").fetchone()["n"]
                        if int(n_admin) <= 1:
                            _redirect(self, "/app/admin?msg=" + urllib.parse.quote("Cannot delete the last admin"))
                            return
                    conn.execute("DELETE FROM users WHERE id=?", (target_user_id,))
                    conn.commit()
                    _redirect(self, "/app/admin?msg=" + urllib.parse.quote("User deleted"))
                    return

            _send_html(self, title="Not Found", status=404, body_html="<h1>Not Found</h1><p class='muted'>Unknown POST route.</p>")
            return

    def translate_path(self, path: str) -> str:
        # Apply our rewrite rules first.
        rewritten = self._rewrite_path(path)
        # Then translate to filesystem path under ROOT_DIR.
        parsed = urllib.parse.urlparse(rewritten)
        clean = posixpath.normpath(urllib.parse.unquote(parsed.path))
        clean = clean.lstrip("/")

        # Prevent escaping the root.
        full = (ROOT_DIR / clean).resolve()
        if ROOT_DIR not in full.parents and full != ROOT_DIR:
            return str(ROOT_DIR)
        return str(full)

    def _rewrite_path(self, path: str) -> str:
        parsed = urllib.parse.urlparse(path)
        p = parsed.path or "/"

        # /Book/<n> -> /Book/Book<n>.html
        m = _BOOK_CHAPTER_RE.match(p)
        if m:
            book = m.group(1)
            chapter = int(m.group(2))
            new_path = f"/{book}/{book}{chapter}.html"
            return urllib.parse.urlunparse(parsed._replace(path=new_path))

        # /Book or /Book/ -> /Book/index.html
        if p != "/" and p.count("/") <= 2:
            # normalize /Book (no trailing slash)
            if not p.endswith("/"):
                # Only rewrite if there is no extension.
                if "." not in p.split("/")[-1]:
                    new_path = p + "/index.html"
                    return urllib.parse.urlunparse(parsed._replace(path=new_path))
            else:
                new_path = p + "index.html"
                return urllib.parse.urlunparse(parsed._replace(path=new_path))

        return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), RewritingHandler)
    print(f"Serving {ROOT_DIR} at http://{args.host}:{args.port}/")
    if args.host == "0.0.0.0":
        try:
            ips = sorted({ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if ip and not ip.startswith("127.")})
        except Exception:
            ips = []
        if ips:
            print("LAN URLs:")
            for ip in ips:
                print(f"  http://{ip}:{args.port}/")
        else:
            print("LAN URL: http://<your-pc-ip>:{}/".format(args.port))
    print("Example: /Mark/1  /Matthew/21  /Mark/")
    print("Timing API: /api/timing (GET/POST)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
