"""
errores.py
==========
Mensajes de error CLAROS para la persona usuaria (Fase 6). `describir(exc)` devuelve (titulo, mensaje, detalle):

    titulo    corto, para la barra del diálogo
    mensaje   qué pasó y qué hacer, en español y sin jerga
    detalle   tipo de excepción y texto técnico (va al log; la ventana lo muestra solo si se pide)

Los errores propios del programa (ErrorValidacion, ErrorBD, ErrorReporte...) ya traen su mensaje: se respetan. Los
errores del sistema (disco lleno, archivo bloqueado, falta de memoria, falta de librerías) se traducen. Ninguna
excepción sale sin mensaje: lo desconocido se describe como «error inesperado» y apunta al archivo de registro.
"""
import errno
import sqlite3

from app.logica_comun import ErrorNoEncontrado, ErrorValidacion


def _nombre(e):
    return f"{type(e).__module__}.{type(e).__name__}"


def describir(exc, ruta_log=None):
    detalle = f"{_nombre(exc)}: {exc}"
    donde = f" Detalles técnicos en el archivo de registro: {ruta_log}" if ruta_log else ""
    if isinstance(exc, ErrorValidacion):
        return "Datos no válidos", "\n".join(f"{k + ': ' if k else ''}{v}" for k, v in exc.errores.items()) or str(exc), detalle
    if isinstance(exc, ErrorNoEncontrado):
        return "No encontrado", str(exc), detalle
    nombre = type(exc).__name__
    if nombre in ("ErrorBD", "ErrorRespaldo", "ErrorReporte", "ErrorExportacion", "ErrorFormatoGeo", "ErrorCRS",
                  "ErrorLectura"):
        return {"ErrorBD": "Base de datos", "ErrorRespaldo": "Respaldo", "ErrorReporte": "Reporte",
                "ErrorExportacion": "Exportación", "ErrorFormatoGeo": "Capa vectorial", "ErrorCRS": "Sistema de coordenadas",
                "ErrorLectura": "Ortomosaico"}[nombre], str(exc), detalle
    if isinstance(exc, MemoryError):
        return ("Memoria insuficiente",
                "El programa se quedó sin memoria. Analice una ROI o una ventana más pequeña, o aumente el tamaño de "
                "tesela en la configuración, y cierre otros programas." + donde, detalle)
    if isinstance(exc, PermissionError):
        return ("Sin permiso o archivo en uso",
                "No se pudo leer o escribir un archivo: está abierto en otro programa (por ejemplo Excel, QGIS o un "
                "visor de PDF) o la carpeta no permite escribir. Ciérrelo o elija otra ubicación." + donde, detalle)
    if isinstance(exc, FileNotFoundError):
        return ("Archivo no encontrado",
                f"No existe el archivo o la carpeta «{getattr(exc, 'filename', '') or exc}». Si lo movió o lo borró, "
                f"vuelva a asignarlo." + donde, detalle)
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "Disco lleno", "No hay espacio en el disco. Libere espacio o elija otra unidad." + donde, detalle
    if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
        return ("Base de datos en uso",
                "La base de datos está bloqueada por otro programa o por otra copia de esta aplicación. Ciérrelos e "
                "intente de nuevo." + donde, detalle)
    if isinstance(exc, sqlite3.DatabaseError):
        return ("Base de datos dañada",
                "SQLite no puede leer la base de datos. Restaure un respaldo desde Archivo > Restaurar respaldo." + donde,
                detalle)
    if isinstance(exc, ImportError):
        return ("Falta una librería",
                f"Falta instalar «{getattr(exc, 'name', None) or exc}». Ejecute: pip install -r requirements.txt" + donde,
                detalle)
    if isinstance(exc, OSError):
        return "Error de archivo", f"No se pudo completar la operación con el archivo: {exc}." + donde, detalle
    return ("Error inesperado",
            f"Ocurrió un error que el programa no esperaba ({nombre}: {exc}). Si el problema se repite, copie el "
            f"mensaje y revise el archivo de registro." + donde, detalle)
