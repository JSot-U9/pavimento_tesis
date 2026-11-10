"""
vista_validacion.py
===================
Pestaña Validación con tres sub-pestañas:
  * Validación      opciones (umbral de solape, tolerancia, referencia), estado de roles/solapes, tabla de
                    unidades ROI × tipo (VP/FP/FN/VN) y totales por tipo. Guarda en `Validacion`.
  * Referencias     geometrías de referencia OPCIONALES (líneas/polígonos en px) por ROI; sin ellas se usa el
                    rectángulo de la ROI (presencia por ROI).
  * Calibración     ajuste de umbrales PROVISIONALES con las ROI de calibración (segundo plano, cancelable),
                    antes/después y guardado SOLO si el usuario confirma.
La vista solo llama a presentadores (que llaman a `logica_*`); los cálculos pesados corren en `tareas`.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from app import graficos
from app.ui.presentadores.formularios import lineas_error
from app.ui.presentadores.p_calibracion import COLUMNAS_CAMBIOS, COLUMNAS_PARAMS, PresentadorCalibracion
from app.ui.presentadores.p_validacion import (COLUMNAS_GEOMETRIAS, COLUMNAS_TOTALES, COLUMNAS_UNIDADES,
                                               PresentadorValidacion)
from app.ui.widget_figura import VisorFigura
from app.ui.widgets import Banner, FormularioEsquema, TablaTreeview

SONDEO_MS = 100


class VistaValidacion(ttk.Frame):
    def __init__(self, master, ctx, gestor_calculos=None):
        super().__init__(master, padding=4)
        self.ctx = ctx
        self.pv = PresentadorValidacion(ctx)
        self.pc = PresentadorCalibracion(ctx, gestor_calculos)
        self._sondeo = None
        self._txt_roles = ""
        self._sel_params = set(self.pc.seleccion_inicial())
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.nb.add(self._tab_validacion(self.nb), text="Validación")
        self.nb.add(self._tab_referencias(self.nb), text="Referencias geométricas")
        self.nb.add(self._tab_calibracion(self.nb), text="Calibración")
        for ev in ("tramo_activo", "rois", "ejecuciones", "bd"):
            ctx.suscribir(ev, lambda *_: self.refrescar())
        self.refrescar()

    # ================================================================= Validación
    def _tab_validacion(self, master):
        f = ttk.Frame(master, padding=8)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(4, weight=1)
        ttk.Label(f, text="Validación contra el campo", style="Titulo.TLabel").grid(row=0, column=0, sticky="w")
        self.banner_roles = Banner(f)
        self.banner_roles.poner_en_grid(row=1, column=0, sticky="ew", pady=4)
        self.banner_roles.ajustar_ancho(900)
        fo = ttk.LabelFrame(f, text="Opciones", padding=8)
        fo.grid(row=2, column=0, sticky="ew", pady=4)
        self.form = FormularioEsquema(fo, self.pv.esquema(), columnas=2, ancho_entrada=12)
        self.form.pack(side="left", fill="x", expand=True)
        self.form.escribir(self.pv.textos_iniciales())
        fb = ttk.Frame(fo)
        fb.pack(side="right", padx=8)
        self.btn_validar = ttk.Button(fb, text="Validar y guardar", style="Accion.TButton", command=self.validar)
        self.btn_validar.pack(fill="x")
        ttk.Label(fb, text="Usa la última ejecución completada\nde cada ROI de prueba.", style="Suave.TLabel").pack(pady=4)
        self.estado = ttk.Label(f, text="", style="Suave.TLabel", justify="left", wraplength=1000)
        self.estado.grid(row=3, column=0, sticky="w", pady=2)
        pan = ttk.PanedWindow(f, orient="vertical")
        pan.grid(row=4, column=0, sticky="nsew")
        self.t_unidades = TablaTreeview(pan, COLUMNAS_UNIDADES, altura=10)
        pan.add(self.t_unidades, weight=3)
        self.t_totales = TablaTreeview(pan, COLUMNAS_TOTALES, altura=5)
        pan.add(self.t_totales, weight=1)
        self.banner_adv = Banner(f)
        self.banner_adv.poner_en_grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.banner_adv.ajustar_ancho(900)
        return f

    def validar(self):
        self.form.limpiar_errores()
        r = self.pv.ejecutar(self.ctx.tramo_id, self.form.leer())
        if not r.ok:
            self.form.mostrar_errores(r.errores)
            self.banner_adv.mostrar("\n".join(f"• {x}" for x in lineas_error([], r.errores)) or r.mensaje, "error")
            return
        self.t_unidades.cargar(self.pv.filas_unidades(), conservar_seleccion=False)
        self.t_totales.cargar(self.pv.filas_totales(), conservar_seleccion=False)
        self._pintar_estado()
        self.banner_adv.mostrar("\n".join(r.advertencias), "aviso")
        self.ctx.emitir("ejecuciones")

    # ================================================================= Referencias
    def _tab_referencias(self, master):
        f = ttk.Frame(master, padding=8)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Geometrías de referencia (opcional)", style="Titulo.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.t_rois = TablaTreeview(f, COLUMNAS_GEOMETRIAS, altura=12, al_seleccionar=lambda *_: self._cargar_geom())
        self.t_rois.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        der = ttk.Frame(f)
        der.grid(row=1, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        ttk.Label(der, text="Si una ROI tiene geometrías, el tipo de campo se valida por solape (Dice) con la tolerancia "
                            "indicada; sin ellas se usa el rectángulo de la ROI (presencia).",
                  style="Suave.TLabel", wraplength=520, justify="left").grid(row=0, column=0, sticky="w")
        self.t_geoms = TablaTreeview(der, (("tipo", "Tipo", 80), ("n", "Puntos", 60), ("origen", "Origen", 80)), altura=5)
        self.t_geoms.grid(row=1, column=0, sticky="ew", pady=6)
        ttk.Button(der, text="Eliminar la seleccionada", command=self._eliminar_geom).grid(row=2, column=0, sticky="w")
        fn = ttk.LabelFrame(der, text="Agregar geometría (coordenadas en píxeles del ortomosaico, «x, y» por línea)", padding=6)
        fn.grid(row=3, column=0, sticky="ew", pady=8)
        self.tipo_geom = tk.StringVar(value="linea")
        ttk.Radiobutton(fn, text="Línea (≥ 2 puntos)", value="linea", variable=self.tipo_geom).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(fn, text="Polígono (≥ 3 puntos)", value="poligono", variable=self.tipo_geom).grid(row=0, column=1, sticky="w")
        self.txt_puntos = tk.Text(fn, height=6, width=34, wrap="none")
        self.txt_puntos.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(fn, text="Agregar", command=self._agregar_geom).grid(row=2, column=0, sticky="w")
        self.banner_geom = Banner(der)
        self.banner_geom.poner_en_grid(row=4, column=0, sticky="ew")
        return f

    def _cargar_geom(self):
        roi = self.t_rois.seleccion()
        self.t_geoms.cargar(self.pv.listar_geometrias(roi) if roi is not None else [], conservar_seleccion=False)

    def _agregar_geom(self):
        roi = self.t_rois.seleccion()
        if roi is None:
            self.banner_geom.mostrar("Elija primero una ROI de la tabla.", "aviso")
            return
        r = self.pv.agregar_geometria(roi, self.tipo_geom.get(), self.txt_puntos.get("1.0", "end"))
        if r.ok:
            self.txt_puntos.delete("1.0", "end")
            self.banner_geom.mostrar("\n".join(r.advertencias), "aviso") if r.advertencias else self.banner_geom.ocultar()
            self._tabla_rois()
            self._cargar_geom()
        else:
            self.banner_geom.mostrar(r.texto_errores(), "error")

    def _eliminar_geom(self):
        g = self.t_geoms.seleccion()
        if g is None:
            return
        if messagebox.askyesno("Geometría de referencia", "¿Eliminar la geometría seleccionada?", parent=self):
            self.pv.eliminar_geometria(g)
            self._tabla_rois()
            self._cargar_geom()

    def _tabla_rois(self):
        self.t_rois.cargar(self.pv.filas_geometrias(self.ctx.tramo_id))

    # ================================================================= Calibración
    def _tab_calibracion(self, master):
        f = ttk.Frame(master, padding=8)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(2, weight=1)
        ttk.Label(f, text="Calibración de umbrales (ROI de calibración)", style="Titulo.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.banner_cal = Banner(f)
        self.banner_cal.poner_en_grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        self.banner_cal.ajustar_ancho(900)
        izq = ttk.LabelFrame(f, text="Parámetros a ajustar (doble clic para marcar/desmarcar)", padding=6)
        izq.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        self.t_params = TablaTreeview(izq, COLUMNAS_PARAMS, altura=12, al_doble_clic=self._alternar_param)
        self.t_params.pack(fill="both", expand=True)
        fc = ttk.Frame(izq)
        fc.pack(fill="x", pady=(6, 0))
        self.objetivo, self.pasadas, self.evals = tk.StringVar(value="f1"), tk.StringVar(value="2"), tk.StringVar(value="120")
        ttk.Label(fc, text="Objetivo").grid(row=0, column=0, sticky="w")
        ttk.Combobox(fc, textvariable=self.objetivo, values=("f1", "kappa"), state="readonly", width=7).grid(row=0, column=1, padx=4)
        ttk.Label(fc, text="Pasadas").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Entry(fc, textvariable=self.pasadas, width=4).grid(row=0, column=3, padx=4)
        ttk.Label(fc, text="Máx. evaluaciones").grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Entry(fc, textvariable=self.evals, width=6).grid(row=0, column=5, padx=4)
        fb = ttk.Frame(izq)
        fb.pack(fill="x", pady=6)
        self.btn_cal = ttk.Button(fb, text="Calibrar", style="Accion.TButton", command=self.calibrar)
        self.btn_cal.pack(side="left")
        self.btn_cancel = ttk.Button(fb, text="Cancelar", style="Peligro.TButton", command=self.pc.cancelar, state="disabled")
        self.btn_cancel.pack(side="left", padx=6)
        self.barra = ttk.Progressbar(fb, mode="determinate", maximum=100)
        self.barra.pack(side="left", fill="x", expand=True, padx=6)
        self.lbl_prog = ttk.Label(izq, text="", style="Suave.TLabel")
        self.lbl_prog.pack(anchor="w")
        der = ttk.Frame(f)
        der.grid(row=2, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        der.rowconfigure(2, weight=1)
        self.lbl_res = ttk.Label(der, text="Sin calibración.", justify="left", wraplength=620)
        self.lbl_res.grid(row=0, column=0, sticky="w")
        self.t_cambios = TablaTreeview(der, COLUMNAS_CAMBIOS, altura=5)
        self.t_cambios.grid(row=1, column=0, sticky="ew", pady=6)
        self.fig_cal = VisorFigura(der, "Sin calibración")
        self.fig_cal.grid(row=2, column=0, sticky="nsew")
        self.btn_guardar = ttk.Button(der, text="Guardar como parámetros base (calibrados)…", command=self.confirmar,
                                      state="disabled")
        self.btn_guardar.grid(row=3, column=0, sticky="e", pady=6)
        return f

    def _alternar_param(self, nombre):
        if nombre is None:
            return
        self._sel_params ^= {nombre}
        self._tabla_params()

    def _tabla_params(self):
        filas = [(n, ("☑" if n in self._sel_params else "☐",) + tuple(v[1:])) for n, v in self.pc.filas_parametros()]
        self.t_params.cargar(filas)

    def calibrar(self):
        r = self.pc.iniciar(self.ctx.tramo_id, sorted(self._sel_params), self.objetivo.get(), self.pasadas.get(),
                            self.evals.get())
        if not r.ok:
            self.banner_cal.mostrar(r.texto_errores(), "error")
            return
        self.banner_cal.mostrar("\n".join(r.advertencias), "aviso") if r.advertencias else self.banner_cal.ocultar()
        self._ocupado(True)
        self._programar()

    def _ocupado(self, si):
        self.btn_cal.configure(state="disabled" if si else "normal")
        self.btn_cancel.configure(state="normal" if si else "disabled")
        self.btn_guardar.configure(state="disabled" if si or not self.pc.puede_confirmar() else "normal")

    def _programar(self):
        if self._sondeo is None:
            self._sondeo = self.after(SONDEO_MS, self._sondear)

    def _sondear(self):
        self._sondeo = None
        seguir = True
        for ev in self.pc.sondear():
            if ev[0] == "progreso":
                self.barra.configure(value=100 * ev[1])
                self.lbl_prog.configure(text=ev[2])
            elif ev[0] == "resultado":
                self._mostrar_resultado()
            elif ev[0] == "mensaje":
                self.banner_cal.mostrar(ev[2], ev[1])
            elif ev[0] == "fin":
                seguir = False
                self.barra.configure(value=0)
                self.lbl_prog.configure(text="")
                self._ocupado(False)
        if seguir and self.pc.ocupado:
            self._programar()
        elif seguir:
            self._ocupado(False)

    def _mostrar_resultado(self):
        self.lbl_res.configure(text=self.pc.texto_antes_despues())
        self.t_cambios.cargar(self.pc.filas_cambios(), conservar_seleccion=False)
        self.fig_cal.mostrar(graficos.fig_calibracion(self.pc.resultado))
        self.banner_cal.mostrar("\n".join(self.pc.resultado["advertencias"]), "aviso")

    def confirmar(self):
        if not self.pc.puede_confirmar():
            return
        if not messagebox.askyesno(
                "Guardar parámetros calibrados",
                "Los parámetros calibrados pasarán a ser los parámetros base y los análisis nuevos con ellos dejarán de "
                "marcarse PROVISIONALES.\n\nLa calibración solo usó las ROI de calibración: valide después con las ROI "
                "de prueba. ¿Guardar?", parent=self):
            return
        r = self.pc.confirmar()
        if r.ok:
            self.banner_cal.mostrar("Parámetros guardados como base (calibrados). Valide con las ROI de prueba.", "aviso")
            self.btn_guardar.configure(state="disabled")
        else:
            self.banner_cal.mostrar(r.texto_errores(), "error")

    # ================================================================= general
    def _pintar_estado(self):
        partes = [self._txt_roles] if self._txt_roles else []
        partes.append(self.pv.texto_estado())
        self.estado.configure(text="\n".join(partes))

    def refrescar(self):
        st = self.pv.estado_roles(self.ctx.tramo_id)
        if st["nivel"] == "ok":
            self.banner_roles.ocultar()
            self._txt_roles = st["texto"]
        else:
            self._txt_roles = ""
            self.banner_roles.mostrar(st["texto"], "error" if st["nivel"] == "error" else "aviso")
        self._pintar_estado()
        self._tabla_rois()
        self._cargar_geom()
        self._tabla_params()

    def cerrar(self):
        if self._sondeo is not None:
            self.after_cancel(self._sondeo)
            self._sondeo = None
        self.pc.cerrar()
