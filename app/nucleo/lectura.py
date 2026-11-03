"""
lectura.py
==========
Lectura del ortomosaico POR VENTANAS: el programa nunca debe cargar el ortomosaico completo.

Interfaz común de todos los lectores:
    lector.ancho, lector.alto          tamaño en píxeles
    lector.gsd_cm                      resolución (cm/px) si el archivo la trae (si no, None)
    lector.transformacion              geo.Transformacion si hay georreferenciación (si no, None)
    lector.leer(x0, y0, x1, y1)        -> (rgb uint8 [h,w,3], nodata bool [h,w] | None)
    lector.cerrar()

Lectores:
  - LectorRasterio: lectura real por ventanas (GeoTIFF). Requiere `rasterio` (opcional).
  - LectorOpenCV:   alternativa sin rasterio. OpenCV/Pillow DECODIFICAN LA IMAGEN COMPLETA (no hay
                    lectura parcial para PNG/JPG), así que se limita por tamaño: si la imagen
                    supera `max_pixeles` se rechaza con un mensaje que explica cómo convertirla.
  - LectorArray:    sobre un arreglo ya en memoria (pruebas, ROI pequeñas, imágenes de ejemplo).
"""
import os

import cv2
import numpy as np

from app.nucleo.estructuras import ErrorLectura
from app.nucleo.geo import Transformacion

try:                                    # opcional
    import rasterio
    from rasterio.windows import Window
    HAY_RASTERIO = True
except ImportError:                     # pragma: no cover
    rasterio = None
    HAY_RASTERIO = False

# Límite del respaldo OpenCV: ~120 Mpx = ~360 MB de RGB (más la copia temporal de decodificación).
MAX_PIXELES_OPENCV = 120_000_000
EXTENSIONES_TIFF = (".tif", ".tiff")


def _a_uint8(arr):
    if arr.dtype == np.uint8:
        return arr
    if arr.dtype == np.uint16:
        return (arr // 257).astype(np.uint8)
    return np.clip(arr, 0, 255).astype(np.uint8)


def _recortar(x0, y0, x1, y1, ancho, alto):
    x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(ancho, int(x1)), min(alto, int(y1))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Ventana fuera del ortomosaico ({ancho}x{alto} px)")
    return x0, y0, x1, y1


class LectorArray:
    """Lector sobre un arreglo RGB en memoria."""

    def __init__(self, rgb, gsd_cm=None, nodata=None, transformacion=None):
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("El arreglo debe tener forma (alto, ancho, 3)")
        self._rgb, self._nodata = _a_uint8(rgb), nodata
        self.alto, self.ancho = rgb.shape[:2]
        self.gsd_cm, self.transformacion = gsd_cm, transformacion

    def leer(self, x0, y0, x1, y1):
        x0, y0, x1, y1 = _recortar(x0, y0, x1, y1, self.ancho, self.alto)
        nd = None if self._nodata is None else self._nodata[y0:y1, x0:x1].copy()
        return self._rgb[y0:y1, x0:x1].copy(), nd

    def cerrar(self):
        pass


class LectorOpenCV:
    """Respaldo sin rasterio: decodifica el archivo completo UNA vez (con tope de tamaño)."""

    def __init__(self, ruta, gsd_cm=None, max_pixeles=MAX_PIXELES_OPENCV):
        if not os.path.isfile(ruta):
            raise ErrorLectura(f"No existe el archivo: {ruta}")
        try:                            # np.fromfile admite rutas con tildes en Windows (imread no)
            datos = np.fromfile(ruta, dtype=np.uint8)
            img = cv2.imdecode(datos, cv2.IMREAD_UNCHANGED)
        except Exception as e:          # pragma: no cover
            raise ErrorLectura(f"No se pudo leer {ruta}: {e}") from e
        if img is None:
            raise ErrorLectura(f"Formato de imagen no soportado o archivo dañado: {ruta}")
        if img.shape[0] * img.shape[1] > max_pixeles:
            raise ErrorLectura(
                f"La imagen tiene {img.shape[1]}x{img.shape[0]} px y supera el límite del lector sin rasterio "
                f"({max_pixeles:,} px). Instale 'rasterio' (pip install rasterio) o convierta el ortomosaico "
                f"a GeoTIFF con teselas desde QGIS (Exportar > Guardar ráster como...).")
        nodata = None
        if img.ndim == 2:
            img = cv2.cvtColor(_a_uint8(img), cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            nodata = img[..., 3] == 0
            img = img[..., :3]
        rgb = cv2.cvtColor(_a_uint8(img), cv2.COLOR_BGR2RGB)
        self._lector = LectorArray(rgb, gsd_cm=gsd_cm, nodata=nodata)
        self.ancho, self.alto = self._lector.ancho, self._lector.alto
        self.gsd_cm, self.transformacion = gsd_cm, None

    def leer(self, x0, y0, x1, y1):
        return self._lector.leer(x0, y0, x1, y1)

    def cerrar(self):
        self._lector = None


class LectorRasterio:
    """Lectura real por ventanas de un GeoTIFF (solo se decodifican las teselas que se piden)."""

    def __init__(self, ruta):
        if not HAY_RASTERIO:
            raise ErrorLectura("rasterio no está instalado (pip install rasterio)")
        try:
            self._ds = rasterio.open(ruta)
        except Exception as e:
            raise ErrorLectura(f"No se pudo abrir {ruta}: {e}") from e
        if self._ds.count < 3:
            self._ds.close()
            raise ErrorLectura("El ortomosaico debe tener al menos 3 bandas (R, G, B)")
        self.ancho, self.alto = self._ds.width, self._ds.height
        afin = self._ds.transform
        self.transformacion = None if afin.is_identity else Transformacion.desde_afin(afin)
        proyectado = self._ds.crs is not None and self._ds.crs.is_projected
        self.gsd_cm = abs(afin.a) * 100.0 if proyectado else None

    def leer(self, x0, y0, x1, y1):
        x0, y0, x1, y1 = _recortar(x0, y0, x1, y1, self.ancho, self.alto)
        ventana = Window(x0, y0, x1 - x0, y1 - y0)
        datos = self._ds.read([1, 2, 3], window=ventana)                 # (3, h, w)
        rgb = np.ascontiguousarray(np.moveaxis(_a_uint8(datos), 0, -1))
        mascara = self._ds.dataset_mask(window=ventana)                  # 255 = dato válido
        nodata = (mascara == 0) if (mascara == 0).any() else None
        return rgb, nodata

    def cerrar(self):
        if self._ds is not None:
            self._ds.close()
            self._ds = None


def abrir(ruta, gsd_cm=None, max_pixeles_opencv=MAX_PIXELES_OPENCV):
    """Abre un ortomosaico con el mejor lector disponible.

    GeoTIFF + rasterio -> lectura por ventanas. Cualquier otro caso -> LectorOpenCV (con tope).
    Si `gsd_cm` se indica, sustituye al del archivo."""
    if not os.path.isfile(ruta):
        raise ErrorLectura(f"No existe el archivo: {ruta}")
    if ruta.lower().endswith(EXTENSIONES_TIFF) and HAY_RASTERIO:
        lector = LectorRasterio(ruta)
    else:
        lector = LectorOpenCV(ruta, gsd_cm=gsd_cm, max_pixeles=max_pixeles_opencv)
    if gsd_cm:
        lector.gsd_cm = float(gsd_cm)
    return lector
