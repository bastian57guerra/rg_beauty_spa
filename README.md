# Sistema de Gestión de Reservas y Venta Remota · RG Beauty Spa

Prototipo funcional de la **Evaluación 3** de Ingeniería de Software (INACAP Sede Copiapó, Primavera 2026).
Aplicación web con agenda de reservas sin traslapes, tienda en línea, promociones para horarios de baja demanda e indicadores para la administración.

**Integrantes:** Leandro Vasquez, Bastian Guerra, Said Rojas · **Docente:** Williams Álvarez Cerda

## Tecnología
Python 3.10 o superior · Flask 3 (servidor web y plantillas) · SQLite (base de datos) · HTML y CSS propios (sin librerías externas).

## Cómo ejecutarlo

```bash
# 1. Crear y activar un entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux o macOS

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Crear la base de datos con datos de demostración
python seed.py                  # usa schema.sql; con --reset la vuelve a crear desde cero

# 4. Iniciar el sistema
python app.py                   # abrir http://127.0.0.1:5000
```

El script de creación de la base de datos es `schema.sql` (12 tablas). `seed.py` lo ejecuta y carga servicios, profesionales, clientas, productos, una promoción, reservas de las últimas cuatro semanas y pedidos de ejemplo.

## Usuarios de demostración
Contraseña de todos: `RgBeauty#2026` (solo para pruebas; se puede cambiar con la variable `RG_DEMO_PASSWORD` antes de ejecutar `seed.py`, y cada persona puede cambiarla en «Mi clave»).

| Perfil | Correo | Qué puede hacer |
|---|---|---|
| Administrador | admin@rgbeautyspa.cl | Todo: catálogos, promociones, indicadores, ventas, auditoría |
| Recepcionista | recepcion@rgbeautyspa.cl | Clientas, reservas (crear, cancelar, reprogramar), avisos |
| Profesional | rosario@rgbeautyspa.cl (también camila@ y daniela@) | Su propia agenda y registro de atención |

Las clientas no necesitan cuenta: reservan y compran desde el sitio público (`/reservar` y `/tienda`).

## Pruebas automáticas
```bash
python -m unittest discover -s tests -v     # 42 pruebas
```
Cubren reglas de reservas (traslapes, reprogramación, concurrencia), tienda (stock, pago rechazado), indicadores, validaciones, autenticación, control de roles, CSRF, inyección SQL, XSS, cabeceras de seguridad y respaldo.

## Respaldo (RNF-05)
```bash
python backup.py                          # crea un respaldo en backups/ y comprueba su integridad
python backup.py --verificar ARCHIVO.db   # verifica un respaldo existente
```

## Estructura
```
app.py              Fábrica de la aplicación, errores y cabeceras
config.py           Parámetros (jornada, sesión, bloqueo de cuenta)
schema.sql          Script de creación de la base de datos
seed.py             Datos de demostración
backup.py           Respaldo y verificación
db.py               Acceso a datos y transacciones
security.py         CSRF, roles, límite de solicitudes, auditoría, cabeceras
validacion.py       Validadores de datos de entrada
eventos.py          Patrón Observer
blueprints/         Rutas: public.py (clientas), auth.py (sesión), panel.py (personal)
services/           Reglas del negocio: reservas, avisos, pedidos, indicadores
templates/ static/  Interfaz (vistas y estilos)
tests/              Pruebas automáticas
```

## Configuración para producción
Copiar `.env.example` y definir `RG_SECRET_KEY`, `RG_COOKIE_SECURE=1` (con HTTPS) y `RG_DEMO=0`. No usar el servidor de desarrollo: ejecutar con un servidor WSGI (por ejemplo `gunicorn "app:create_app()"`) detrás de HTTPS.

## Alcance y limitaciones del prototipo
- Los avisos (confirmación y recordatorio) se **registran** en la base de datos; el envío real por correo o SMS queda para la siguiente etapa.
- La pasarela de pago es de **prueba (sandbox)**: no pide ni guarda datos de tarjetas.
- No incluye la aplicación móvil nativa ni la lista de espera automática (RF-13, definido como «No por ahora»).
