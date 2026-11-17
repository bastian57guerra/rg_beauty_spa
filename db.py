"""Acceso a la base de datos SQLite (capa de datos)."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def conectar(ruta):
    con = sqlite3.connect(ruta, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def cerrar_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(ruta):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = conectar(ruta)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.close()


@contextmanager
def transaccion(db):
    """Bloquea la escritura mientras se valida y guarda, para que dos personas
    no puedan tomar el mismo horario o el mismo stock a la vez."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
