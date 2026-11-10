"""
vista_estadistica.py
====================
Pestaña Estadística: elige el conjunto de ejecuciones validadas (método + parámetros) y muestra, en sub-pestañas,
métricas por tipo con IC, concordancia (kappa y matrices de confusión), error de medidas (Bland-Altman, correlación,
prueba pareada), Tablas 2-4 del cap. 3.2 y la comparación de dos conjuntos (McNemar). Todo viene de
`PresentadorEstadistica` (que llama a `logica_estadistica`); los gráficos son `Figure` de `app.graficos`.
Lo calculado con parámetros provisionales se rotula PROVISIONAL.
"""
import tkinter as tk
from tkinter import ttk

from app.nucleo.estructuras import TIPOS
from app.ui.presentadores.p_estadistica import (COLUMNAS_CONCORDANCIA, COLUMNAS_MEDIDAS, COLUMNAS_METRICAS,
                                                COLUMNAS_TABLAS, COLUMNAS_TOTALES, COLUMNAS_TRAMOS, NOMBRE_TIPO, PresentadorEstadistica)
from app.ui.widget_figura import VisorFigura
from app.ui.widgets import Banner, TablaTreeview


class _TablaYFigura(ttk.Frame):
    """Tabla arriba; abajo, selector de figura + figura."""

    def __init__(self, master, pres, columnas, claves_figuras, altura=6):
        super().__init__(master)
        self.pres = pres
        self.claves = claves_figuras
        self.claves_activas = list(claves_figuras)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)
        self.tabla = TablaTreeview(self, columnas, altura=altura)
        self.tabla.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Label(bar, text="Gráfico").pack(side="left")
        self.sel = tk.StringVar()
        nombres = dict(PresentadorEstadistica.FIGURAS)
        self.combo = ttk.Combobox(bar, textvariable=self.sel, state="readonly", width=34,
                                  values=[nombres[c] for c in claves_figuras])
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", lambda _e: self.pintar_figura())
        self.combo.current(0)
        self.fig = VisorFigura(self, "Sin datos para este gráfico")
        self.fig.grid(row=2, column=0, sticky="nsew", pady=4)

    def filtrar_figuras(self, visibles):
        """Deja en el selector solo las figuras de este panel que están en `visibles` [(clave, nombre)]."""
        ok = {c for c, _ in visibles}
        self.claves_activas = [c for c in self.claves if c in ok]
        nombres = dict(PresentadorEstadistica.FIGURAS)
        self.combo.configure(values=[nombres[c] for c in self.claves_activas])
        self.combo.current(0)

    def pintar_figura(self):
        i = self.combo.current()
        self.fig.mostrar(self.pres.figura(self.claves_activas[i]) if i >= 0 else None)


class VistaEstadistica(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master, padding=4)
        self.ctx = ctx
        self.pres = PresentadorEstadistica(ctx)
        self._claves = []
        self._construir()
        for ev in ("tramo_activo", "ejecuciones", "validacion", "bd"):
            ctx.suscribir(ev, lambda *_: self.refrescar())
        self.refrescar()

    def _construir(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(2, 6))
        ttk.Label(top, text="Conjunto validado", style="Subtitulo.TLabel").pack(side="left")
        self.sel = tk.StringVar()
        self.combo = ttk.Combobox(top, textvariable=self.sel, state="readonly", width=70)
        self.combo.pack(side="left", padx=8)
        ttk.Button(top, text="Calcular", style="Accion.TButton", command=self.calcular).pack(side="left")
        ttk.Button(top, text="Ver advertencias", command=self.ver_advertencias).pack(side="left", padx=6)
        self.var_avanzada = tk.BooleanVar(value=self.pres.avanzada)
        ttk.Checkbutton(top, text="Mostrar pruebas avanzadas (McNemar, Bland-Altman, correlaciones, pareadas)",
                        variable=self.var_avanzada, command=self._cambio_avanzada).pack(side="right")
        self._advertencias = []
        self.banner = Banner(self)
        self.banner.pack(fill="x", pady=2)
        self.banner.ajustar_ancho(1100)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.p_metricas = _TablaYFigura(self.nb, self.pres, COLUMNAS_METRICAS, ("metricas", "conteos"))
        self.nb.add(self.p_metricas, text="Métricas por tipo")
        self.p_conc = _TablaYFigura(self.nb, self.pres, COLUMNAS_CONCORDANCIA, ("conf_tipo", "conf_sev_obs", "conf_sev_py"),
                                    altura=5)
        self.nb.add(self.p_conc, text="Concordancia (kappa)")
        self.p_med = _TablaYFigura(self.nb, self.pres, COLUMNAS_MEDIDAS,
                                   ("ba_longitud_m", "ba_ancho_mm", "ba_area_m2", "disp_longitud_m", "disp_ancho_mm",
                                    "disp_area_m2"), altura=4)
        self.nb.add(self.p_med, text="Error de medidas")
        self.nb.add(self._tab_tablas(self.nb), text="Tablas 2-4")
        self.nb.add(self._tab_tramos(self.nb), text="Comparar tramos")
        self._tab_cmp = self._tab_comparar(self.nb)
        self.nb.add(self._tab_cmp, text="Comparar ejecuciones")
        self._aplicar_avanzada()

    def _tab_tablas(self, master):
        f = ttk.Frame(master, padding=6)
        f.columnconfigure(0, weight=1)
        self.tablas = {}
        for fila, (clave, titulo) in enumerate((("tabla2", "Tabla 2 · Grietas longitudinales y transversales"),
                                                ("tabla3", "Tabla 3 · Piel de cocodrilo"), ("tabla4", "Tabla 4 · Baches"))):
            lf = ttk.LabelFrame(f, text=titulo, padding=4)
            lf.grid(row=fila, column=0, sticky="ew", pady=3)
            lf.columnconfigure(0, weight=1)
            self.tablas[clave] = TablaTreeview(lf, COLUMNAS_TABLAS[clave], altura=3)
            self.tablas[clave].grid(row=0, column=0, sticky="ew")
        lf = ttk.LabelFrame(f, text="Totales por tipo", padding=4)
        lf.grid(row=3, column=0, sticky="ew", pady=3)
        lf.columnconfigure(0, weight=1)
        self.t_totales = TablaTreeview(lf, COLUMNAS_TOTALES, altura=4)
        self.t_totales.grid(row=0, column=0, sticky="ew")
        return f

    def _tab_tramos(self, master):
        f = ttk.Frame(master, padding=8)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)
        ttk.Label(f, text="Comparación DESCRIPTIVA entre tramos (sin inferencia): frecuencia, dimensiones y % de área afectada "
                          "de lo detectado en las ROI de prueba validadas.", style="Suave.TLabel", wraplength=1000,
                  justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(f, text="Comparar tramos", style="Accion.TButton", command=self.comparar_tramos).grid(row=1, column=0, sticky="w", pady=6)
        self.t_tramos = TablaTreeview(f, COLUMNAS_TRAMOS, altura=14)
        self.t_tramos.grid(row=2, column=0, sticky="nsew")
        self.lbl_tramos = ttk.Label(f, text="", style="Suave.TLabel", wraplength=1000, justify="left")
        self.lbl_tramos.grid(row=3, column=0, sticky="w", pady=4)
        return f

    def comparar_tramos(self):
        r = self.pres.comparar_tramos()
        self.t_tramos.cargar(self.pres.filas_tramos(), conservar_seleccion=False)
        self.lbl_tramos.configure(text="\n".join(r.advertencias) if r.ok else r.texto_errores())

    def _tab_comparar(self, master):
        f = ttk.Frame(master, padding=8)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="McNemar sobre las mismas ROI de prueba (acierto = VP o VN). Compare p. ej. 'actual' vs 'sun', "
                          "o los mismos umbrales antes y después de calibrar.", style="Suave.TLabel", wraplength=900,
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
        self.cmp_a, self.cmp_b, self.cmp_tipo = tk.StringVar(), tk.StringVar(), tk.StringVar(value="todos")
        for i, (txt, var) in enumerate((("Conjunto A", self.cmp_a), ("Conjunto B", self.cmp_b))):
            ttk.Label(f, text=txt).grid(row=1 + i, column=0, sticky="w", pady=4)
            cb = ttk.Combobox(f, textvariable=var, state="readonly", width=70)
            cb.grid(row=1 + i, column=1, sticky="w", padx=6)
            setattr(self, f"cb_{'ab'[i]}", cb)
        ttk.Label(f, text="Tipo").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=self.cmp_tipo, state="readonly", width=20,
                     values=["todos"] + list(TIPOS)).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Button(f, text="Comparar", style="Accion.TButton", command=self.comparar).grid(row=4, column=0, pady=8, sticky="w")
        self.res_cmp = ttk.Label(f, text="", justify="left", wraplength=1000)
        self.res_cmp.grid(row=5, column=0, columnspan=3, sticky="w")
        return f

    # ---------------------------------------------------------------- acciones
    def refrescar(self):
        gr = self.pres.listar_grupos(self.ctx.tramo_id)
        self._claves = [c for c, _ in gr]
        textos = [t for _, t in gr]
        for cb in (self.combo, self.cb_a, self.cb_b):
            cb.configure(values=textos)
        if textos:
            self.combo.current(0)
            self.cb_a.current(0)
            if len(textos) > 1:
                self.cb_b.current(1)
        else:
            for v in (self.sel, self.cmp_a, self.cmp_b):
                v.set("")
        self.pres.elegir_grupo(self._claves[0] if self._claves else None)
        self.banner.mostrar("" if self._claves else "No hay validación guardada para este tramo: valide en la pestaña "
                                                    "Validación.", "aviso")

    def calcular(self):
        i = self.combo.current()
        self.pres.elegir_grupo(self._claves[i] if i >= 0 else None)
        r = self.pres.calcular(self.ctx.tramo_id)
        if not r.ok:
            self.banner.mostrar(r.texto_errores(), "error")
            return
        lineas = list(r.advertencias)
        lineas += [f"No se pudo calcular «{k}»: {v}" for k, v in self.pres.errores_parciales().items()]
        self._advertencias = lineas
        self.banner.mostrar(self.pres.resumen_advertencias(lineas), "aviso")
        self.p_metricas.tabla.cargar(self.pres.filas_metricas(), conservar_seleccion=False)
        self.p_conc.tabla.cargar(self.pres.filas_concordancia(), conservar_seleccion=False)
        self.p_med.tabla.cargar(self.pres.filas_medidas(), conservar_seleccion=False)
        for p in (self.p_metricas, self.p_conc, self.p_med):
            p.pintar_figura()
        for k, t in self.tablas.items():
            t.cargar(self.pres.filas_tabla(k), conservar_seleccion=False)
        self.t_totales.cargar(self.pres.filas_totales(), conservar_seleccion=False)

    def _cambio_avanzada(self):
        self.pres.fijar_avanzada(self.var_avanzada.get())
        self._aplicar_avanzada()
        if self.pres.res:
            self.calcular()

    def _aplicar_avanzada(self):
        """Oculta o muestra lo avanzado: pestaña McNemar, columnas de correlación/pareadas y gráficos Bland-Altman."""
        av = self.pres.avanzada
        self.p_med.tabla.arbol.configure(displaycolumns=self.pres.columnas_medidas())
        if av:
            self.nb.add(self._tab_cmp, text="Comparar ejecuciones")
        else:
            self.nb.hide(self._tab_cmp)
        for panel in (self.p_metricas, self.p_conc, self.p_med):
            panel.filtrar_figuras(self.pres.figuras_visibles())

    def ver_advertencias(self):
        from app.ui.dialogo_reporte import DialogoTexto
        DialogoTexto(self, "Advertencias de la estadística",
                     "\n".join("• " + a for a in self._advertencias) or "Sin advertencias.")

    def comparar(self):
        ia, ib = self.cb_a.current(), self.cb_b.current()
        tipo = self.cmp_tipo.get()
        r = self.pres.comparar(self._claves[ia] if ia >= 0 else None, self._claves[ib] if ib >= 0 else None,
                               None if tipo in ("", "todos") else tipo)
        self.res_cmp.configure(text=self.pres.texto_comparacion(r.datos) if r.ok else r.texto_errores())
