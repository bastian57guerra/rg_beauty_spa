"""Tienda en línea: carrito, pago simulado y descuento de stock (RF-07 y RF-08)."""
import secrets

import config
from db import transaccion
from services.reservas import ErrorNegocio, ahora, a_texto


class PagoRechazado(ErrorNegocio):
    pass


def cobrar(monto, medio, simular_rechazo=False):
    """Pasarela de pago de prueba (sandbox). No recibe ni guarda datos de tarjetas."""
    if simular_rechazo:
        return False, ""
    return True, "SBX-" + secrets.token_hex(4).upper()


def es_fuera_de_horario(momento):
    dentro = (momento.weekday() in config.DIAS_ATENCION
              and config.HORA_APERTURA <= momento.hour < config.HORA_CIERRE)
    return 0 if dentro else 1


def crear_pedido(db, carrito, comprador, medio_pago, simular_rechazo=False):
    if not carrito:
        raise ErrorNegocio("El carrito está vacío.")
    momento = ahora()
    with transaccion(db):
        lineas, total = [], 0
        for pid, cantidad in carrito.items():
            p = db.execute("SELECT * FROM productos WHERE id = ? AND activo = 1", (pid,)).fetchone()
            if not p:
                raise ErrorNegocio("Uno de los productos ya no está disponible.")
            if p["stock"] < cantidad:
                raise ErrorNegocio(f"No hay stock suficiente de {p['nombre']}.")
            lineas.append((p, cantidad))
            total += p["precio"] * cantidad
        aprobado, ref = cobrar(total, medio_pago, simular_rechazo)
        if not aprobado:
            raise PagoRechazado("El pago fue rechazado. Puede intentarlo nuevamente.")
        codigo = secrets.token_urlsafe(8)
        cur = db.execute(
            "INSERT INTO pedidos (codigo, comprador_nombre, comprador_telefono, comprador_email, total, "
            "medio_pago, pago_ref, estado, fuera_horario, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, 'Pagado', ?, ?)",
            (codigo, comprador["nombre"], comprador["telefono"], comprador["email"], total, medio_pago, ref,
             es_fuera_de_horario(momento), a_texto(momento)))
        for p, cantidad in lineas:
            actualizado = db.execute("UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ?",
                                     (cantidad, p["id"], cantidad)).rowcount
            if actualizado != 1:
                raise ErrorNegocio(f"No hay stock suficiente de {p['nombre']}.")
            db.execute("INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unit) VALUES (?, ?, ?, ?)",
                       (cur.lastrowid, p["id"], cantidad, p["precio"]))
    return codigo
