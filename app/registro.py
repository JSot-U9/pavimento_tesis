"""
registro.py
===========
Registro (log) a archivo de la aplicación (Fase 6).

    configurar(directorio=None, nivel='INFO', consola=True) -> ruta del archivo
        Archivo rotativo «pavimento_tesis.log» (1 MB × 5 copias, UTF-8) en `directorio`; por defecto
        $PAVIMENTO_LOG_DIR, y si no, la carpeta de datos de la aplicación del usuario:
            Windows  %LOCALAPPDATA%\\pavimento_tesis\\logs      Linux/macOS  ~/.local/state/pavimento_tesis/logs
        Si esa carpeta no se puede escribir se usa la carpeta temporal del sistema. Instala además ganchos para que las
        excepciones no capturadas (hilo principal y de trabajo) queden en el registro con su traza. Exporta la ruta en
        la variable de entorno PAVIMENTO_LOG (la ventana la cita en los mensajes de error).
    carpeta_por_defecto()
"""
import logging
import logging.handlers
import os
import sys
import tempfile
import threading

NOMBRE = "pavimento_tesis.log"
FORMATO = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
_MARCA = "_pavimento_handler"


def carpeta_por_defecto():
    if os.environ.get("PAVIMENTO_LOG_DIR"):
        return os.environ["PAVIMENTO_LOG_DIR"]
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "pavimento_tesis", "logs")
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "pavimento_tesis", "logs")


def _carpeta_escribible(carpeta):
    try:
        os.makedirs(carpeta, exist_ok=True)
        prueba = os.path.join(carpeta, ".escritura")
        with open(prueba, "w") as f:
            f.write("x")
        os.remove(prueba)
        return carpeta
    except OSError:
        return None


def configurar(directorio=None, nivel="INFO", consola=True):
    carpeta = _carpeta_escribible(directorio or carpeta_por_defecto()) or _carpeta_escribible(
        os.path.join(tempfile.gettempdir(), "pavimento_tesis_logs"))
    raiz = logging.getLogger()
    for h in list(raiz.handlers):                              # idempotente: quita los de una llamada anterior
        if getattr(h, _MARCA, False):
            raiz.removeHandler(h)
            h.close()
    raiz.setLevel(getattr(logging, str(nivel).upper(), logging.INFO))
    fmt = logging.Formatter(FORMATO)
    ruta = None
    if carpeta:
        ruta = os.path.join(carpeta, NOMBRE)
        fh = logging.handlers.RotatingFileHandler(ruta, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        setattr(fh, _MARCA, True)
        raiz.addHandler(fh)
        os.environ["PAVIMENTO_LOG"] = ruta
    if consola:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        setattr(ch, _MARCA, True)
        raiz.addHandler(ch)
    log = logging.getLogger("pavimento")

    def _no_capturada(tipo, valor, tb):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, tb)
            return
        log.critical("Excepción no capturada", exc_info=(tipo, valor, tb))

    def _en_hilo(args):
        if args.exc_type is SystemExit:
            return
        log.critical("Excepción no capturada en el hilo %s", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _no_capturada
    threading.excepthook = _en_hilo
    log.info("Registro iniciado: %s", ruta or "(sin archivo: no hay carpeta escribible)")
    return ruta
