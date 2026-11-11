"""
vista_comparacion.py
====================
Pestaña «Métodos» (Fase 7): compara el método 'actual' con 'sun' (Sun, 2009) sobre las MISMAS ROI de prueba y los MISMOS
Params. «Analizar y validar con ambos» corre los dos métodos en segundo plano (con progreso y cancelación), valida cada
uno y compara; «Comparar lo ya validado» solo compara. Muestra métricas, tiempo/RAM y la conclusión (solo cifras).
Toda la lógica está en `PresentadorComparacion`; aquí solo hay widgets.
"""
import tkinter as tk
from tkinter import ttk

from app.ui.presentadores.p_comparacion import COLUMNAS_METRICAS, COLUMNAS_RENDIMIENTO, PresentadorComparacion
from app.ui.widgets import Banner, FrameDesplazable, TablaTreeview

SONDEO_MS = 200


class VistaComparacion(ttk.Frame):
    def __init__(self, master, ctx, gestor=None):
        super().__init__(master, padding=4)
        self.ctx = ctx
        self.pres = PresentadorComparacion(ctx, gestor)
        self._sondeo = None
        marco = FrameDesplazable(self)
        marco.pack(fill="both", expand=True)
        c = marco.interior
        c.columnconfigure(0, weight=1)
        ttk.Label(c, text="Comparación de métodos de detección: «actual» (black-hat + MAD) vs «sun» (Sun, 2009)",
                  style="Subtitulo.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(c, text="Mismas ROI de prueba, mismos Params base y misma referencia de campo. «sun» solo detecta grietas "
                          "lineales: se compara únicamente en ese tipo de deterioro.", style="Suave.TLabel",
                  wraplength=1000, justify="left").grid(row=1, column=0, sticky="w", padx=8)
        fs = ttk.Frame(c)
        fs.grid(row=2, column=0, sticky="w", padx=8, pady=6)
        mets = self.pres.metodos_disponibles()
        self.v_a, self.v_b = tk.StringVar(value=self.pres.metodo_a), tk.StringVar(value=self.pres.metodo_b)
        ttk.Label(fs, text="Método A").pack(side="left")
        self.cb_a = ttk.Combobox(fs, textvariable=self.v_a, values=mets, state="readonly", width=10)
        self.cb_a.pack(side="left", padx=(4, 12))
        ttk.Label(fs, text="Método B").pack(side="left")
        self.cb_b = ttk.Combobox(fs, textvariable=self.v_b, values=mets, state="readonly", width=10)
        self.cb_b.pack(side="left", padx=(4, 0))
        self.banner = Banner(c)
        self.banner.poner_en_grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        self.banner.ajustar_ancho(1000)
        fb = ttk.Frame(c)
        fb.grid(row=4, column=0, sticky="ew", padx=8)
        self.btn_ejecutar = ttk.Button(fb, text="Analizar y validar con ambos", style="Accion.TButton", command=self.ejecutar)
        self.btn_ejecutar.pack(side="left")
        self.btn_comparar = ttk.Button(fb, text="Comparar lo ya validado", command=self.comparar)
        self.btn_comparar.pack(side="left", padx=6)
        self.btn_cancel = ttk.Button(fb, text="Cancelar", command=self.pres.cancelar, state="disabled")
        self.btn_cancel.pack(side="left")
        self.barra = ttk.Progressbar(fb, maximum=100, length=200)
        self.barra.pack(side="left", padx=10)
        self.lbl_prog = ttk.Label(fb, text="", style="Suave.TLabel")
        self.lbl_prog.pack(side="left")
        ttk.Label(c, text="Métricas (mismas unidades ROI × tipo)", style="Subtitulo.TLabel").grid(
            row=5, column=0, sticky="w", padx=8, pady=(10, 2))
        self.t_metricas = TablaTreeview(c, COLUMNAS_METRICAS, altura=7)
        self.t_metricas.grid(row=6, column=0, sticky="ew", padx=8)
        ttk.Label(c, text="Tiempo de cómputo y RAM", style="Subtitulo.TLabel").grid(row=7, column=0, sticky="w", padx=8,
                                                                                     pady=(10, 2))
        self.t_rend = TablaTreeview(c, COLUMNAS_RENDIMIENTO, altura=3)
        self.t_rend.grid(row=8, column=0, sticky="ew", padx=8)
        ttk.Label(c, text="Conclusión (solo cifras calculadas)", style="Subtitulo.TLabel").grid(
            row=9, column=0, sticky="w", padx=8, pady=(10, 2))
        self.txt = tk.Text(c, height=14, wrap="word", state="disabled", relief="flat", background="#f7f8fa")
        self.txt.grid(row=10, column=0, sticky="ew", padx=8, pady=(0, 8))
        for ev in ("tramo_activo", "bd"):
            ctx.suscribir(ev, lambda *_: self.limpiar())

    # ---------------------------------------------------------------- acciones
    def _elegir(self):
        r = self.pres.fijar_metodos(self.v_a.get(), self.v_b.get())
        if not r.ok:
            self.banner.mostrar(r.texto_errores(), "error")
        return r.ok

    def comparar(self):
        if not self._elegir():
            return
        r = self.pres.comparar(self.ctx.tramo_id)
        if not r.ok:
            self.banner.mostrar(r.texto_errores(), "error")
            return
        self.mostrar(r.datos)

    def ejecutar(self):
        if not self._elegir():
            return
        r = self.pres.iniciar(self.ctx.tramo_id)
        if not r.ok:
            self.banner.mostrar(r.texto_errores(), "error")
            return
        self.banner.ocultar()
        self._ocupado(True)
        self._programar()

    def _ocupado(self, si):
        self.btn_ejecutar.configure(state="disabled" if si else "normal")
        self.btn_comparar.configure(state="disabled" if si else "normal")
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
            elif ev[0] == "mensaje":
                self.banner.mostrar(ev[2], ev[1])
            elif ev[0] == "comparacion":
                self.mostrar(ev[1])
            elif ev[0] == "fin":
                seguir = False
                self.barra.configure(value=0)
                self.lbl_prog.configure(text="")
                self._ocupado(False)
        if seguir and self.pres.ocupado:
            self._programar()
        elif seguir:
            self._ocupado(False)

    # ---------------------------------------------------------------- resultados
    def mostrar(self, c):
        self.t_metricas.cargar(self.pres.filas_metricas(c), conservar_seleccion=False)
        self.t_rend.cargar(self.pres.filas_rendimiento(c), conservar_seleccion=False)
        texto = self.pres.texto_conclusiones(c)
        adv = self.pres.texto_advertencias(c)
        if adv:
            texto += "\n\nAdvertencias y límites\n" + adv
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", texto)
        self.txt.configure(state="disabled")
        if c["provisional"]:
            self.banner.mostrar("PROVISIONAL: parámetros sin calibrar con datos reales; no es evidencia final.", "aviso")
        else:
            self.banner.ocultar()

    def limpiar(self):
        self.t_metricas.limpiar()
        self.t_rend.limpiar()
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.banner.ocultar()
        self.pres.comparacion = None

    def cerrar(self):
        self.pres.cerrar()
