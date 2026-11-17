"""Medidas de seguridad transversales (OWASP): CSRF, sesión, roles, límites y auditoría."""
import hmac
import secrets
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for

import config
from db import get_db

_intentos = defaultdict(deque)


# ---------- CSRF (A01 / A04) ----------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def verificar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("_csrf", "")
        esperado = session.get("_csrf", "")
        if not esperado or not hmac.compare_digest(enviado, esperado):
            abort(400, "El formulario expiró o no es válido. Vuelva a intentarlo.")


# ---------- Sesión y control de acceso (A01 / A07) ----------
def cargar_usuario():
    g.usuario = None
    uid = session.get("uid")
    if uid:
        fila = get_db().execute(
            "SELECT id, nombre, email, rol, profesional_id FROM usuarios WHERE id = ? AND activo = 1",
            (uid,),
        ).fetchone()
        if fila:
            g.usuario = fila
        else:
            session.clear()


def rol_requerido(*roles):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kw):
            if g.usuario is None:
                flash("Inicie sesión para continuar.", "aviso")
                return redirect(url_for("auth.login"))
            if g.usuario["rol"] not in roles:
                abort(403)
            return vista(*args, **kw)
        return envoltura
    return decorador


# ---------- Límite de solicitudes (A04 / A07) ----------
def limitar(clave, maximo=30, ventana=60):
    if not current_app.config.get("RATELIMIT_ACTIVO", True):
        return
    ahora = time.monotonic()
    cola = _intentos[(clave, request.remote_addr)]
    while cola and ahora - cola[0] > ventana:
        cola.popleft()
    if len(cola) >= maximo:
        abort(429)
    cola.append(ahora)


# ---------- Auditoría (A09) ----------
def auditar(accion, detalle="", usuario_id=None):
    from services.reservas import ahora, a_texto
    uid = usuario_id if usuario_id is not None else (g.usuario["id"] if g.get("usuario") else None)
    get_db().execute(
        "INSERT INTO auditoria (usuario_id, accion, detalle, ip, creado_en) VALUES (?, ?, ?, ?, ?)",
        (uid, accion, detalle[:300], request.remote_addr, a_texto(ahora())),
    )


# ---------- Cabeceras de seguridad (A05) ----------
def cabeceras(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith(("/panel", "/login")):
        resp.headers["Cache-Control"] = "no-store"
    return resp
