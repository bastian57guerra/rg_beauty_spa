"""Validación de los datos que ingresa el usuario (lado servidor)."""
import re
from datetime import date, datetime

COMUNES = {"password", "contraseña", "1234567890", "qwerty12345", "admin12345", "rgbeauty123"}

RE_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]{1,79}$")
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
RE_TEL = re.compile(r"^(?:\+?56)?9\d{8}$")
RE_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ErrorValidacion(ValueError):
    pass


def _limpio(valor):
    texto = re.sub(r"[\x00-\x1f\x7f]", " ", str(valor if valor is not None else ""))
    return " ".join(texto.split())


def texto(valor, campo, minimo=1, maximo=120):
    v = _limpio(valor)
    if not minimo <= len(v) <= maximo:
        raise ErrorValidacion(f"{campo}: debe tener entre {minimo} y {maximo} caracteres.")
    return v


def nombre_persona(valor, campo="Nombre"):
    v = _limpio(valor)
    if not RE_NOMBRE.match(v):
        raise ErrorValidacion(f"{campo}: use solo letras y espacios (entre 2 y 80 caracteres).")
    return v


def telefono(valor, campo="Teléfono"):
    v = re.sub(r"[ \-()]", "", str(valor or ""))
    if not RE_TEL.match(v):
        raise ErrorValidacion(f"{campo}: ingrese un celular chileno válido, por ejemplo +56 9 1234 5678.")
    return "+56" + v[-9:]


def email(valor, campo="Correo", obligatorio=False):
    v = _limpio(valor).lower()
    if not v:
        if obligatorio:
            raise ErrorValidacion(f"{campo}: es obligatorio.")
        return None
    if len(v) > 120 or not RE_EMAIL.match(v):
        raise ErrorValidacion(f"{campo}: no tiene un formato válido.")
    return v


def entero(valor, campo, minimo, maximo):
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ErrorValidacion(f"{campo}: debe ser un número entero.")
    if not minimo <= n <= maximo:
        raise ErrorValidacion(f"{campo}: debe estar entre {minimo} y {maximo}.")
    return n


def fecha(valor, campo="Fecha"):
    try:
        return datetime.strptime(str(valor or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ErrorValidacion(f"{campo}: use el formato AAAA-MM-DD.")


def fecha_hora(valor, campo="Horario"):
    try:
        return datetime.strptime(str(valor or "").strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise ErrorValidacion(f"{campo}: no es válido.")


def hora(valor, campo="Hora"):
    v = str(valor or "").strip()
    if not RE_HORA.match(v):
        raise ErrorValidacion(f"{campo}: use el formato HH:MM.")
    return v


def opcion(valor, campo, permitidos):
    v = str(valor or "").strip()
    if v not in permitidos:
        raise ErrorValidacion(f"{campo}: la opción elegida no es válida.")
    return v


def password_valida(clave):
    """Política de contraseñas: mínimo 10 caracteres, con letras y números."""
    c = str(clave or "")
    if len(c) < 10 or len(c) > 128:
        raise ErrorValidacion("La contraseña debe tener entre 10 y 128 caracteres.")
    if not re.search(r"[A-Za-z]", c) or not re.search(r"\d", c):
        raise ErrorValidacion("La contraseña debe combinar letras y números.")
    if c.lower() in COMUNES:
        raise ErrorValidacion("La contraseña elegida es demasiado común.")
    return c


class Form:
    """Recorre un formulario acumulando todos los errores en una sola pasada."""

    def __init__(self, datos):
        self.datos = datos
        self.errores = []

    def get(self, campo, funcion, *args, **kw):
        try:
            return funcion(self.datos.get(campo, ""), *args, **kw)
        except ErrorValidacion as e:
            self.errores.append(str(e))
            return None

    def marcado(self, campo):
        return self.datos.get(campo) == "on"

    @property
    def valido(self):
        return not self.errores
