"""
ventana_principal.py
====================
Ventana principal (Tk + ttk, tema clam): selector de tramo activo, pestañas Tramos / Fichas / Análisis / Validación / Estadística y barra
de estado. Sin login. Las pestañas comparten un `Contexto` (tramo activo y eventos de cambio).

F5 añade las pestañas Validación (con referencias geométricas y calibración) y Estadística; F6, la pestaña Reportes
(PDF/XLSX/CSV, exportación a QGIS, respaldo de la BD). F7 añade la pestaña Métodos (comparación 'actual' vs 'sun').
"""
import logging
import os
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from app import logica_tutorial
from app.ui.presentadores.p_tutorial import debe_ofrecer, recordar_no_preguntar
from app.ui.dialogo_tutorial import DialogoOfertaTutorial
from app.ui import estilos
from app.ui.panel_tutorial import PanelTutorial
from app.ui.presentadores.base import Contexto
from app.ui.presentadores.p_tramos import PresentadorTramos
from app.ui.presentadores.p_tutorial import PresentadorTutorial
from app.ui.vista_analisis import VistaAnalisis
from app.ui.vista_comparacion import VistaComparacion
from app.ui.vista_estadistica import VistaEstadistica
from app.ui.vista_fichas import VistaFichas
from app.ui.vista_reportes import VistaReportes
from app.ui.vista_tramos import VistaTramos
from app.ui.vista_validacion import VistaValidacion

log = logging.getLogger("pavimento.ui")
TITULO = "Detección de deterioros en pavimentos flexibles"


class VentanaPrincipal(tk.Tk):
    def __init__(self, ruta_bd="", abrir_bd: Optional[Callable[[str], str]] = None, gestor=None, geometria="1360x820",
                 gestor_calculos=None, gestor_reportes=None, gestor_metodos=None):
        super().__init__()
        self.ruta_bd, self._abrir_bd = ruta_bd, abrir_bd
        self.panel_tutorial = None            # PanelTutorial mientras el modo tutorial está activo
        self._bd_real = None                  # BD que se restaura al salir del tutorial
        self._rutas_tut = None
        self.ctx = Contexto()
        self.title(TITULO)
        self.geometry(geometria)
        self.minsize(1000, 640)
        estilos.aplicar(self)
        self._tramos = PresentadorTramos(self.ctx)
        self._ids = []
        self._construir_menu()
        self._construir(gestor, gestor_calculos, gestor_reportes, gestor_metodos)
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
        a.add_command(label="Respaldo y restauración…", command=self.ir_a_reportes)
        a.add_separator()
        a.add_command(label="Salir", command=self.cerrar)
        m.add_cascade(label="Archivo", menu=a)
        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Tutorial guiado con datos de ejemplo…", command=self.iniciar_tutorial)
        h.add_command(label="Salir del tutorial", command=self.salir_tutorial, state="disabled")
        h.add_separator()
        h.add_command(label="Acerca de", command=self.acerca)
        self._menu_ayuda = h
        m.add_cascade(label="Ayuda", menu=h)
        self.configure(menu=m)

    def _construir(self, gestor, gestor_calculos=None, gestor_calculos_reportes=None, gestor_metodos=None):
        top = ttk.Frame(self, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Tramo activo", style="Subtitulo.TLabel").pack(side="left")
        self.sel = tk.StringVar()
        self.combo = ttk.Combobox(top, textvariable=self.sel, state="readonly", width=44)
        self.combo.pack(side="left", padx=8)
        self.combo.bind("<<ComboboxSelected>>", self._elegido)
        self.btn_tutorial = ttk.Button(top, text="Tutorial (F1)", style="Accion.TButton", command=self.iniciar_tutorial)
        self.btn_tutorial.pack(side="right", padx=(8, 0))
        ttk.Label(top, text="Herramienta de apoyo a la tesis · la severidad oficial es la de la ficha de campo",
                  style="Suave.TLabel").pack(side="right")
        self.bind("<F1>", lambda e: self.iniciar_tutorial())
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.v_tramos = VistaTramos(self.nb, self.ctx, ir_a_visor=self.ir_a_visor)
        self.v_fichas = VistaFichas(self.nb, self.ctx)
        self.v_analisis = VistaAnalisis(self.nb, self.ctx, gestor)
        self.nb.add(self.v_tramos, text="Tramos")
        self.nb.add(self.v_fichas, text="Fichas")
        self.v_validacion = VistaValidacion(self.nb, self.ctx, gestor_calculos)
        self.v_estadistica = VistaEstadistica(self.nb, self.ctx)
        self.v_reportes = VistaReportes(self.nb, self.ctx, gestor_calculos_reportes)
        self.nb.add(self.v_analisis, text="Análisis")
        self.nb.add(self.v_validacion, text="Validación")
        self.nb.add(self.v_estadistica, text="Estadística")
        self.v_metodos = VistaComparacion(self.nb, self.ctx, gestor_metodos)
        self.nb.add(self.v_metodos, text="Métodos")
        self.nb.add(self.v_reportes, text="Reportes")
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

    def ir_a_reportes(self):
        self.nb.select(self.v_reportes)

    def _ocupado(self):
        return self.v_analisis.pres.ocupado or self.v_validacion.pc.ocupado or self.v_reportes.pres.ocupado or self.v_metodos.pres.ocupado

    def ir_a_visor(self, modo="mover"):
        self.nb.select(self.v_analisis)
        self.v_analisis.ir_a_visor(modo)

    # ---------------------------------------------------------------- menú
    def cambiar_bd(self):
        if self._abrir_bd is None:
            return
        if self._ocupado():
            messagebox.showwarning("Base de datos", "Hay un análisis, una calibración o un reporte en curso: espere o cancélelo.",
                                   parent=self)
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
            "Acerca de", f"{TITULO}\n\nTesis UNSAAC, Cusco, 2026.\nVersión: Fase 7 de 7 + modo tutorial.\n\n"
            "Los umbrales del motor son PROVISIONALES (calibrados con imágenes sintéticas).\n"
            "La severidad oficial es la de la ficha de campo.", parent=self)

    # ---------------------------------------------------------------- modo tutorial
    def _hay_bd_real(self):
        return bool(self.ruta_bd) and self.ruta_bd != ":memory:"

    def iniciar_tutorial(self, confirmar=True):
        """Abre la base de datos de PRÁCTICA (con el ejemplo sintético) y muestra el panel guiado. Los datos reales no
        se tocan: al salir se vuelve a abrir la base de datos que estaba en uso."""
        if self.panel_tutorial is not None:
            return
        if self._abrir_bd is None or not self._hay_bd_real():
            messagebox.showinfo("Tutorial", "El tutorial necesita una base de datos en archivo para poder volver a ella al "
                                            "salir. Abra o cree una con «Archivo ▸ Abrir o crear base de datos».", parent=self)
            return
        if self._ocupado():
            messagebox.showwarning("Tutorial", "Hay un análisis, una calibración o un reporte en curso: espere o cancélelo.",
                                   parent=self)
            return
        if confirmar and not messagebox.askyesno(
                "Tutorial guiado",
                "El tutorial usa una base de datos de PRÁCTICA con un ejemplo sintético; sus datos reales no se tocan y "
                "puede volver a ellos con «Salir del tutorial».\n\n¿Iniciar el tutorial?", parent=self):
            return
        self._bd_real = self.ruta_bd
        self._abrir_tutorial(logica_tutorial.carpeta_tutorial(self.ruta_bd))

    def ofrecer_tutorial(self):
        """Al abrir el programa con la base de datos vacía (usuario nuevo) pregunta si quiere hacer el tutorial. Responde:
        «Sí» lo inicia, «Ahora no» vuelve a preguntar la próxima vez y «No volver a preguntar» lo recuerda en la BD.
        El tutorial siempre se puede abrir después con el botón «Tutorial», F1 o el menú Ayuda."""
        if self.panel_tutorial is not None or self._abrir_bd is None or not self._hay_bd_real():
            return None
        if not debe_ofrecer():
            return None
        eleccion = DialogoOfertaTutorial(self).abrir()
        if eleccion == "no_preguntar":
            recordar_no_preguntar()
        elif eleccion == "si":
            self.iniciar_tutorial(confirmar=False)
        return eleccion

    def _abrir_tutorial(self, carpeta):
        try:
            self._rutas_tut = logica_tutorial.preparar(carpeta)
            self.ruta_bd = self._abrir_bd(self._rutas_tut["bd"])
        except Exception as e:                       # noqa: BLE001 - volver a la BD real y avisar
            log.error("No se pudo preparar el tutorial", exc_info=True)
            self._restaurar_bd_real()
            messagebox.showerror("Tutorial", f"No se pudo preparar el tutorial:\n{e}", parent=self)
            return
        self.ctx.modo_tutorial = True
        self.ctx.fijar_tramo(None)
        self.ctx.emitir("bd")
        self._estado_bd()
        self.title(f"{TITULO} — MODO TUTORIAL")
        self._menu_ayuda.entryconfigure("Salir del tutorial", state="normal")
        self._menu_ayuda.entryconfigure("Tutorial guiado con datos de ejemplo…", state="disabled")
        self.btn_tutorial.state(["disabled"])
        vr = self.v_reportes
        vr.v_carpeta.set(self._rutas_tut["reportes"])
        vr.v_autor.set("Estudiante (tutorial)")
        vr.v_inst.set("UNSAAC")
        pres = PresentadorTutorial(self.ctx, carpeta, self._acciones_tutorial())
        self.panel_tutorial = PanelTutorial(self, pres, self._tutorial_paso, self._tutorial_hacer, self.salir_tutorial,
                                            self.reiniciar_tutorial, self._ocupado)
        self.panel_tutorial.pack(side="right", fill="y", before=self.nb, padx=(0, 6), pady=6)

    def _cerrar_panel_tutorial(self):
        if self.panel_tutorial is not None:
            self.panel_tutorial.cerrar()
            self.panel_tutorial.destroy()
            self.panel_tutorial = None

    def _restaurar_bd_real(self):
        if self._bd_real and self._abrir_bd is not None:
            self.ruta_bd = self._abrir_bd(self._bd_real)
        self.ctx.modo_tutorial = False
        self.ctx.fijar_tramo(None)
        self.ctx.emitir("bd")
        self._estado_bd()
        self.title(TITULO)

    def salir_tutorial(self, confirmar=True):
        if self.panel_tutorial is None:
            return
        if self._ocupado():
            messagebox.showwarning("Tutorial", "Hay un análisis, una calibración o un reporte en curso: espere o cancélelo.",
                                   parent=self)
            return
        if confirmar and not messagebox.askyesno("Salir del tutorial", "Se vuelve a su base de datos real. ¿Salir del tutorial?",
                                                 parent=self):
            return
        self._cerrar_panel_tutorial()
        self._restaurar_bd_real()
        self._bd_real = None
        self._menu_ayuda.entryconfigure("Salir del tutorial", state="disabled")
        self._menu_ayuda.entryconfigure("Tutorial guiado con datos de ejemplo…", state="normal")
        self.btn_tutorial.state(["!disabled"])

    def reiniciar_tutorial(self, confirmar=True):
        if self.panel_tutorial is None:
            return
        if self._ocupado():
            messagebox.showwarning("Tutorial", "Hay un análisis, una calibración o un reporte en curso: espere o cancélelo.",
                                   parent=self)
            return
        if confirmar and not messagebox.askyesno("Reiniciar el tutorial", "Se borra la práctica y se empieza de nuevo. "
                                                 "¿Reiniciar?", parent=self):
            return
        carpeta = self._rutas_tut["carpeta"]
        self._cerrar_panel_tutorial()
        self._abrir_tutorial(carpeta)

    def _tutorial_paso(self, paso):
        """Lleva al usuario a la pestaña (y subpestaña) del paso."""
        vistas = {"tramos": self.v_tramos, "analisis": self.v_analisis, "validacion": self.v_validacion,
                  "estadistica": self.v_estadistica, "metodos": self.v_metodos, "reportes": self.v_reportes}
        if paso.pestana in vistas:
            self.nb.select(vistas[paso.pestana])
        if paso.pestana == "analisis":
            a = self.v_analisis
            a.nb.select(a.panel_roi if paso.id in ("rois", "roles") else 0)

    def _tutorial_hacer(self):
        r = self.panel_tutorial.pres.hacer()
        if not r.ok:
            self.panel_tutorial.mostrar_aviso(r.texto_errores() or r.mensaje, "error")
        elif r.advertencias:
            self.panel_tutorial.mostrar_aviso("\n".join(r.advertencias), "aviso")

    def _acciones_tutorial(self):
        """«Hacerlo por mí»: maneja las vistas REALES con las mismas funciones que sus botones, para que el usuario vea
        el formulario llenarse y el resultado aparecer."""
        R = lambda: self._rutas_tut                                    # noqa: E731 - cambia al reiniciar
        a = self.v_analisis

        def crear_tramo():
            vt = self.v_tramos
            self.nb.select(vt)
            vt.nuevo()
            for k, v in logica_tutorial.DATOS_TRAMO.items():
                vt.form.poner(k, str(v))
            self.update_idletasks()
            vt.guardar()

        def asignar_ortomosaico():
            vt = self.v_tramos
            self.nb.select(vt)
            vt.ruta.set(R()["ortomosaico"])
            vt.gsd.set("0.5")
            self.update_idletasks()
            vt.asignar()

        def importar_eje():
            self.nb.select(self.v_tramos)
            return self._tramos.importar_eje(self.ctx.tramo_id, R()["eje"])

        def importar_rois():
            self.nb.select(a)
            a.nb.select(a.panel_roi)
            return a.panel_roi.pres.importar(self.ctx.tramo_id, R()["rois"], dict(logica_tutorial.OPCIONES_ROI), False)

        def asignar_roles():
            self.nb.select(a)
            a.nb.select(a.panel_roi)
            return a.panel_roi.pres.asignar_roles(self.ctx.tramo_id, "0.5", "42", False)

        def analizar():
            self.nb.select(a)
            a.nb.select(0)
            a.alcance.set("rol")
            a.cb_rol.set("prueba")
            a.metodo.set("actual")
            a.pres.metodo = "actual"
            self.update_idletasks()
            a.analizar()

        def validar():
            self.nb.select(self.v_validacion)
            self.update_idletasks()
            self.v_validacion.validar()

        def comparar():
            self.nb.select(self.v_metodos)
            self.update_idletasks()
            self.v_metodos.ejecutar()

        def reportes():
            vr = self.v_reportes
            self.nb.select(vr)
            vr.v_carpeta.set(R()["reportes"])
            self.update_idletasks()
            vr.generar(con_vista_previa=False)

        return {"crear_tramo": crear_tramo, "asignar_ortomosaico": asignar_ortomosaico, "importar_eje": importar_eje,
                "importar_rois": importar_rois, "asignar_roles": asignar_roles, "analizar": analizar, "validar": validar,
                "comparar": comparar, "reportes": reportes}

    # ---------------------------------------------------------------- cierre y errores
    def cerrar(self):
        if self._ocupado() and not messagebox.askyesno(
                "Salir", "Hay un análisis, una calibración o un reporte en curso. ¿Cancelarlo y salir?", parent=self):
            return
        try:
            self._cerrar_panel_tutorial()
            self.v_metodos.cerrar()
            self.v_reportes.cerrar()
            self.v_validacion.cerrar()
            self.v_analisis.cerrar()
        finally:
            self.destroy()

    def _excepcion(self, tipo, valor, tb):
        from app import errores
        log.error("Excepción en un callback de Tk:\n%s", "".join(traceback.format_exception(tipo, valor, tb)))
        titulo, mensaje, _detalle = errores.describir(valor, ruta_log=os.environ.get("PAVIMENTO_LOG"))
        try:
            messagebox.showerror(titulo, f"{mensaje}\n\nLa aplicación sigue abierta.", parent=self)
        except tk.TclError:
            pass
