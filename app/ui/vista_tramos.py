"""
vista_tramos.py
===============
Pestaña Tramos: CRUD de la Ficha 1 (formulario generado desde `esquema_tramo`), ortomosaico asignado y eje de
vía. Toda la lógica está en `PresentadorTramos`; aquí solo hay widgets.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.ui import dialogo_reporte
from app.ui.presentadores import formularios
from app.ui.presentadores.p_tramos import COLUMNAS, PresentadorTramos
from app.ui.widgets import Banner, FormularioEsquema, FrameDesplazable, TablaTreeview


class VistaTramos(ttk.Frame):
    def __init__(self, master, ctx, ir_a_visor=None):
        super().__init__(master, padding=8)
        self.ctx, self.pres, self.ir_a_visor = ctx, PresentadorTramos(ctx), ir_a_visor
        self._id = None
        self._construir()
        ctx.suscribir("tramos", self.recargar)
        ctx.suscribir("eje", lambda *_: self._info())
        ctx.suscribir("bd", lambda *_: self.recargar())
        ctx.suscribir("tramo_activo", self._tramo_activo)
        self.recargar()

    def _construir(self):
        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        izq = ttk.Frame(pan, padding=(0, 0, 8, 0))
        ttk.Label(izq, text="Tramos", style="Titulo.TLabel").pack(anchor="w", pady=(0, 6))
        self.tabla = TablaTreeview(izq, COLUMNAS, altura=16, al_seleccionar=self._elegido)
        self.tabla.pack(fill="both", expand=True)
        b = ttk.Frame(izq)
        b.pack(fill="x", pady=(6, 0))
        ttk.Button(b, text="Nuevo tramo", command=self.nuevo).pack(side="left")
        ttk.Button(b, text="Eliminar", style="Peligro.TButton", command=self.eliminar).pack(side="left", padx=6)
        pan.add(izq, weight=1)

        der = FrameDesplazable(pan)
        pan.add(der, weight=2)
        c = der.interior
        c.columnconfigure(0, weight=1)
        f1 = ttk.LabelFrame(c, text="Ficha 1 · datos del tramo", padding=10)
        f1.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        f1.columnconfigure(0, weight=1)
        self.form = FormularioEsquema(f1, self.pres.esquema(), columnas=2, ancho_entrada=18)
        self.form.grid(row=0, column=0, sticky="ew")
        ttk.Button(f1, text="Guardar tramo", style="Accion.TButton", command=self.guardar).grid(
            row=1, column=0, sticky="e", pady=(8, 0))

        fo = ttk.LabelFrame(c, text="Ortomosaico", padding=10)
        fo.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        fo.columnconfigure(1, weight=1)
        self.info_orto = ttk.Label(fo, text="", justify="left", wraplength=560)
        self.info_orto.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.ruta, self.gsd, self.epsg = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(fo, text="Archivo").grid(row=1, column=0, sticky="w")
        ttk.Entry(fo, textvariable=self.ruta).grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Button(fo, text="Examinar…", command=self._examinar).grid(row=1, column=3)
        ttk.Label(fo, text="GSD (cm/px)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fo, textvariable=self.gsd, width=10).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(fo, text="Solo si el archivo no lo indica (PNG/JPG)", style="Suave.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(fo, text="EPSG").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fo, textvariable=self.epsg, width=10).grid(row=3, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Button(fo, text="Asignar ortomosaico", style="Accion.TButton", command=self.asignar).grid(
            row=4, column=0, columnspan=4, sticky="e", pady=(8, 0))
        self.aviso_orto = Banner(fo).poner_en_grid(row=5, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        fe = ttk.LabelFrame(c, text="Eje de vía", padding=10)
        fe.grid(row=2, column=0, sticky="ew", padx=(0, 6))
        self.info_eje = ttk.Label(fe, text="", wraplength=560, justify="left")
        self.info_eje.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(fe, text="Importar eje (CSV / GeoJSON / GPKG)…", command=self.importar_eje).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(fe, text="Dibujar en el visor…", command=lambda: self._dibujar_eje()).grid(
            row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        self.aviso_eje = Banner(fe).poner_en_grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self._habilitar(False)

    # ---------------------------------------------------------------- lista
    def recargar(self, *_):
        r = self.pres.listar()
        filas = [(t["id"], self.pres.fila(t)) for t in (r.datos or [])]
        self.tabla.cargar(filas)
        if self._id is not None and not any(i == self._id for i, _ in filas):
            self._id = None
        if self._id is None and self.ctx.tramo_id is not None and any(i == self.ctx.tramo_id for i, _ in filas):
            self._id = self.ctx.tramo_id
            self.tabla.seleccionar(self._id)
        self._cargar_form()

    def _tramo_activo(self, tramo_id):
        """El tramo activo cambió desde fuera (selector superior u otra pestaña)."""
        if tramo_id != self._id:
            self._id = tramo_id
            self.tabla.seleccionar(tramo_id)
            self._cargar_form()

    def _elegido(self, iid):
        self._id = iid
        self.ctx.fijar_tramo(iid)
        self._cargar_form()

    def nuevo(self):
        self.tabla.seleccionar(None)
        self._id = None
        self._cargar_form()
        self.form.foco("codigo")

    def _cargar_form(self):
        self.aviso_orto.ocultar()
        self.aviso_eje.ocultar()
        t = self.pres.obtener(self._id).datos if self._id is not None else None
        self.form.escribir(formularios.datos_a_textos(self.pres.esquema(), t))
        self._habilitar(t is not None)
        self.ruta.set((t or {}).get("ortomosaico_ruta") or "")
        self.gsd.set("")
        self.epsg.set("")
        self._info()

    def _habilitar(self, hay_tramo):
        for fr in (self.info_orto, ):
            pass
        self._hay_tramo = hay_tramo

    def _info(self):
        t = self.pres.obtener(self._id).datos if self._id is not None else None
        self.info_orto.configure(text=self.pres.info_ortomosaico(t) if t else "Guarde el tramo para asignar un ortomosaico.")
        self.info_eje.configure(text=self.pres.info_eje(self._id) if t else "Guarde el tramo para definir su eje.")

    # ---------------------------------------------------------------- acciones
    def guardar(self):
        r = self.pres.guardar(self.form.leer(), self._id)
        if not r.ok:
            self.form.mostrar_errores(r.errores)
            return
        self._id = r.datos["id"]
        self.ctx.fijar_tramo(self._id)
        self.recargar()
        self.tabla.seleccionar(self._id)
        if r.advertencias:
            self.form.mostrar_aviso("Guardado con advertencias:\n" + "\n".join("• " + a for a in r.advertencias))

    def eliminar(self):
        if self._id is None:
            return
        aviso = self.pres.aviso_borrado(self._id)
        if not messagebox.askyesno("Eliminar tramo", f"¿Eliminar el tramo seleccionado?\n\n{aviso}", icon="warning",
                                   parent=self):
            return
        r = self.pres.eliminar(self._id, confirmado=True)
        if not r.ok:
            messagebox.showerror("No se pudo eliminar", r.texto_errores(), parent=self)
        self._id = None

    def _examinar(self):
        r = filedialog.askopenfilename(parent=self, title="Ortomosaico",
                                       filetypes=[("Ortomosaico", "*.tif *.tiff *.png *.jpg *.jpeg"), ("Todos", "*.*")])
        if r:
            self.ruta.set(r)

    def asignar(self):
        if self._id is None:
            messagebox.showinfo("Ortomosaico", "Primero guarde el tramo.", parent=self)
            return
        r = self.pres.asignar_ortomosaico(self._id, self.ruta.get().strip(), self.gsd.get(), self.epsg.get())
        if not r.ok:
            self.aviso_orto.mostrar("No se pudo asignar:\n" + "\n".join(
                "• " + x for x in formularios.lineas_error(
                    [{"nombre": "gsd_cm", "etiqueta": "GSD"}, {"nombre": "epsg", "etiqueta": "EPSG"},
                     {"nombre": "ruta", "etiqueta": "Archivo"}], r.errores)), "error")
            return
        self._info()
        self.aviso_orto.mostrar("\n".join(r.advertencias), "aviso") if r.advertencias else self.aviso_orto.ocultar()

    def importar_eje(self):
        if self._id is None:
            messagebox.showinfo("Eje de vía", "Primero guarde el tramo.", parent=self)
            return
        pedido = dialogo_reporte.DialogoImportar(
            self, "Importar eje de vía",
            [("Eje", "*.csv *.geojson *.json *.gpkg"), ("Todos", "*.*")],
            [("sistema", "Coordenadas", "opcion", ("auto", "px", "geo"), "auto"),
             ("prog", "Progresiva inicial (m, opcional)", "texto", (), "")]).abrir()
        if not pedido:
            return
        ruta, op = pedido
        r = self.pres.importar_eje(self._id, ruta, op["sistema"], op["prog"])
        if not r.ok:
            self.aviso_eje.mostrar("No se pudo importar el eje:\n" + r.texto_errores(), "error")
            return
        self._info()
        self.aviso_eje.mostrar("\n".join(r.advertencias), "aviso") if r.advertencias else self.aviso_eje.ocultar()

    def _dibujar_eje(self):
        if self._id is None:
            messagebox.showinfo("Eje de vía", "Primero guarde el tramo y asigne el ortomosaico.", parent=self)
        elif self.ir_a_visor:
            self.ir_a_visor("eje")
