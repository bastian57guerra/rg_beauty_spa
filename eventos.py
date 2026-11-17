"""Patrón Observer: la reserva publica un evento y los avisos se suscriben a él."""
import logging

_suscriptores = {}
log = logging.getLogger("rg.eventos")


def suscribir(evento, funcion):
    _suscriptores.setdefault(evento, []).append(funcion)


def publicar(evento, **datos):
    for funcion in _suscriptores.get(evento, []):
        try:
            funcion(**datos)
        except Exception:  # un aviso fallido nunca debe deshacer una reserva ya guardada
            log.exception("Falló el suscriptor %s del evento %s", funcion.__name__, evento)
