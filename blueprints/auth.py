"""Inicio y cierre de sesión (RF-01) y cambio de contraseña."""
from datetime import timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db
from security import auditar, limitar, rol_requerido
from services.reservas import a_texto, ahora
from validacion import ErrorValidacion, password_valida

bp = Blueprint("auth", __name__)
HASH_FALSO = generate_password_hash("contraseña-falsa-para-igualar-tiempos")
MENSAJE_FALLO = "Correo o contraseña incorrectos, o cuenta bloqueada temporalmente."


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("panel.inicio"))
    if request.method == "POST":
        limitar("login", 20, 300)
        from flask import current_app
        cfg = current_app.config
        db = get_db()
        correo = (request.form.get("email") or "").strip().lower()[:120]
        clave = (request.form.get("password") or "")[:200]
        u = db.execute("SELECT * FROM usuarios WHERE email = ?", (correo,)).fetchone()
        momento = a_texto(ahora())
        bloqueado = bool(u and u["bloqueado_hasta"] and u["bloqueado_hasta"] > momento)
        # Siempre se calcula un hash para que el tiempo de respuesta no revele si el correo existe.
        coincide = check_password_hash(u["password_hash"] if u else HASH_FALSO, clave)
        if u and u["activo"] and coincide and not bloqueado:
            db.execute("UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?", (u["id"],))
            session.clear()  # sesión nueva al autenticar (evita fijación de sesión)
            session["uid"] = u["id"]
            session.permanent = True
            auditar("login_ok", correo, usuario_id=u["id"])
            return redirect(url_for("panel.inicio"))
        if u:
            intentos = u["intentos_fallidos"] + 1
            hasta = None
            if intentos >= cfg["MAX_INTENTOS_LOGIN"]:
                hasta = a_texto(ahora() + timedelta(minutes=cfg["MINUTOS_BLOQUEO"]))
                intentos = 0
            db.execute("UPDATE usuarios SET intentos_fallidos = ?, bloqueado_hasta = COALESCE(?, bloqueado_hasta) "
                       "WHERE id = ?", (intentos, hasta, u["id"]))
        auditar("login_fallido", correo, usuario_id=u["id"] if u else None)
        flash(MENSAJE_FALLO, "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    if g.usuario:
        auditar("logout", g.usuario["email"])
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("public.inicio"))


@bp.route("/panel/clave", methods=["GET", "POST"])
@rol_requerido("administrador", "recepcionista", "profesional")
def cambiar_clave():
    if request.method == "POST":
        db = get_db()
        actual = request.form.get("actual", "")[:200]
        nueva = request.form.get("nueva", "")
        fila = db.execute("SELECT password_hash FROM usuarios WHERE id = ?", (g.usuario["id"],)).fetchone()
        try:
            if not check_password_hash(fila["password_hash"], actual):
                raise ErrorValidacion("La contraseña actual no es correcta.")
            password_valida(nueva)
            if request.form.get("repetir") != nueva:
                raise ErrorValidacion("Las contraseñas nuevas no coinciden.")
        except ErrorValidacion as e:
            flash(str(e), "error")
        else:
            db.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(nueva), g.usuario["id"]))
            auditar("cambio_clave")
            flash("Contraseña actualizada.", "ok")
            return redirect(url_for("panel.inicio"))
    campos = [
        {"nombre": "actual", "etiqueta": "Contraseña actual", "tipo": "password"},
        {"nombre": "nueva", "etiqueta": "Contraseña nueva", "tipo": "password",
         "ayuda": "Mínimo 10 caracteres, con letras y números."},
        {"nombre": "repetir", "etiqueta": "Repetir contraseña nueva", "tipo": "password"},
    ]
    return render_template("panel/form.html", titulo="Cambiar contraseña", campos=campos, boton="Guardar")
