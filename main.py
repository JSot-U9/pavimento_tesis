"""
Punto de entrada: inicializa la base de datos (ruta configurable) y abre la ventana principal. Sin login.

    python main.py                       BD por defecto: $PAVIMENTO_BD o ./datos/pavimento.db
    python main.py --bd D:\\tesis\\pavimento.db
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
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
        _error_fatal("Base de datos", str(e))
        return 2
    from app.ui import estilos
    from app.ui.ventana_principal import VentanaPrincipal
    estilos.hacer_dpi_consciente()
    app = VentanaPrincipal(ruta_bd=ruta, abrir_bd=basedatos.inicializar)
    app.mainloop()
    basedatos.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
