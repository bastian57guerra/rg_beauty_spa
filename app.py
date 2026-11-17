"""Sistema de Gestión de Reservas y Venta Remota - RG Beauty Spa (prototipo, Evaluación 3)."""
import logging

from flask import Flask, render_template

import config
import db as basedatos
import security
from validacion import ErrorValidacion  # noqa: F401  (se reexporta para las rutas)


def clp(valor):
    return "$" + f"{int(valor):,}".replace(",", ".")


def fecha_cl(txt):
    s = str(txt)[:10]
    return f"{s[8:10]}-{s[5:7]}-{s[0:4]}"


def hora_cl(txt):
    return str(txt)[11:16]


MENSAJES_ERROR = {
    403: "No tiene permiso para ver esta página.",
    404: "La página que busca no existe.",
    405: "Esa acción no está permitida en esta página.",
    413: "Los datos enviados son demasiado grandes.",
    429: "Hay demasiadas solicitudes. Espere un momento.",
}


def create_app(configuracion=None):
    app = Flask(__name__)
    app.config.from_object(config.Config)
    if configuracion:
        app.config.update(configuracion)

    app.teardown_appcontext(basedatos.cerrar_db)
    app.before_request(security.cargar_usuario)
    app.before_request(security.verificar_csrf)
    app.after_request(security.cabeceras)
    app.jinja_env.filters["clp"] = clp
    app.jinja_env.filters["fecha_cl"] = fecha_cl
    app.jinja_env.filters["hora_cl"] = hora_cl
    app.jinja_env.globals["csrf_token"] = security.csrf_token

    from blueprints.auth import bp as auth_bp
    from blueprints.panel import bp as panel_bp
    from blueprints.public import bp as public_bp
    import services.avisos  # noqa: F401  (registra los suscriptores de eventos)
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(panel_bp)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error_controlado(e):
        # El 400 trae su propio texto (por ejemplo, el aviso de CSRF); los demás usan mensajes fijos.
        detalle = e.description if e.code == 400 else MENSAJES_ERROR[e.code]
        return render_template("error.html", codigo=e.code, mensaje=detalle), e.code

    @app.errorhandler(500)
    def error_interno(e):
        logging.getLogger("rg").exception("Error interno")
        return render_template("error.html", codigo=500,
                               mensaje="Ocurrió un problema. Intente nuevamente en unos minutos."), 500

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
