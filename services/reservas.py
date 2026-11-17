"""Lógica de negocio de la agenda: horarios, traslapes, reservas y cambios de estado."""
import secrets
from datetime import datetime, timedelta

import config
import eventos
from db import transaccion

FORMATO = "%Y-%m-%d %H:%M"


class ErrorNegocio(Exception):
    """Regla del negocio incumplida; el mensaje se puede mostrar a la persona."""


def ahora():
    if config.ZONA:
        return datetime.now(config.ZONA).replace(tzinfo=None)
    return datetime.now()


def a_texto(dt):
    return dt.strftime(FORMATO)


def a_fecha(txt):
    return datetime.strptime(txt, FORMATO)


def hay_traslape(db, profesional_id, inicio, fin, excluir_id=None):
    """Dos bloques se superponen si cada uno empieza antes de que termine el otro."""
    sql = ("SELECT 1 FROM reservas WHERE profesional_id = ? AND estado != 'Cancelada' "
           "AND inicio < ? AND fin > ?")
    params = [profesional_id, fin, inicio]
    if excluir_id:
        sql += " AND id != ?"
        params.append(excluir_id)
    return db.execute(sql, params).fetchone() is not None


def _servicio_y_profesional(db, servicio_id, profesional_id):
    servicio = db.execute("SELECT * FROM servicios WHERE id = ? AND activo = 1", (servicio_id,)).fetchone()
    prof = db.execute("SELECT * FROM profesionales WHERE id = ? AND activo = 1", (profesional_id,)).fetchone()
    if not servicio or not prof:
        raise ErrorNegocio("El servicio o el profesional elegido no está disponible.")
    realiza = db.execute(
        "SELECT 1 FROM profesional_servicio WHERE profesional_id = ? AND servicio_id = ?",
        (profesional_id, servicio_id)).fetchone()
    if not realiza:
        raise ErrorNegocio("El profesional elegido no realiza ese servicio.")
    return servicio, prof


def _validar_bloque(inicio, duracion):
    fin = inicio + timedelta(minutes=duracion)
    if inicio.minute % config.PASO_MINUTOS or inicio.second:
        raise ErrorNegocio("El horario elegido no es válido.")
    if inicio.weekday() not in config.DIAS_ATENCION:
        raise ErrorNegocio("El salón no atiende ese día.")
    abre = inicio.replace(hour=config.HORA_APERTURA, minute=0, second=0, microsecond=0)
    cierra = inicio.replace(hour=config.HORA_CIERRE, minute=0, second=0, microsecond=0)
    if inicio < abre or fin > cierra:
        raise ErrorNegocio("El horario queda fuera de la jornada de atención.")
    if inicio <= ahora():
        raise ErrorNegocio("No se puede reservar en un horario que ya pasó.")
    if inicio.date() > ahora().date() + timedelta(days=config.DIAS_MAX_ANTICIPACION):
        raise ErrorNegocio("Solo se puede reservar con hasta %d días de anticipación." % config.DIAS_MAX_ANTICIPACION)
    return fin


def promocion_para(db, inicio):
    dia = str(inicio.weekday())
    f, h = inicio.strftime("%Y-%m-%d"), inicio.strftime("%H:%M")
    filas = db.execute(
        "SELECT * FROM promociones WHERE activa = 1 AND fecha_desde <= ? AND fecha_hasta >= ? "
        "AND hora_desde <= ? AND hora_hasta > ? ORDER BY descuento_pct DESC", (f, f, h, h)).fetchall()
    for p in filas:
        if dia in p["dias"].split(","):
            return p
    return None


def _precio(servicio, promo):
    return servicio["precio"] * (100 - promo["descuento_pct"]) // 100 if promo else servicio["precio"]


def horarios_disponibles(db, servicio_id, profesional_id, dia, excluir_id=None):
    servicio, _ = _servicio_y_profesional(db, servicio_id, profesional_id)
    if dia.weekday() not in config.DIAS_ATENCION:
        return []
    f = dia.strftime("%Y-%m-%d")
    sql = ("SELECT inicio, fin FROM reservas WHERE profesional_id = ? AND estado != 'Cancelada' "
           "AND inicio >= ? AND inicio < ?")
    params = [profesional_id, f + " 00:00", f + " 23:59"]
    if excluir_id:
        sql += " AND id != ?"
        params.append(excluir_id)
    ocupados = [(a_fecha(r["inicio"]), a_fecha(r["fin"])) for r in db.execute(sql, params)]
    t = datetime(dia.year, dia.month, dia.day, config.HORA_APERTURA)
    cierre = datetime(dia.year, dia.month, dia.day, config.HORA_CIERRE)
    limite = ahora() + timedelta(days=config.DIAS_MAX_ANTICIPACION)
    libres = []
    while t + timedelta(minutes=servicio["duracion_min"]) <= cierre:
        fin = t + timedelta(minutes=servicio["duracion_min"])
        if t > ahora() and t <= limite and not any(o_i < fin and o_f > t for o_i, o_f in ocupados):
            promo = promocion_para(db, t)
            libres.append({"inicio": a_texto(t), "hora": t.strftime("%H:%M"),
                           "precio": _precio(servicio, promo),
                           "promo": promo["nombre"] if promo else None})
        t += timedelta(minutes=config.PASO_MINUTOS)
    return libres


def crear_reserva(db, cliente_id, servicio_id, profesional_id, inicio, origen):
    servicio, _ = _servicio_y_profesional(db, servicio_id, profesional_id)
    fin = _validar_bloque(inicio, servicio["duracion_min"])
    promo = promocion_para(db, inicio)
    with transaccion(db):
        if hay_traslape(db, profesional_id, a_texto(inicio), a_texto(fin)):
            raise ErrorNegocio("Ese horario acaba de ser tomado. Elija otro, por favor.")
        codigo = secrets.token_urlsafe(8)
        cur = db.execute(
            "INSERT INTO reservas (codigo, cliente_id, profesional_id, servicio_id, inicio, fin, estado, "
            "origen, promocion_id, precio_final, creada_en) VALUES (?, ?, ?, ?, ?, ?, 'Confirmada', ?, ?, ?, ?)",
            (codigo, cliente_id, profesional_id, servicio_id, a_texto(inicio), a_texto(fin), origen,
             promo["id"] if promo else None, _precio(servicio, promo), a_texto(ahora())))
        reserva_id = cur.lastrowid
    eventos.publicar("reserva_confirmada", db=db, reserva_id=reserva_id)
    return reserva_id, codigo


def _reserva(db, reserva_id):
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if not r:
        raise ErrorNegocio("La reserva no existe.")
    return r


def reprogramar(db, reserva_id, nuevo_inicio):
    r = _reserva(db, reserva_id)
    if r["estado"] != "Confirmada":
        raise ErrorNegocio("Solo se pueden reprogramar reservas confirmadas.")
    servicio = db.execute("SELECT * FROM servicios WHERE id = ?", (r["servicio_id"],)).fetchone()
    fin = _validar_bloque(nuevo_inicio, servicio["duracion_min"])
    promo = promocion_para(db, nuevo_inicio)
    with transaccion(db):
        if hay_traslape(db, r["profesional_id"], a_texto(nuevo_inicio), a_texto(fin), excluir_id=reserva_id):
            raise ErrorNegocio("Ese horario ya está ocupado.")
        db.execute("UPDATE reservas SET inicio = ?, fin = ?, promocion_id = ?, precio_final = ? WHERE id = ?",
                   (a_texto(nuevo_inicio), a_texto(fin), promo["id"] if promo else None,
                    _precio(servicio, promo), reserva_id))
    eventos.publicar("reserva_reprogramada", db=db, reserva_id=reserva_id)


def cancelar(db, reserva_id):
    r = _reserva(db, reserva_id)
    if r["estado"] != "Confirmada":
        raise ErrorNegocio("Solo se pueden cancelar reservas confirmadas.")
    db.execute("UPDATE reservas SET estado = 'Cancelada' WHERE id = ?", (reserva_id,))
    eventos.publicar("reserva_cancelada", db=db, reserva_id=reserva_id)


def marcar_atencion(db, reserva_id, estado):
    if estado not in ("Atendida", "No asistió"):
        raise ErrorNegocio("Estado no válido.")
    r = _reserva(db, reserva_id)
    if r["estado"] != "Confirmada":
        raise ErrorNegocio("Solo se puede registrar la atención de una reserva confirmada.")
    if a_fecha(r["inicio"]) > ahora():
        raise ErrorNegocio("La atención aún no comienza.")
    db.execute("UPDATE reservas SET estado = ? WHERE id = ?", (estado, reserva_id))
