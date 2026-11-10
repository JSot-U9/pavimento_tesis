"""
logica_respaldo.py
==================
Respaldo y restauración de la base de datos SQLite (Fase 6).

    crear_respaldo(destino=None, motivo='manual')   copia CONSISTENTE con la API de respaldo de SQLite (válida aunque la BD
                                                    esté abierta y en modo WAL); la comprueba con integrity_check
    respaldo_automatico()                           una copia por día al abrir el programa (si `respaldo_automatico`),
                                                    conservando las últimas `respaldos_a_conservar`
    listar_respaldos() · verificar_respaldo(ruta)
    restaurar_respaldo(ruta)                        verifica, GUARDA una copia de seguridad de la BD actual
                                                    («antes_de_restaurar») y reemplaza; reabre la BD

Los respaldos viven en «respaldos/» junto al archivo de la BD. Una BD en memoria no se puede respaldar.
Solo se restauran archivos que sean una BD de este programa (tablas esperadas, esquema no más nuevo que el del programa).
"""
import glob
import logging
import os
import shutil
import sqlite3
from datetime import datetime

from app import basedatos, logica_configuracion as cfg

log = logging.getLogger("pavimento.respaldo")
TABLAS_ESPERADAS = ("tramo", "roi", "ejecucion_analisis", "deteccion", "validacion", "configuracion")
PREFIJO = "pavimento_"


class ErrorRespaldo(ValueError):
    """No se puede respaldar o restaurar (BD en memoria, archivo ilegible, esquema incompatible...)."""


def _ruta_bd():
    ruta = basedatos.ruta_actual()
    if not ruta:
        raise ErrorRespaldo("La base de datos no está abierta.")
    if ruta == ":memory:":
        raise ErrorRespaldo("La base de datos está en memoria: no hay archivo que respaldar.")
    return os.path.abspath(ruta)


def carpeta_respaldos(ruta_bd=None):
    return os.path.join(os.path.dirname(os.path.abspath(ruta_bd or _ruta_bd())), "respaldos")


def _copiar(origen, destino):
    """Copia consistente origen -> destino con sqlite3.Connection.backup (no copia un -wal a medias)."""
    src = sqlite3.connect(f"file:{os.path.abspath(origen).replace(os.sep, '/')}?mode=ro", uri=True)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def verificar_respaldo(ruta):
    """{'ok', 'problemas', 'tramos', 'tamano', 'esquema'}. Nunca modifica el archivo."""
    problemas = []
    out = {"ruta": ruta, "ok": False, "problemas": problemas, "tramos": None, "esquema": None, "tamano": None}
    if not os.path.isfile(ruta):
        problemas.append("el archivo no existe")
        return out
    out["tamano"] = os.path.getsize(ruta)
    try:
        con = sqlite3.connect(f"file:{os.path.abspath(ruta).replace(os.sep, '/')}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problemas.append("la base de datos está dañada (integrity_check)")
            tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            faltan = [t for t in TABLAS_ESPERADAS if t not in tablas]
            if faltan:
                problemas.append("no es una base de datos de este programa (faltan tablas: " + ", ".join(faltan) + ")")
            else:
                out["tramos"] = con.execute("SELECT COUNT(*) FROM tramo").fetchone()[0]
            out["esquema"] = con.execute("PRAGMA user_version").fetchone()[0]
            if out["esquema"] > basedatos.VERSION_ESQUEMA:
                problemas.append(f"esquema v{out['esquema']}, más nuevo que el del programa (v{basedatos.VERSION_ESQUEMA})")
            elif 0 < out["esquema"] < basedatos.VERSION_ESQUEMA:
                problemas.append(f"esquema v{out['esquema']}: requiere migración a v{basedatos.VERSION_ESQUEMA}")
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        problemas.append(f"no es una base de datos SQLite válida ({e})")
    out["ok"] = not problemas
    return out


def crear_respaldo(destino=None, motivo="manual"):
    """Respalda la BD actual. `destino`: archivo .db o carpeta (por defecto «respaldos/» junto a la BD)."""
    origen = _ruta_bd()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{PREFIJO}{sello}_{motivo}.db"
    if destino and not os.path.isdir(destino) and os.path.splitext(destino)[1].lower() in (".db", ".sqlite", ".bak"):
        ruta = os.path.abspath(destino)
    else:
        ruta = os.path.join(destino or carpeta_respaldos(origen), nombre)
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        if os.path.abspath(ruta) == origen:
            raise ErrorRespaldo("El respaldo no puede sobrescribir la propia base de datos.")
        tmp = ruta + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        _copiar(origen, tmp)
        v = verificar_respaldo(tmp)
        if not v["ok"]:
            os.remove(tmp)
            raise ErrorRespaldo("El respaldo generado no pasó la verificación: " + "; ".join(v["problemas"]))
        os.replace(tmp, ruta)
    except PermissionError as e:
        raise ErrorRespaldo(f"No se pudo escribir el respaldo en «{ruta}»: sin permiso o archivo en uso.") from e
    except OSError as e:
        raise ErrorRespaldo(f"No se pudo escribir el respaldo en «{ruta}»: {e}") from e
    except sqlite3.Error as e:
        raise ErrorRespaldo(f"No se pudo copiar la base de datos: {e}") from e
    log.info("Respaldo creado: %s (%d bytes)", ruta, os.path.getsize(ruta))
    return {"ruta": ruta, "tamano": os.path.getsize(ruta), "tramos": v["tramos"], "fecha": sello}


def listar_respaldos(carpeta=None):
    """[{ruta, nombre, tamano, fecha}] más reciente primero."""
    carpeta = carpeta or carpeta_respaldos()
    out = []
    for r in glob.glob(os.path.join(carpeta, "*.db")):
        st = os.stat(r)
        out.append({"ruta": r, "nombre": os.path.basename(r), "tamano": st.st_size,
                    "fecha": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), "_t": st.st_mtime})
    out.sort(key=lambda x: -x["_t"])
    for x in out:
        del x["_t"]
    return out


def _rotar(carpeta, conservar):
    """Borra los respaldos AUTOMÁTICOS más antiguos (los manuales y «antes_de_restaurar» no se tocan)."""
    auto = [x for x in listar_respaldos(carpeta) if x["nombre"].endswith("_automatico.db")]
    borrados = []
    for x in auto[conservar:]:
        try:
            os.remove(x["ruta"])
            borrados.append(x["nombre"])
        except OSError:
            log.warning("No se pudo borrar el respaldo antiguo %s", x["ruta"])
    return borrados


def respaldo_automatico():
    """Crea el respaldo diario si está activado y aún no hay uno de hoy. Devuelve el dict del respaldo o None.
    Nunca lanza: un fallo del respaldo no debe impedir abrir el programa (se registra)."""
    try:
        if not cfg.obtener("respaldo_automatico") or basedatos.ruta_actual() in (None, ":memory:"):
            return None
        carpeta = carpeta_respaldos()
        hoy = datetime.now().strftime("%Y%m%d")
        if glob.glob(os.path.join(carpeta, f"{PREFIJO}{hoy}_*_automatico.db")):
            return None
        r = crear_respaldo(motivo="automatico")
        _rotar(carpeta, int(cfg.obtener("respaldos_a_conservar")))
        return r
    except Exception:                                              # noqa: BLE001
        log.exception("No se pudo crear el respaldo automático")
        return None


def restaurar_respaldo(ruta):
    """Reemplaza la BD actual por el respaldo `ruta` (verificado). Deja antes una copia «antes_de_restaurar».
    Reabre la BD restaurada. Devuelve {'restaurado', 'copia_previa', 'tramos'}."""
    destino = _ruta_bd()
    v = verificar_respaldo(ruta)
    if not v["ok"]:
        raise ErrorRespaldo("No se puede restaurar «" + os.path.basename(ruta) + "»: " + "; ".join(v["problemas"]))
    if os.path.abspath(ruta) == destino:
        raise ErrorRespaldo("El respaldo elegido es la propia base de datos abierta.")
    previa = crear_respaldo(motivo="antes_de_restaurar")
    tmp = destino + ".restaurando"
    try:
        _copiar(ruta, tmp)
        basedatos.cerrar()
        for sufijo in ("-wal", "-shm"):
            if os.path.exists(destino + sufijo):
                os.remove(destino + sufijo)
        os.replace(tmp, destino)
    except Exception as e:                                         # noqa: BLE001 - dejar la BD usable pase lo que pase
        if os.path.exists(tmp):
            os.remove(tmp)
        try:
            basedatos.inicializar(destino)
        except basedatos.ErrorBD:
            pass
        if isinstance(e, PermissionError):
            raise ErrorRespaldo("No se pudo reemplazar la base de datos: el archivo está en uso por otro programa.") from e
        raise ErrorRespaldo(f"No se pudo restaurar: {e}") from e
    basedatos.inicializar(destino)
    log.info("BD restaurada desde %s (copia previa: %s)", ruta, previa["ruta"])
    return {"restaurado": ruta, "copia_previa": previa["ruta"], "tramos": v["tramos"]}
