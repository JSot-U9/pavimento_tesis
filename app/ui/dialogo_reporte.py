"""
dialogo_reporte.py
==================
Diálogos modales de informe:

    DialogoInforme      muestra un informe de importación (resumen, errores por fila, advertencias) y,
                        si procede, pide CONFIRMAR antes de guardar.
    DialogoImportar     pide archivo y opciones de una importación.
    DialogoTexto        muestra un texto largo (p. ej. el reparto de roles).
    flujo_importacion   vista previa (simular=True) -> confirmar -> importar de verdad.
"""
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional, Sequence

from app.ui import estilos
from app.ui.widgets import TablaTreeview


class _Modal(tk.Toplevel):
    def __init__(self, master, titulo, ancho=640, alto=460):
        super().__init__(master)
        self.title(titulo)
        self.configure(background=estilos.FONDO)
        self.transient(master.winfo_toplevel())
        self.geometry(f"{ancho}x{alto}")
        self.resultado = None
        self.bind("<Escape>", lambda e: self.destroy())

    def abrir(self):
        self.update_idletasks()
        try:
            self.grab_set()
        except tk.TclError:                       # ventana aún no visible (p. ej. sin gestor de ventanas)
            pass
        self.wait_window(self)
        return self.resultado


class DialogoInforme(_Modal):
    def __init__(self, master, informe, confirmable=False):
        super().__init__(master, informe.titulo, 700, 520)
        marco = ttk.Frame(self, padding=12)
        marco.pack(fill="both", expand=True)
        ttk.Label(marco, text=informe.titulo, style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(marco, text=informe.resumen(), justify="left", wraplength=660).pack(anchor="w", pady=(6, 8))
        nb = ttk.Notebook(marco)
        nb.pack(fill="both", expand=True)
        if informe.errores:
            t = TablaTreeview(nb, (("fila", "Fila", 60), ("msg", "Error", 560)), altura=8)
            t.cargar([(i, (f, m)) for i, (f, m) in enumerate(informe.errores)])
            nb.add(t, text=f"Errores ({len(informe.errores)})")
        if informe.advertencias:
            t = TablaTreeview(nb, (("n", "N.º", 50), ("msg", "Advertencia", 570)), altura=8)
            t.cargar([(i, (i + 1, m)) for i, m in enumerate(informe.advertencias)])
            nb.add(t, text=f"Advertencias ({len(informe.advertencias)})")
        if not nb.tabs():
            nb.destroy()
            ttk.Label(marco, text="Sin errores ni advertencias.", style="Ok.TLabel").pack(anchor="w")
        pie = ttk.Frame(marco)
        pie.pack(fill="x", pady=(10, 0))
        if confirmable:
            b = ttk.Button(pie, text="Confirmar importación", style="Accion.TButton", command=self._ok)
            b.pack(side="right")
            if not informe.puede_confirmar:
                b.state(["disabled"])
            ttk.Button(pie, text="Cancelar", command=self.destroy).pack(side="right", padx=6)
        else:
            ttk.Button(pie, text="Cerrar", command=self.destroy).pack(side="right")

    def _ok(self):
        self.resultado = True
        self.destroy()


class DialogoTexto(_Modal):
    def __init__(self, master, titulo, texto):
        super().__init__(master, titulo, 560, 360)
        marco = ttk.Frame(self, padding=12)
        marco.pack(fill="both", expand=True)
        caja = tk.Text(marco, wrap="word", height=10, relief="flat", background="#ffffff", padx=8, pady=6)
        caja.insert("1.0", texto)
        caja.configure(state="disabled")
        caja.pack(fill="both", expand=True)
        ttk.Button(marco, text="Cerrar", command=self.destroy).pack(anchor="e", pady=(8, 0))


class DialogoImportar(_Modal):
    """opciones = [(nombre, etiqueta, tipo 'opcion'|'bool'|'texto', valores, defecto)]."""

    def __init__(self, master, titulo, tipos_archivo: Sequence[tuple], opciones: Sequence[tuple]):
        super().__init__(master, titulo, 560, 120 + 36 * len(opciones))
        self._tipos = tipos_archivo
        marco = ttk.Frame(self, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)
        ttk.Label(marco, text="Archivo").grid(row=0, column=0, sticky="w")
        self.ruta = tk.StringVar()
        ttk.Entry(marco, textvariable=self.ruta).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(marco, text="Examinar…", command=self._examinar).grid(row=0, column=2)
        self._vars = {}
        for i, (n, et, tipo, vals, defecto) in enumerate(opciones, start=1):
            if tipo == "bool":
                v = tk.BooleanVar(value=bool(defecto))
                ttk.Checkbutton(marco, text=et, variable=v).grid(row=i, column=0, columnspan=3, sticky="w", pady=3)
            else:
                v = tk.StringVar(value=str(defecto))
                ttk.Label(marco, text=et).grid(row=i, column=0, sticky="w", pady=3)
                if tipo == "opcion":
                    w = ttk.Combobox(marco, textvariable=v, values=list(vals), state="readonly", width=14)
                else:
                    w = ttk.Entry(marco, textvariable=v, width=18)
                w.grid(row=i, column=1, sticky="w", padx=6)
            self._vars[n] = v
        pie = ttk.Frame(marco)
        pie.grid(row=len(opciones) + 1, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(pie, text="Vista previa", style="Accion.TButton", command=self._ok).pack(side="right")
        ttk.Button(pie, text="Cancelar", command=self.destroy).pack(side="right", padx=6)

    def _examinar(self):
        r = filedialog.askopenfilename(parent=self, filetypes=self._tipos)
        if r:
            self.ruta.set(r)

    def _ok(self):
        if self.ruta.get().strip():
            self.resultado = (self.ruta.get().strip(), {n: v.get() for n, v in self._vars.items()})
            self.destroy()


def flujo_importacion(master, titulo, tipos_archivo, opciones, ejecutar: Callable[[str, dict, bool], object],
                      alerta: Callable[[str], None]) -> Optional[object]:
    """1) pide archivo/opciones; 2) ejecuta con simular=True y muestra el informe; 3) si el usuario confirma,
    ejecuta de verdad. `ejecutar(ruta, opciones, simular) -> Resultado` (con .datos = InformeImportacion).
    Devuelve el informe final o None."""
    pedido = DialogoImportar(master, titulo, tipos_archivo, opciones).abrir()
    if not pedido:
        return None
    ruta, op = pedido
    prev = ejecutar(ruta, op, True)
    if not prev.ok:
        alerta(prev.texto_errores())
        return None
    if not DialogoInforme(master, prev.datos, confirmable=True).abrir():
        return None
    fin = ejecutar(ruta, op, False)
    if not fin.ok:
        alerta(fin.texto_errores())
        return None
    DialogoInforme(master, fin.datos).abrir()
    return fin.datos
