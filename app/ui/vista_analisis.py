"""
vista_analisis.py
=================
Pestaña Análisis: visor + panel de ROI + control del análisis (alcance, método, parámetros PROVISIONALES,
Analizar / Cancelar con barra de progreso) + tabla de detecciones y resumen por tipo.

La interfaz no se congela: el análisis corre en el hilo de `tareas.GestorTareas`; esta vista sondea la cola
con `after` y es `PresentadorAnalisis.sondear()` quien guarda el resultado en la BD (hilo principal).
"""
import tkinter as tk
from tkinter import messagebox, ttk

from app.nucleo.estructuras import TIPOS
from app.ui import estilos
from app.ui.dialogo_parametros import DialogoParametros
from app.ui.panel_roi import PanelROI
from app.ui.presentadores.p_analisis import ALCANCES, COLUMNAS_DET, NOMBRE_TIPO, PresentadorAnalisis
from app.ui.presentadores.p_roi import PresentadorROI
from app.ui.presentadores.p_tramos import PresentadorTramos
from app.ui.visor import VisorOrtomosaico
from app.ui.widgets import Banner, FrameDesplazable, TablaTreeview

SONDEO_MS = 100


class VistaAnalisis(ttk.Frame):
    def __init__(self, master, ctx, gestor=None):
        super().__init__(master, padding=4)
        self.ctx = ctx
        self.pres = PresentadorAnalisis(ctx, gestor)
        self.tramos = PresentadorTramos(ctx)
        self._tramo = None
        self._mapa_roi = {}
        self._sondeo = None
        self._ejec_ids = []
        self._construir()
        ctx.suscribir("tramo_activo", lambda *_: self._cambio_tramo())
        ctx.suscribir("ortomosaico", lambda *_: self._cambio_tramo())
        ctx.suscribir("eje", lambda *_: self._pintar_eje())
        ctx.suscribir("ejecuciones", lambda *_: self._historial())
        ctx.suscribir("bd", lambda *_: self._cambio_tramo())
        ctx.suscribir("params", lambda *_: self._params_info())     # F5: tras guardar parámetros calibrados
        self._cambio_tramo()

    # ---------------------------------------------------------------- construcción
    def _construir(self):
        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        self.nb = ttk.Notebook(pan)
        pan.add(self.nb, weight=0)
        self.nb.add(self._tab_analisis(self.nb), text="Análisis")
        der = ttk.PanedWindow(pan, orient="vertical")
        pan.add(der, weight=1)
        self.visor = VisorOrtomosaico(der, al_roi=self._roi_dibujada, al_eje=self._eje_dibujado,
                                      al_ventana=self._ventana_dibujada, al_seleccion=self._det_en_visor)
        der.add(self.visor, weight=3)
        der.add(self._resultados(der), weight=2)
        self.panel_roi = PanelROI(self.nb, self.ctx, al_cambiar=self._rois_cambiaron, al_ir=self._ir_region)
        self.nb.add(self.panel_roi, text="ROI")

    def _tab_analisis(self, master):
        cont = FrameDesplazable(master)
        c = cont.interior
        c.columnconfigure(0, weight=1)
        self.aviso_prov = Banner(c)
        self.aviso_prov.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        self.aviso_prov.ajustar_ancho(380)
        # alcance
        fa = ttk.LabelFrame(c, text="Qué analizar", padding=8)
        fa.grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        fa.columnconfigure(1, weight=1)
        self.alcance = tk.StringVar(value="roi")
        self.cb_roi, self.cb_rol = tk.StringVar(), tk.StringVar(value="calibracion")
        self.win = [tk.StringVar() for _ in range(4)]
        ttk.Radiobutton(fa, text=ALCANCES[0][1], value="roi", variable=self.alcance).grid(row=0, column=0, sticky="w")
        self.combo_roi = ttk.Combobox(fa, textvariable=self.cb_roi, state="readonly", width=28)
        self.combo_roi.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Radiobutton(fa, text=ALCANCES[1][1], value="ventana", variable=self.alcance).grid(row=1, column=0,
                                                                                               sticky="w", pady=4)
        fw = ttk.Frame(fa)
        fw.grid(row=1, column=1, sticky="w", padx=6)
        for v in self.win:
            ttk.Entry(fw, textvariable=v, width=7).pack(side="left", padx=1)
        ttk.Button(fa, text="Usar la zona visible", style="Herramienta.TButton", command=self._zona_visible).grid(
            row=2, column=1, sticky="w", padx=6)
        ttk.Label(fa, text="x0, y0, x1, y1 en píxeles", style="Suave.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(fa, text=ALCANCES[2][1], value="tramo", variable=self.alcance).grid(row=3, column=0,
                                                                                             sticky="w", pady=4)
        ttk.Radiobutton(fa, text=ALCANCES[3][1], value="rol", variable=self.alcance).grid(row=4, column=0, sticky="w")
        self.combo_rol = ttk.Combobox(fa, textvariable=self.cb_rol, state="readonly", width=14,
                                      values=PresentadorROI(self.ctx).roles())
        self.combo_rol.grid(row=4, column=1, sticky="w", padx=6)
        # método y parámetros
        fm = ttk.LabelFrame(c, text="Método y parámetros", padding=8)
        fm.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        self.metodo = tk.StringVar(value=self.pres.metodo)
        ttk.Label(fm, text="Método").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(fm, textvariable=self.metodo, values=self.pres.metodos_disponibles(), state="readonly",
                          width=12)
        cb.grid(row=0, column=1, sticky="w", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: setattr(self.pres, "metodo", self.metodo.get()))
        ttk.Button(fm, text="Parámetros…", command=self._parametros).grid(row=0, column=2, padx=6)
        self.lbl_params = ttk.Label(fm, text="", style="Suave.TLabel")
        self.lbl_params.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        # ejecución
        fe = ttk.LabelFrame(c, text="Ejecución", padding=8)
        fe.grid(row=3, column=0, sticky="ew", padx=6, pady=4)
        fe.columnconfigure(0, weight=1)
        b = ttk.Frame(fe)
        b.grid(row=0, column=0, sticky="ew")
        self.btn_analizar = ttk.Button(b, text="Analizar", style="Accion.TButton", command=self.analizar)
        self.btn_analizar.pack(side="left")
        self.btn_cancelar = ttk.Button(b, text="Cancelar", style="Peligro.TButton", command=self.cancelar)
        self.btn_cancelar.pack(side="left", padx=6)
        self.btn_cancelar.state(["disabled"])
        self.barra = ttk.Progressbar(fe, mode="determinate", maximum=100)
        self.barra.grid(row=1, column=0, sticky="ew", pady=6)
        self.lbl_prog = ttk.Label(fe, text="Listo.", style="Suave.TLabel", wraplength=380, justify="left")
        self.lbl_prog.grid(row=2, column=0, sticky="w")
        self.msg = Banner(fe).poner_en_grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.msg.ajustar_ancho(380)
        return cont

    def _resultados(self, master):
        f = ttk.Frame(master, padding=(0, 4, 0, 0))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Resultados", style="Subtitulo.TLabel").pack(side="left")
        ttk.Label(top, text="  Ejecución").pack(side="left")
        self.hist = tk.StringVar()
        self.combo_hist = ttk.Combobox(top, textvariable=self.hist, state="readonly", width=48)
        self.combo_hist.pack(side="left", padx=4)
        self.combo_hist.bind("<<ComboboxSelected>>", self._elegir_ejecucion)
        ttk.Label(top, text="Tipo").pack(side="left", padx=(10, 2))
        self.filtro = tk.StringVar(value="todos")
        cf = ttk.Combobox(top, textvariable=self.filtro, state="readonly", width=18,
                          values=["todos"] + [NOMBRE_TIPO[t] for t in TIPOS])
        cf.pack(side="left")
        cf.bind("<<ComboboxSelected>>", self._filtrar)
        self.lbl_ejec = ttk.Label(f, text="", style="Suave.TLabel", wraplength=900, justify="left")
        self.lbl_ejec.grid(row=1, column=0, sticky="ew", pady=2)
        nb = ttk.Notebook(f)
        nb.grid(row=2, column=0, sticky="nsew")
        p1 = ttk.PanedWindow(nb, orient="horizontal")
        self.tabla = TablaTreeview(p1, COLUMNAS_DET, altura=6, al_seleccionar=self._det_en_tabla)
        p1.add(self.tabla, weight=3)
        self.detalle = tk.Text(p1, width=38, height=6, wrap="word", relief="flat", background="#ffffff", padx=8,
                               pady=6, state="disabled")
        p1.add(self.detalle, weight=1)
        nb.add(p1, text="Detecciones")
        self.tabla_res = TablaTreeview(nb, (("tipo", "Tipo", 160), ("n", "N.º", 60), ("l", "Longitud total (m)", 130),
                                            ("a", "Área total (m²)", 120)), altura=5)
        nb.add(self.tabla_res, text="Resumen por tipo")
        return f

    # ---------------------------------------------------------------- tramo, visor y datos
    def _cambio_tramo(self):
        tid = self.ctx.tramo_id
        self._tramo = self.tramos.obtener(tid).datos if tid is not None else None
        t = self._tramo
        self.pres.limpiar()
        self.visor.fijar_detecciones([])
        self.visor.fijar_ventana(None)
        self.panel_roi.fijar_gsd(t.get("gsd_cm") if t else None)
        if t and t.get("ortomosaico_ruta") and t.get("ancho_px"):
            self.visor.cargar(t["ortomosaico_ruta"], t["ancho_px"], t["alto_px"], t["gsd_cm"])
        else:
            self.visor.cargar(None)
        self._pintar_eje()
        self.panel_roi.recargar()
        self._historial()
        self._refrescar_resultados()
        self._params_info()

    def _pintar_eje(self):
        e = self.tramos.eje(self.ctx.tramo_id) if self.ctx.tramo_id is not None else None
        self.visor.fijar_eje(e["vertices_px"] if e else None)

    def _rois_cambiaron(self, rois, sel):
        self.visor.fijar_rois(rois, sel)
        etiquetas = [self.panel_roi.pres.etiqueta(r, self._tramo.get("gsd_cm") if self._tramo else None) for r in rois]
        self._mapa_roi = dict(zip(etiquetas, [r["id"] for r in rois]))
        self.combo_roi.configure(values=etiquetas)
        if sel is not None:
            r = next((x for x in rois if x["id"] == sel), None)
            if r:
                self.cb_roi.set(self.panel_roi.pres.etiqueta(r, self._tramo.get("gsd_cm") if self._tramo else None))
        elif self.cb_roi.get() not in self._mapa_roi:
            self.cb_roi.set(etiquetas[0] if etiquetas else "")

    def _ir_region(self, region):
        self.visor.ir_a_region(region)

    # ---------------------------------------------------------------- eventos del visor
    def ir_a_visor(self, modo):
        """Desde otras pestañas: deja el visor listo para dibujar (p. ej. el eje)."""
        self.visor.fijar_modo(modo)

    def _roi_dibujada(self, region):
        self.nb.select(self.panel_roi)
        self.panel_roi.fijar_region(region)
        self.visor.fijar_modo("mover")

    def _ventana_dibujada(self, region):
        for v, x in zip(self.win, region):
            v.set(str(x))
        self.alcance.set("ventana")

    def _eje_dibujado(self, pts):
        if self.ctx.tramo_id is None:
            return
        if not messagebox.askyesno("Eje de vía", f"Eje con {len(pts)} vértices.\n¿Guardarlo como eje de vía del tramo?",
                                   parent=self):
            return
        r = self.tramos.guardar_eje_px(self.ctx.tramo_id, pts)
        if not r.ok:
            messagebox.showerror("Eje de vía", r.texto_errores(), parent=self)
        else:
            self.visor.fijar_modo("mover")
            if r.advertencias:
                messagebox.showwarning("Eje de vía", "\n".join(r.advertencias), parent=self)

    def _zona_visible(self):
        r = self.visor.region_visible()
        if r:
            self._ventana_dibujada(r)
            self.visor.fijar_ventana(r)

    def _det_en_visor(self, det_id):
        self.pres.seleccion = det_id
        self.tabla.seleccionar(det_id)
        self._mostrar_detalle(det_id)

    def _det_en_tabla(self, det_id):
        self.pres.seleccion = det_id
        self.visor.seleccionar_deteccion(det_id, centrar=True)
        self._mostrar_detalle(det_id)

    def _mostrar_detalle(self, det_id):
        self.detalle.configure(state="normal")
        self.detalle.delete("1.0", "end")
        self.detalle.insert("1.0", self.pres.detalle_deteccion(det_id) if det_id is not None else
                            "Haga clic en una detección (visor o tabla) para ver sus medidas.")
        self.detalle.configure(state="disabled")

    # ---------------------------------------------------------------- parámetros
    def _parametros(self):
        d = DialogoParametros(self, self.pres)
        self._params_info()
        return d

    def _params_info(self):
        mod = self.pres.parametros_modificados()
        self.lbl_params.configure(text=("Parámetros base" if not mod else f"{len(mod)} parámetro(s) modificado(s): "
                                                                          + ", ".join(mod[:4]) + ("…" if len(mod) > 4 else "")))
        self.aviso_prov.mostrar(self.pres.aviso_provisional(), "aviso")

    # ---------------------------------------------------------------- análisis
    def _argumentos(self):
        a = self.alcance.get()
        if a == "roi":
            return a, {"roi_id": self._mapa_roi.get(self.cb_roi.get())}
        if a == "ventana":
            return a, {"region": [v.get() for v in self.win], "tramo": self._tramo}
        if a == "rol":
            return a, {"rol": self.cb_rol.get()}
        return a, {}

    def analizar(self):
        self.msg.ocultar()
        a, kw = self._argumentos()
        if a == "tramo" and self._tramo and messagebox.askokcancel(
                "Ortomosaico completo", "Analizar el ortomosaico completo puede tardar mucho. "
                "Puede cancelar en cualquier momento. ¿Continuar?", parent=self) is False:
            return
        r = self.pres.iniciar(self.ctx.tramo_id, a, **kw)
        if not r.ok:
            self.msg.mostrar("No se puede analizar:\n" + "\n".join("• " + x for x in r.texto_errores(
                {"roi": "ROI", "region": "Ventana", "rol": "Rol", "tramo": "Tramo"}).splitlines()), "error")
            return
        self._ocupado(True)
        self.barra.configure(value=0)
        self.lbl_prog.configure(text="Iniciando…")
        self._programar()

    def cancelar(self):
        self.pres.cancelar()
        self.btn_cancelar.state(["disabled"])
        self.lbl_prog.configure(text="Cancelando… (termina la tesela en curso)")

    def _ocupado(self, si):
        self.btn_analizar.state(["disabled"] if si else ["!disabled"])
        self.btn_cancelar.state(["!disabled"] if si else ["disabled"])

    def _programar(self):
        if self._sondeo is None:
            self._sondeo = self.after(SONDEO_MS, self._sondear)

    def _sondear(self):
        self._sondeo = None
        for ev in self.pres.sondear():
            if ev[0] == "progreso":
                self.barra.configure(value=ev[1] * 100)
                self.lbl_prog.configure(text=ev[2])
            elif ev[0] == "ejecucion":
                self._refrescar_resultados()
                self._historial()
                self.visor.ir_a_region(self._region_de(ev[1])) if ev[1]["alcance"] != "tramo" else None
            elif ev[0] == "mensaje":
                self.msg.mostrar(ev[2], "error" if ev[1] == "error" else "aviso")
            elif ev[0] == "fin":
                self._ocupado(False)
                self.barra.configure(value=100 if self.pres.ejecucion and self.pres.ejecucion["estado"] == "completada" else 0)
                self.lbl_prog.configure(text="Listo.")
        if self.pres.ocupado:
            self._programar()
        elif self.btn_analizar.instate(["disabled"]):
            self._ocupado(False)

    @staticmethod
    def _region_de(e):
        return (e["x0"], e["y0"], e["x1"], e["y1"])

    # ---------------------------------------------------------------- resultados
    def _historial(self):
        h = self.pres.historial(self.ctx.tramo_id)
        self._ejec_ids = [i for i, _ in h]
        self.combo_hist.configure(values=[t for _, t in h])
        e = self.pres.ejecucion
        if e and e["id"] in self._ejec_ids:
            self.combo_hist.current(self._ejec_ids.index(e["id"]))
        else:
            self.hist.set("")

    def _elegir_ejecucion(self, _e=None):
        i = self.combo_hist.current()
        if i < 0:
            return
        r = self.pres.cargar_ejecucion(self._ejec_ids[i])
        if not r.ok:
            self.msg.mostrar(r.texto_errores(), "error")
        self._refrescar_resultados()

    def _filtrar(self, _e=None):
        v = self.filtro.get()
        inv = {NOMBRE_TIPO[t]: t for t in TIPOS}
        self.pres.filtro_tipo = inv.get(v)
        self._refrescar_resultados()

    def _refrescar_resultados(self):
        self.lbl_ejec.configure(text=self.pres.texto_ejecucion())
        dets = self.pres.detecciones_filtradas()
        self.tabla.cargar([(d["id"], self.pres.fila_deteccion(d)) for d in dets], conservar_seleccion=False)
        self.tabla_res.cargar([(i, f) for i, f in enumerate(self.pres.filas_resumen())])
        self.visor.fijar_detecciones(self.pres.para_visor(), self.pres.seleccion)
        self._mostrar_detalle(self.pres.seleccion)

    def cerrar(self):
        """Antes de destruir la ventana: cancela y espera al hilo (registra la incidencia)."""
        if self._sondeo is not None:
            self.after_cancel(self._sondeo)
            self._sondeo = None
        self.pres.cerrar()
        self.visor.descargar()
