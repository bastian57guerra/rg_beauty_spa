"""Indicadores de ocupación, cancelación y tiempos muertos, y reporte de ventas (RF-10 y RF-11)."""
from collections import defaultdict
from datetime import timedelta

import config
from services.reservas import a_fecha

NOMBRES_DIA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def calcular(db, desde, hasta):
    n_prof = db.execute("SELECT COUNT(*) FROM profesionales WHERE activo = 1").fetchone()[0]
    min_dia = (config.HORA_CIERRE - config.HORA_APERTURA) * 60
    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    cuenta_dias = defaultdict(int)
    for d in dias:
        if d.weekday() in config.DIAS_ATENCION:
            cuenta_dias[d.weekday()] += 1
    disponibles = sum(cuenta_dias.values()) * n_prof * min_dia

    filas = db.execute(
        "SELECT profesional_id, inicio, fin, estado FROM reservas WHERE substr(inicio, 1, 10) BETWEEN ? AND ?",
        (desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d"))).fetchall()
    ocupados = canceladas = no_asistio = 0
    por_dia = defaultdict(int)
    agenda = defaultdict(list)
    for f in filas:
        ini, fin = a_fecha(f["inicio"]), a_fecha(f["fin"])
        if f["estado"] == "Cancelada":
            canceladas += 1
        elif f["estado"] == "No asistió":
            no_asistio += 1
        else:
            minutos = int((fin - ini).total_seconds() // 60)
            ocupados += minutos
            por_dia[ini.weekday()] += minutos
            agenda[(f["profesional_id"], ini.date())].append((ini, fin))

    muerto = 0
    for bloques in agenda.values():
        bloques.sort()
        for (_, fin_a), (ini_b, _) in zip(bloques, bloques[1:]):
            muerto += max(0, int((ini_b - fin_a).total_seconds() // 60))

    def pct(a, b):
        return round(100 * a / b, 1) if b else 0.0

    detalle_dias = []
    for i in config.DIAS_ATENCION:
        disp = cuenta_dias.get(i, 0) * n_prof * min_dia
        detalle_dias.append({"dia": NOMBRES_DIA[i], "pct": pct(por_dia.get(i, 0), disp), "ocupados": por_dia.get(i, 0)})
    return {
        "total_reservas": len(filas), "canceladas": canceladas, "no_asistio": no_asistio,
        "pct_cancelacion": pct(canceladas, len(filas)),
        "ocupados_min": ocupados, "disponibles_min": disponibles,
        "pct_ocupacion": min(100.0, pct(ocupados, disponibles)),
        "tiempo_muerto_min": muerto, "por_dia": detalle_dias,
    }


def ventas(db, desde, hasta, base=None):
    d0, d1 = desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d")
    fila = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total, "
        "COALESCE(SUM(CASE WHEN fuera_horario = 1 THEN 1 ELSE 0 END), 0) AS n_fuera, "
        "COALESCE(SUM(CASE WHEN fuera_horario = 1 THEN total ELSE 0 END), 0) AS total_fuera "
        "FROM pedidos WHERE estado = 'Pagado' AND substr(creado_en, 1, 10) BETWEEN ? AND ?", (d0, d1)).fetchone()
    top = db.execute(
        "SELECT p.nombre, SUM(d.cantidad) AS unidades, SUM(d.cantidad * d.precio_unit) AS monto "
        "FROM detalle_pedido d JOIN pedidos o ON o.id = d.pedido_id JOIN productos p ON p.id = d.producto_id "
        "WHERE o.estado = 'Pagado' AND substr(o.creado_en, 1, 10) BETWEEN ? AND ? "
        "GROUP BY p.id ORDER BY monto DESC LIMIT 5", (d0, d1)).fetchall()
    variacion = round(100 * (fila["total"] - base) / base, 1) if base else None
    return {"n": fila["n"], "total": fila["total"], "n_fuera": fila["n_fuera"],
            "total_fuera": fila["total_fuera"], "top": top, "variacion": variacion}
