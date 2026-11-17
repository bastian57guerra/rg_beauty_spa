"""Pruebas automáticas del prototipo. Ejecutar con:  python -m unittest discover -s tests -v"""
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup  # noqa: E402
import config  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402
from db import conectar, transaccion  # noqa: E402
from services import avisos, indicadores, pedidos, reservas  # noqa: E402
from services.reservas import ErrorNegocio, ahora  # noqa: E402
from validacion import ErrorValidacion, nombre_persona, password_valida, telefono  # noqa: E402

CLAVE = seed.CLAVE_DEMO


def proximo_dia_habil(desde_dias=20):
    d = ahora().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=desde_dias)
    while d.weekday() not in config.DIAS_ATENCION:
        d += timedelta(days=1)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.tmp.name, "prueba.db")
        seed.sembrar(self.ruta)
        self.app = create_app({"DATABASE": self.ruta, "TESTING": True, "RATELIMIT_ACTIVO": False})
        self.client = self.app.test_client()
        self.db = conectar(self.ruta)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def csrf(self, url="/login"):
        html = self.client.get(url).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def login(self, correo="admin@rgbeautyspa.cl", clave=CLAVE, cliente=None):
        c = cliente or self.client
        html = c.get("/login").get_data(as_text=True)
        tok = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        return c.post("/login", data={"_csrf": tok, "email": correo, "password": clave})

    def ids(self):
        s = self.db.execute("SELECT id FROM servicios WHERE nombre = 'Corte y peinado'").fetchone()[0]
        p = self.db.execute("SELECT id FROM profesionales WHERE nombre = 'Rosario Gómez'").fetchone()[0]
        c = self.db.execute("SELECT id FROM clientes LIMIT 1").fetchone()[0]
        return s, p, c


class PruebasReservas(Base):
    def test_no_permite_traslape(self):
        s, p, c = self.ids()
        ini = proximo_dia_habil().replace(hour=11)
        reservas.crear_reserva(self.db, c, s, p, ini, "recepcion")
        with self.assertRaises(ErrorNegocio):
            reservas.crear_reserva(self.db, c, s, p, ini + timedelta(minutes=30), "web")

    def test_permite_reservas_consecutivas(self):
        s, p, c = self.ids()
        ini = proximo_dia_habil().replace(hour=11)
        reservas.crear_reserva(self.db, c, s, p, ini, "web")
        reservas.crear_reserva(self.db, c, s, p, ini + timedelta(hours=1), "web")  # empieza justo al terminar la otra

    def test_cancelar_libera_el_horario(self):
        s, p, c = self.ids()
        ini = proximo_dia_habil().replace(hour=12)
        rid, _ = reservas.crear_reserva(self.db, c, s, p, ini, "web")
        libres = [h["inicio"] for h in reservas.horarios_disponibles(self.db, s, p, ini.date())]
        self.assertNotIn(reservas.a_texto(ini), libres)
        reservas.cancelar(self.db, rid)
        libres = [h["inicio"] for h in reservas.horarios_disponibles(self.db, s, p, ini.date())]
        self.assertIn(reservas.a_texto(ini), libres)

    def test_reprogramar_con_conflicto_no_cambia_la_reserva(self):
        s, p, c = self.ids()
        dia = proximo_dia_habil()
        a, _ = reservas.crear_reserva(self.db, c, s, p, dia.replace(hour=10), "web")
        reservas.crear_reserva(self.db, c, s, p, dia.replace(hour=12), "web")
        with self.assertRaises(ErrorNegocio):
            reservas.reprogramar(self.db, a, dia.replace(hour=11, minute=30))
        self.assertEqual(self.db.execute("SELECT inicio FROM reservas WHERE id = ?", (a,)).fetchone()[0],
                         reservas.a_texto(dia.replace(hour=10)))

    def test_reprogramar_a_horario_libre(self):
        s, p, c = self.ids()
        dia = proximo_dia_habil()
        a, _ = reservas.crear_reserva(self.db, c, s, p, dia.replace(hour=10), "web")
        reservas.reprogramar(self.db, a, dia.replace(hour=15))
        self.assertEqual(self.db.execute("SELECT inicio FROM reservas WHERE id = ?", (a,)).fetchone()[0],
                         reservas.a_texto(dia.replace(hour=15)))

    def test_rechaza_horarios_invalidos(self):
        s, p, c = self.ids()
        dia = proximo_dia_habil()
        for ini in (dia.replace(hour=8), dia.replace(hour=18, minute=30), dia.replace(hour=11, minute=10),
                    ahora() - timedelta(days=1)):
            with self.assertRaises(ErrorNegocio):
                reservas.crear_reserva(self.db, c, s, p, ini, "web")

    def test_profesional_debe_realizar_el_servicio(self):
        _, p, c = self.ids()
        masaje = self.db.execute("SELECT id FROM servicios WHERE nombre = 'Masaje relajante'").fetchone()[0]
        with self.assertRaises(ErrorNegocio):
            reservas.crear_reserva(self.db, c, masaje, p, proximo_dia_habil().replace(hour=11), "web")

    def test_promocion_se_aplica_en_la_franja(self):
        s, p, c = self.ids()
        dia = proximo_dia_habil()
        while dia.weekday() not in (1, 2):
            dia += timedelta(days=1)
        _, cod = reservas.crear_reserva(self.db, c, s, p, dia.replace(hour=16), "web")
        precio = self.db.execute("SELECT precio_final FROM reservas WHERE codigo = ?", (cod,)).fetchone()[0]
        self.assertEqual(precio, 18000 * 80 // 100)

    def test_marcar_atencion_solo_si_ya_comenzo(self):
        s, p, c = self.ids()
        rid, _ = reservas.crear_reserva(self.db, c, s, p, proximo_dia_habil().replace(hour=11), "web")
        with self.assertRaises(ErrorNegocio):
            reservas.marcar_atencion(self.db, rid, "Atendida")

    def test_dos_reservas_simultaneas_solo_una_se_guarda(self):
        import threading
        s, p, c = self.ids()
        ini = proximo_dia_habil().replace(hour=15)
        resultados = []

        def intentar():
            con = conectar(self.ruta)
            try:
                reservas.crear_reserva(con, c, s, p, ini, "web")
                resultados.append("ok")
            except ErrorNegocio:
                resultados.append("conflicto")
            finally:
                con.close()

        hilos = [threading.Thread(target=intentar) for _ in range(6)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(resultados.count("ok"), 1)
        self.assertEqual(resultados.count("conflicto"), 5)

    def test_la_confirmacion_genera_aviso(self):
        s, p, c = self.ids()
        antes = self.db.execute("SELECT COUNT(*) FROM avisos").fetchone()[0]
        reservas.crear_reserva(self.db, c, s, p, proximo_dia_habil().replace(hour=13), "web")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM avisos").fetchone()[0], antes + 1)

    def test_recordatorios_no_se_duplican(self):
        s, p, c = self.ids()
        dia = ahora().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        while dia.weekday() not in config.DIAS_ATENCION:
            dia += timedelta(days=1)
        reservas.crear_reserva(self.db, c, s, p, dia.replace(hour=14), "web")
        n1 = avisos.generar_recordatorios(self.db, dia.date())
        n2 = avisos.generar_recordatorios(self.db, dia.date())
        self.assertGreaterEqual(n1, 1)
        self.assertEqual(n2, 0)


class PruebasTienda(Base):
    def producto(self, nombre):
        return self.db.execute("SELECT * FROM productos WHERE nombre LIKE ?", (nombre + "%",)).fetchone()

    COMPRADOR = {"nombre": "Ana Pérez", "telefono": "+56912345678", "email": None}

    def test_compra_descuenta_stock_y_suma_total(self):
        p = self.producto("Shampoo")
        antes = p["stock"]
        cod = pedidos.crear_pedido(self.db, {p["id"]: 2}, self.COMPRADOR, "Tarjeta (sandbox)")
        self.assertEqual(self.producto("Shampoo")["stock"], antes - 2)
        total = self.db.execute("SELECT total FROM pedidos WHERE codigo = ?", (cod,)).fetchone()[0]
        self.assertEqual(total, p["precio"] * 2)

    def test_sin_stock_no_permite_comprar(self):
        p = self.producto("Kit de manicure")
        with self.assertRaises(ErrorNegocio):
            pedidos.crear_pedido(self.db, {p["id"]: 1}, self.COMPRADOR, "Tarjeta (sandbox)")

    def test_pago_rechazado_no_guarda_pedido_ni_baja_stock(self):
        p = self.producto("Shampoo")
        antes = p["stock"]
        n = self.db.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
        with self.assertRaises(pedidos.PagoRechazado):
            pedidos.crear_pedido(self.db, {p["id"]: 1}, self.COMPRADOR, "Tarjeta (sandbox)", simular_rechazo=True)
        self.assertEqual(self.producto("Shampoo")["stock"], antes)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0], n)

    def test_error_a_mitad_revierte_todo(self):
        a, b = self.producto("Shampoo"), self.producto("Kit de manicure")
        antes = a["stock"]
        with self.assertRaises(ErrorNegocio):
            pedidos.crear_pedido(self.db, {a["id"]: 1, b["id"]: 1}, self.COMPRADOR, "Tarjeta (sandbox)")
        self.assertEqual(self.producto("Shampoo")["stock"], antes)

    def test_fuera_de_horario(self):
        sabado_noche = proximo_dia_habil()
        while sabado_noche.weekday() != 5:
            sabado_noche += timedelta(days=1)
        self.assertEqual(pedidos.es_fuera_de_horario(sabado_noche.replace(hour=21)), 1)
        self.assertEqual(pedidos.es_fuera_de_horario(sabado_noche.replace(hour=12)), 0)
        self.assertEqual(pedidos.es_fuera_de_horario(sabado_noche + timedelta(days=1)), 1)  # domingo


class PruebasIndicadores(Base):
    def test_indicadores_con_datos_conocidos(self):
        self.db.executescript("DELETE FROM avisos; DELETE FROM reservas;")
        s, p, c = self.ids()
        dia = (ahora() - timedelta(days=10)).replace(hour=0, minute=0, second=0, microsecond=0)
        while dia.weekday() not in config.DIAS_ATENCION:
            dia -= timedelta(days=1)
        for h, estado in ((10, "Atendida"), (13, "Atendida"), (16, "Cancelada")):
            ini = dia.replace(hour=h)
            self.db.execute(
                "INSERT INTO reservas (codigo, cliente_id, profesional_id, servicio_id, inicio, fin, estado, origen, "
                "precio_final, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, 'web', 18000, '2026-01-01 00:00')",
                (f"c{h}", c, p, s, reservas.a_texto(ini), reservas.a_texto(ini + timedelta(hours=1)), estado))
        r = indicadores.calcular(self.db, dia.date(), dia.date())
        self.assertEqual(r["ocupados_min"], 120)
        self.assertEqual(r["disponibles_min"], 3 * 9 * 60)
        self.assertEqual(r["tiempo_muerto_min"], 120)  # hueco entre las 11:00 y las 13:00
        self.assertEqual(r["canceladas"], 1)
        self.assertEqual(r["pct_cancelacion"], 33.3)

    def test_reporte_de_ventas(self):
        hoy = ahora().date()
        v = indicadores.ventas(self.db, hoy - timedelta(days=30), hoy, base=100000)
        self.assertEqual(v["n"], 26)
        self.assertLessEqual(v["total_fuera"], v["total"])
        self.assertIsNotNone(v["variacion"])


class PruebasValidacion(unittest.TestCase):
    def test_telefono(self):
        self.assertEqual(telefono("+56 9 1234 5678"), "+56912345678")
        self.assertEqual(telefono("912345678"), "+56912345678")
        for malo in ("123", "+5622345678", "abcdefghi", "9123456789012"):
            with self.assertRaises(ErrorValidacion):
                telefono(malo)

    def test_nombre(self):
        self.assertEqual(nombre_persona("  María   José  "), "María José")
        for malo in ("", "A", "<script>alert(1)</script>", "Juan123"):
            with self.assertRaises(ErrorValidacion):
                nombre_persona(malo)

    def test_politica_de_contrasenas(self):
        self.assertTrue(password_valida("Segura2026xy"))
        for mala in ("corta1", "sololetrasaquiii", "12345678901234", "password"):
            with self.assertRaises(ErrorValidacion):
                password_valida(mala)


class PruebasSeguridad(Base):
    def test_panel_exige_sesion(self):
        r = self.client.get("/panel/agenda")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_login_correcto_y_contrasena_hasheada(self):
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/panel/").status_code, 200)
        h = self.db.execute("SELECT password_hash FROM usuarios WHERE email = 'admin@rgbeautyspa.cl'").fetchone()[0]
        self.assertNotIn(CLAVE, h)
        self.assertTrue(h.startswith(("scrypt:", "pbkdf2:")))

    def test_login_incorrecto_mensaje_generico(self):
        r = self.login(clave="incorrecta123")
        self.assertEqual(r.status_code, 200)
        r2 = self.login(correo="noexiste@x.cl", clave="incorrecta123")
        txt1 = re.search(r'class="mensaje error"[^>]*>([^<]+)', r.get_data(as_text=True)).group(1)
        txt2 = re.search(r'class="mensaje error"[^>]*>([^<]+)', r2.get_data(as_text=True)).group(1)
        self.assertEqual(txt1, txt2)

    def test_bloqueo_tras_cinco_intentos(self):
        for _ in range(5):
            self.login(clave="incorrecta123")
        r = self.login()  # ahora con la clave correcta, pero la cuenta está bloqueada
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/panel/").status_code, 302)

    def test_csrf_obligatorio(self):
        r = self.client.post("/login", data={"email": "admin@rgbeautyspa.cl", "password": CLAVE})
        self.assertEqual(r.status_code, 400)
        self.login()
        r = self.client.post("/panel/avisos/recordatorios", data={})
        self.assertEqual(r.status_code, 400)

    def test_control_de_roles(self):
        self.login("recepcion@rgbeautyspa.cl")
        self.assertEqual(self.client.get("/panel/servicios").status_code, 403)
        self.assertEqual(self.client.get("/panel/indicadores").status_code, 403)
        self.assertEqual(self.client.get("/panel/clientes").status_code, 200)

    def test_profesional_solo_ve_su_agenda_y_no_edita_catalogos(self):
        self.login("rosario@rgbeautyspa.cl")
        self.assertEqual(self.client.get("/panel/clientes").status_code, 403)
        self.assertEqual(self.client.get("/panel/productos").status_code, 403)
        html = self.client.get("/panel/agenda?fecha=" + ahora().strftime("%Y-%m-%d")).get_data(as_text=True)
        self.assertNotIn("Camila Pizarro", html.split("<tbody>")[1])

    def test_profesional_no_puede_marcar_reserva_ajena(self):
        camila = self.db.execute("SELECT id FROM profesionales WHERE nombre = 'Camila Pizarro'").fetchone()[0]
        ajena = self.db.execute("SELECT id FROM reservas WHERE profesional_id = ? LIMIT 1", (camila,)).fetchone()[0]
        self.login("rosario@rgbeautyspa.cl")
        tok = self.csrf("/panel/agenda")
        r = self.client.post(f"/panel/reservas/{ajena}/atencion", data={"_csrf": tok, "estado": "Atendida"})
        self.assertEqual(r.status_code, 403)

    def test_cabeceras_de_seguridad(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_cookie_de_sesion_httponly(self):
        r = self.login()
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_inyeccion_sql_en_busqueda_no_rompe_ni_filtra(self):
        self.login("recepcion@rgbeautyspa.cl")
        r = self.client.get("/panel/clientes", query_string={"q": "' OR 1=1 --"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Valentina Rojas", r.get_data(as_text=True))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 8)

    def test_xss_se_escapa_en_la_salida(self):
        self.db.execute("UPDATE clientes SET nombre = '<script>alert(1)</script>' WHERE id = 1")
        self.login("recepcion@rgbeautyspa.cl")
        html = self.client.get("/panel/clientes").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_reserva_publica_valida_datos_y_consentimiento(self):
        s, p, _ = self.ids()
        ini = reservas.a_texto(proximo_dia_habil().replace(hour=11))
        tok = self.csrf()
        base = {"_csrf": tok, "servicio": s, "profesional": p, "inicio": ini, "nombre": "Ana Pérez",
                "telefono": "+56 9 8765 4321", "email": ""}
        r = self.client.post("/reservar/confirmar", data=base)  # sin consentimiento
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM clientes WHERE telefono = '+56987654321'").fetchone()[0], 0)
        r = self.client.post("/reservar/confirmar", data={**base, "telefono": "123", "consentimiento": "on"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM clientes WHERE nombre = 'Ana Pérez'").fetchone()[0], 0)
        r = self.client.post("/reservar/confirmar", data={**base, "consentimiento": "on"})
        self.assertIn("/reserva/", r.headers["Location"])
        self.assertEqual(self.client.get(r.headers["Location"]).status_code, 200)

    def test_codigo_de_reserva_inexistente(self):
        self.assertEqual(self.client.get("/reserva/noexiste").status_code, 404)

    def test_cambio_de_contrasena_con_politica(self):
        self.login()
        tok = self.csrf("/panel/clave")
        r = self.client.post("/panel/clave", data={"_csrf": tok, "actual": CLAVE, "nueva": "corta", "repetir": "corta"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/panel/clave", data={"_csrf": tok, "actual": CLAVE, "nueva": "NuevaClave2026", "repetir": "NuevaClave2026"})
        self.assertEqual(r.status_code, 302)
        otro = self.app.test_client()
        self.assertEqual(self.login(clave="NuevaClave2026", cliente=otro).status_code, 302)

    def test_anonimizar_clienta(self):
        self.login()
        tok = self.csrf("/panel/clientes")
        cid = self.db.execute("SELECT id FROM clientes WHERE nombre = 'Valentina Rojas'").fetchone()[0]
        self.client.post(f"/panel/clientes/{cid}/anonimizar", data={"_csrf": tok})
        fila = self.db.execute("SELECT nombre, telefono, anonimizado FROM clientes WHERE id = ?", (cid,)).fetchone()
        self.assertEqual((fila[0], fila[1], fila[2]), ("Clienta anonimizada", "ANONIMO", 1))

    def test_acciones_quedan_en_auditoria(self):
        self.login()
        n = self.db.execute("SELECT COUNT(*) FROM auditoria WHERE accion = 'login_ok'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_errores_no_muestran_detalles_internos(self):
        r = self.client.get("/panel/no-existe")
        self.assertIn(r.status_code, (302, 404))
        r = self.client.get("/pagina-inexistente")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("Traceback", r.get_data(as_text=True))

    def test_salud(self):
        r = self.client.get("/health")
        self.assertEqual(r.get_json()["estado"], "ok")


class PruebasRespaldo(Base):
    def test_respaldo_es_integro_y_restaurable(self):
        backup.CARPETA = Path(self.tmp.name) / "bk"
        destino = backup.respaldar(self.ruta)
        self.assertTrue(backup.verificar(destino))
        con = sqlite3.connect(destino)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 8)
        con.close()


if __name__ == "__main__":
    unittest.main()
