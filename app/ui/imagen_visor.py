"""
imagen_visor.py
===============
Lectura del ortomosaico PARA MOSTRAR, sin cargarlo entero y sin Tk:

  - `FuenteImagen.miniatura()`  pirámide de un nivel: vista general con un presupuesto de píxeles.
  - `FuenteImagen.leer_zona()`  lectura de la zona visible, ya remuestreada al tamaño de pantalla
                                (con rasterio la lectura decimada aprovecha las overviews del GeoTIFF).
  - `LectorAsincrono`           hilo que atiende las peticiones (gana la última) para que la interfaz no se
                                congele al desplazarse o al generar la miniatura de un archivo enorme.

El hilo del visor solo lee imagen: no toca Tk ni la BD. Sin rasterio se usa el lector de OpenCV del núcleo
(que decodifica la imagen completa, con su tope de 120 Mpx).
"""
import queue
import threading
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

from app.nucleo import lectura
from app.nucleo.estructuras import ErrorLectura
from app.ui.visor_modelo import escala_miniatura

MINI_PIXELES = 4_000_000


def _a_uint8(arr):
    if arr.dtype == np.uint8:
        return arr
    if arr.dtype == np.uint16:
        return (arr // 257).astype(np.uint8)
    return np.clip(arr, 0, 255).astype(np.uint8)


def a_ppm(rgb: np.ndarray) -> bytes:
    """RGB uint8 (h, w, 3) -> bytes PPM, que Tk muestra con PhotoImage(data=...) sin Pillow."""
    h, w = rgb.shape[:2]
    return b"P6 %d %d 255\n" % (w, h) + np.ascontiguousarray(rgb).tobytes()


class FuenteImagen:
    """Abre el archivo una vez y sirve lecturas parciales. Úsese desde UN solo hilo."""

    def __init__(self, ruta: Optional[str] = None, lector=None):
        self._ds = None
        self._lector = None
        if lector is not None:                                     # pruebas / imágenes en memoria
            self._lector = lector
        elif ruta and ruta.lower().endswith(lectura.EXTENSIONES_TIFF) and lectura.HAY_RASTERIO:
            try:
                self._ds = lectura.rasterio.open(ruta)
            except Exception as e:
                raise ErrorLectura(f"No se pudo abrir {ruta}: {e}") from e
            if self._ds.count < 3:
                self._ds.close()
                raise ErrorLectura("El ortomosaico debe tener al menos 3 bandas (R, G, B)")
        else:
            self._lector = lectura.abrir(ruta)
        src = self._ds if self._ds is not None else self._lector
        self.ancho, self.alto = (src.width, src.height) if self._ds is not None else (src.ancho, src.alto)

    # ---------------------------------------------------------------- lectura
    def _leer_nativo(self, x0, y0, x1, y1):
        if self._ds is not None:
            v = lectura.Window(x0, y0, x1 - x0, y1 - y0)
            return np.ascontiguousarray(np.moveaxis(_a_uint8(self._ds.read([1, 2, 3], window=v)), 0, -1))
        return self._lector.leer(x0, y0, x1, y1)[0]

    def leer_zona(self, region, salida: Tuple[int, int]) -> np.ndarray:
        """RGB (alto_salida, ancho_salida, 3) de `region` = (x0, y0, x1, y1) remuestreada al tamaño `salida`."""
        x0, y0, x1, y1 = (int(v) for v in region)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.ancho, x1), min(self.alto, y1)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("Zona fuera del ortomosaico")
        sw, sh = max(1, int(salida[0])), max(1, int(salida[1]))
        w, h = x1 - x0, y1 - y0
        if self._ds is not None and (sw < w or sh < h):            # reducción: lectura decimada (usa overviews)
            v = lectura.Window(x0, y0, w, h)
            datos = self._ds.read([1, 2, 3], window=v, out_shape=(3, sh, sw),
                                  resampling=lectura.rasterio.enums.Resampling.average)
            return np.ascontiguousarray(np.moveaxis(_a_uint8(datos), 0, -1))
        rgb = self._leer_nativo(x0, y0, x1, y1)
        if (sw, sh) == (w, h):
            return rgb
        inter = cv2.INTER_NEAREST if (sw >= w and sh >= h) else cv2.INTER_AREA
        return cv2.resize(rgb, (sw, sh), interpolation=inter)

    def miniatura(self, max_pixeles: int = MINI_PIXELES):
        """(rgb, escala) con escala = píxeles de miniatura por píxel del ortomosaico (1.0 = resolución completa)."""
        e = escala_miniatura(self.ancho, self.alto, max_pixeles)
        mw, mh = max(1, int(round(self.ancho * e))), max(1, int(round(self.alto * e)))
        rgb = self.leer_zona((0, 0, self.ancho, self.alto), (mw, mh))
        return rgb, mw / float(self.ancho)

    def cerrar(self):
        if self._ds is not None:
            self._ds.close()
            self._ds = None
        if self._lector is not None:
            self._lector.cerrar()
            self._lector = None


class LectorAsincrono:
    """Hilo lector. `pedir_*` no bloquean; `sondear()` devuelve lo ya listo:
         ('abierto', ancho, alto) · ('miniatura', rgb, escala) · ('zona', clave, region, rgb) · ('error', texto)
    Si llegan varias peticiones de zona mientras se lee una, solo se atiende la última."""

    def __init__(self, abrir: Callable[[], FuenteImagen]):
        self._abrir = abrir
        self._cv = threading.Condition()
        self._mini = True                      # la miniatura se pide al empezar
        self._zona = None
        self._parar = False
        self._out: "queue.Queue[tuple]" = queue.Queue()
        self._hilo = threading.Thread(target=self._bucle, name="lector-visor", daemon=True)
        self._hilo.start()

    def pedir_zona(self, clave, region, salida):
        with self._cv:
            self._zona = (clave, tuple(region), tuple(salida))
            self._cv.notify()

    def sondear(self):
        out = []
        while True:
            try:
                out.append(self._out.get_nowait())
            except queue.Empty:
                return out

    def cerrar(self, timeout=3.0):
        with self._cv:
            self._parar = True
            self._cv.notify()
        self._hilo.join(timeout)

    def _bucle(self):
        fuente = None
        try:
            try:
                fuente = self._abrir()
                self._out.put(("abierto", fuente.ancho, fuente.alto))
            except Exception as e:             # noqa: BLE001
                self._out.put(("error", str(e)))
                return
            while True:
                with self._cv:
                    while not self._parar and not self._mini and self._zona is None:
                        self._cv.wait()
                    if self._parar:
                        return
                    hacer_mini, self._mini = self._mini, False
                    zona = None if hacer_mini else self._zona
                    if zona is not None:
                        self._zona = None
                try:
                    if hacer_mini:
                        rgb, esc = fuente.miniatura()
                        self._out.put(("miniatura", rgb, esc))
                    else:
                        clave, region, salida = zona
                        self._out.put(("zona", clave, region, fuente.leer_zona(region, salida)))
                except Exception as e:         # noqa: BLE001
                    self._out.put(("error", f"No se pudo leer el ortomosaico: {e}"))
        finally:
            if fuente is not None:
                fuente.cerrar()
