"""
panel_tutorial.py
=================
Panel lateral del MODO TUTORIAL (Tk + ttk). Solo dibuja: qué paso toca, qué está hecho y los botones. La lógica (pasos,
estado, textos) está en `presentadores/p_tutorial.py`; las acciones de «Hacerlo por mí» las ejecuta la ventana principal.
El panel mira el avance cada ~1 s (la base de datos manda): reconoce los pasos hechos a mano o por el botón.
"""
import tkinter as tk
from tkinter import ttk
from typing import Callable

from app.ui import estilos
from app.ui.widgets import Banner

SONDEO_MS = 900
ANCHO = 370


class PanelTutorial(ttk.Frame):
    def __init__(self, master, pres, al_cambiar_paso: Callable, al_hacer: Callable, al_salir: Callable,
                 al_reiniciar: Callable, esta_ocupado: Callable[[], bool] = lambda: False):
        super().__init__(master, padding=8, width=ANCHO)
        self.pres, self._cambio, self._hacer, self._salir, self._reiniciar = pres, al_cambiar_paso, al_hacer, al_salir, al_reiniciar
        self._ocupado = esta_ocupado
        self._sondeo = None
        self._firma = None
        self.pack_propagate(False)
        # --- cabecera
        ttk.Label(self, text="MODO TUTORIAL · datos de práctica", style="Aviso.TLabel").pack(fill="x")
        ttk.Label(self, text="Sus datos reales no se tocan.", style="Suave.TLabel").pack(anchor="w", pady=(2, 4))
        self.barra = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.barra.pack(fill="x")
        self.lbl_progreso = ttk.Label(self, text="", style="Suave.TLabel")
        self.lbl_progreso.pack(anchor="w", pady=(2, 4))
        # --- lista de pasos
        self.lista = ttk.Treeview(self, columns=("t",), show="", height=len(pres.pasos), selectmode="browse", style="Tutorial.Treeview")
        self.lista.column("t", width=ANCHO - 40, stretch=True)
        self.lista.tag_configure("hecho", foreground=estilos.OK)
        self.lista.tag_configure("actual", background=estilos.ACENTO_CLARO)
        self.lista.pack(fill="x")
        self.lista.bind("<<TreeviewSelect>>", self._elegida)
        # --- paso actual
        self.lbl_paso = ttk.Label(self, text="", style="Titulo.TLabel", wraplength=ANCHO - 24, justify="left")
        self.lbl_paso.pack(anchor="w", pady=(8, 2))
        cuerpo = ttk.Frame(self)
        self.txt = tk.Text(cuerpo, wrap="word", height=8, width=10, relief="flat", background=estilos.FONDO_PANEL,
                           foreground=estilos.TEXTO, padx=8, pady=6, borderwidth=1, highlightthickness=1,
                           highlightbackground=estilos.BORDE, cursor="arrow")
        sb = ttk.Scrollbar(cuerpo, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        fam = estilos.fuente_base()
        self.txt.tag_configure("h", font=(fam, 10, "bold"), foreground=estilos.ACENTO_OSCURO, spacing1=6)
        self.txt.tag_configure("n", lmargin1=6, lmargin2=20)
        self.txt.tag_configure("ver", foreground=estilos.OK)
        # --- archivo de ejemplo
        self.fila_arch = ttk.Frame(self)
        ttk.Label(self.fila_arch, text="Archivo de ejemplo:", style="Suave.TLabel").pack(anchor="w")
        f2 = ttk.Frame(self.fila_arch)
        f2.pack(fill="x")
        self.v_ruta = tk.StringVar()
        ttk.Entry(f2, textvariable=self.v_ruta, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(f2, text="Copiar ruta", style="Herramienta.TButton", command=self._copiar).pack(side="left", padx=(4, 0))
        # --- estado y mensajes
        self.lbl_estado = ttk.Label(self, text="", style="Subtitulo.TLabel")
        self.msg = Banner(self)
        self.msg.ajustar_ancho(ANCHO - 30)
        # --- botones
        b = self._fila_botones = ttk.Frame(self)
        self.btn_ant = ttk.Button(b, text="◀ Anterior", command=self._anterior)
        self.btn_ant.pack(side="left")
        self.btn_hacer = ttk.Button(b, text="Hacerlo por mí", style="Accion.TButton", command=self._hacer_clic)
        self.btn_hacer.pack(side="left", padx=6)
        self.btn_sig = ttk.Button(b, text="Siguiente ▶", command=self._siguiente)
        self.btn_sig.pack(side="left")
        pie = ttk.Frame(self)
        ttk.Button(pie, text="Reiniciar tutorial", style="Herramienta.TButton", command=self._reiniciar).pack(side="left")
        ttk.Button(pie, text="Salir del tutorial", style="Herramienta.TButton", command=self._salir).pack(side="right")
        # lo de abajo se empaqueta primero: así los botones nunca quedan recortados y el texto absorbe el espacio libre
        pie.pack(side="bottom", fill="x", pady=(2, 0))
        b.pack(side="bottom", fill="x", pady=(4, 2))
        self.lbl_estado.pack(side="bottom", anchor="w", pady=(6, 2))
        cuerpo.pack(side="top", fill="both", expand=True)
        self._poblar_lista()
        self.mostrar_paso(notificar=True)
        self._programar()

    # ---------------------------------------------------------------- dibujo
    def _poblar_lista(self):
        self.lista.delete(*self.lista.get_children())
        for i, icono, titulo in self.pres.lista():
            tags = ("hecho",) if icono == "✔" else (("actual",) if icono == "▶" else ())
            self.lista.insert("", "end", iid=str(i), values=(f"{icono}  {titulo}",), tags=tags)

    def _escribir(self, p):
        t = self.txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", "Qué es\n", "h")
        t.insert("end", p.que + "\n")
        t.insert("end", "Cómo hacerlo\n", "h")
        for n, linea in enumerate(p.como, 1):
            t.insert("end", f"{n}. {linea}\n", "n")
        t.insert("end", "Qué debería ver\n", "h")
        t.insert("end", p.ver + "\n", "ver")
        t.configure(state="disabled")
        t.yview_moveto(0)

    def mostrar_paso(self, notificar=False):
        p = self.pres.paso
        self.lbl_paso.configure(text=f"{self.pres.titulo_paso()} · {p.titulo}")
        self._escribir(p)
        ruta = self.pres.archivo_del_paso()
        if ruta:
            self.v_ruta.set(ruta)
            self.fila_arch.pack(side="bottom", fill="x", pady=(6, 0), after=self.lbl_estado)
        else:
            self.fila_arch.pack_forget()
        self._quitar_aviso()
        self.refrescar_estado(forzar=True)
        if notificar:
            self._cambio(p)

    def refrescar_estado(self, forzar=False):
        pres = self.pres
        firma = (pres.indice, tuple(i for i in range(pres.total) if pres.hecho(i)), self._ocupado())
        if not forzar and firma == self._firma:
            return
        self._firma = firma
        self._poblar_lista()
        self.lista.selection_remove(*self.lista.selection())
        self.barra.configure(value=100 * pres.fraccion())
        self.lbl_progreso.configure(text=pres.texto_progreso())
        hecho = pres.hecho()
        self.lbl_estado.configure(text=pres.texto_estado(), style="Ok.TLabel" if (hecho or pres.paso.informativo) else "Subtitulo.TLabel")
        ocupado = self._ocupado()
        auto = not pres.paso.informativo
        self.btn_hacer.state(["!disabled"] if (auto and not hecho and not ocupado) else ["disabled"])
        self.btn_hacer.pack_forget() if not auto else self.btn_hacer.pack(side="left", padx=6, after=self.btn_ant)
        self.btn_ant.state(["!disabled"] if pres.indice > 0 else ["disabled"])
        self.btn_sig.state(["!disabled"] if pres.puede_siguiente() else ["disabled"])
        self.btn_sig.configure(style="Accion.TButton" if pres.siguiente_recomendado() else "TButton")

    # ---------------------------------------------------------------- eventos
    def _elegida(self, _e=None):
        s = self.lista.selection()
        if s and self.pres.ir_a(int(s[0])):
            self.mostrar_paso(notificar=True)

    def _anterior(self):
        if self.pres.anterior():
            self.mostrar_paso(notificar=True)

    def _siguiente(self):
        if self.pres.siguiente():
            self.mostrar_paso(notificar=True)

    def _hacer_clic(self):
        self._quitar_aviso()
        b = self.pres.bloqueo()
        if b:
            self.mostrar_aviso(b)
            return
        self._hacer()
        self.refrescar_estado(forzar=True)

    def mostrar_aviso(self, texto, nivel="aviso"):
        self.msg.mostrar(texto, nivel)
        self.msg.pack(side="bottom", fill="x", after=self._fila_botones)

    def _quitar_aviso(self):
        self.msg.ocultar()
        self.msg.pack_forget()

    def _copiar(self):
        self.clipboard_clear()
        self.clipboard_append(self.v_ruta.get())

    # ---------------------------------------------------------------- sondeo
    def _programar(self):
        self._sondeo = self.after(SONDEO_MS, self._tick)

    def _tick(self):
        self._sondeo = None
        try:
            self.pres.refrescar()
            self.refrescar_estado()
        finally:
            self._programar()

    def cerrar(self):
        if self._sondeo is not None:
            self.after_cancel(self._sondeo)
            self._sondeo = None
