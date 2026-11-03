"""
geo.py
======
Conversión píxel <-> coordenadas del mapa (la que usa QGIS) con una transformación afín:

    X = a·col + b·fila + c          Y = d·col + e·fila + f

Es la misma convención de GDAL/rasterio (para un mapa 'norte arriba', e es negativo).
No requiere rasterio: solo guarda los seis coeficientes.
"""
from typing import NamedTuple

import numpy as np


class Transformacion(NamedTuple):
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def norte_arriba(cls, x_origen, y_origen, gsd_m):
        """Transformación de un ortomosaico 'norte arriba' con esquina superior izquierda dada."""
        return cls(gsd_m, 0.0, x_origen, 0.0, -gsd_m, y_origen)

    @classmethod
    def desde_afin(cls, afin):
        """Desde un objeto affine.Affine de rasterio (a, b, c, d, e, f)."""
        return cls(afin.a, afin.b, afin.c, afin.d, afin.e, afin.f)

    def _det(self):
        det = self.a * self.e - self.b * self.d
        if abs(det) < 1e-18:
            raise ValueError("Transformación geográfica no invertible (determinante 0)")
        return det

    def px_a_geo(self, col, fila):
        """Píxel (col, fila) -> (X, Y). Acepta escalares o arreglos."""
        col, fila = np.asarray(col, dtype=float), np.asarray(fila, dtype=float)
        return self.a * col + self.b * fila + self.c, self.d * col + self.e * fila + self.f

    def geo_a_px(self, x, y):
        """(X, Y) -> píxel (col, fila) fraccionarios."""
        det = self._det()
        x, y = np.asarray(x, dtype=float) - self.c, np.asarray(y, dtype=float) - self.f
        return (self.e * x - self.b * y) / det, (-self.d * x + self.a * y) / det

    def gsd_m(self):
        """Tamaño de píxel en metros (media de los dos ejes)."""
        return float((np.hypot(self.a, self.d) + np.hypot(self.b, self.e)) / 2.0)

    def a_lista(self):
        return list(self)
