"""
Punto de entrada: inicializa la base de datos (ruta configurable) y abre la ventana principal. Sin login.

    python main.py                       BD por defecto: $PAVIMENTO_BD o ./datos/pavimento.db
    python main.py --bd D:\\tesis\\pavimento.db
    python main.py --log-dir D:\\tesis\\logs --verbose

El registro se guarda en un archivo rotativo (ver app/registro.py); la ventana cita su ruta si ocurre un error.
Una copia de seguridad diaria de la BD se crea al abrir (desactivable en la pestaña Reportes).
"""
import argparse
import logging
import sys


def _error_fatal(titulo, mensaje):
    print(f"{titulo}: {mensaje}", file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(titulo, mensaje)
        r.destroy()
    except Exception:                                 # noqa: BLE001 - sin pantalla: ya salió por stderr
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Detección de deterioros en pavimentos flexibles (RGB)")
    ap.add_argument("--bd", help="ruta del archivo SQLite (se crea si no existe)")
    ap.add_argument("--log-dir", help="carpeta del archivo de registro (por defecto, la carpeta de datos del usuario)")
    ap.add_argument("--verbose", action="store_true", help="registrar también mensajes de depuración")
    args = ap.parse_args(argv)
    from app import registro
    ruta_log = registro.configurar(args.log_dir, "DEBUG" if args.verbose else "INFO")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        _error_fatal("Falta Tkinter", "Instale Tkinter (Linux: sudo apt install python3-tk; Windows: reinstale "
                                      "Python marcando «tcl/tk and IDLE»).")
        return 2
    from app import basedatos
    try:
        ruta = basedatos.inicializar(args.bd)
    except basedatos.ErrorBD as e:
        logging.getLogger("pavimento").error("No se pudo abrir la base de datos: %s", e)
        _error_fatal("Base de datos", f"{e}\n\nSi la base de datos está dañada, restaure un respaldo de la carpeta "
                                      f"«respaldos» junto al archivo .db.\nRegistro: {ruta_log}")
        return 2
    from app import logica_respaldo
    logica_respaldo.respaldo_automatico()
    from app.ui import estilos
    from app.ui.ventana_principal import VentanaPrincipal
    estilos.hacer_dpi_consciente()
    try:
        app = VentanaPrincipal(ruta_bd=ruta, abrir_bd=basedatos.inicializar)
        app.mainloop()
    except Exception as e:                                # noqa: BLE001 - último recurso: registrar y avisar
        logging.getLogger("pavimento").critical("La aplicación terminó por un error", exc_info=True)
        from app import errores
        titulo, mensaje, _ = errores.describir(e, ruta_log)
        _error_fatal(titulo, mensaje)
        return 1
    finally:
        basedatos.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
