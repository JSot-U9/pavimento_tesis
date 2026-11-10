"""
vista_reportes.py
=================
Pestaña Reportes (Fase 6), con tres bloques:

  1. Reporte del tramo activo: PDF / Excel / CSV. «Vista previa» muestra qué se va a incluir y las conclusiones
     (solo cifras calculadas); «Generar» escribe los archivos en un hilo de trabajo con progreso y cancelación.
  2. Exportar a QGIS: GeoPackage o GeoJSON con detecciones, ROI y eje de vía en el CRS del ortomosaico.
  3. Respaldo de la base de datos: crear, listar y restaurar (con copia de seguridad previa).

Toda la lógica está en `PresentadorReportes`; aquí solo hay widgets. Lo calculado con parámetros provisionales se
rotula PROVISIONAL.
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.ui.dialogo_reporte import DialogoVistaPrevia, abrir_en_sistema
from app.ui.presentadores.p_reportes import CAPAS, COLUMNAS_RESPALDOS, FORMATOS, PresentadorReportes
from app.ui.widgets import Banner, FrameDesplazable, TablaTreeview

SONDEO_MS = 150


class VistaReportes(ttk.Frame):
    def __init__(self, master, ctx, gestor_calculos=None):
        super().__init__(master, padding=4)
        self.ctx = ctx
        self.pres = PresentadorReportes(ctx, gestor_calculos)
        self._sondeo = None
        self._carpeta_ultima = ""
        marco = FrameDesplazable(self)
        marco.pack(fill="both", expand=True)
        self.cuerpo = marco.interior
        self.cuerpo.columnconfigure(0, weight=1)
        self._bloque_reporte(self.cuerpo).grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self._bloque_qgis(self.cuerpo).grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self._bloque_respaldo(self.cuerpo).grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        for ev in ("tramo_activo", "ejecuciones", "validacion", "ortomosaico", "bd"):
            ctx.suscribir(ev, lambda *_: self.refrescar())
        self.refrescar()

    # ================================================================= 1. reporte
    def _bloque_reporte(self, master):
        lf = ttk.LabelFrame(master, text="Reporte del tramo activo (PDF · Excel · CSV)", padding=10)
        lf.columnconfigure(1, weight=1)
        o = self.pres.opciones_por_defecto()
        self.v_fmt = {}
        fmts = ttk.Frame(lf)
        fmts.grid(row=0, column=0, columnspan=3, sticky="w")
        for clave, nombre in FORMATOS:
            v = tk.BooleanVar(value=clave in o["formatos"])
            self.v_fmt[clave] = v
            ttk.Checkbutton(fmts, text=nombre, variable=v).pack(side="left", padx=(0, 14))
        self.v_titulo, self.v_autor, self.v_inst = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for fila, (txt, var) in enumerate((("Título (opcional)", self.v_titulo), ("Autor (opcional)", self.v_autor),
                                           ("Institución (opcional)", self.v_inst)), start=1):
            ttk.Label(lf, text=txt).grid(row=fila, column=0, sticky="w", pady=2, padx=(0, 8))
            ttk.Entry(lf, textvariable=var).grid(row=fila, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(lf, text="Carpeta de destino").grid(row=4, column=0, sticky="w", pady=2)
        self.v_carpeta = tk.StringVar()
        ttk.Entry(lf, textvariable=self.v_carpeta).grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Button(lf, text="Examinar…", command=self._elegir_carpeta).grid(row=4, column=2, padx=(6, 0))
        self.v_excluir_fp = tk.BooleanVar(value=o["excluir_fp"])
        ttk.Checkbutton(lf, text="Los falsos positivos NO entran al conteo (siguen registrados en la validación y en el "
                                 "Excel/CSV)", variable=self.v_excluir_fp).grid(row=5, column=0, columnspan=3, sticky="w",
                                                                              pady=(6, 0))
        self.v_excel_es = tk.BooleanVar(value=o["excel_es"])
        ttk.Checkbutton(lf, text="CSV para Excel en español (separador «;» y coma decimal)",
                        variable=self.v_excel_es).grid(row=6, column=0, columnspan=3, sticky="w")
        self.banner_rep = Banner(lf)
        self.banner_rep.poner_en_grid(row=7, column=0, columnspan=3, sticky="ew", pady=6)
        self.banner_rep.ajustar_ancho(900)
        fb = ttk.Frame(lf)
        fb.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.btn_prev = ttk.Button(fb, text="Vista previa…", command=self.vista_previa)
        self.btn_prev.pack(side="left")
        self.btn_gen = ttk.Button(fb, text="Generar", style="Accion.TButton", command=self.generar)
        self.btn_gen.pack(side="left", padx=6)
        self.btn_cancel = ttk.Button(fb, text="Cancelar", command=self.pres.cancelar, state="disabled")
        self.btn_cancel.pack(side="left")
        self.barra = ttk.Progressbar(fb, maximum=100, length=180)
        self.barra.pack(side="left", padx=10)
        self.lbl_prog = ttk.Label(fb, text="", style="Suave.TLabel")
        self.lbl_prog.pack(side="left")
        self.t_archivos = TablaTreeview(lf, (("tipo", "Tipo", 130), ("archivo", "Archivo", 340), ("tam", "Tamaño / motivo", 360)),
                                        altura=4, al_doble_clic=self._abrir_archivo)
        self.t_archivos.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        fa = ttk.Frame(lf)
        fa.grid(row=10, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(fa, text="Abrir archivo", command=lambda: self._abrir_archivo(self.t_archivos.seleccion())).pack(side="left")
        ttk.Button(fa, text="Abrir carpeta", command=self._abrir_carpeta).pack(side="left", padx=6)
        return lf

    def _opciones(self):
        return {"formatos": [k for k, v in self.v_fmt.items() if v.get()], "excluir_fp": self.v_excluir_fp.get(),
                "excel_es": self.v_excel_es.get(), "titulo": self.v_titulo.get(), "autor": self.v_autor.get(),
                "institucion": self.v_inst.get()}

    def _elegir_carpeta(self):
        c = filedialog.askdirectory(parent=self, title="Carpeta de destino de los reportes")
        if c:
            self.v_carpeta.set(c)

    def vista_previa(self):
        r = self.pres.vista_previa(self.ctx.tramo_id, self._opciones())
        if not r.ok:
            self.banner_rep.mostrar(r.texto_errores(), "error")
            return None
        self.banner_rep.ocultar()
        d = r.datos["datos"]
        nombres = dict(FORMATOS)
        fm = ", ".join(nombres[f] for f in self._opciones()["formatos"])
        dlg = DialogoVistaPrevia(self, r.datos["texto"], d["conclusiones"], d["advertencias"], fm)
        return dlg.abrir()

    def generar(self):
        if self.vista_previa() is not True:
            return
        r = self.pres.iniciar(self.ctx.tramo_id, self._opciones(), self.v_carpeta.get())
        if not r.ok:
            self.banner_rep.mostrar(r.texto_errores(), "error")
            return
        self.banner_rep.mostrar("\n".join(r.advertencias), "aviso") if r.advertencias else self.banner_rep.ocultar()
        self.t_archivos.limpiar()
        self._ocupado(True)
        self._programar()

    def _ocupado(self, si):
        self.btn_gen.configure(state="disabled" if si else "normal")
        self.btn_prev.configure(state="disabled" if si else "normal")
        self.btn_cancel.configure(state="normal" if si else "disabled")

    def _programar(self):
        if self._sondeo is None:
            self._sondeo = self.after(SONDEO_MS, self._sondear)

    def _sondear(self):
        self._sondeo = None
        seguir = True
        for ev in self.pres.sondear():
            if ev[0] == "progreso":
                self.barra.configure(value=100 * ev[1])
                self.lbl_prog.configure(text=ev[2])
            elif ev[0] == "resultado":
                self._mostrar_resultado(ev[1])
            elif ev[0] == "mensaje":
                self.banner_rep.mostrar(ev[2], ev[1])
            elif ev[0] == "fin":
                seguir = False
                self.barra.configure(value=0)
                self.lbl_prog.configure(text="")
                self._ocupado(False)
        if seguir and self.pres.ocupado:
            self._programar()
        elif seguir:
            self._ocupado(False)

    def _mostrar_resultado(self, res):
        self.t_archivos.cargar(self.pres.filas_archivos(res), conservar_seleccion=False)
        archivos = list(res["archivos"].values())
        if archivos:
            self._carpeta_ultima = os.path.dirname(archivos[0])
        partes = []
        if res["provisional"]:
            partes.append("PROVISIONAL: el reporte se calculó con parámetros sin calibrar con datos reales.")
        if res["omitidos"]:
            partes.append(f"{len(res['omitidos'])} archivo(s) no se generaron (ver la tabla).")
        if partes:
            self.banner_rep.mostrar("\n".join(partes), "error" if res["omitidos"] else "aviso")
        else:
            self.banner_rep.ocultar()

    def _abrir_archivo(self, iid):
        if iid and os.path.isfile(str(iid)) and not abrir_en_sistema(str(iid)):
            messagebox.showinfo("Abrir archivo", f"No se pudo abrir automáticamente:\n{iid}", parent=self)

    def _abrir_carpeta(self):
        c = self._carpeta_ultima or self.v_carpeta.get().strip()
        if c and os.path.isdir(c):
            abrir_en_sistema(c)

    # ================================================================= 2. QGIS
    def _bloque_qgis(self, master):
        lf = ttk.LabelFrame(master, text="Exportar a QGIS (detecciones, ROI y eje de vía)", padding=10)
        lf.columnconfigure(1, weight=1)
        self.lbl_geo = ttk.Label(lf, text="", style="Suave.TLabel", wraplength=900, justify="left")
        self.lbl_geo.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(lf, text="Formato").grid(row=1, column=0, sticky="w")
        self.v_formato = tk.StringVar(value="GeoPackage (.gpkg)")
        ttk.Combobox(lf, textvariable=self.v_formato, state="readonly", width=24,
                     values=("GeoPackage (.gpkg)", "GeoJSON (un archivo por capa)")).grid(row=1, column=1, sticky="w", padx=6)
        fc = ttk.Frame(lf)
        fc.grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(fc, text="Capas").pack(side="left", padx=(0, 8))
        self.v_capas = {}
        for clave, nombre in CAPAS:
            v = tk.BooleanVar(value=True)
            self.v_capas[clave] = v
            ttk.Checkbutton(fc, text=nombre, variable=v).pack(side="left", padx=(0, 12))
        self.v_wgs84 = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="Reproyectar a WGS84 (EPSG:4326) en vez del CRS del ortomosaico",
                        variable=self.v_wgs84).grid(row=3, column=0, columnspan=3, sticky="w")
        self.v_solo_conteo = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="Omitir las detecciones de falsos positivos (por defecto se exportan, con "
                                 "«incluida_en_conteo» = No)", variable=self.v_solo_conteo).grid(row=4, column=0, columnspan=3,
                                                                                               sticky="w")
        self.v_pixeles = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="Si no hay georreferenciación, exportar en coordenadas de imagen (sin CRS)",
                        variable=self.v_pixeles).grid(row=5, column=0, columnspan=3, sticky="w")
        self.banner_qgis = Banner(lf)
        self.banner_qgis.poner_en_grid(row=6, column=0, columnspan=3, sticky="ew", pady=6)
        self.banner_qgis.ajustar_ancho(900)
        ttk.Button(lf, text="Exportar…", style="Accion.TButton", command=self.exportar).grid(row=7, column=0, sticky="w",
                                                                                           pady=(2, 0))
        return lf

    def exportar(self):
        gpkg = self.v_formato.get().startswith("GeoPackage")
        tramo = self.ctx.tramo_id
        if tramo is None:
            self.banner_qgis.mostrar("Elija un tramo.", "error")
            return
        if gpkg:
            destino = filedialog.asksaveasfilename(parent=self, title="Exportar GeoPackage", defaultextension=".gpkg",
                                                   filetypes=[("GeoPackage", "*.gpkg")], confirmoverwrite=False)
        else:
            destino = filedialog.askdirectory(parent=self, title="Carpeta para los GeoJSON")
        if not destino:
            return
        sobre = False
        if gpkg and os.path.exists(destino):
            if not messagebox.askyesno("Exportar", f"«{os.path.basename(destino)}» ya existe. ¿Reemplazarlo?", parent=self):
                return
            sobre = True
        r = self.pres.exportar(tramo, destino, "gpkg" if gpkg else "geojson",
                               [k for k, v in self.v_capas.items() if v.get()], self.v_wgs84.get(), self.v_pixeles.get(),
                               self.v_solo_conteo.get(), sobre)
        if not r.ok and not gpkg and "Ya existe" in r.texto_errores():
            if messagebox.askyesno("Exportar", r.texto_errores() + "\n\n¿Reemplazar los archivos existentes?", parent=self):
                r = self.pres.exportar(tramo, destino, "geojson", [k for k, v in self.v_capas.items() if v.get()],
                                       self.v_wgs84.get(), self.v_pixeles.get(), self.v_solo_conteo.get(), True)
        if not r.ok:
            self.banner_qgis.mostrar(r.texto_errores(), "error")
            return
        adv = list(r.datos["advertencias"])
        self.banner_qgis.mostrar("\n".join([self.pres.texto_exportacion(r.datos)] + adv), "aviso" if adv else "aviso")

    # ================================================================= 3. respaldo
    def _bloque_respaldo(self, master):
        lf = ttk.LabelFrame(master, text="Respaldo de la base de datos", padding=10)
        lf.columnconfigure(0, weight=1)
        self.t_resp = TablaTreeview(lf, COLUMNAS_RESPALDOS, altura=4)
        self.t_resp.grid(row=0, column=0, sticky="ew")
        fb = ttk.Frame(lf)
        fb.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(fb, text="Crear respaldo ahora", style="Accion.TButton", command=self.crear_respaldo).pack(side="left")
        ttk.Button(fb, text="Guardar copia en…", command=lambda: self.crear_respaldo(True)).pack(side="left", padx=6)
        ttk.Button(fb, text="Restaurar el seleccionado…", command=lambda: self.restaurar(False)).pack(side="left")
        ttk.Button(fb, text="Restaurar desde un archivo…", command=lambda: self.restaurar(True)).pack(side="left", padx=6)
        self.v_auto = tk.BooleanVar(value=self.pres.respaldo_automatico)
        ttk.Checkbutton(lf, text="Respaldo automático diario al abrir el programa", variable=self.v_auto,
                        command=lambda: self.pres.fijar_respaldo_automatico(self.v_auto.get())).grid(row=2, column=0,
                                                                                                    sticky="w", pady=(6, 0))
        self.banner_resp = Banner(lf)
        self.banner_resp.poner_en_grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.banner_resp.ajustar_ancho(900)
        return lf

    def crear_respaldo(self, elegir=False):
        destino = None
        if elegir:
            destino = filedialog.asksaveasfilename(parent=self, title="Guardar copia de la base de datos",
                                                   defaultextension=".db", filetypes=[("SQLite", "*.db")])
            if not destino:
                return
        r = self.pres.crear_respaldo(destino)
        if r.ok:
            self.banner_resp.mostrar(f"Respaldo creado y verificado: {r.datos['ruta']}", "aviso")
            self._tabla_respaldos()
        else:
            self.banner_resp.mostrar(r.texto_errores(), "error")

    def restaurar(self, desde_archivo):
        ruta = None
        if desde_archivo:
            ruta = filedialog.askopenfilename(parent=self, title="Restaurar desde…",
                                              filetypes=[("SQLite", "*.db *.sqlite *.bak"), ("Todos", "*.*")])
        else:
            ruta = self.t_resp.seleccion()
            if not ruta:
                self.banner_resp.mostrar("Elija un respaldo de la lista.", "error")
                return
        if not ruta:
            return
        v = self.pres.verificar(str(ruta))
        if not v.ok:
            self.banner_resp.mostrar("No se puede restaurar ese archivo: " + v.texto_errores(), "error")
            return
        if not messagebox.askyesno(
                "Restaurar respaldo",
                f"Se reemplazará la base de datos actual por «{os.path.basename(str(ruta))}» "
                f"({v.datos['tramos']} tramo(s)).\n\nAntes se guardará una copia de la base actual (…_antes_de_restaurar). "
                f"¿Continuar?", parent=self):
            return
        r = self.pres.restaurar(str(ruta))
        if r.ok:
            self.banner_resp.mostrar(f"Base de datos restaurada. Copia de la anterior: {r.datos['copia_previa']}", "aviso")
            self._tabla_respaldos()
        else:
            self.banner_resp.mostrar(r.texto_errores(), "error")

    def _tabla_respaldos(self):
        self.t_resp.cargar(self.pres.filas_respaldos())

    # ================================================================= general
    def refrescar(self):
        try:
            self.lbl_geo.configure(text=self.pres.estado_georreferencia(self.ctx.tramo_id))
        except Exception:                                           # noqa: BLE001 - BD recién cambiada
            self.lbl_geo.configure(text="")
        self._tabla_respaldos()

    def cerrar(self):
        if self._sondeo is not None:
            self.after_cancel(self._sondeo)
            self._sondeo = None
        self.pres.cerrar()
