"""
ventana_principal.py
====================
Ventana principal (Tk + ttk, tema clam): selector de tramo activo, pestañas Tramos / Fichas / Análisis y barra
de estado. Sin login. Las pestañas comparten un `Contexto` (tramo activo y eventos de cambio).

Faltan para F5/F6 (no se implementan aquí): validación, estadística, reportes y exportación a QGIS.
"""
import logging
import os
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from app.ui import estilos
from app.ui.presentadores.base import Contexto
from app.ui.presentadores.p_tramos import PresentadorTramos
from app.ui.vista_analisis import VistaAnalisis
from app.ui.vista_fichas import VistaFichas
from app.ui.vista_tramos import VistaTramos

log = logging.getLogger("pavimento.ui")
TITULO = "Detección de deterioros en pavimentos flexibles"


class VentanaPrincipal(tk.Tk):
    def __init__(self, ruta_bd="", abrir_bd: Optional[Callable[[str], str]] = None, gestor=None, geometria="1360x820"):
        super().__init__()
        self.ruta_bd, self._abrir_bd = ruta_bd, abrir_bd
        self.ctx = Contexto()
        self.title(TITULO)
        self.geometry(geometria)
        self.minsize(1000, 640)
        estilos.aplicar(self)
        self._tramos = PresentadorTramos(self.ctx)
        self._ids = []
        self._construir_menu()
        self._construir(gestor)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.report_callback_exception = self._excepcion
        self.ctx.suscribir("tramos", lambda *_: self._cargar_tramos())
        self.ctx.suscribir("tramo_activo", lambda *_: self._sincronizar())
        self.ctx.suscribir("bd", lambda *_: self._cargar_tramos())
        self._cargar_tramos(inicial=True)

    # ---------------------------------------------------------------- construcción
    def _construir_menu(self):
        m = tk.Menu(self)
        a = tk.Menu(m, tearoff=False)
        a.add_command(label="Abrir o crear base de datos…", command=self.cambiar_bd)
        a.add_separator()
        a.add_command(label="Salir", command=self.cerrar)
        m.add_cascade(label="Archivo", menu=a)
        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Acerca de", command=self.acerca)
        m.add_cascade(label="Ayuda", menu=h)
        self.configure(menu=m)

    def _construir(self, gestor):
        top = ttk.Frame(self, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Tramo activo", style="Subtitulo.TLabel").pack(side="left")
        self.sel = tk.StringVar()
        self.combo = ttk.Combobox(top, textvariable=self.sel, state="readonly", width=44)
        self.combo.pack(side="left", padx=8)
        self.combo.bind("<<ComboboxSelected>>", self._elegido)
        ttk.Label(top, text="Herramienta de apoyo a la tesis · la severidad oficial es la de la ficha de campo",
                  style="Suave.TLabel").pack(side="right")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.v_tramos = VistaTramos(self.nb, self.ctx, ir_a_visor=self.ir_a_visor)
        self.v_fichas = VistaFichas(self.nb, self.ctx)
        self.v_analisis = VistaAnalisis(self.nb, self.ctx, gestor)
        self.nb.add(self.v_tramos, text="Tramos")
        self.nb.add(self.v_fichas, text="Fichas")
        self.nb.add(self.v_analisis, text="Análisis")
        self.estado = ttk.Label(self, text="", style="Estado.TLabel", anchor="w")
        self.estado.pack(fill="x", side="bottom")
        self._estado_bd()

    def _estado_bd(self):
        self.estado.configure(text=f"Base de datos: {os.path.abspath(self.ruta_bd) if self.ruta_bd else '—'}")

    # ---------------------------------------------------------------- tramo activo
    def _cargar_tramos(self, inicial=False):
        r = self._tramos.listar()
        tramos = r.datos or []
        self._ids = [t["id"] for t in tramos]
        self.combo.configure(values=[f"{t['codigo']} — {t['via'] or 'sin nombre'}" for t in tramos])
        if self.ctx.tramo_id not in self._ids:
            self.ctx.fijar_tramo(self._ids[0] if (inicial and self._ids) else None)
        self._sincronizar()

    def _sincronizar(self):
        if self.ctx.tramo_id in self._ids:
            self.combo.current(self._ids.index(self.ctx.tramo_id))
        else:
            self.sel.set("")

    def _elegido(self, _e=None):
        i = self.combo.current()
        if i >= 0:
            self.ctx.fijar_tramo(self._ids[i])

    def ir_a_visor(self, modo="mover"):
        self.nb.select(self.v_analisis)
        self.v_analisis.ir_a_visor(modo)

    # ---------------------------------------------------------------- menú
    def cambiar_bd(self):
        if self._abrir_bd is None:
            return
        if self.v_analisis.pres.ocupado:
            messagebox.showwarning("Base de datos", "Hay un análisis en curso: espere o cancélelo.", parent=self)
            return
        ruta = filedialog.asksaveasfilename(parent=self, title="Base de datos", defaultextension=".db",
                                            filetypes=[("SQLite", "*.db *.sqlite"), ("Todos", "*.*")],
                                            confirmoverwrite=False)
        if not ruta:
            return
        try:
            self.ruta_bd = self._abrir_bd(ruta)
        except Exception as e:                       # noqa: BLE001
            messagebox.showerror("Base de datos", f"No se pudo abrir la base de datos:\n{e}", parent=self)
            return
        self.ctx.fijar_tramo(None)
        self.ctx.emitir("bd")
        self._estado_bd()

    def acerca(self):
        messagebox.showinfo(
            "Acerca de", f"{TITULO}\n\nTesis UNSAAC, Cusco, 2026.\nVersión: Fase 4 de 7.\n\n"
            "Los umbrales del motor son PROVISIONALES (calibrados con imágenes sintéticas).\n"
            "La severidad oficial es la de la ficha de campo.", parent=self)

    # ---------------------------------------------------------------- cierre y errores
    def cerrar(self):
        if self.v_analisis.pres.ocupado and not messagebox.askyesno(
                "Salir", "Hay un análisis en curso. ¿Cancelarlo y salir?", parent=self):
            return
        try:
            self.v_analisis.cerrar()
        finally:
            self.destroy()

    def _excepcion(self, tipo, valor, tb):
        log.error("Excepción en un callback de Tk:\n%s", "".join(traceback.format_exception(tipo, valor, tb)))
        try:
            messagebox.showerror("Error inesperado", f"{tipo.__name__}: {valor}\n\nLa aplicación sigue abierta; "
                                                      f"revise el registro (consola) para más detalle.", parent=self)
        except tk.TclError:
            pass
