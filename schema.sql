-- Script de creación de la base de datos de RG Beauty Spa (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profesionales (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 80),
    activo  INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS usuarios (
    id                INTEGER PRIMARY KEY,
    nombre            TEXT NOT NULL,
    email             TEXT NOT NULL UNIQUE,
    password_hash     TEXT NOT NULL,
    rol               TEXT NOT NULL CHECK (rol IN ('administrador', 'recepcionista', 'profesional')),
    profesional_id    INTEGER REFERENCES profesionales(id),
    activo            INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    intentos_fallidos INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta   TEXT,
    creado_en         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clientes (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL,
    telefono      TEXT NOT NULL,
    email         TEXT,
    consentimiento INTEGER NOT NULL DEFAULT 0 CHECK (consentimiento IN (0, 1)),
    anonimizado   INTEGER NOT NULL DEFAULT 0 CHECK (anonimizado IN (0, 1)),
    creado_en     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_clientes_telefono ON clientes(telefono) WHERE anonimizado = 0;

CREATE TABLE IF NOT EXISTS servicios (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL UNIQUE,
    duracion_min  INTEGER NOT NULL CHECK (duracion_min BETWEEN 15 AND 480),
    precio        INTEGER NOT NULL CHECK (precio >= 0),
    activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS profesional_servicio (
    profesional_id INTEGER NOT NULL REFERENCES profesionales(id) ON DELETE CASCADE,
    servicio_id    INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
    PRIMARY KEY (profesional_id, servicio_id)
);

CREATE TABLE IF NOT EXISTS promociones (
    id             INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL,
    descuento_pct  INTEGER NOT NULL CHECK (descuento_pct BETWEEN 1 AND 90),
    dias           TEXT NOT NULL,              -- días de la semana separados por coma (0 = lunes)
    hora_desde     TEXT NOT NULL,              -- HH:MM
    hora_hasta     TEXT NOT NULL,              -- HH:MM
    fecha_desde    TEXT NOT NULL,              -- AAAA-MM-DD
    fecha_hasta    TEXT NOT NULL,
    activa         INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
    CHECK (fecha_desde <= fecha_hasta),
    CHECK (hora_desde < hora_hasta)
);

CREATE TABLE IF NOT EXISTS reservas (
    id              INTEGER PRIMARY KEY,
    codigo          TEXT NOT NULL UNIQUE,
    cliente_id      INTEGER NOT NULL REFERENCES clientes(id),
    profesional_id  INTEGER NOT NULL REFERENCES profesionales(id),
    servicio_id     INTEGER NOT NULL REFERENCES servicios(id),
    inicio          TEXT NOT NULL,             -- AAAA-MM-DD HH:MM
    fin             TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'Confirmada'
                    CHECK (estado IN ('Confirmada', 'Cancelada', 'Atendida', 'No asistió')),
    origen          TEXT NOT NULL CHECK (origen IN ('web', 'recepcion')),
    promocion_id    INTEGER REFERENCES promociones(id),
    precio_final    INTEGER NOT NULL CHECK (precio_final >= 0),
    creada_en       TEXT NOT NULL,
    CHECK (inicio < fin)
);
CREATE INDEX IF NOT EXISTS ix_reservas_prof_inicio ON reservas(profesional_id, inicio);

CREATE TABLE IF NOT EXISTS avisos (
    id          INTEGER PRIMARY KEY,
    reserva_id  INTEGER NOT NULL REFERENCES reservas(id),
    tipo        TEXT NOT NULL CHECK (tipo IN ('confirmacion', 'recordatorio', 'reprogramacion', 'cancelacion')),
    canal       TEXT NOT NULL CHECK (canal IN ('correo', 'sms')),
    destino     TEXT NOT NULL,
    mensaje     TEXT NOT NULL,
    estado      TEXT NOT NULL,
    creado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS productos (
    id           INTEGER PRIMARY KEY,
    nombre       TEXT NOT NULL,
    descripcion  TEXT,
    precio       INTEGER NOT NULL CHECK (precio >= 0),
    stock        INTEGER NOT NULL CHECK (stock >= 0),
    activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS pedidos (
    id                  INTEGER PRIMARY KEY,
    codigo              TEXT NOT NULL UNIQUE,
    comprador_nombre    TEXT NOT NULL,
    comprador_telefono  TEXT NOT NULL,
    comprador_email     TEXT,
    total               INTEGER NOT NULL CHECK (total >= 0),
    medio_pago          TEXT NOT NULL,
    pago_ref            TEXT NOT NULL,
    estado              TEXT NOT NULL CHECK (estado IN ('Pagado')),
    fuera_horario       INTEGER NOT NULL CHECK (fuera_horario IN (0, 1)),
    creado_en           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detalle_pedido (
    id           INTEGER PRIMARY KEY,
    pedido_id    INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    producto_id  INTEGER NOT NULL REFERENCES productos(id),
    cantidad     INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unit  INTEGER NOT NULL CHECK (precio_unit >= 0)
);

CREATE TABLE IF NOT EXISTS auditoria (
    id          INTEGER PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuarios(id),
    accion      TEXT NOT NULL,
    detalle     TEXT,
    ip          TEXT,
    creado_en   TEXT NOT NULL
);
