"""
dialogo_parametros.py
=====================
Edición de los parámetros del motor para el análisis siguiente. Los marcados con ⚠ son PROVISIONALES
(calibrados solo con imágenes sintéticas). Se muestran TODOS los errores de una vez.
"""
from tkinter import ttk

from app.ui.dialogo_reporte import _Modal
from app.ui.widgets import Banner, FormularioEsquema, FrameDesplazable


class DialogoParametros(_Modal):
    def __init__(self, master, pres):
        super().__init__(master, "Parámetros del análisis", 760, 640)
        self.pres = pres
        m = ttk.Frame(self, padding=10)
        m.pack(fill="both", expand=True)
        ttk.Label(m, text="Parámetros del motor", style="Titulo.TLabel").pack(anchor="w")
        aviso = Banner(m)
        aviso.pack(fill="x", pady=6)
        aviso.mostrar(pres.aviso_provisional() or "Parámetros calibrados con datos reales.", "aviso")
        aviso.ajustar_ancho(700)
        ttk.Label(m, text="⚠ = provisional. La resolución (cm/px) sale del tramo. Los cambios valen para los "
                          "análisis de esta sesión; no modifican la configuración guardada.",
                  style="Suave.TLabel", wraplength=700, justify="left").pack(anchor="w")
        cont = FrameDesplazable(m)
        cont.pack(fill="both", expand=True, pady=6)
        campos = pres.campos_parametros()
        esquema = [{"nombre": c["nombre"], "etiqueta": ("⚠ " if c["provisional"] else "") + c["descripcion"],
                    "tipo": "texto", "requerido": True, "opciones": [], "minimo": None, "maximo": None, "unidad": ""}
                   for c in campos]
        self.form = FormularioEsquema(cont.interior, esquema, ancho_entrada=12, resumen=True)
        self.form.pack(fill="x", padx=4)
        self.form.escribir({c["nombre"]: c["valor"] for c in campos})
        pie = ttk.Frame(m)
        pie.pack(fill="x")
        ttk.Button(pie, text="Aplicar", style="Accion.TButton", command=self._aplicar).pack(side="right")
        ttk.Button(pie, text="Cerrar", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(pie, text="Restablecer", command=self._restablecer).pack(side="left")
        self.abrir()

    def _aplicar(self):
        r = self.pres.validar_parametros({k: str(v) for k, v in self.form.leer().items()})
        if not r.ok:
            self.form.mostrar_errores({k: v for k, v in r.errores.items() if k}, extra_general=r.errores.get("", ""))
            return
        self.resultado = True
        self.destroy()

    def _restablecer(self):
        self.pres.restablecer_parametros()
        self.form.escribir({c["nombre"]: c["valor"] for c in self.pres.campos_parametros()})
