"""Single-administrator HTTPS sessions and operational routes."""
from collections import deque
from contextlib import closing
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
from threading import Lock
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import config, db
from .api import now, ok

router = APIRouter(prefix="/api/admin", tags=["admin"])
COOKIE = "__Host-jianzhou-admin"
SESSION_SECONDS = 8 * 60 * 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/healthz", "/admin", "/api/admin/login", "/api/admin/session"}
logger = logging.getLogger(__name__)


def web_origin() -> str:
    origin = (os.environ.get("JIANZHOU_WEB_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        raise RuntimeError("JIANZHOU_WEB_ORIGIN must be a single HTTPS origin")
    return origin


def _password() -> str:
    return os.environ.get("JIANZHOU_ADMIN_PASSWORD", "")


def _digest(token: str) -> str:
    return hmac.new(_password().encode(), token.encode(), hashlib.sha256).hexdigest()


def _session(request: Request) -> str | None:
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) != 43 or len(_password()) < 16:
        return None
    digest = _digest(token)
    row = db.query_one("SELECT expires FROM web_sessions WHERE token_digest=? AND expires>?", (digest, int(time.time())))
    return digest if row else None


def _audit(method: str, route: str, status: int) -> None:
    try:
        db.execute("INSERT INTO web_audit(occurred_at, method, route, status) VALUES(?,?,?,?)", (now(), method, route, status))
    except sqlite3.Error:
        logger.error("Could not record administrator operation on %s", route)


def _denied(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"success": False, "error": {"code": code, "message": message}}, status_code=status, headers={"Cache-Control": "no-store"})


def _is_public(request: Request) -> bool:
    path = request.url.path
    if path == "/api/admin/login":
        return request.method == "POST"
    return request.method in {"GET", "HEAD"} and (path in PUBLIC_PATHS or path.startswith("/assets/"))


def _trusted_write_origin(request: Request, origin: str) -> bool:
    headers = request.headers
    if headers.get("origin") == origin:
        return True
    # Codespaces rewrites the browser Origin to the local forwarding target.
    # Require the original HTTPS host and same-origin browser metadata.
    return (
        config.BUILD_PROFILE == "codespaces"
        and os.environ.get("CODESPACES") == "true"
        and headers.get("origin") in {"http://localhost:8741", "http://127.0.0.1:8741"}
        and headers.get("host") == urlsplit(origin).netloc
        and headers.get("sec-fetch-site") == "same-origin"
        and headers.get("referer", "").startswith(origin + "/")
    )


async def authorize(request: Request, call_next, origin: str):
    path = request.url.path
    mutating = request.method not in SAFE_METHODS
    if mutating and not _trusted_write_origin(request, origin):
        return _denied("ORIGIN_NOT_ALLOWED", "请从工作台页面发起操作。", 403)
    if not _is_public(request):
        request.state.admin = _session(request)
        if not request.state.admin:
            if path == "/" and request.method == "GET":
                return RedirectResponse("/admin?next=workbench", status_code=303, headers={"Cache-Control": "no-store"})
            return _denied("ADMIN_REQUIRED", "请登录后继续。", 401)
    response = await call_next(request)
    if not path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store"
    if mutating and getattr(request.state, "admin", None):
        route = getattr(request.scope.get("route"), "path", None)
        if route and path.startswith("/api/"):
            _audit(request.method, route if route.startswith("/api/") else "/api" + route,
                   response.status_code)
    return response


async def hide_validation_input(request: Request, exc: RequestValidationError):
    return _denied("VALIDATION_FAILED", "请检查必填字段和输入格式。", 422)


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


_attempts = deque()
_attempt_lock = Lock()


@router.get("/session")
def session_status(request: Request):
    return ok({"authenticated": bool(_session(request)), "configured": 16 <= len(_password()) <= 512})


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    password = _password()
    if len(password) < 16:
        return _denied("ADMIN_SETUP_REQUIRED", "请先在云端设置至少 16 位的管理员密码。", 503)
    stamp = time.monotonic()
    with _attempt_lock:
        while _attempts and _attempts[0] <= stamp - 60:
            _attempts.popleft()
        if len(_attempts) >= 8:
            return _denied("ADMIN_RATE_LIMIT", "尝试次数过多，请稍后重试。", 429)
        expected = hashlib.sha256(password.encode()).digest()
        actual = hashlib.sha256(body.password.encode()).digest()
        if not secrets.compare_digest(expected, actual):
            _attempts.append(stamp)
            _audit("POST", "/api/admin/login", 401)
            return _denied("ADMIN_LOGIN_FAILED", "管理员密码不正确。", 401)
        _attempts.clear()
    token = secrets.token_urlsafe(32)
    timestamp = int(time.time())
    with db.transaction():
        db.execute("DELETE FROM web_sessions WHERE expires<=? OR token_digest=?", (timestamp, _session(request) or ""))
        db.execute("INSERT INTO web_sessions(token_digest, expires) VALUES(?,?)", (_digest(token), timestamp + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, path="/", secure=True, httponly=True, samesite="strict")
    _audit("POST", "/api/admin/login", 200)
    return ok({"authenticated": True})


@router.post("/logout")
def logout(request: Request, response: Response):
    db.execute("DELETE FROM web_sessions WHERE token_digest=?", (request.state.admin,))
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return ok({"authenticated": False})


@router.get("/operations")
def operations():
    return ok({
        "audit": db.query("SELECT occurred_at, method, route, status FROM web_audit ORDER BY id DESC LIMIT 50"),
        "errors": db.query("SELECT ts, code, stage, provider, trace_id FROM error_logs ORDER BY ts DESC LIMIT 30"),
        "encrypted_keys": bool(os.environ.get("JIANZHOU_SECRET_KEY")),
    })


@router.post("/backup")
def download_backup():
    """Export a consistent database snapshot without active sessions."""
    workspace = tempfile.TemporaryDirectory(prefix="jianzhou-export-")
    path = Path(workspace.name) / "jianzhou-backup.db"
    try:
        with closing(sqlite3.connect(path)) as target:
            db.connect().backup(target)
            target.execute("DELETE FROM web_sessions")
            target.commit()
    except Exception:
        workspace.cleanup()
        raise
    return FileResponse(path, filename=path.name, media_type="application/octet-stream", background=BackgroundTask(workspace.cleanup))
