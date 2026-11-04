"""
panel_roi.py
============
Panel de ROI (regiones de interés): lista, formulario, roles calibración / prueba (`asignar_roles`) e
importación con vista previa. La ROI se dibuja en el visor y llega aquí con `fijar_region`.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui import dialogo_reporte
from app.ui.presentadores import formularios
from app.ui.presentadores.p_roi import COLUMNAS, OPCIONES_IMPORTACION_ROI, PresentadorROI
from app.ui.widgets import Banner, FormularioEsquema, FrameDesplazable, TablaTreeview


class PanelROI(ttk.Frame):
    def __init__(self, master, ctx, al_cambiar=None, al_ir=None):
        super().__init__(master, padding=6)
        self.ctx, self.pres, self._al_cambiar, self._al_ir = ctx, PresentadorROI(ctx), al_cambiar, al_ir
        self._id, self.rois = None, []
        self._gsd = None
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Rol").pack(side="left")
        self.filtro = tk.StringVar(value="todos")
        cb = ttk.Combobox(top, textvariable=self.filtro, state="readonly", width=12,
                          values=["todos"] + self.pres.roles())
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.recargar())
        self.cuenta = ttk.Label(top, text="", style="Suave.TLabel")
        self.cuenta.pack(side="right")
        self.tabla = TablaTreeview(self, COLUMNAS, altura=7, al_seleccionar=self._elegida)
        self.tabla.pack(fill="both", expand=True, pady=4)
        b = ttk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="Importar…", command=self.importar).pack(side="left")
        ttk.Button(b, text="Asignar roles…", command=self.asignar_roles).pack(side="left", padx=4)
        ttk.Button(b, text="Solapes", command=self.solapes).pack(side="left")
        ttk.Button(b, text="Ir a la ROI", command=self.ir).pack(side="right")
        self.cont = FrameDesplazable(self, fondo="#f3f4f6")
        self.cont.pack(fill="both", expand=True, pady=(6, 0))
        caja = ttk.LabelFrame(self.cont.interior, text="ROI", padding=8)
        caja.pack(fill="x")
        self.form = FormularioEsquema(caja, self.pres.esquema(), columnas=1, ancho_entrada=20)
        self.form.pack(fill="x")
        f = ttk.Frame(self.cont.interior)
        f.pack(fill="x", pady=6)
        ttk.Button(f, text="Nueva", command=self.nueva).pack(side="left")
        ttk.Button(f, text="Eliminar", style="Peligro.TButton", command=self.eliminar).pack(side="left", padx=6)
        ttk.Button(f, text="Guardar ROI", style="Accion.TButton", command=self.guardar).pack(side="right")
        ctx.suscribir("tramo_activo", lambda *_: self.recargar())
        ctx.suscribir("rois", lambda *_: self.recargar())
        ctx.suscribir("bd", lambda *_: self.recargar())
        self.recargar()

    def fijar_gsd(self, gsd_cm):
        self._gsd = gsd_cm

    # ---------------------------------------------------------------- lista
    def _rol(self):
        v = self.filtro.get()
        return None if v == "todos" else v

    def recargar(self):
        tid = self.ctx.tramo_id
        todas = self.pres.listar(tid).datos or []
        self.rois = todas
        mostradas = [r for r in todas if self._rol() in (None, r["rol"])]
        self.tabla.cargar([(r["id"], self.pres.fila(r)) for r in mostradas])
        n = {k: sum(1 for r in todas if r["rol"] == k) for k in self.pres.roles()}
        self.cuenta.configure(text=f"{len(todas)} ROI · cal. {n.get('calibracion', 0)} · prueba {n.get('prueba', 0)}")
        if self._id not in {r["id"] for r in todas}:
            self._id = None
            self._cargar()
        if self._al_cambiar:
            self._al_cambiar(todas, self._id)

    def _elegida(self, iid):
        self._id = iid
        self._cargar()
        if self._al_cambiar:
            self._al_cambiar(self.rois, self._id)

    def _cargar(self):
        r = next((x for x in self.rois if x["id"] == self._id), None)
        self.form.escribir(formularios.datos_a_textos(self.pres.esquema(), r))

    def seleccionada(self):
        return next((x for x in self.rois if x["id"] == self._id), None)

    def ir(self):
        r = self.seleccionada()
        if r and self._al_ir:
            self._al_ir(self.pres.region(r))

    # ---------------------------------------------------------------- edición
    def nueva(self):
        self.tabla.seleccionar(None)
        self._id = None
        self._cargar()
        self.form.foco("codigo")
        if self._al_cambiar:
            self._al_cambiar(self.rois, None)

    def fijar_region(self, region):
        """Rectángulo dibujado en el visor: prepara una ROI nueva con esas coordenadas."""
        self.nueva()
        for k, v in self.pres.region_a_datos(region).items():
            self.form.poner(k, v)
        self.form.poner("rol", "sin_asignar")
        self.form.foco("codigo")

    def guardar(self):
        datos = self.form.leer()
        if self.ctx.tramo_id is None:
            messagebox.showinfo("ROI", "Elija un tramo.", parent=self)
            return
        r = self.pres.actualizar(self._id, datos) if self._id is not None else self.pres.crear(self.ctx.tramo_id, datos)
        if not r.ok:
            self.form.mostrar_errores(r.errores)
            return
        self._id = r.datos["id"]
        self.recargar()
        self.tabla.seleccionar(self._id)
        self._cargar()
        if r.advertencias:
            self.form.mostrar_aviso("Guardada con advertencias:\n" + "\n".join("• " + a for a in r.advertencias))

    def eliminar(self):
        if self._id is None or not messagebox.askyesno("Eliminar ROI", "¿Eliminar la ROI seleccionada?\n(Se borran "
                                                       "también sus detecciones.)", icon="warning", parent=self):
            return
        r = self.pres.eliminar(self._id)
        if not r.ok:
            messagebox.showerror("No se pudo eliminar", r.texto_errores(), parent=self)
        self._id = None

    # ---------------------------------------------------------------- roles, solapes, importación
    def asignar_roles(self):
        if self.ctx.tramo_id is None:
            return
        d = _DialogoRoles(self)
        if not d.resultado:
            return
        prop, sem, rea = d.resultado
        r = self.pres.asignar_roles(self.ctx.tramo_id, prop, sem, rea)
        if not r.ok:
            messagebox.showerror("Asignar roles", r.texto_errores({"proporcion_calibracion": "Proporción",
                                                                   "semilla": "Semilla"}), parent=self)
            return
        dialogo_reporte.DialogoTexto(self, "Reparto calibración / prueba", self.pres.texto_roles(r.datos)).abrir()

    def solapes(self):
        r = self.pres.solapes(self.ctx.tramo_id) if self.ctx.tramo_id is not None else None
        if r is not None and r.ok:
            dialogo_reporte.DialogoTexto(self, "Solapes entre ROI", self.pres.texto_solapes(r.datos)).abrir()

    def importar(self):
        if self.ctx.tramo_id is None:
            messagebox.showinfo("Importar", "Elija un tramo.", parent=self)
            return
        dialogo_reporte.flujo_importacion(
            self, "Importar ROI", [("ROI", "*.csv *.txt *.geojson *.json *.gpkg"), ("Todos", "*.*")],
            OPCIONES_IMPORTACION_ROI,
            lambda ruta, op, simular: self.pres.importar(self.ctx.tramo_id, ruta, op, simular),
            lambda m: messagebox.showerror("Importación", m, parent=self))


class _DialogoRoles(dialogo_reporte._Modal):
    def __init__(self, master):
        super().__init__(master, "Asignar roles", 380, 220)
        m = ttk.Frame(self, padding=12)
        m.pack(fill="both", expand=True)
        self.p, self.s, self.r = tk.StringVar(value="0.5"), tk.StringVar(value="42"), tk.BooleanVar(value=False)
        ttk.Label(m, text="Proporción para calibración (0-1)").grid(row=0, column=0, sticky="w")
        ttk.Entry(m, textvariable=self.p, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(m, text="Semilla (reproducible)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(m, textvariable=self.s, width=8).grid(row=1, column=1, padx=6)
        ttk.Checkbutton(m, text="Reasignar también las ROI que ya tienen rol", variable=self.r).grid(
            row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(m, text="Reparto estratificado por tipo.", style="Suave.TLabel").grid(row=3, column=0, columnspan=2,
                                                                                         sticky="w", pady=6)
        f = ttk.Frame(m)
        f.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(f, text="Asignar", style="Accion.TButton", command=self._ok).pack(side="right")
        ttk.Button(f, text="Cancelar", command=self.destroy).pack(side="right", padx=6)
        self.abrir()

    def _ok(self):
        self.resultado = (self.p.get(), self.s.get(), self.r.get())
        self.destroy()
