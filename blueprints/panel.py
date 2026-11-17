"""Panel interno: agenda, clientes, catálogos, promociones, indicadores y reportes."""
import sqlite3
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from db import get_db
from security import auditar, rol_requerido
from services import avisos, indicadores, reservas
from services.reservas import ErrorNegocio, ahora, a_texto
from validacion import (ErrorValidacion, Form, email, entero, fecha, fecha_hora, hora,
                        nombre_persona, telefono, texto)

bp = Blueprint("panel", __name__, url_prefix="/panel")
ADMIN, RECEP, PROF = "administrador", "recepcionista", "profesional"
TODOS = (ADMIN, RECEP, PROF)
DIAS = [("0", "Lunes"), ("1", "Martes"), ("2", "Miércoles"), ("3", "Jueves"), ("4", "Viernes"), ("5", "Sábado")]
GET_POST = ["GET", "POST"]


# ---------- utilidades ----------
def _activo(v):
    return 1 if v == "on" else 0


def _lista(sql, *params):
    return get_db().execute(sql, params).fetchall()


def _errores(f):
    for err in f.errores:
        flash(err, "error")


def _campos(spec, datos):
    return [{**c, "valor": datos.get(c["nombre"], c.get("defecto", ""))} for c in spec]


def _renderizar(titulo, spec, datos, boton="Guardar", volver=None):
    return render_template("panel/form.html", titulo=titulo, campos=_campos(spec, datos), boton=boton, volver=volver)


def _leer(spec, datos):
    f = Form(datos)
    return f, {c["nombre"]: f.get(c["nombre"], c["val"]) for c in spec}


def _editar(tabla, spec, fila_id, titulo, destino, nombre_accion):
    """Alta o edición genérica. 'tabla' y las columnas salen del código, nunca del usuario."""
    db = get_db()
    fila = db.execute(f"SELECT * FROM {tabla} WHERE id = ?", (fila_id,)).fetchone() if fila_id else None
    if fila_id and not fila:
        abort(404)
    datos = dict(fila) if fila else {}
    if request.method == "POST":
        f, vals = _leer(spec, request.form)
        if f.valido:
            cols = list(vals)
            sql = (f"UPDATE {tabla} SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE id = ?" if fila
                   else f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})")
            try:
                db.execute(sql, [vals[c] for c in cols] + ([fila_id] if fila else []))
            except sqlite3.IntegrityError:
                flash("Ya existe un registro con esos datos.", "error")
            else:
                auditar(nombre_accion, str(vals.get("nombre", fila_id)))
                flash("Cambios guardados.", "ok")
                return redirect(url_for(destino))
        else:
            _errores(f)
        datos = request.form
    return _renderizar(titulo, spec, datos, volver=url_for(destino))


@bp.before_request
def _exigir_sesion():
    if g.usuario is None:
        flash("Inicie sesión para continuar.", "aviso")
        return redirect(url_for("auth.login"))


@bp.get("/")
def inicio():
    sql = "SELECT COUNT(*) FROM reservas WHERE substr(inicio, 1, 10) = ? AND estado != 'Cancelada'"
    params = [ahora().strftime("%Y-%m-%d")]
    if g.usuario["rol"] == PROF:
        sql += " AND profesional_id = ?"
        params.append(g.usuario["profesional_id"])
    return render_template("panel/inicio.html", reservas_hoy=_lista(sql, *params)[0][0])


# ---------- Agenda (RF-04, RF-05, RF-12) ----------
@bp.get("/agenda")
def agenda():
    try:
        dia = fecha(request.args["fecha"]) if request.args.get("fecha") else ahora().date()
    except ErrorValidacion as e:
        flash(str(e), "error")
        dia = ahora().date()
    prof_id = None
    if g.usuario["rol"] == PROF:
        prof_id = g.usuario["profesional_id"]
    elif request.args.get("profesional"):
        try:
            prof_id = entero(request.args["profesional"], "Profesional", 1, 10**9)
        except ErrorValidacion:
            prof_id = None
    sql = ("SELECT r.*, c.nombre AS cliente, c.telefono, s.nombre AS servicio, p.nombre AS profesional "
           "FROM reservas r JOIN clientes c ON c.id = r.cliente_id JOIN servicios s ON s.id = r.servicio_id "
           "JOIN profesionales p ON p.id = r.profesional_id WHERE substr(r.inicio, 1, 10) = ?")
    params = [dia.strftime("%Y-%m-%d")]
    if prof_id:
        sql += " AND r.profesional_id = ?"
        params.append(prof_id)
    return render_template("panel/agenda.html", filas=_lista(sql + " ORDER BY r.inicio", *params), dia=dia,
                           prof_id=prof_id, ahora=a_texto(ahora()), ayer=dia - timedelta(days=1),
                           manana=dia + timedelta(days=1),
                           profesionales=_lista("SELECT * FROM profesionales WHERE activo = 1 ORDER BY nombre"))


@bp.route("/reservas/nueva", methods=GET_POST)
@rol_requerido(ADMIN, RECEP)
def reserva_nueva():
    db = get_db()
    datos = request.form if request.method == "POST" else request.args
    f = Form(datos)
    cid = f.get("cliente", entero, "Clienta", 1, 10**9) if datos.get("cliente") else None
    sid = f.get("servicio", entero, "Servicio", 1, 10**9) if datos.get("servicio") else None
    pid = f.get("profesional", entero, "Profesional", 1, 10**9) if datos.get("profesional") else None
    if request.method == "POST":
        inicio = f.get("inicio", fecha_hora)
        if f.valido and cid and sid and pid:
            try:
                rid, _ = reservas.crear_reserva(db, cid, sid, pid, inicio, "recepcion")
            except (ErrorNegocio, sqlite3.IntegrityError) as e:
                flash(str(e) if isinstance(e, ErrorNegocio) else "No se pudo guardar la reserva.", "error")
                return redirect(url_for("panel.reserva_nueva", cliente=cid, servicio=sid, profesional=pid,
                                        fecha=inicio.date()))
            auditar("reserva_creada", f"id {rid}")
            flash("Reserva confirmada.", "ok")
            return redirect(url_for("panel.agenda", fecha=inicio.date()))
        for err in f.errores or ["Complete todos los datos de la reserva."]:
            flash(err, "error")
        return redirect(url_for("panel.reserva_nueva"))
    dia = f.get("fecha", fecha) if datos.get("fecha") else None
    horarios = None
    if cid and sid and pid and dia and f.valido:
        try:
            horarios = reservas.horarios_disponibles(db, sid, pid, dia)
        except ErrorNegocio as e:
            flash(str(e), "error")
    _errores(f)
    return render_template(
        "panel/reserva_nueva.html", horarios=horarios, cid=cid, sid=sid, pid=pid, dia=dia,
        clientes=_lista("SELECT id, nombre, telefono FROM clientes WHERE anonimizado = 0 ORDER BY nombre"),
        servicios=_lista("SELECT id, nombre FROM servicios WHERE activo = 1 ORDER BY nombre"),
        profesionales=_lista("SELECT id, nombre FROM profesionales WHERE activo = 1 ORDER BY nombre"),
        hoy=ahora().date().isoformat())


def _reserva_o_404(rid):
    r = get_db().execute("SELECT * FROM reservas WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    return r


@bp.post("/reservas/<int:rid>/cancelar")
@rol_requerido(ADMIN, RECEP)
def reserva_cancelar(rid):
    r = _reserva_o_404(rid)
    try:
        reservas.cancelar(get_db(), rid)
        auditar("reserva_cancelada", f"id {rid}")
        flash("Reserva cancelada. El horario quedó disponible.", "ok")
    except ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("panel.agenda", fecha=r["inicio"][:10]))


@bp.route("/reservas/<int:rid>/reprogramar", methods=GET_POST)
@rol_requerido(ADMIN, RECEP)
def reserva_reprogramar(rid):
    db = get_db()
    r = _reserva_o_404(rid)
    if request.method == "POST":
        f = Form(request.form)
        inicio = f.get("inicio", fecha_hora)
        if f.valido:
            try:
                reservas.reprogramar(db, rid, inicio)
            except ErrorNegocio as e:
                flash(str(e), "error")
                return redirect(url_for("panel.reserva_reprogramar", rid=rid, fecha=inicio.date()))
            auditar("reserva_reprogramada", f"id {rid}")
            flash("Reserva reprogramada.", "ok")
            return redirect(url_for("panel.agenda", fecha=inicio.date()))
        flash(f.errores[0], "error")
        return redirect(url_for("panel.reserva_reprogramar", rid=rid))
    horarios, dia = None, None
    if request.args.get("fecha"):
        try:
            dia = fecha(request.args["fecha"])
            horarios = reservas.horarios_disponibles(db, r["servicio_id"], r["profesional_id"], dia, excluir_id=rid)
        except (ErrorValidacion, ErrorNegocio) as e:
            flash(str(e), "error")
    detalle = db.execute("SELECT c.nombre AS cliente, s.nombre AS servicio, p.nombre AS profesional FROM reservas r "
                         "JOIN clientes c ON c.id = r.cliente_id JOIN servicios s ON s.id = r.servicio_id "
                         "JOIN profesionales p ON p.id = r.profesional_id WHERE r.id = ?", (rid,)).fetchone()
    return render_template("panel/reprogramar.html", r=r, detalle=detalle, horarios=horarios, dia=dia,
                           hoy=ahora().date().isoformat())


@bp.post("/reservas/<int:rid>/atencion")
@rol_requerido(ADMIN, PROF)
def reserva_atencion(rid):
    r = _reserva_o_404(rid)
    if g.usuario["rol"] == PROF and r["profesional_id"] != g.usuario["profesional_id"]:
        abort(403)
    try:
        reservas.marcar_atencion(get_db(), rid, request.form.get("estado", ""))
        auditar("atencion_registrada", f"id {rid}: {request.form.get('estado')}")
        flash("Atención registrada.", "ok")
    except ErrorNegocio as e:
        flash(str(e), "error")
    return redirect(url_for("panel.agenda", fecha=r["inicio"][:10]))


# ---------- Clientas (RF-02) ----------
SPEC_CLIENTE = [
    {"nombre": "nombre", "etiqueta": "Nombre completo", "val": lambda v: nombre_persona(v)},
    {"nombre": "telefono", "etiqueta": "Teléfono celular", "tipo": "tel", "val": lambda v: telefono(v),
     "ayuda": "Ejemplo: +56 9 1234 5678"},
    {"nombre": "email", "etiqueta": "Correo (opcional)", "tipo": "email", "requerido": False,
     "val": lambda v: email(v)},
    {"nombre": "consentimiento", "etiqueta": "La clienta autoriza el tratamiento de sus datos personales",
     "tipo": "checkbox", "val": _activo},
]


@bp.get("/clientes")
@rol_requerido(ADMIN, RECEP)
def clientes():
    q = " ".join((request.args.get("q") or "").split())[:60]
    sql, params = "SELECT * FROM clientes", []
    if q:
        sql += " WHERE nombre LIKE ? OR telefono LIKE ?"
        params = [f"%{q}%", f"%{q}%"]
    return render_template("panel/clientes.html", filas=_lista(sql + " ORDER BY nombre LIMIT 200", *params), q=q)


@bp.route("/clientes/nuevo", methods=GET_POST, defaults={"cid": None}, endpoint="cliente_nuevo")
@bp.route("/clientes/<int:cid>/editar", methods=GET_POST, endpoint="cliente_editar")
@rol_requerido(ADMIN, RECEP)
def cliente_guardar(cid):
    """Alta (cid=None) o edición de una clienta."""
    db = get_db()
    fila = db.execute("SELECT * FROM clientes WHERE id = ? AND anonimizado = 0", (cid,)).fetchone() if cid else None
    if cid and not fila:
        abort(404)
    titulo, volver = ("Editar clienta" if fila else "Nueva clienta"), url_for("panel.clientes")
    if request.method == "POST":
        f, v = _leer(SPEC_CLIENTE, request.form)
        if f.valido:
            try:
                if fila:
                    db.execute("UPDATE clientes SET nombre = ?, telefono = ?, email = ?, consentimiento = ? WHERE id = ?",
                               (v["nombre"], v["telefono"], v["email"], v["consentimiento"], cid))
                else:
                    db.execute("INSERT INTO clientes (nombre, telefono, email, consentimiento, creado_en) "
                               "VALUES (?, ?, ?, ?, ?)",
                               (v["nombre"], v["telefono"], v["email"], v["consentimiento"], a_texto(ahora())))
            except sqlite3.IntegrityError:
                flash("Ya existe una clienta con ese teléfono.", "error")
            else:
                auditar("cliente_editado", f"id {cid}") if fila else auditar("cliente_creado", v["nombre"])
                flash("Datos actualizados." if fila else "Clienta registrada.", "ok")
                return redirect(volver)
        else:
            _errores(f)
        return _renderizar(titulo, SPEC_CLIENTE, request.form, volver=volver)
    return _renderizar(titulo, SPEC_CLIENTE, dict(fila) if fila else {}, volver=volver)


@bp.post("/clientes/<int:cid>/anonimizar")
@rol_requerido(ADMIN)
def cliente_anonimizar(cid):
    """Supresión de datos personales a solicitud de la clienta (derecho de cancelación)."""
    db = get_db()
    c = db.execute("SELECT * FROM clientes WHERE id = ? AND anonimizado = 0", (cid,)).fetchone()
    if not c:
        abort(404)
    db.execute("UPDATE avisos SET destino = 'anonimizado', mensaje = '[eliminado]' WHERE reserva_id IN "
               "(SELECT id FROM reservas WHERE cliente_id = ?)", (cid,))
    db.execute("UPDATE pedidos SET comprador_nombre = 'Anonimizado', comprador_telefono = 'ANONIMO', "
               "comprador_email = NULL WHERE comprador_telefono = ?", (c["telefono"],))
    db.execute("UPDATE clientes SET nombre = 'Clienta anonimizada', telefono = 'ANONIMO', email = NULL, "
               "consentimiento = 0, anonimizado = 1 WHERE id = ?", (cid,))
    auditar("cliente_anonimizado", f"id {cid}")
    flash("Los datos personales de la clienta fueron eliminados.", "ok")
    return redirect(url_for("panel.clientes"))


# ---------- Servicios, profesionales y productos (RF-03, RF-07) ----------
SPEC_SERVICIO = [
    {"nombre": "nombre", "etiqueta": "Nombre del servicio", "val": lambda v: texto(v, "Nombre", 2, 80)},
    {"nombre": "duracion_min", "etiqueta": "Duración (minutos)", "tipo": "number",
     "val": lambda v: entero(v, "Duración", 15, 480), "ayuda": "Entre 15 y 480 minutos."},
    {"nombre": "precio", "etiqueta": "Precio (CLP)", "tipo": "number",
     "val": lambda v: entero(v, "Precio", 0, 10_000_000)},
    {"nombre": "activo", "etiqueta": "Servicio activo", "tipo": "checkbox", "val": _activo, "defecto": 1},
]
SPEC_PRODUCTO = [
    {"nombre": "nombre", "etiqueta": "Nombre del producto", "val": lambda v: texto(v, "Nombre", 2, 80)},
    {"nombre": "descripcion", "etiqueta": "Descripción", "tipo": "textarea", "requerido": False,
     "val": lambda v: texto(v, "Descripción", 0, 300)},
    {"nombre": "precio", "etiqueta": "Precio (CLP)", "tipo": "number",
     "val": lambda v: entero(v, "Precio", 0, 10_000_000)},
    {"nombre": "stock", "etiqueta": "Stock disponible", "tipo": "number", "val": lambda v: entero(v, "Stock", 0, 100_000)},
    {"nombre": "activo", "etiqueta": "Publicado en la tienda", "tipo": "checkbox", "val": _activo, "defecto": 1},
]


@bp.get("/servicios")
@rol_requerido(ADMIN)
def servicios():
    return render_template("panel/servicios.html", filas=_lista("SELECT * FROM servicios ORDER BY nombre"))


@bp.route("/servicios/nuevo", methods=GET_POST)
@rol_requerido(ADMIN)
def servicio_nuevo():
    return _editar("servicios", SPEC_SERVICIO, None, "Nuevo servicio", "panel.servicios", "servicio_creado")


@bp.route("/servicios/<int:sid>/editar", methods=GET_POST)
@rol_requerido(ADMIN)
def servicio_editar(sid):
    return _editar("servicios", SPEC_SERVICIO, sid, "Editar servicio", "panel.servicios", "servicio_editado")


@bp.get("/productos")
@rol_requerido(ADMIN)
def productos():
    return render_template("panel/productos.html", filas=_lista("SELECT * FROM productos ORDER BY nombre"))


@bp.route("/productos/nuevo", methods=GET_POST)
@rol_requerido(ADMIN)
def producto_nuevo():
    return _editar("productos", SPEC_PRODUCTO, None, "Nuevo producto", "panel.productos", "producto_creado")


@bp.route("/productos/<int:pid>/editar", methods=GET_POST)
@rol_requerido(ADMIN)
def producto_editar(pid):
    return _editar("productos", SPEC_PRODUCTO, pid, "Editar producto", "panel.productos", "producto_editado")


@bp.get("/profesionales")
@rol_requerido(ADMIN)
def profesionales():
    filas = _lista(
        "SELECT p.*, COALESCE(GROUP_CONCAT(s.nombre, ', '), '') AS servicios FROM profesionales p "
        "LEFT JOIN profesional_servicio ps ON ps.profesional_id = p.id LEFT JOIN servicios s ON s.id = ps.servicio_id "
        "GROUP BY p.id ORDER BY p.nombre")
    return render_template("panel/profesionales.html", filas=filas)


@bp.route("/profesionales/nuevo", methods=GET_POST, defaults={"pid": None}, endpoint="profesional_nuevo")
@bp.route("/profesionales/<int:pid>/editar", methods=GET_POST, endpoint="profesional_editar")
@rol_requerido(ADMIN)
def profesional_guardar(pid):
    """Alta (pid=None) o edición de un profesional y de los servicios que realiza."""
    db = get_db()
    fila = db.execute("SELECT * FROM profesionales WHERE id = ?", (pid,)).fetchone() if pid else None
    if pid and not fila:
        abort(404)
    todos = _lista("SELECT id, nombre FROM servicios WHERE activo = 1 ORDER BY nombre")
    validos = {str(s["id"]) for s in todos}
    spec = [
        {"nombre": "nombre", "etiqueta": "Nombre del profesional", "val": lambda v: nombre_persona(v)},
        {"nombre": "activo", "etiqueta": "Profesional activo", "tipo": "checkbox", "val": _activo, "defecto": 1},
        {"nombre": "servicios", "etiqueta": "Servicios que realiza", "tipo": "multicheck",
         "opciones": [(str(s["id"]), s["nombre"]) for s in todos], "val": lambda v: v},
    ]
    if request.method == "POST":
        f = Form(request.form)
        nombre = f.get("nombre", nombre_persona)
        activo = _activo(request.form.get("activo"))
        elegidos = [s for s in request.form.getlist("servicios") if s in validos]
        if f.valido:
            if fila:
                db.execute("UPDATE profesionales SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, pid))
            else:
                pid = db.execute("INSERT INTO profesionales (nombre, activo) VALUES (?, ?)", (nombre, activo)).lastrowid
            db.execute("DELETE FROM profesional_servicio WHERE profesional_id = ?", (pid,))
            db.executemany("INSERT INTO profesional_servicio (profesional_id, servicio_id) VALUES (?, ?)",
                           [(pid, int(s)) for s in elegidos])
            auditar("profesional_guardado", nombre)
            flash("Cambios guardados.", "ok")
            return redirect(url_for("panel.profesionales"))
        _errores(f)
        datos = {"nombre": request.form.get("nombre", ""), "activo": request.form.get("activo", ""),
                 "servicios": set(elegidos)}
    elif fila:
        sel = {str(r["servicio_id"]) for r in _lista(
            "SELECT servicio_id FROM profesional_servicio WHERE profesional_id = ?", pid)}
        datos = {"nombre": fila["nombre"], "activo": fila["activo"], "servicios": sel}
    else:
        datos = {"servicios": set()}
    return _renderizar("Editar profesional" if fila else "Nuevo profesional", spec, datos,
                       volver=url_for("panel.profesionales"))


# ---------- Promociones (RF-09) ----------
@bp.route("/promociones", methods=GET_POST)
@rol_requerido(ADMIN)
def promociones():
    db = get_db()
    hoy = ahora().date()
    spec = [
        {"nombre": "nombre", "etiqueta": "Nombre de la promoción"},
        {"nombre": "descuento_pct", "etiqueta": "Descuento (%)", "tipo": "number", "ayuda": "Entre 1 y 90."},
        {"nombre": "dias", "etiqueta": "Días de la semana", "tipo": "multicheck", "opciones": DIAS},
        {"nombre": "hora_desde", "etiqueta": "Desde la hora", "tipo": "time", "defecto": "15:00"},
        {"nombre": "hora_hasta", "etiqueta": "Hasta la hora", "tipo": "time", "defecto": "19:00"},
        {"nombre": "fecha_desde", "etiqueta": "Vigente desde", "tipo": "date", "defecto": hoy.isoformat()},
        {"nombre": "fecha_hasta", "etiqueta": "Vigente hasta", "tipo": "date",
         "defecto": (hoy + timedelta(days=30)).isoformat()},
    ]
    datos = {"dias": set()}
    if request.method == "POST":
        f = Form(request.form)
        nombre = f.get("nombre", texto, "Nombre", 3, 80)
        pct = f.get("descuento_pct", entero, "Descuento", 1, 90)
        d0 = f.get("hora_desde", hora, "Hora desde")
        d1 = f.get("hora_hasta", hora, "Hora hasta")
        f0 = f.get("fecha_desde", fecha, "Fecha desde")
        f1 = f.get("fecha_hasta", fecha, "Fecha hasta")
        dias = [d for d in request.form.getlist("dias") if d in dict(DIAS)]
        if not dias:
            f.errores.append("Elija al menos un día de la semana.")
        if f.valido and d0 >= d1:
            f.errores.append("La hora de término debe ser posterior a la de inicio.")
        if f.valido and f0 > f1:
            f.errores.append("La fecha de término debe ser posterior a la de inicio.")
        if f.valido:
            db.execute("INSERT INTO promociones (nombre, descuento_pct, dias, hora_desde, hora_hasta, fecha_desde, "
                       "fecha_hasta, activa) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                       (nombre, pct, ",".join(sorted(dias)), d0, d1, f0.isoformat(), f1.isoformat()))
            auditar("promocion_creada", nombre)
            flash("Promoción creada.", "ok")
            return redirect(url_for("panel.promociones"))
        _errores(f)
        datos = {**request.form, "dias": set(dias)}
    return render_template("panel/promociones.html", campos=_campos(spec, datos), dias=dict(DIAS),
                           filas=_lista("SELECT * FROM promociones ORDER BY activa DESC, fecha_hasta DESC"))


@bp.post("/promociones/<int:pid>/alternar")
@rol_requerido(ADMIN)
def promocion_alternar(pid):
    get_db().execute("UPDATE promociones SET activa = 1 - activa WHERE id = ?", (pid,))
    auditar("promocion_alternada", f"id {pid}")
    return redirect(url_for("panel.promociones"))


# ---------- Indicadores y ventas (RF-10, RF-11) ----------
def _rango():
    hoy = ahora().date()
    f = Form(request.args)
    desde = f.get("desde", fecha, "Desde") if request.args.get("desde") else hoy - timedelta(days=27)
    hasta = f.get("hasta", fecha, "Hasta") if request.args.get("hasta") else hoy
    if f.valido and desde > hasta:
        f.errores.append("La fecha inicial no puede ser posterior a la final.")
    if f.valido and (hasta - desde).days > 366:
        f.errores.append("El rango máximo es de un año.")
    if not f.valido:
        _errores(f)
        return hoy - timedelta(days=27), hoy
    return desde, hasta


@bp.get("/indicadores")
@rol_requerido(ADMIN)
def indicadores_vista():
    desde, hasta = _rango()
    return render_template("panel/indicadores.html", ind=indicadores.calcular(get_db(), desde, hasta),
                           desde=desde, hasta=hasta)


@bp.get("/ventas")
@rol_requerido(ADMIN)
def ventas_vista():
    desde, hasta = _rango()
    base = None
    if request.args.get("base"):
        try:
            base = entero(request.args["base"], "Línea base", 1, 10**10)
        except ErrorValidacion as e:
            flash(str(e), "error")
    return render_template("panel/ventas.html", v=indicadores.ventas(get_db(), desde, hasta, base),
                           desde=desde, hasta=hasta, base=base)


# ---------- Avisos y auditoría (RF-06) ----------
@bp.get("/avisos")
@rol_requerido(ADMIN, RECEP)
def avisos_vista():
    return render_template("panel/avisos.html", filas=_lista("SELECT * FROM avisos ORDER BY id DESC LIMIT 100"))


@bp.post("/avisos/recordatorios")
@rol_requerido(ADMIN, RECEP)
def avisos_recordatorios():
    n = avisos.generar_recordatorios(get_db())
    auditar("recordatorios_generados", f"{n} avisos")
    flash(f"Se generaron {n} recordatorios para las reservas de mañana.", "ok")
    return redirect(url_for("panel.avisos_vista"))


@bp.get("/auditoria")
@rol_requerido(ADMIN)
def auditoria():
    filas = _lista("SELECT a.*, u.email FROM auditoria a LEFT JOIN usuarios u ON u.id = a.usuario_id "
                   "ORDER BY a.id DESC LIMIT 150")
    return render_template("panel/auditoria.html", filas=filas)
