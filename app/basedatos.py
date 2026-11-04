"""
basedatos.py
============
Conexión a SQLite, creación del esquema y sesiones.

    inicializar(ruta)      abre (o crea) la BD; ':memory:' para pruebas
    nueva_sesion()         context manager: commit si todo va bien, rollback si hay excepción
    cerrar()

Regla de capas: solo `logica_*` usan `nueva_sesion`; las vistas no.
Hilos: SQLite y Tk no se comparten entre hilos. El hilo de trabajo SOLO calcula (núcleo); la BD se
escribe desde el hilo principal (`logica_deteccion.guardar_resultado`).
"""
import os
import sqlite3
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import modelos
from app.modelos import Base

VERSION_ESQUEMA = 1          # PRAGMA user_version; subirla exige escribir una migración

# Catálogo SEMILLA: solo los códigos cuya equivalencia con el motor es conocida. El catálogo completo de
# la Ficha 2 (21 códigos) se carga con logica_importacion.importar_csv('catalogo', ...) o desde la vista.
CATALOGO_SEMILLA = (
    ("GLO", "Grieta longitudinal", "Fisuras y grietas", "longitudinal"),
    ("GTR", "Grieta transversal", "Fisuras y grietas", "transversal"),
    ("GPC", "Grieta piel de cocodrilo", "Fisuras y grietas", "piel_cocodrilo"),
    ("HUE", "Hueco (bache)", "Desprendimientos", "bache"),
)

_engine = None
_Sesion = None
_ruta = None


class ErrorBD(Exception):
    """La base de datos no se puede abrir o tiene un esquema incompatible."""


def ruta_por_defecto():
    return os.environ.get("PAVIMENTO_BD") or os.path.join(os.getcwd(), "datos", "pavimento.db")


def inicializar(ruta=None):
    """Abre la BD (la crea si no existe), verifica la versión del esquema y siembra el catálogo."""
    global _engine, _Sesion, _ruta
    cerrar()
    ruta = ruta or ruta_por_defecto()
    en_memoria = ruta == ":memory:"
    if not en_memoria:
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    kw = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}} if en_memoria else {}
    try:
        motor = create_engine("sqlite://" if en_memoria else f"sqlite:///{ruta}", **kw)
    except Exception as e:                                       # pragma: no cover
        raise ErrorBD(f"No se pudo abrir la base de datos {ruta}: {e}") from e

    @event.listens_for(motor, "connect")
    def _pragmas(conn, _):
        if isinstance(conn, sqlite3.Connection):
            conn.isolation_level = None          # receta SQLAlchemy: SAVEPOINT correcto con pysqlite
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if not en_memoria:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    @event.listens_for(motor, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    try:
        with motor.begin() as c:
            version = c.execute(text("PRAGMA user_version")).scalar()
            if version > VERSION_ESQUEMA:
                raise ErrorBD(f"La base de datos tiene esquema v{version}, más nuevo que el de este programa "
                              f"(v{VERSION_ESQUEMA}). Actualice el programa.")
            if 0 < version < VERSION_ESQUEMA:
                raise ErrorBD(f"La base de datos tiene esquema v{version} y requiere migración a v{VERSION_ESQUEMA}.")
            Base.metadata.create_all(c)
            c.execute(text(f"PRAGMA user_version={VERSION_ESQUEMA}"))
    except ErrorBD:
        motor.dispose()
        raise
    except Exception as e:
        motor.dispose()
        raise ErrorBD(f"No se pudo abrir la base de datos {ruta}: {e}") from e
    _engine, _Sesion, _ruta = motor, sessionmaker(motor, expire_on_commit=False), ruta
    _sembrar_catalogo()
    return ruta


def _sembrar_catalogo():
    with nueva_sesion() as s:
        if s.scalar(select(modelos.CatalogoPatologia.id).limit(1)) is None:
            s.add_all(modelos.CatalogoPatologia(codigo=c, nombre=n, grupo=g, tipo_motor=t)
                      for c, n, g, t in CATALOGO_SEMILLA)


def cerrar():
    global _engine, _Sesion, _ruta
    if _engine is not None:
        _engine.dispose()
    _engine = _Sesion = _ruta = None


def ruta_actual():
    return _ruta


@contextmanager
def nueva_sesion():
    if _Sesion is None:
        raise ErrorBD("La base de datos no está inicializada: llame a basedatos.inicializar()")
    s = _Sesion()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()
