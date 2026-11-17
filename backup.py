"""Respaldo diario de la base de datos (RNF-05).

Uso:  python backup.py                      crea un respaldo en la carpeta backups/
      python backup.py --verificar ARCHIVO  comprueba que un respaldo se puede abrir y está íntegro
Para automatizarlo: programar este comando una vez al día (cron en Linux o Programador de tareas en Windows).
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import config

CARPETA = config.BASE_DIR / "backups"
CONSERVAR = 14


def respaldar(origen=None):
    origen = Path(origen or config.Config.DATABASE)
    CARPETA.mkdir(exist_ok=True)
    destino = CARPETA / f"rg_beauty_spa_{datetime.now():%Y%m%d_%H%M%S}.db"
    with sqlite3.connect(origen) as src, sqlite3.connect(destino) as dst:
        src.backup(dst)  # copia consistente aunque la base esté en uso
    for viejo in sorted(CARPETA.glob("rg_beauty_spa_*.db"))[:-CONSERVAR]:
        viejo.unlink()
    return destino


def verificar(archivo):
    con = sqlite3.connect(archivo)
    try:
        resultado = con.execute("PRAGMA integrity_check").fetchone()[0]
        tablas = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    finally:
        con.close()
    return resultado == "ok" and tablas > 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verificar":
        print("Respaldo íntegro." if verificar(sys.argv[2]) else "El respaldo tiene problemas.")
    else:
        destino = respaldar()
        print(f"Respaldo creado: {destino} ({'íntegro' if verificar(destino) else 'con problemas'})")
