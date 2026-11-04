"""
vista_fichas.py
===============
Pestaña Fichas: vuelos, condiciones ambientales, GCP, catálogo de patologías, inspecciones y patologías
(con geometría y severidad). Los formularios se generan desde `esquema_ficha` / `esquema_patologia`.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui import dialogo_reporte
from app.ui.presentadores import formularios
from app.ui.presentadores.p_fichas import (COLUMNAS, COLUMNAS_PATOLOGIA, FICHAS, TITULOS, PresentadorFichas)
from app.ui.widgets import Banner, FormularioEsquema, FrameDesplazable, TablaTreeview

OPC_IMPORT = [("si_existe", "Si ya existe", "opcion", ("error", "omitir", "actualizar"), "error"),
              ("estricto", "Estricto (no importar nada si una fila falla)", "bool", (), True)]
TIPOS_CSV = [("CSV", "*.csv *.txt"), ("Todos", "*.*")]


class PanelFicha(ttk.Frame):
    """Tabla + formulario de una ficha genérica."""

    def __init__(self, master, ctx, pres: PresentadorFichas, ficha, al_seleccionar=None):
        super().__init__(master, padding=8)
        self.ctx, self.pres, self.ficha, self._sel_cb = ctx, pres, ficha, al_seleccionar
        self._id = None
        self.form = None
        self._tramo = None
        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        izq = ttk.Frame(pan, padding=(0, 0, 8, 0))
        self.aviso = Banner(izq).poner_en_grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.tabla = TablaTreeview(izq, COLUMNAS[ficha], altura=12, al_seleccionar=self._elegido)
        self.tabla.grid(row=1, column=0, sticky="nsew")
        izq.rowconfigure(1, weight=1)
        izq.columnconfigure(0, weight=1)
        b = ttk.Frame(izq)
        b.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(b, text="Nuevo", command=self.nuevo).pack(side="left")
        ttk.Button(b, text="Eliminar", style="Peligro.TButton", command=self.eliminar).pack(side="left", padx=6)
        ttk.Button(b, text="Importar CSV…", command=self.importar).pack(side="right")
        pan.add(izq, weight=3)
        self.der = FrameDesplazable(pan)
        pan.add(self.der, weight=2)
        self.caja = ttk.LabelFrame(self.der.interior, text=TITULOS[ficha], padding=10)
        self.caja.pack(fill="x", padx=(0, 6))
        self.boton = ttk.Button(self.der.interior, text="Guardar", style="Accion.TButton", command=self.guardar)
        self.boton.pack(anchor="e", padx=(0, 6), pady=8)
        ctx.suscribir("tramo_activo", lambda *_: self.recargar())
        ctx.suscribir("tramos", lambda *_: self.recargar())
        ctx.suscribir("bd", lambda *_: self.recargar())
        ctx.suscribir("fichas", self._fichas_cambio)
        self.recargar()

    def _fichas_cambio(self, ficha=None):
        if ficha in (None, self.ficha, "vuelo"):
            self.recargar(reconstruir=ficha == "vuelo" and self.ficha in ("condicion", "gcp"))

    # ---------------------------------------------------------------- formulario
    def _reconstruir(self):
        if self.form is not None:
            self.form.destroy()
        esq = self.pres.esquema(self.ficha)
        self.form = FormularioEsquema(self.caja, esq, selectores=self.pres.selectores(self.ficha, self.ctx.tramo_id),
                                      ancho_entrada=22)
        self.form.pack(fill="x")

    def recargar(self, reconstruir=True):
        tid = self.ctx.tramo_id
        sin_tramo = self.pres.necesita_tramo(self.ficha) and tid is None
        if reconstruir or self.form is None or tid != self._tramo:
            self._reconstruir()
        self._tramo = tid
        if sin_tramo:
            self.aviso.mostrar("Elija un tramo (arriba) para ver y registrar estas fichas.", "aviso")
        else:
            self.aviso.ocultar()
        r = self.pres.listar(self.ficha, tid)
        datos = r.datos or []
        self._datos = {d["id"]: d for d in datos}
        self.tabla.cargar([(d["id"], self.pres.fila(self.ficha, d)) for d in datos])
        if self._id not in self._datos:
            self._id = None
        self._cargar_form()
        for w in (self.boton,):
            w.state(["disabled"] if sin_tramo else ["!disabled"])

    def _cargar_form(self):
        d = self._datos.get(self._id)
        self.form.escribir(formularios.datos_a_textos(self.pres.esquema(self.ficha), d))
        self.form.solo_lectura(["codigo"], activo=self.ficha == "catalogo" and d is not None)

    def _elegido(self, iid):
        self._id = iid
        self._cargar_form()
        if self._sel_cb:
            self._sel_cb(iid)

    def nuevo(self):
        self.tabla.seleccionar(None)
        self._id = None
        self._cargar_form()
        self.form.foco()
        if self._sel_cb:
            self._sel_cb(None)

    # ---------------------------------------------------------------- acciones
    def guardar(self):
        datos = self.form.leer()
        tid = self.ctx.tramo_id
        r = (self.pres.actualizar(self.ficha, self._id, datos) if self._id is not None
             else self.pres.crear(self.ficha, datos, tid))
        if not r.ok:
            self.form.mostrar_errores(r.errores)
            return
        self._id = r.datos["id"]
        self.recargar(reconstruir=False)
        self.tabla.seleccionar(self._id)
        if self._sel_cb:
            self._sel_cb(self._id)

    def eliminar(self):
        if self._id is None:
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar el registro seleccionado?", icon="warning", parent=self):
            return
        r = self.pres.eliminar(self.ficha, self._id)
        if not r.ok:
            messagebox.showerror("No se pudo eliminar", r.texto_errores(), parent=self)
        self._id = None

    def importar(self):
        if self.pres.necesita_tramo(self.ficha) and self.ctx.tramo_id is None:
            messagebox.showinfo("Importar", "Elija primero un tramo.", parent=self)
            return
        dialogo_reporte.flujo_importacion(
            self, f"Importar {TITULOS[self.ficha].lower()}", TIPOS_CSV, OPC_IMPORT,
            lambda ruta, op, simular: self.pres.importar(self.ficha, ruta, self.ctx.tramo_id, op["si_existe"],
                                                         bool(op["estricto"]), simular),
            lambda m: messagebox.showerror("Importación", m, parent=self))


class PanelPatologias(ttk.Frame):
    """Patologías (Ficha 2) de la inspección elegida, con geometría (Ficha 4) y severidad (Ficha 3)."""

    def __init__(self, master, ctx, pres: PresentadorFichas):
        super().__init__(master, padding=8)
        self.ctx, self.pres = ctx, pres
        self._insp, self._id = None, None
        self._datos = {}
        ttk.Label(self, text="Patologías de la inspección", style="Subtitulo.TLabel").pack(anchor="w")
        self.tabla = TablaTreeview(self, COLUMNAS_PATOLOGIA, altura=6, al_seleccionar=self._elegida)
        self.tabla.pack(fill="x", pady=4)
        b = ttk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="Nueva", command=self.nueva).pack(side="left")
        ttk.Button(b, text="Eliminar", style="Peligro.TButton", command=self.eliminar).pack(side="left", padx=6)
        ttk.Button(b, text="Importar CSV…", command=self.importar).pack(side="right")
        self.cont = FrameDesplazable(self)
        self.cont.pack(fill="both", expand=True, pady=(6, 0))
        self.formas = None
        ctx.suscribir("rois", lambda *_: self._reconstruir())
        ctx.suscribir("tramo_activo", lambda *_: self._reconstruir())
        self._reconstruir()

    def _reconstruir(self):
        for w in self.cont.interior.winfo_children():
            w.destroy()
        esq = self.pres.esquema_patologia()
        sel = self.pres.selectores_patologia(self.ctx.tramo_id)
        i = self.cont.interior
        self.f_pat = FormularioEsquema(self._caja(i, "Patología (Ficha 2)"), esq["patologia"], selectores=sel,
                                       columnas=2, ancho_entrada=16, resumen=False)
        self.f_geo = FormularioEsquema(self._caja(i, "Geometría (Ficha 4) · anchos en mm"), esq["geometria"], columnas=2,
                                       ancho_entrada=12, resumen=False)
        self.f_sev = FormularioEsquema(self._caja(i, "Severidad oficial (Ficha 3)"), esq["severidad"], columnas=1,
                                       ancho_entrada=22, resumen=False)
        for f in (self.f_pat, self.f_geo, self.f_sev):
            f.pack(fill="x")
        self.resumen = Banner(i)
        self._btn = ttk.Button(i, text="Guardar patología", style="Accion.TButton", command=self.guardar)
        self._btn.pack(anchor="e", pady=8)
        self._cargar()

    @staticmethod
    def _caja(master, texto):
        c = ttk.LabelFrame(master, text=texto, padding=8)
        c.pack(fill="x", pady=(0, 6))
        return c

    def fijar_inspeccion(self, insp_id):
        self._insp, self._id = insp_id, None
        self.recargar()

    def recargar(self):
        r = self.pres.listar_patologias(self._insp)
        self._datos = {p["id"]: p for p in (r.datos or [])}
        self.tabla.cargar([(p["id"], self.pres.fila_patologia(p)) for p in self._datos.values()])
        if self._id not in self._datos:
            self._id = None
        self._cargar()

    def _cargar(self):
        p = self._datos.get(self._id)
        e = self.pres.esquema_patologia()
        self.f_pat.escribir(formularios.datos_a_textos(e["patologia"], p))
        self.f_geo.escribir(formularios.datos_a_textos(e["geometria"], (p or {}).get("geometria")))
        self.f_sev.escribir(formularios.datos_a_textos(e["severidad"], (p or {}).get("severidad")))
        self.resumen.pack_forget()

    def _elegida(self, iid):
        self._id = iid
        self._cargar()

    def nueva(self):
        self.tabla.seleccionar(None)
        self._id = None
        self._cargar()

    def guardar(self):
        if self._insp is None:
            messagebox.showinfo("Patología", "Elija o cree primero una inspección.", parent=self)
            return
        pat, geo, sev = self.f_pat.leer(), self.f_geo.leer(), self.f_sev.leer()
        r = (self.pres.actualizar_patologia(self._id, pat, geo, sev) if self._id is not None
             else self.pres.registrar_patologia(self._insp, pat, geo, sev))
        if not r.ok:
            e = self.pres.esquema_patologia()
            self.f_pat.mostrar_errores({k: v for k, v in r.errores.items() if k in {c["nombre"] for c in e["patologia"]}})
            self.f_geo.mostrar_errores({k: v for k, v in r.errores.items() if k in {c["nombre"] for c in e["geometria"]}})
            self.f_sev.mostrar_errores({k: v for k, v in r.errores.items() if k in {c["nombre"] for c in e["severidad"]}})
            todas = formularios.lineas_error(e["patologia"] + e["geometria"] + e["severidad"], r.errores)
            self.resumen.pack(fill="x", pady=(6, 0), before=self._btn)
            self.resumen.mostrar("No se pudo guardar:\n" + "\n".join("• " + x for x in todas), "error")
            return
        self._id = r.datos["id"]
        self.recargar()
        self.tabla.seleccionar(self._id)

    def eliminar(self):
        if self._id is None or not messagebox.askyesno("Eliminar", "¿Eliminar la patología seleccionada?",
                                                       icon="warning", parent=self):
            return
        r = self.pres.eliminar_patologia(self._id)
        if not r.ok:
            messagebox.showerror("No se pudo eliminar", r.texto_errores(), parent=self)
        self._id = None
        self.recargar()

    def importar(self):
        if self._insp is None:
            messagebox.showinfo("Importar", "Elija primero una inspección.", parent=self)
            return
        dialogo_reporte.flujo_importacion(
            self, "Importar patologías (Fichas 2-4)", TIPOS_CSV, OPC_IMPORT[1:],
            lambda ruta, op, simular: self.pres.importar_patologias(self._insp, ruta, bool(op["estricto"]), simular),
            lambda m: messagebox.showerror("Importación", m, parent=self))
        self.recargar()


class VistaFichas(ttk.Frame):
    def __init__(self, master, ctx):
        super().__init__(master, padding=4)
        self.ctx, self.pres = ctx, PresentadorFichas(ctx)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        for f in ("vuelo", "condicion", "gcp", "catalogo"):
            nb.add(PanelFicha(nb, ctx, self.pres, f), text=TITULOS[f])
        pan = ttk.PanedWindow(nb, orient="horizontal")
        self.pat = PanelPatologias(pan, ctx, self.pres)
        self.insp = PanelFicha(pan, ctx, self.pres, "inspeccion", al_seleccionar=self.pat.fijar_inspeccion)
        pan.add(self.insp, weight=2)
        pan.add(self.pat, weight=3)
        nb.add(pan, text="Inspecciones y patologías")
        ctx.suscribir("tramo_activo", lambda *_: self.pat.fijar_inspeccion(None))
        ctx.suscribir("fichas", lambda f=None: self.pat.recargar() if f == "patologia" else None)
