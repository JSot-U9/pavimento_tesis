"""
visor.py
========
Visor del ortomosaico por ventanas (Canvas de Tk). NUNCA carga el ortomosaico entero:

    - una miniatura (con presupuesto de píxeles) para la vista general y mientras se desplaza;
    - la zona visible se lee del archivo en un hilo (`imagen_visor.LectorAsincrono`) ya remuestreada al
      tamaño de pantalla, y se pinta cuando llega.

Herramientas: Mover (arrastrar; clic = seleccionar detección), ROI (rectángulo), Eje (polilínea: clic añade
vértice, doble clic/Enter termina, Retroceso quita el último, Esc cancela) y Ventana (rectángulo de análisis).
Rueda = zoom en el cursor; botón central = desplazar en cualquier herramienta.
La geometría vive en `visor_modelo` (sin Tk, con pruebas).
"""
import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

import cv2

from app.nucleo.estructuras import COLORES
from app.ui import estilos, imagen_visor as iv, visor_modelo as vm
from app.ui.widgets import _rueda

COLOR_TIPO = {t: "#%02x%02x%02x" % c for t, c in COLORES.items()}
MODOS = (("mover", "Mover / seleccionar"), ("roi", "Dibujar ROI"), ("eje", "Dibujar eje"),
         ("ventana", "Ventana de análisis"))
AYUDA = {
    "mover": "Arrastre para desplazar · rueda: zoom · clic en una detección: ver sus medidas",
    "roi": "Arrastre un rectángulo para crear una ROI",
    "eje": "Clic: añadir vértice · doble clic o Enter: terminar · Retroceso: quitar último · Esc: cancelar",
    "ventana": "Arrastre un rectángulo: será la ventana de análisis",
}
REFRESCO_MS = 40


class VisorOrtomosaico(ttk.Frame):
    def __init__(self, master, al_roi=None, al_eje=None, al_ventana=None, al_seleccion=None, al_cursor=None,
                 **kw):
        super().__init__(master, **kw)
        self.al_roi, self.al_eje, self.al_ventana = al_roi, al_eje, al_ventana
        self.al_seleccion, self.al_cursor = al_seleccion, al_cursor
        self.modelo: Optional[vm.ModeloVisor] = None
        self.gsd_cm = 0.5
        self._lector: Optional[iv.LectorAsincrono] = None
        self._mini = None                      # (rgb, escala)
        self._foto = None                      # PhotoImage vigente
        self._zona = None                      # (clave, region, rgb)
        self._clave_pedida = None
        self._mensaje = "Sin ortomosaico: asigne uno al tramo (pestaña Tramos)."
        self._rois, self._roi_sel, self._eje = [], None, None
        self._dets, self._det_sel, self._ventana = [], None, None
        self._modo = tk.StringVar(value="mover")
        self._arrastre = None                  # estado de un arrastre en curso
        self._vertices = []                    # polilínea en dibujo (px del ortomosaico)
        self._cursor = None
        self._pendiente = None
        self._sondeo = None
        self._construir()

    # ---------------------------------------------------------------- construcción
    def _construir(self):
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 4))
        for valor, texto in MODOS:
            ttk.Radiobutton(barra, text=texto, value=valor, variable=self._modo, style="Toolbutton",
                            command=self._cambio_modo).pack(side="left", padx=1)
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=6)
        for texto, fn in (("Ajustar", self.ajustar), ("100 %", lambda: self.zoom_a(1.0)), ("＋", lambda: self.zoom(vm.ZOOM_PASO)),
                          ("－", lambda: self.zoom(1 / vm.ZOOM_PASO))):
            ttk.Button(barra, text=texto, style="Herramienta.TButton", width=6 if len(texto) > 1 else 3,
                       command=fn).pack(side="left", padx=1)
        self._coords = ttk.Label(barra, text="", style="Suave.TLabel")
        self._coords.pack(side="right")
        self.lienzo = tk.Canvas(self, background=estilos.FONDO_VISOR, highlightthickness=1,
                                highlightbackground=estilos.BORDE, cursor="arrow", takefocus=1, width=640, height=420)
        self.lienzo.pack(fill="both", expand=True)
        self._ayuda = ttk.Label(self, text=AYUDA["mover"], style="Suave.TLabel")
        self._ayuda.pack(fill="x", pady=(3, 0))
        c = self.lienzo
        c.bind("<Configure>", self._on_configure)
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._doble)
        c.bind("<ButtonPress-2>", self._pan_ini)
        c.bind("<B2-Motion>", self._pan_mov)
        c.bind("<Button-3>", lambda e: self._quitar_vertice())
        c.bind("<Motion>", self._hover)
        c.bind("<MouseWheel>", self._on_rueda)
        c.bind("<Button-4>", self._on_rueda)
        c.bind("<Button-5>", self._on_rueda)
        c.bind("<Enter>", lambda e: c.focus_set())
        c.bind("<Escape>", lambda e: self.cancelar_dibujo())
        c.bind("<Return>", lambda e: self.terminar_eje())
        c.bind("<BackSpace>", lambda e: self._quitar_vertice())
        c.bind("<plus>", lambda e: self.zoom(vm.ZOOM_PASO))
        c.bind("<minus>", lambda e: self.zoom(1 / vm.ZOOM_PASO))
        c.bind("<Key-0>", lambda e: self.ajustar())

    # ---------------------------------------------------------------- carga
    def cargar(self, ruta: Optional[str], ancho=None, alto=None, gsd_cm=0.5):
        """Muestra un ortomosaico (o lo quita con ruta=None). La lectura ocurre en un hilo."""
        self.descargar()
        if not ruta or not ancho:
            self._mensaje = "Sin ortomosaico: asigne uno al tramo (pestaña Tramos)."
            self._dibujar()
            return
        self.gsd_cm = gsd_cm or 0.5
        self.modelo = vm.ModeloVisor(ancho, alto, max(1, self.lienzo.winfo_width()), max(1, self.lienzo.winfo_height()))
        self._mensaje = "Generando miniatura…"
        self._lector = iv.LectorAsincrono(lambda: iv.FuenteImagen(ruta))
        self._sondear()
        self._dibujar()

    def descargar(self):
        if self._sondeo is not None:
            self.after_cancel(self._sondeo)
            self._sondeo = None
        if self._lector is not None:
            self._lector.cerrar()
        self._lector, self.modelo, self._mini, self._zona = None, None, None, None
        self._foto, self._clave_pedida = None, None
        self._vertices, self._arrastre = [], None

    def destroy(self):
        self.descargar()
        super().destroy()

    def _sondear(self):
        self._sondeo = None
        if self._lector is None:
            return
        cambio = False
        for ev in self._lector.sondear():
            if ev[0] == "miniatura":
                self._mini, self._mensaje, cambio = (ev[1], ev[2]), "", True
            elif ev[0] == "zona":
                self._zona, cambio = (ev[1], ev[2], ev[3]), True
            elif ev[0] == "error":
                self._mensaje, cambio = ev[1], True
        if cambio:
            self._dibujar()
        self._sondeo = self.after(REFRESCO_MS * 2, self._sondear)

    # ---------------------------------------------------------------- datos superpuestos
    def fijar_rois(self, rois, seleccionada=None):
        self._rois, self._roi_sel = list(rois), seleccionada
        self._dibujar_superposicion()

    def fijar_eje(self, vertices):
        self._eje = [tuple(v) for v in vertices] if vertices else None
        self._dibujar_superposicion()

    def fijar_detecciones(self, dets, seleccion=None):
        self._dets, self._det_sel = list(dets), seleccion
        self._dibujar_superposicion()

    def fijar_ventana(self, region):
        self._ventana = tuple(region) if region else None
        self._dibujar_superposicion()

    def seleccionar_deteccion(self, det_id, centrar=False):
        self._det_sel = det_id
        if centrar and self.modelo and det_id is not None:
            d = next((x for x in self._dets if x["id"] == det_id), None)
            if d and not self.modelo.interseca(d["bbox"]):
                self.modelo.centrar_en((d["bbox"][0] + d["bbox"][2]) / 2, (d["bbox"][1] + d["bbox"][3]) / 2)
                self._dibujar()
                return
        self._dibujar_superposicion()

    def ir_a_region(self, region):
        if self.modelo:
            self.modelo.enfocar_region(region)
            self._dibujar()

    def region_visible(self):
        return self.modelo.region_visible() if self.modelo else None

    # ---------------------------------------------------------------- vista
    def ajustar(self):
        if self.modelo:
            self.modelo.ajustar()
            self._dibujar()

    def zoom(self, factor, px=None, py=None):
        if self.modelo:
            self.modelo.zoom(factor, px, py)
            self._dibujar()

    def zoom_a(self, escala):
        if self.modelo:
            self.modelo.zoom_a(escala)
            self._dibujar()

    def _on_configure(self, e):
        if self.modelo:
            self.modelo.redimensionar(e.width, e.height)
        self._dibujar()

    def _on_rueda(self, e):
        self.zoom(vm.ZOOM_PASO if _rueda(e) < 0 else 1 / vm.ZOOM_PASO, e.x, e.y)

    # ---------------------------------------------------------------- herramientas
    @property
    def modo(self):
        return self._modo.get()

    def fijar_modo(self, modo):
        self._modo.set(modo)
        self._cambio_modo()

    def _cambio_modo(self):
        self.cancelar_dibujo()
        self.lienzo.configure(cursor="arrow" if self.modo == "mover" else "crosshair")
        self._ayuda.configure(text=AYUDA[self.modo])

    def cancelar_dibujo(self):
        self._vertices, self._arrastre = [], None
        self.lienzo.delete("goma")
        self._dibujar_superposicion()

    def _img(self, e):
        return self.modelo.pantalla_a_imagen(e.x, e.y)

    def _press(self, e):
        self.lienzo.focus_set()
        if not self.modelo:
            return
        if self.modo == "eje":
            return
        self._arrastre = {"x": e.x, "y": e.y, "px": e.x, "py": e.y, "movido": False, "p0": self._img(e)}

    def _motion(self, e):
        a = self._arrastre
        if not self.modelo or not a:
            return
        if abs(e.x - a["x"]) + abs(e.y - a["y"]) > 3:
            a["movido"] = True
        if self.modo == "mover":
            self.modelo.desplazar(e.x - a["px"], e.y - a["py"])
            a["px"], a["py"] = e.x, e.y
            self._dibujar(rapido=True)
        else:
            self.lienzo.delete("goma")
            self.lienzo.create_rectangle(a["x"], a["y"], e.x, e.y, outline=estilos.COLOR_DIBUJO, dash=(5, 3),
                                         width=2, tags="goma")

    def _release(self, e):
        if not self.modelo:
            return
        if self.modo == "eje":
            x, y = self._img(e)
            self._vertices.append((x, y))
            self._dibujar_superposicion()
            return
        a, self._arrastre = self._arrastre, None
        if not a:
            return
        self.lienzo.delete("goma")
        if self.modo == "mover":
            if a["movido"]:
                self._pedir_zona()
            else:
                self._clic(e)
            return
        if not a["movido"]:
            return
        r = vm.normalizar_rect(a["p0"], self._img(e), self.modelo.ancho, self.modelo.alto)
        if r[2] - r[0] < 4 or r[3] - r[1] < 4:
            return
        if self.modo == "roi" and self.al_roi:
            self.al_roi(r)
        elif self.modo == "ventana":
            self.fijar_ventana(r)
            if self.al_ventana:
                self.al_ventana(r)

    def _doble(self, e):
        if self.modo == "eje":
            self.terminar_eje()

    def _clic(self, e):
        x, y = self._img(e)
        det = vm.deteccion_en_punto(self._dets, x, y, 5.0 / self.modelo.escala)
        self._det_sel = det
        self._dibujar_superposicion()
        if self.al_seleccion:
            self.al_seleccion(det)

    def terminar_eje(self):
        pts = vm.limpiar_polilinea(self._vertices, tol=2.0 / (self.modelo.escala if self.modelo else 1))
        self._vertices = []
        self._dibujar_superposicion()
        if len(pts) >= 2 and self.al_eje:
            self.al_eje(pts)

    def _quitar_vertice(self):
        if self._vertices:
            self._vertices.pop()
            self._dibujar_superposicion()

    def _pan_ini(self, e):
        self._pan = (e.x, e.y)

    def _pan_mov(self, e):
        if self.modelo and getattr(self, "_pan", None):
            self.modelo.desplazar(e.x - self._pan[0], e.y - self._pan[1])
            self._pan = (e.x, e.y)
            self._dibujar(rapido=True)

    def _hover(self, e):
        self._cursor = (e.x, e.y)
        if self.modelo:
            x, y = self._img(e)
            if 0 <= x < self.modelo.ancho and 0 <= y < self.modelo.alto:
                m = self.modelo
                self._coords.configure(text=f"x {x:,.0f}  y {y:,.0f} px · zoom {m.escala * 100:.1f} %"
                                       f" · 1 px = {self.gsd_cm:g} cm")
                if self.al_cursor:
                    self.al_cursor(x, y)
        if self.modo == "eje" and self._vertices:
            self._dibujar_superposicion()

    # ---------------------------------------------------------------- dibujo
    def _dibujar(self, rapido=False):
        """Imagen de fondo + superposiciones. `rapido`: durante el arrastre solo se usa la miniatura."""
        c = self.lienzo
        c.delete("img")
        c.delete("txt")
        m = self.modelo
        if m is None or (self._mini is None and self._zona is None):
            c.delete("ovl")
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, text=self._mensaje, fill="#cbd2d9",
                          width=max(200, c.winfo_width() - 60), justify="center", tags="txt")
            return
        region = m.region_visible()
        salida = m.salida_de_region(region)
        pos = m.posicion_de_region(region)
        rgb = None
        clave = (region, salida)
        if self._zona and self._zona[0] == clave:
            rgb = self._zona[2]
        elif self._mini is not None:
            rgb = self._recorte_miniatura(region, salida)
        if rgb is not None:
            self._foto = tk.PhotoImage(data=iv.a_ppm(rgb), format="PPM")
            c.create_image(pos[0], pos[1], image=self._foto, anchor="nw", tags="img")
            c.tag_lower("img")
        if self._mensaje:
            c.create_text(c.winfo_width() / 2, 14, text=self._mensaje, fill="#cbd2d9", tags="txt")
        fuente_necesaria = m.necesita_fuente(self._mini[1] if self._mini else None)
        if fuente_necesaria and self._lector is not None and self._mini is not None and not (
                self._zona and self._zona[0] == clave):
            if rapido:
                self._pedir_zona()
            elif clave != self._clave_pedida:
                self._clave_pedida = clave
                self._lector.pedir_zona(clave, region, salida)
        self._dibujar_superposicion()

    def _pedir_zona(self):
        """Pide la zona nítida cuando el usuario deja de mover (120 ms)."""
        if self._pendiente is not None:
            self.after_cancel(self._pendiente)
        self._pendiente = self.after(120, self._pedir_ya)

    def _pedir_ya(self):
        self._pendiente = None
        if self.modelo and self._lector and self._mini is not None:
            self._dibujar()

    def _recorte_miniatura(self, region, salida):
        rgb, esc = self._mini
        x0, y0, x1, y1 = region
        tx0, ty0 = int(x0 * esc), int(y0 * esc)
        tx1, ty1 = max(tx0 + 1, int(math.ceil(x1 * esc))), max(ty0 + 1, int(math.ceil(y1 * esc)))
        corte = rgb[ty0:ty1, tx0:tx1]
        if corte.size == 0:
            return None
        if esc >= 1.0 and self.modelo.escala >= 1.0:
            inter = cv2.INTER_NEAREST
        elif self.modelo.escala < esc:
            inter = cv2.INTER_AREA
        else:
            inter = cv2.INTER_LINEAR
        return cv2.resize(corte, salida, interpolation=inter)

    def _dibujar_superposicion(self):
        c, m = self.lienzo, self.modelo
        c.delete("ovl")
        if m is None:
            return
        S = m.imagen_a_pantalla
        for r in self._rois:
            if not m.interseca((r["x0"], r["y0"], r["x1"], r["y1"])):
                continue
            x0, y0 = S(r["x0"], r["y0"])
            x1, y1 = S(r["x1"], r["y1"])
            sel = r.get("id") == self._roi_sel
            col = estilos.COLOR_ROL.get(r.get("rol"), "#718096")
            c.create_rectangle(x0, y0, x1, y1, outline=estilos.COLOR_SELECCION if sel else col,
                               width=3 if sel else 2, tags="ovl")
            c.create_text(x0 + 4, y0 + 3, text=r.get("codigo", ""), anchor="nw", fill=col if not sel else "#ffffff",
                          font=("TkDefaultFont", 9, "bold"), tags="ovl")
        if self._ventana:
            x0, y0, x1, y1 = m.region_a_pantalla(self._ventana)
            c.create_rectangle(x0, y0, x1, y1, outline=estilos.COLOR_VENTANA, width=2, dash=(6, 3), tags="ovl")
        if self._eje:
            self._linea(self._eje, estilos.COLOR_EJE, 3, puntos=True, flecha=True)
        for d in self._dets:
            if m.interseca(d["bbox"]):
                self._detalle(d, d["id"] == self._det_sel)
        if self._vertices:
            pts = list(self._vertices)
            if self._cursor and self.modo == "eje":
                pts.append(m.pantalla_a_imagen(*self._cursor))
            self._linea(pts, estilos.COLOR_DIBUJO, 2, puntos=True, dash=(5, 3))
        self._barra_escala()

    def _linea(self, pts, color, ancho, puntos=False, dash=None, flecha=False):
        c, S = self.lienzo, self.modelo.imagen_a_pantalla
        flat = [v for p in pts for v in S(*p)]
        if len(flat) >= 4:
            c.create_line(*flat, fill=color, width=ancho, dash=dash, tags="ovl",
                          arrow="last" if flecha else None, arrowshape=(14, 16, 5))
        if puntos:
            for p in pts:
                x, y = S(*p)
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="#000000", tags="ovl")

    def _detalle(self, d, seleccionada):
        c, m = self.lienzo, self.modelo
        col = COLOR_TIPO.get(d["tipo"], "#ffffff")
        geom = d.get("geom") or []
        paso = max(1, len(geom) // 500)
        pts = geom[::paso] if len(geom) > 500 else geom
        flat = [v for p in pts for v in m.imagen_a_pantalla(*p)]
        ancho = 4 if seleccionada else 2
        if seleccionada:
            x0, y0 = m.imagen_a_pantalla(d["bbox"][0], d["bbox"][1])
            x1, y1 = m.imagen_a_pantalla(d["bbox"][2], d["bbox"][3])
            c.create_rectangle(x0 - 4, y0 - 4, x1 + 4, y1 + 4, outline=estilos.COLOR_SELECCION, dash=(4, 3), width=1,
                               tags="ovl")
        if (d.get("geom_tipo") or "").startswith("poligono") and len(flat) >= 6:
            c.create_polygon(*flat, outline=col, fill="", width=ancho, tags="ovl")
        elif len(flat) >= 4:
            c.create_line(*flat, fill=col, width=ancho, tags="ovl")
        else:
            x0, y0 = m.imagen_a_pantalla(d["bbox"][0], d["bbox"][1])
            x1, y1 = m.imagen_a_pantalla(d["bbox"][2], d["bbox"][3])
            c.create_rectangle(x0, y0, x1, y1, outline=col, width=ancho, tags="ovl")

    def _barra_escala(self):
        c, m = self.lienzo, self.modelo
        m_por_px = (self.gsd_cm / 100.0) / m.escala
        objetivo = 110 * m_por_px
        pot = 10 ** math.floor(math.log10(objetivo))
        v = next(k * pot for k in (1, 2, 5, 10) if k * pot >= objetivo * 0.7)
        largo = v / m_por_px
        x, y = 14, c.winfo_height() - 18
        c.create_line(x, y, x + largo, y, fill="#ffffff", width=3, tags="ovl")
        c.create_line(x, y - 5, x, y + 5, fill="#ffffff", width=2, tags="ovl")
        c.create_line(x + largo, y - 5, x + largo, y + 5, fill="#ffffff", width=2, tags="ovl")
        c.create_text(x + largo / 2, y - 9, text=f"{v:g} m" if v >= 1 else f"{v * 100:g} cm", fill="#ffffff",
                      tags="ovl")
