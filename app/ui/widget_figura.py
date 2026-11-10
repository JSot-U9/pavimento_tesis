"""
widget_figura.py
================
`VisorFigura`: muestra un `matplotlib.figure.Figure` (de `app.graficos`) dentro de Tk con `FigureCanvasTkAgg`.
La figura se ajusta al tamaño del widget. La misma Figure sirve para `savefig` (PDF de F6): este widget solo la muestra.
"""
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class VisorFigura(ttk.Frame):
    def __init__(self, master, vacio="Sin datos", **kw):
        super().__init__(master, **kw)
        self._vacio = vacio
        self._fig = None
        self._canvas = None
        self._aviso = ttk.Label(self, text=vacio, style="Suave.TLabel", anchor="center")
        self._aviso.pack(fill="both", expand=True)
        self._tarea = None

    @property
    def figura(self):
        return self._fig

    def mostrar(self, fig, vacio=None):
        """Muestra `fig` (o el texto de «sin datos» si es None). Libera la figura anterior."""
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        self._fig = fig
        if fig is None:
            self._aviso.configure(text=vacio or self._vacio)
            self._aviso.pack(fill="both", expand=True)
            return
        self._aviso.pack_forget()
        self._canvas = FigureCanvasTkAgg(fig, master=self)
        w = self._canvas.get_tk_widget()
        w.configure(highlightthickness=0, background="white", width=120, height=90)   # tamaño mínimo: la figura se adapta al hueco
        w.pack(fill="both", expand=True)
        w.bind("<Configure>", self._ajustar)
        self._canvas.draw_idle()

    def _ajustar(self, e):
        if self._fig is None or e.width < 80 or e.height < 80:
            return
        dpi = self._fig.get_dpi()
        self._fig.set_size_inches(e.width / dpi, e.height / dpi, forward=False)
        if self._tarea is not None:
            self.after_cancel(self._tarea)
        self._tarea = self.after(60, self._dibujar)

    def _dibujar(self):
        self._tarea = None
        if self._canvas is not None:
            self._canvas.draw_idle()

    def destroy(self):
        if self._tarea is not None:
            try:
                self.after_cancel(self._tarea)
            except tk.TclError:
                pass
        super().destroy()
