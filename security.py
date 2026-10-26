"""CSRF, sesión/roles, anti fuerza bruta, cabeceras y subida segura de documentos."""
from __future__ import annotations

import hmac
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import abort, current_app, g, redirect, request, session, url_for

from db import get_db
from models import User


# --- Sesión y roles -------------------------------------------------------------------
def home_for(user: User) -> str:
    return url_for({"client": "client.dashboard", "transporter": "transporter.dashboard", "admin": "admin.dashboard"}[user.role])


def login_required(*roles: str):
    """@login_required() = cualquier usuario logueado; @login_required("client", "admin") = solo esos roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.index"))
            if roles and g.user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def start_session(user: User) -> None:
    session.clear()  # evita fijación de sesión
    session["user_id"] = user.id
    session.permanent = True


# --- CSRF -----------------------------------------------------------------------------
def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _csrf_protect():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("_csrf", "")
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, description="La sesión expiró o el formulario no es válido. Volvé a intentarlo.")


def _load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        user = get_db().get(User, uid)
        if user and user.is_active:
            g.user = user
        else:
            session.clear()


def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if g.get("user") is not None:
        response.headers.setdefault("Cache-Control", "no-store")  # no cachear pantallas con datos personales
    return response


def init_security(app) -> None:
    app.before_request(_load_user)
    app.before_request(_csrf_protect)
    app.after_request(_security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token


# --- Anti fuerza bruta (en memoria, por proceso) ----------------------------------------
_attempts: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _prune(key: str, window: int) -> deque:
    q = _attempts[key]
    cutoff = time.monotonic() - window
    while q and q[0] < cutoff:
        q.popleft()
    return q


def is_throttled(key: str) -> bool:
    cfg = current_app.config
    with _lock:
        return len(_prune(key, cfg["LOGIN_WINDOW_SECONDS"])) >= cfg["LOGIN_MAX_ATTEMPTS"]


def register_failure(key: str) -> None:
    with _lock:
        _prune(key, current_app.config["LOGIN_WINDOW_SECONDS"]).append(time.monotonic())


def clear_failures(key: str) -> None:
    with _lock:
        _attempts.pop(key, None)


# --- Documentos privados (DNI / licencia) -----------------------------------------------
class UploadError(ValueError):
    pass


_SIGNATURES = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"%PDF-", "pdf"))
DOC_MIMETYPES = {"jpg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}


def uploads_dir() -> Path:
    path = Path(current_app.instance_path) / "uploads"   # FUERA de /static: no es público
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_document(file_storage, user_id: int, kind: str) -> str:
    """Valida por contenido (no por extensión), limita el tamaño y guarda con nombre aleatorio."""
    limit = current_app.config["MAX_UPLOAD_BYTES"]
    data = file_storage.stream.read(limit + 1)
    if len(data) > limit:
        raise UploadError(f"El archivo supera el máximo de {limit // (1024 * 1024)} MB.")
    ext = next((e for sig, e in _SIGNATURES if data.startswith(sig)), None)
    if ext is None:
        raise UploadError("Formato no válido: subí una imagen JPG o PNG, o un PDF.")
    name = f"{user_id}_{kind}_{uuid.uuid4().hex}.{ext}"
    (uploads_dir() / name).write_bytes(data)
    return name


def delete_document(name: str | None) -> None:
    if name:
        try:
            (uploads_dir() / Path(name).name).unlink(missing_ok=True)
        except OSError:
            pass
