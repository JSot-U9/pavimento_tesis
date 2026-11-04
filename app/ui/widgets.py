"""
widgets.py
==========
Widgets reutilizables (ttk, tema clam). Sin lógica de negocio: reciben datos ya preparados por los
presentadores y devuelven textos/valores crudos para que `logica_*` los valide.

    FrameDesplazable   contenedor con barra de desplazamiento vertical
    TablaTreeview      Treeview con barras, orden por encabezado y callbacks
    FormularioEsquema  formulario generado desde un esquema (`esquema_tramo`, `esquema_ficha`, ...)
    Banner             caja de aviso / error que se oculta sola
"""
import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Sequence

from app.ui import estilos
from app.ui.presentadores import formularios

SI_NO = ("", "Sí", "No")


def _rueda(evento):
    """Dirección de la rueda del ratón (-1 arriba / +1 abajo) en Windows, macOS y Linux."""
    if evento.num == 4:
        return -1
    if evento.num == 5:
        return 1
    return -1 if evento.delta > 0 else 1


class FrameDesplazable(ttk.Frame):
    """Contenedor con desplazamiento vertical. Poner los hijos en `.interior`."""

    def __init__(self, master, fondo=estilos.FONDO, **kw):
        super().__init__(master, **kw)
        self.lienzo = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=fondo)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.lienzo.yview)
        self.lienzo.configure(yscrollcommand=self.barra.set)
        self.lienzo.pack(side="left", fill="both", expand=True)
        self.barra.pack(side="right", fill="y")
        self.interior = ttk.Frame(self.lienzo)
        self._ventana = self.lienzo.create_window((0, 0), window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda e: self.lienzo.configure(scrollregion=self.lienzo.bbox("all")))
        self.lienzo.bind("<Configure>", lambda e: self.lienzo.itemconfigure(self._ventana, width=e.width))
        for w in (self.lienzo, self.interior):
            w.bind("<Enter>", self._activar_rueda)
            w.bind("<Leave>", self._desactivar_rueda)

    def _activar_rueda(self, _e=None):
        self.lienzo.bind_all("<MouseWheel>", self._rueda_evento)
        self.lienzo.bind_all("<Button-4>", self._rueda_evento)
        self.lienzo.bind_all("<Button-5>", self._rueda_evento)

    def _desactivar_rueda(self, _e=None):
        # al pasar a un hijo también se dispara <Leave>: solo soltamos si el puntero salió del contenedor
        x, y = self.winfo_pointerxy()
        w = self.winfo_containing(x, y)
        while w is not None:
            if w is self:
                return
            w = getattr(w, "master", None)
        for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.lienzo.unbind_all(s)

    def _rueda_evento(self, e):
        if self.interior.winfo_height() > self.lienzo.winfo_height():
            self.lienzo.yview_scroll(_rueda(e) * 2, "units")

    def destroy(self):
        for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.lienzo.unbind_all(s)
            except tk.TclError:
                pass
        super().destroy()


class TablaTreeview(ttk.Frame):
    """Treeview con barras de desplazamiento. `columnas` = [(id, encabezado, ancho)]; las filas son
    (iid, valores). Clic en el encabezado ordena (numérico si todos los valores lo son)."""

    def __init__(self, master, columnas: Sequence[tuple], altura=8, al_seleccionar: Optional[Callable] = None,
                 al_doble_clic: Optional[Callable] = None, seleccion_multiple=False, **kw):
        super().__init__(master, **kw)
        self.columnas = [c[0] for c in columnas]
        self._orden = (None, False)
        self.arbol = ttk.Treeview(self, columns=self.columnas, show="headings", height=altura,
                                  selectmode="extended" if seleccion_multiple else "browse")
        for cid, texto, ancho in columnas:
            self.arbol.heading(cid, text=texto, command=lambda c=cid: self.ordenar(c))
            self.arbol.column(cid, width=ancho, minwidth=36, stretch=True, anchor="w")
        vs = ttk.Scrollbar(self, orient="vertical", command=self.arbol.yview)
        hs = ttk.Scrollbar(self, orient="horizontal", command=self.arbol.xview)
        self.arbol.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._al_seleccionar, self._al_doble = al_seleccionar, al_doble_clic
        self._actual = None            # última selección ya conocida por la vista (el evento de Tk llega tarde)
        self.arbol.bind("<<TreeviewSelect>>", self._seleccion_cambio)
        if al_doble_clic:
            self.arbol.bind("<Double-1>", lambda e: al_doble_clic(self.seleccion()))

    def _seleccion_cambio(self, _e=None):
        """<<TreeviewSelect>> se entrega de forma ASÍNCRONA: solo se avisa si la selección difiere de la que la
        vista ya conoce (así los cambios hechos por programa no disparan el callback ni borran el formulario)."""
        s = self.seleccion()
        if s == self._actual:
            return
        self._actual = s
        if self._al_seleccionar:
            self._al_seleccionar(s)

    def cargar(self, filas: List[tuple], conservar_seleccion=True):
        """Reemplaza el contenido. No dispara `al_seleccionar` (la vista ya sabe lo que cargó)."""
        previa = self.seleccion() if conservar_seleccion else None
        self.arbol.delete(*self.arbol.get_children())
        for iid, valores in filas:
            self.arbol.insert("", "end", iid=str(iid), values=tuple(valores))
        if self._orden[0] is not None:
            self.ordenar(self._orden[0], invertir=self._orden[1], alternar=False)
        if previa is not None and self.arbol.exists(str(previa)):
            self.arbol.selection_set(str(previa))
        self._actual = self.seleccion()

    def seleccion(self):
        s = self.arbol.selection()
        if not s:
            return None
        return self._convertir(s[0])

    def selecciones(self):
        return [self._convertir(s) for s in self.arbol.selection()]

    @staticmethod
    def _convertir(iid):
        try:
            return int(iid)
        except ValueError:
            return iid

    def seleccionar(self, iid, notificar=False):
        if iid is not None and self.arbol.exists(str(iid)):
            self.arbol.selection_set(str(iid))
            self.arbol.see(str(iid))
        else:
            self.arbol.selection_remove(*self.arbol.selection())
        if not notificar:
            self._actual = self.seleccion()

    def limpiar(self):
        self.cargar([], conservar_seleccion=False)

    def ordenar(self, col, invertir=None, alternar=True):
        if invertir is None:
            invertir = (self._orden[0] == col and not self._orden[1]) if alternar else False
        items = [(self.arbol.set(i, col), i) for i in self.arbol.get_children("")]

        def clave(par):
            t = par[0].replace(",", ".").split(" ")[0]
            try:
                return (0, float(t), "")
            except ValueError:
                return (1, 0.0, par[0].lower())
        items.sort(key=clave, reverse=invertir)
        for k, (_, i) in enumerate(items):
            self.arbol.move(i, "", k)
        self._orden = (col, invertir)


class Banner(ttk.Label):
    """Caja de aviso (ámbar) o error (rojo) que ocupa su fila solo cuando tiene texto."""

    def __init__(self, master, **kw):
        super().__init__(master, wraplength=520, justify="left", **kw)
        self._grid = None

    def mostrar(self, texto: str, nivel="aviso"):
        if not texto:
            return self.ocultar()
        self.configure(text=texto, style="ErrorCaja.TLabel" if nivel == "error" else "Aviso.TLabel")
        if self._grid is not None and not self.winfo_ismapped():
            self.grid()

    def ocultar(self):
        self.configure(text="")
        if self._grid is not None:
            self.grid_remove()

    def poner_en_grid(self, **opciones):
        self._grid = opciones
        self.grid(**opciones)
        self.grid_remove()
        return self

    def ajustar_ancho(self, ancho):
        self.configure(wraplength=max(120, ancho))


class FormularioEsquema(ttk.Frame):
    """Formulario generado desde un esquema (lista de dicts de `logica_*.esquema_*`).

    `selectores` = {campo: [(valor, etiqueta)]}: ese campo se elige de una lista (p. ej. el vuelo) en vez de
    escribir un id. `leer()` devuelve valores CRUDOS (texto; bool -> True/False/None; selector -> su valor):
    la validación y conversión son de `logica_*`, que informa TODOS los errores a la vez, y
    `mostrar_errores()` los pinta junto a cada campo y en un resumen con una línea por error."""

    def __init__(self, master, esquema: List[dict], selectores: Optional[Dict[str, list]] = None, columnas=1,
                 ancho_entrada=26, resumen=True, **kw):
        super().__init__(master, **kw)
        self.esquema = list(esquema)
        self.selectores = dict(selectores or {})
        self._cols = max(1, columnas)
        self._cw: Dict[str, tk.Widget] = {}
        self._var: Dict[str, tk.StringVar] = {}
        self._err: Dict[str, ttk.Label] = {}
        self._lab: Dict[str, ttk.Label] = {}
        self._ancho = ancho_entrada
        self._al_cambiar: Optional[Callable] = None
        self._construir()
        self._resumen = Banner(self)
        if resumen:
            self._resumen.poner_en_grid(row=1000, column=0, columnspan=3 * self._cols, sticky="ew", pady=(6, 0))
        for c in range(self._cols):
            self.columnconfigure(3 * c + 1, weight=1)

    # ---------------------------------------------------------------- construcción
    def _construir(self):
        for k, campo in enumerate(self.esquema):
            col, fila = divmod(k, -(-len(self.esquema) // self._cols))
            base = 3 * col
            nombre = campo["nombre"]
            marca = " *" if campo["requerido"] else ""
            lab = ttk.Label(self, text=campo["etiqueta"] + marca, anchor="w")
            lab.grid(row=2 * fila, column=base, sticky="w", padx=(0 if col == 0 else 14, 6), pady=(5, 0))
            var = tk.StringVar()
            if nombre in self.selectores:
                w = ttk.Combobox(self, textvariable=var, state="readonly", width=self._ancho - 2,
                                 values=[""] + [e for _, e in self.selectores[nombre]])
            elif campo["tipo"] == "bool":
                w = ttk.Combobox(self, textvariable=var, state="readonly", width=self._ancho - 2, values=SI_NO)
            elif campo["tipo"] == "opcion":
                w = ttk.Combobox(self, textvariable=var, state="readonly", width=self._ancho - 2,
                                 values=[""] + list(campo["opciones"]))
            else:
                w = ttk.Entry(self, textvariable=var, width=self._ancho)
            w.grid(row=2 * fila, column=base + 1, sticky="ew", pady=(5, 0))
            pista = formularios.pista(campo)
            ttk.Label(self, text=pista, style="Suave.TLabel").grid(row=2 * fila, column=base + 2, sticky="w",
                                                                   padx=(6, 0), pady=(5, 0))
            err = ttk.Label(self, text="", style="Error.TLabel", wraplength=220, justify="left")
            err.grid(row=2 * fila + 1, column=base + 1, columnspan=2, sticky="w")
            err.grid_remove()
            for widget in (w,):
                var.trace_add("write", lambda *_a, n=nombre: self._cambio(n))
            self._cw[nombre], self._var[nombre], self._err[nombre], self._lab[nombre] = w, var, err, lab

    def _cambio(self, nombre):
        self._marcar(nombre, None)                       # al editar un campo se quita su error
        if self._al_cambiar:
            self._al_cambiar(nombre)

    def al_cambiar(self, fn: Callable):
        self._al_cambiar = fn

    # ---------------------------------------------------------------- valores
    def _a_texto(self, nombre, valor):
        campo = next(c for c in self.esquema if c["nombre"] == nombre)
        if nombre in self.selectores:
            return next((e for v, e in self.selectores[nombre] if v == valor), "")
        if campo["tipo"] == "bool":
            return "" if valor is None or valor == "" else ("Sí" if valor in (True, "Sí", "Si", "si", "1") else "No")
        return "" if valor is None else str(valor)

    def escribir(self, textos: Dict[str, object]):
        """Pone valores (textos o valores de la BD) en los campos; los ausentes quedan vacíos."""
        for nombre in self._cw:
            self._var[nombre].set(self._a_texto(nombre, textos.get(nombre)))
        self.limpiar_errores()

    def limpiar(self):
        self.escribir({})

    def poner(self, nombre, valor):
        """Cambia un solo campo."""
        if nombre in self._var:
            self._var[nombre].set(self._a_texto(nombre, valor))

    def leer(self) -> Dict[str, object]:
        out = {}
        for campo in self.esquema:
            n = campo["nombre"]
            t = self._var[n].get().strip()
            if n in self.selectores:
                out[n] = next((v for v, e in self.selectores[n] if e == t), None) if t else None
            elif campo["tipo"] == "bool":
                out[n] = None if not t else (t == "Sí")
            else:
                out[n] = t
        return out

    def habilitar(self, activo=True, excepto: Sequence[str] = ()):
        for n, w in self._cw.items():
            if n in excepto:
                continue
            if isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if activo else "disabled")
            else:
                w.configure(state="normal" if activo else "disabled")

    def solo_lectura(self, nombres: Sequence[str], activo=True):
        for n in nombres:
            w = self._cw.get(n)
            if w is None:
                continue
            if isinstance(w, ttk.Combobox):
                w.configure(state="disabled" if activo else "readonly")
            else:
                w.configure(state="readonly" if activo else "normal")

    def foco(self, nombre=None):
        n = nombre or self.esquema[0]["nombre"]
        self._cw[n].focus_set()

    # ---------------------------------------------------------------- errores
    def _marcar(self, nombre, mensaje):
        w, err = self._cw[nombre], self._err[nombre]
        estilo = "Error.TCombobox" if isinstance(w, ttk.Combobox) else "Error.TEntry"
        if mensaje:
            w.configure(style=estilo)
            err.configure(text=mensaje)
            err.grid()
        else:
            w.configure(style="TCombobox" if isinstance(w, ttk.Combobox) else "TEntry")
            err.configure(text="")
            err.grid_remove()

    def limpiar_errores(self):
        for n in self._cw:
            self._marcar(n, None)
        self._resumen.ocultar()

    def mostrar_errores(self, errores: Dict[str, str], extra_general: str = ""):
        """Pinta TODOS los mensajes: junto a cada campo y en un resumen (una línea por error)."""
        for n in self._cw:
            self._marcar(n, None)
        propios, _ = formularios.repartir_errores(self.esquema, errores)
        for n, msg in propios.items():
            self._marcar(n, msg)
        lineas = formularios.lineas_error(self.esquema, errores)
        if extra_general:
            lineas.append(extra_general)
        if lineas:
            self._resumen.mostrar("No se pudo guardar:\n" + "\n".join("• " + x for x in lineas), "error")
        else:
            self._resumen.ocultar()
        primero = next(iter(propios), None)
        if primero:
            self._cw[primero].focus_set()

    def mostrar_aviso(self, texto: str):
        self._resumen.mostrar(texto, "aviso")
