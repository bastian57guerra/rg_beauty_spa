"""Configuración central del prototipo de RG Beauty Spa."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo("America/Santiago")
except Exception:  # si el equipo no tiene base de zonas horarias, se usa la hora local
    ZONA = None

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"

# Jornada de atención del salón (RF-04 y RF-11)
HORA_APERTURA = 10
HORA_CIERRE = 19
DIAS_ATENCION = (0, 1, 2, 3, 4, 5)  # 0 = lunes ... 5 = sábado
PASO_MINUTOS = 30
DIAS_MAX_ANTICIPACION = 60


def _bandera(nombre, defecto="0"):
    """Lee una variable de entorno como sí/no: acepta 1, true, si o yes (sin importar mayúsculas)."""
    return os.environ.get(nombre, defecto).strip().lower() in ("1", "true", "si", "sí", "yes")


def _clave_secreta():
    """La clave de sesión viene del entorno o se genera una sola vez y se guarda en instance/."""
    desde_entorno = os.environ.get("RG_SECRET_KEY", "").strip()
    if desde_entorno:
        return desde_entorno
    INSTANCE_DIR.mkdir(exist_ok=True)
    archivo = INSTANCE_DIR / "secret.key"
    if not archivo.exists() or not archivo.read_text(encoding="utf-8").strip():
        archivo.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(archivo, 0o600)  # solo el dueño puede leerla (en Windows no tiene efecto)
        except OSError:
            pass
    return archivo.read_text(encoding="utf-8").strip()


class Config:
    # Base de datos y clave
    DATABASE = os.environ.get("RG_DATABASE", str(INSTANCE_DIR / "rg_beauty_spa.db"))
    SECRET_KEY = _clave_secreta()

    # Sesión
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bandera("RG_COOKIE_SECURE")  # activar solo con HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

    # Límites y protección contra abuso
    MAX_CONTENT_LENGTH = 64 * 1024  # tamaño máximo de una solicitud, en bytes
    MAX_INTENTOS_LOGIN = 5
    MINUTOS_BLOQUEO = 15
    RATELIMIT_ACTIVO = True

    # Modo demostración (muestra la opción «simular pago rechazado»); apagar en producción
    MODO_DEMO = _bandera("RG_DEMO", "1")