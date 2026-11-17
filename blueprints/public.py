"""Sitio público: reservas en línea (RF-04), catálogo y compra (RF-07 y RF-08)."""
from datetime import timedelta

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)

import config
from db import get_db
from security import limitar
from services import pedidos, reservas
from services.reservas import ErrorNegocio, ahora
from validacion import (ErrorValidacion, Form, email, entero, fecha, fecha_hora, nombre_persona,
                        opcion, telefono)

bp = Blueprint("public", __name__)
MEDIOS_PAGO = ("Tarjeta (sandbox)", "Transferencia (sandbox)")


@bp.get("/")
def inicio():
    return render_template("inicio.html")


@bp.get("/health")
def salud():
    try:
        get_db().execute("SELECT 1").fetchone()
        return jsonify(estado="ok", base_de_datos="ok")
    except Exception:
        return jsonify(estado="error"), 503


# ---------------- Reservas ----------------
@bp.get("/reservar")
def reservar():
    db = get_db()
    servicios = db.execute("SELECT * FROM servicios WHERE activo = 1 ORDER BY nombre").fetchall()
    servicio = profesionales = horarios = None
    prof_id = dia = None
    sid = request.args.get("servicio")
    if sid:
        try:
            s = entero(sid, "Servicio", 1, 10**9)
            servicio = db.execute("SELECT * FROM servicios WHERE id = ? AND activo = 1", (s,)).fetchone()
        except ErrorValidacion:
            servicio = None
        if servicio:
            profesionales = db.execute(
                "SELECT p.* FROM profesionales p JOIN profesional_servicio ps ON ps.profesional_id = p.id "
                "WHERE ps.servicio_id = ? AND p.activo = 1 ORDER BY p.nombre", (servicio["id"],)).fetchall()
            if request.args.get("profesional") and request.args.get("fecha"):
                f = Form(request.args)
                prof_id = f.get("profesional", entero, "Profesional", 1, 10**9)
                dia = f.get("fecha", fecha)
                if f.valido:
                    try:
                        horarios = reservas.horarios_disponibles(db, servicio["id"], prof_id, dia)
                    except ErrorNegocio as e:
                        flash(str(e), "error")
                else:
                    for err in f.errores:
                        flash(err, "error")
        else:
            flash("El servicio elegido no existe.", "error")
    hoy = ahora().date()
    return render_template("reservar.html", servicios=servicios, servicio=servicio,
                           profesionales=profesionales, horarios=horarios, prof_id=prof_id, dia=dia,
                           min_fecha=hoy.isoformat(),
                           max_fecha=(hoy + timedelta(days=config.DIAS_MAX_ANTICIPACION)).isoformat())


@bp.get("/reservar/datos")
def reservar_datos():
    db = get_db()
    f = Form(request.args)
    sid = f.get("servicio", entero, "Servicio", 1, 10**9)
    pid = f.get("profesional", entero, "Profesional", 1, 10**9)
    inicio = f.get("inicio", fecha_hora)
    if not f.valido:
        flash(f.errores[0], "error")
        return redirect(url_for("public.reservar"))
    try:
        servicio, prof = reservas._servicio_y_profesional(db, sid, pid)
        libres = reservas.horarios_disponibles(db, sid, pid, inicio.date())
    except ErrorNegocio as e:
        flash(str(e), "error")
        return redirect(url_for("public.reservar"))
    elegido = next((h for h in libres if h["inicio"] == reservas.a_texto(inicio)), None)
    if not elegido:
        flash("Ese horario ya no está disponible. Elija otro.", "error")
        return redirect(url_for("public.reservar", servicio=sid, profesional=pid, fecha=inicio.date()))
    return render_template("reservar_datos.html", servicio=servicio, prof=prof, inicio=inicio, elegido=elegido)


@bp.post("/reservar/confirmar")
def reservar_confirmar():
    limitar("reservar", 15, 60)
    db = get_db()
    f = Form(request.form)
    sid = f.get("servicio", entero, "Servicio", 1, 10**9)
    pid = f.get("profesional", entero, "Profesional", 1, 10**9)
    inicio = f.get("inicio", fecha_hora)
    nombre = f.get("nombre", nombre_persona)
    tel = f.get("telefono", telefono)
    correo = f.get("email", email)
    if not f.marcado("consentimiento"):
        f.errores.append("Debe aceptar el tratamiento de sus datos personales para reservar.")
    if not f.valido:
        for err in f.errores:
            flash(err, "error")
        return redirect(url_for("public.reservar_datos", servicio=sid or 0, profesional=pid or 0,
                                inicio=request.form.get("inicio", "")))
    cliente = db.execute("SELECT id FROM clientes WHERE telefono = ? AND anonimizado = 0", (tel,)).fetchone()
    try:
        if cliente:
            cliente_id = cliente["id"]
        else:
            cliente_id = db.execute(
                "INSERT INTO clientes (nombre, telefono, email, consentimiento, creado_en) VALUES (?, ?, ?, 1, ?)",
                (nombre, tel, correo, reservas.a_texto(ahora()))).lastrowid
        _, codigo = reservas.crear_reserva(db, cliente_id, sid, pid, inicio, "web")
    except ErrorNegocio as e:
        flash(str(e), "error")
        return redirect(url_for("public.reservar", servicio=sid, profesional=pid, fecha=inicio.date()))
    return redirect(url_for("public.reserva_ok", codigo=codigo))


@bp.get("/reserva/<codigo>")
def reserva_ok(codigo):
    r = get_db().execute(
        "SELECT r.*, s.nombre AS servicio, p.nombre AS profesional, c.nombre AS cliente FROM reservas r "
        "JOIN servicios s ON s.id = r.servicio_id JOIN profesionales p ON p.id = r.profesional_id "
        "JOIN clientes c ON c.id = r.cliente_id WHERE r.codigo = ?", (codigo[:20],)).fetchone()
    if not r:
        return render_template("error.html", codigo=404, mensaje="No encontramos esa reserva."), 404
    return render_template("reserva_ok.html", r=r)


# ---------------- Tienda ----------------
def _carrito():
    return session.setdefault("carrito", {})


@bp.get("/tienda")
def tienda():
    productos = get_db().execute("SELECT * FROM productos WHERE activo = 1 ORDER BY nombre").fetchall()
    return render_template("tienda.html", productos=productos)


@bp.post("/carrito/agregar")
def carrito_agregar():
    f = Form(request.form)
    pid = f.get("producto", entero, "Producto", 1, 10**9)
    cant = f.get("cantidad", entero, "Cantidad", 1, 10)
    if not f.valido:
        flash(f.errores[0], "error")
        return redirect(url_for("public.tienda"))
    p = get_db().execute("SELECT * FROM productos WHERE id = ? AND activo = 1", (pid,)).fetchone()
    if not p or p["stock"] <= 0:
        flash("El producto no está disponible.", "error")
        return redirect(url_for("public.tienda"))
    carrito = _carrito()
    nueva = min(carrito.get(str(pid), 0) + cant, p["stock"], 10)
    carrito[str(pid)] = nueva
    session.modified = True
    flash(f"Agregado: {p['nombre']}.", "ok")
    return redirect(url_for("public.carrito"))


def _detalle_carrito():
    db, lineas, total = get_db(), [], 0
    for pid, cant in _carrito().items():
        p = db.execute("SELECT * FROM productos WHERE id = ? AND activo = 1", (int(pid),)).fetchone()
        if p:
            lineas.append({"p": p, "cantidad": cant, "subtotal": p["precio"] * cant})
            total += p["precio"] * cant
    return lineas, total


@bp.get("/carrito")
def carrito():
    lineas, total = _detalle_carrito()
    return render_template("carrito.html", lineas=lineas, total=total)


@bp.post("/carrito/quitar")
def carrito_quitar():
    _carrito().pop(str(request.form.get("producto", ""))[:10], None)
    session.modified = True
    return redirect(url_for("public.carrito"))


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    lineas, total = _detalle_carrito()
    if not lineas:
        flash("Su carrito está vacío.", "aviso")
        return redirect(url_for("public.tienda"))
    if request.method == "POST":
        limitar("checkout", 10, 60)
        f = Form(request.form)
        nombre = f.get("nombre", nombre_persona)
        tel = f.get("telefono", telefono)
        correo = f.get("email", email)
        medio = f.get("medio_pago", opcion, "Medio de pago", MEDIOS_PAGO)
        if not f.marcado("consentimiento"):
            f.errores.append("Debe aceptar el tratamiento de sus datos personales para comprar.")
        if f.valido:
            rechazo = current_app.config["MODO_DEMO"] and f.marcado("simular_rechazo")
            carrito = {int(k): v for k, v in _carrito().items()}
            try:
                codigo = pedidos.crear_pedido(get_db(), carrito,
                                              {"nombre": nombre, "telefono": tel, "email": correo}, medio, rechazo)
            except ErrorNegocio as e:
                flash(str(e), "error")
            else:
                session.pop("carrito", None)
                return redirect(url_for("public.pedido", codigo=codigo))
        else:
            for err in f.errores:
                flash(err, "error")
    return render_template("checkout.html", lineas=lineas, total=total, medios=MEDIOS_PAGO,
                           demo=current_app.config["MODO_DEMO"])


@bp.get("/pedido/<codigo>")
def pedido(codigo):
    db = get_db()
    p = db.execute("SELECT * FROM pedidos WHERE codigo = ?", (codigo[:20],)).fetchone()
    if not p:
        return render_template("error.html", codigo=404, mensaje="No encontramos ese pedido."), 404
    detalle = db.execute("SELECT d.*, pr.nombre FROM detalle_pedido d JOIN productos pr ON pr.id = d.producto_id "
                         "WHERE d.pedido_id = ?", (p["id"],)).fetchall()
    return render_template("pedido.html", p=p, detalle=detalle)
