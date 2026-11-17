"""Crea la base de datos y carga datos de demostración.

Uso:  python seed.py            (crea la base si no existe)
      python seed.py --reset    (borra y vuelve a crear la base de demostración)
"""
import os
import random
import secrets
import sys
from datetime import timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

import config
import services.avisos  # noqa: F401  (registra los avisos automáticos)
from db import conectar, init_db
from services import pedidos, reservas
from services.reservas import ErrorNegocio, a_texto, ahora

CLAVE_DEMO = os.environ.get("RG_DEMO_PASSWORD", "RgBeauty#2026")

SERVICIOS = [("Corte y peinado", 60, 18000), ("Coloración", 120, 45000), ("Manicure", 45, 12000),
             ("Limpieza facial", 60, 25000), ("Masaje relajante", 60, 28000)]
PROFESIONALES = [("Rosario Gómez", ["Corte y peinado", "Coloración"]),
                 ("Camila Pizarro", ["Manicure", "Limpieza facial"]),
                 ("Daniela Soto", ["Limpieza facial", "Masaje relajante", "Manicure"])]
CLIENTAS = [("Valentina Rojas", "+56911111111"), ("Javiera Morales", "+56922222222"),
            ("Constanza Díaz", "+56933333333"), ("Fernanda Castillo", "+56944444444"),
            ("Antonia Herrera", "+56955555555"), ("Paula Contreras", "+56966666666"),
            ("Marcela Núñez", "+56977777777"), ("Isidora Vega", "+56988888888")]
PRODUCTOS = [("Shampoo reparador 500 ml", "Para cabello dañado o teñido.", 12990, 60),
             ("Acondicionador hidratante", "Suavidad y brillo diario.", 11990, 60),
             ("Mascarilla capilar", "Tratamiento intensivo semanal.", 15990, 40),
             ("Sérum facial vitamina C", "Luminosidad e hidratación.", 24990, 30),
             ("Crema hidratante de día", "Con protección solar FPS 30.", 19990, 40),
             ("Esmalte semipermanente", "Colores de temporada.", 6990, 80),
             ("Aceite de argán", "Nutrición para puntas.", 14990, 30),
             ("Kit de manicure", "Edición limitada (sin stock).", 9990, 0)]
PESO_DIA = {0: 0.35, 1: 0.3, 2: 0.3, 3: 0.6, 4: 0.7, 5: 0.85}  # menor demanda lunes a miércoles


def sembrar(ruta, reiniciar=False):
    if reiniciar:
        for sufijo in ("", "-wal", "-shm"):
            Path(str(ruta) + sufijo).unlink(missing_ok=True)
    init_db(ruta)
    db = conectar(ruta)
    if db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]:
        db.close()
        return False
    rnd = random.Random(2026)
    hoy = ahora()
    t = a_texto(hoy)

    ids_serv = {}
    for nombre, dur, precio in SERVICIOS:
        ids_serv[nombre] = db.execute("INSERT INTO servicios (nombre, duracion_min, precio) VALUES (?, ?, ?)",
                                      (nombre, dur, precio)).lastrowid
    ids_prof = {}
    for nombre, servs in PROFESIONALES:
        pid = db.execute("INSERT INTO profesionales (nombre) VALUES (?)", (nombre,)).lastrowid
        ids_prof[nombre] = pid
        for s in servs:
            db.execute("INSERT INTO profesional_servicio VALUES (?, ?)", (pid, ids_serv[s]))

    hash_demo = generate_password_hash(CLAVE_DEMO)
    usuarios = [("Administradora RG", "admin@rgbeautyspa.cl", "administrador", None),
                ("Recepción RG", "recepcion@rgbeautyspa.cl", "recepcionista", None),
                ("Rosario Gómez", "rosario@rgbeautyspa.cl", "profesional", ids_prof["Rosario Gómez"]),
                ("Camila Pizarro", "camila@rgbeautyspa.cl", "profesional", ids_prof["Camila Pizarro"]),
                ("Daniela Soto", "daniela@rgbeautyspa.cl", "profesional", ids_prof["Daniela Soto"])]
    for nombre, correo, rol, pid in usuarios:
        db.execute("INSERT INTO usuarios (nombre, email, password_hash, rol, profesional_id, creado_en) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (nombre, correo, hash_demo, rol, pid, t))
    ids_cli = [db.execute("INSERT INTO clientes (nombre, telefono, consentimiento, creado_en) VALUES (?, ?, 1, ?)",
                          (n, tel, t)).lastrowid for n, tel in CLIENTAS]
    for nombre, desc, precio, stock in PRODUCTOS:
        db.execute("INSERT INTO productos (nombre, descripcion, precio, stock) VALUES (?, ?, ?, ?)",
                   (nombre, desc, precio, stock))
    db.execute("INSERT INTO promociones (nombre, descuento_pct, dias, hora_desde, hora_hasta, fecha_desde, fecha_hasta) "
               "VALUES ('Tarde de martes y miércoles', 20, '1,2', '15:00', '19:00', ?, ?)",
               ((hoy - timedelta(days=60)).strftime("%Y-%m-%d"), (hoy + timedelta(days=60)).strftime("%Y-%m-%d")))

    # Historial de 4 semanas para que los indicadores tengan datos
    servicios = {r["id"]: r for r in db.execute("SELECT * FROM servicios")}
    permitidos = {}
    for r in db.execute("SELECT * FROM profesional_servicio"):
        permitidos.setdefault(r["profesional_id"], []).append(r["servicio_id"])
    for atras in range(28, 0, -1):
        dia = (hoy - timedelta(days=atras)).replace(hour=0, minute=0, second=0, microsecond=0)
        if dia.weekday() not in config.DIAS_ATENCION:
            continue
        for pid, lista in permitidos.items():
            for _ in range(int(PESO_DIA[dia.weekday()] * 8)):
                sid = rnd.choice(lista)
                ini = dia.replace(hour=config.HORA_APERTURA) + timedelta(minutes=30 * rnd.randint(0, 15))
                fin = ini + timedelta(minutes=servicios[sid]["duracion_min"])
                if fin > dia.replace(hour=config.HORA_CIERRE) or reservas.hay_traslape(db, pid, a_texto(ini), a_texto(fin)):
                    continue
                x = rnd.random()
                estado = "Atendida" if x < 0.8 else ("No asistió" if x < 0.87 else "Cancelada")
                db.execute(
                    "INSERT INTO reservas (codigo, cliente_id, profesional_id, servicio_id, inicio, fin, estado, origen, "
                    "precio_final, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (secrets.token_urlsafe(8), rnd.choice(ids_cli), pid, sid, a_texto(ini), a_texto(fin), estado,
                     rnd.choice(["web", "recepcion"]), servicios[sid]["precio"], a_texto(ini - timedelta(days=2))))

    # Dos reservas de hoy (ya iniciadas) para probar el registro de atención
    hoy0 = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    if hoy0.weekday() in config.DIAS_ATENCION:
        for hora_ini, nombre_prof, nombre_serv in ((10, "Rosario Gómez", "Corte y peinado"), (10, "Camila Pizarro", "Manicure")):
            pid, sid = ids_prof[nombre_prof], ids_serv[nombre_serv]
            ini = hoy0.replace(hour=hora_ini)
            fin = ini + timedelta(minutes=servicios[sid]["duracion_min"])
            if not reservas.hay_traslape(db, pid, a_texto(ini), a_texto(fin)):
                db.execute("INSERT INTO reservas (codigo, cliente_id, profesional_id, servicio_id, inicio, fin, estado, "
                           "origen, precio_final, creada_en) VALUES (?, ?, ?, ?, ?, ?, 'Confirmada', 'recepcion', ?, ?)",
                           (secrets.token_urlsafe(8), rnd.choice(ids_cli), pid, sid, a_texto(ini), a_texto(fin),
                            servicios[sid]["precio"], a_texto(hoy - timedelta(days=1))))

    # Reservas futuras creadas con la lógica real (generan sus avisos de confirmación)
    for _ in range(14):
        dia = hoy0 + timedelta(days=rnd.randint(1, 10))
        pid = rnd.choice(list(permitidos))
        sid = rnd.choice(permitidos[pid])
        ini = dia.replace(hour=config.HORA_APERTURA) + timedelta(minutes=30 * rnd.randint(0, 12))
        try:
            reservas.crear_reserva(db, rnd.choice(ids_cli), sid, pid, ini, rnd.choice(["web", "recepcion"]))
        except ErrorNegocio:
            pass

    # Pedidos de las últimas semanas, parte de ellos fuera del horario del local
    productos = [r for r in db.execute("SELECT * FROM productos WHERE stock > 0")]
    for _ in range(26):
        momento = hoy - timedelta(days=rnd.randint(1, 27), hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59))
        elegidos = rnd.sample(productos, rnd.randint(1, 3))
        total = 0
        cur = db.execute(
            "INSERT INTO pedidos (codigo, comprador_nombre, comprador_telefono, total, medio_pago, pago_ref, estado, "
            "fuera_horario, creado_en) VALUES (?, ?, ?, 0, 'Tarjeta (sandbox)', ?, 'Pagado', ?, ?)",
            (secrets.token_urlsafe(8), *rnd.choice(CLIENTAS), "SBX-" + secrets.token_hex(4).upper(),
             pedidos.es_fuera_de_horario(momento), a_texto(momento)))
        for p in elegidos:
            cant = rnd.randint(1, 2)
            total += p["precio"] * cant
            db.execute("INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unit) VALUES (?, ?, ?, ?)",
                       (cur.lastrowid, p["id"], cant, p["precio"]))
            db.execute("UPDATE productos SET stock = MAX(stock - ?, 0) WHERE id = ?", (cant, p["id"]))
        db.execute("UPDATE pedidos SET total = ? WHERE id = ?", (total, cur.lastrowid))
    db.close()
    return True


if __name__ == "__main__":
    creada = sembrar(config.Config.DATABASE, reiniciar="--reset" in sys.argv)
    print("Base de datos creada con datos de demostración." if creada else "La base ya tenía datos; no se modificó.")
    if creada:
        print(f"Usuarios de demostración (contraseña: {CLAVE_DEMO}):")
        print("  admin@rgbeautyspa.cl · recepcion@rgbeautyspa.cl · rosario@rgbeautyspa.cl")
