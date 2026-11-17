"""Confirmaciones y recordatorios (RF-06). En el prototipo el envío es simulado:
se guarda el mensaje que se enviaría por correo o SMS."""
from datetime import timedelta

import eventos
from services.reservas import ahora, a_fecha, a_texto

PLANTILLAS = {
    "confirmacion": "Hola {nombre}, tu reserva de {servicio} con {profesional} quedó confirmada para el {fecha} a las {hora}. Código: {codigo}.",
    "recordatorio": "Hola {nombre}, te recordamos tu hora de {servicio} con {profesional} el {fecha} a las {hora} en RG Beauty Spa.",
    "reprogramacion": "Hola {nombre}, tu reserva de {servicio} fue reprogramada para el {fecha} a las {hora}. Código: {codigo}.",
    "cancelacion": "Hola {nombre}, tu reserva de {servicio} del {fecha} a las {hora} fue cancelada.",
}


def registrar(db, reserva_id, tipo):
    r = db.execute(
        "SELECT r.codigo, r.inicio, c.nombre AS cliente, c.telefono, c.email, s.nombre AS servicio, "
        "p.nombre AS profesional FROM reservas r JOIN clientes c ON c.id = r.cliente_id "
        "JOIN servicios s ON s.id = r.servicio_id JOIN profesionales p ON p.id = r.profesional_id "
        "WHERE r.id = ?", (reserva_id,)).fetchone()
    if not r:
        return
    inicio = a_fecha(r["inicio"])
    mensaje = PLANTILLAS[tipo].format(
        nombre=r["cliente"].split()[0], servicio=r["servicio"], profesional=r["profesional"],
        fecha=inicio.strftime("%d-%m-%Y"), hora=inicio.strftime("%H:%M"), codigo=r["codigo"])
    canal, destino = ("correo", r["email"]) if r["email"] else ("sms", r["telefono"])
    db.execute("INSERT INTO avisos (reserva_id, tipo, canal, destino, mensaje, estado, creado_en) "
               "VALUES (?, ?, ?, ?, ?, 'Simulado', ?)",
               (reserva_id, tipo, canal, destino, mensaje, a_texto(ahora())))


def generar_recordatorios(db, dia=None):
    """Crea el recordatorio de las reservas confirmadas de un día (por defecto, mañana)."""
    dia = dia or (ahora().date() + timedelta(days=1))
    f = dia.strftime("%Y-%m-%d")
    filas = db.execute(
        "SELECT id FROM reservas WHERE estado = 'Confirmada' AND substr(inicio, 1, 10) = ? "
        "AND id NOT IN (SELECT reserva_id FROM avisos WHERE tipo = 'recordatorio')", (f,)).fetchall()
    for fila in filas:
        registrar(db, fila["id"], "recordatorio")
    return len(filas)


eventos.suscribir("reserva_confirmada", lambda db, reserva_id: registrar(db, reserva_id, "confirmacion"))
eventos.suscribir("reserva_reprogramada", lambda db, reserva_id: registrar(db, reserva_id, "reprogramacion"))
eventos.suscribir("reserva_cancelada", lambda db, reserva_id: registrar(db, reserva_id, "cancelacion"))
