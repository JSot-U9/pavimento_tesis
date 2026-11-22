"""
dialogo_tutorial.py
===================
Diálogo que ofrece el tutorial al usuario nuevo. Devuelve 'si', 'ahora_no' o 'no_preguntar' (cerrar con Esc = 'ahora_no').
"""
from tkinter import ttk

from app.ui.dialogo_reporte import _Modal


class DialogoOfertaTutorial(_Modal):
    def __init__(self, master):
        super().__init__(master, "Bienvenido", 520, 250)
        m = ttk.Frame(self, padding=14)
        m.pack(fill="both", expand=True)
        ttk.Label(m, text="¿Primera vez con el programa?", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(m, justify="left", wraplength=480, text=(
            "Hay un tutorial guiado de unos 10 minutos con un ejemplo sintético: le explica cada paso (tramo, ortomosaico, "
            "ROI, análisis, validación, reportes) y puede hacerlo por usted.\n\nUsa una base de datos de práctica: sus "
            "datos no se tocan. Podrá abrirlo cuando quiera con el botón «Tutorial» o la tecla F1.")).pack(anchor="w", pady=10)
        b = ttk.Frame(m)
        b.pack(side="bottom", fill="x")
        ttk.Button(b, text="Empezar el tutorial", style="Accion.TButton", command=lambda: self._elegir("si")).pack(side="left")
        ttk.Button(b, text="Ahora no", command=lambda: self._elegir("ahora_no")).pack(side="left", padx=8)
        ttk.Button(b, text="No volver a preguntar", style="Herramienta.TButton",
                   command=lambda: self._elegir("no_preguntar")).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", lambda: self._elegir("ahora_no"))

    def _elegir(self, valor):
        self.resultado = valor
        self.destroy()
