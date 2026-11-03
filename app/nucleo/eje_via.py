"""
eje_via.py
==========
Eje de vía como POLILÍNEA en píxeles del ortomosaico. Reemplaza al ángulo único `eje_via_deg`:
en vías de montaña con curvas, la dirección del eje cambia, así que el ángulo longitudinal /
transversal de cada grieta se calcula con la dirección LOCAL del eje.

Qué ofrece (todo vectorizado: acepta un punto o arreglos de puntos):
  - angulo_local_deg(x, y)   dirección del eje (0-180°, convención de imagen: y hacia abajo)
  - progresiva_m(x, y)       distancia (m) a lo largo del eje hasta la proyección del punto
  - lado_via(x, y)           'derecha' / 'izquierda' respecto al sentido de avance
  - distancia_lateral_m      distancia perpendicular al eje (m)
"""
import numpy as np

from app.nucleo.geo import Transformacion


class EjeVia:
    def __init__(self, vertices_px, gsd_m, progresiva_inicial_m=0.0, ventana_m=4.0):
        v = np.asarray(vertices_px, dtype=float)
        if v.ndim != 2 or v.shape[1] != 2 or len(v) < 2:
            raise ValueError("El eje de vía necesita al menos 2 vértices (x, y)")
        if gsd_m <= 0:
            raise ValueError("gsd_m debe ser mayor que 0")
        seg = np.diff(v, axis=0)
        largos = np.hypot(seg[:, 0], seg[:, 1])
        validos = largos > 1e-9                    # se descartan vértices repetidos
        if not validos.any():
            raise ValueError("Todos los vértices del eje de vía son iguales")
        keep = np.concatenate([[True], validos])
        self.vertices = v[keep]
        self.gsd_m = float(gsd_m)
        self.progresiva_inicial_m = float(progresiva_inicial_m)
        self.ventana_m = float(ventana_m)
        self._seg = np.diff(self.vertices, axis=0)
        self._largo = np.hypot(self._seg[:, 0], self._seg[:, 1])
        self._acum = np.concatenate([[0.0], np.cumsum(self._largo)])      # longitud acumulada (px)

    # ---------------------------------------------------------------- constructores
    @classmethod
    def recto(cls, angulo_deg, ancho_px, alto_px, gsd_m, **kw):
        """Eje recto que cruza el centro de la imagen con el ángulo dado (compatibilidad con eje_via_deg)."""
        cx, cy = ancho_px / 2.0, alto_px / 2.0
        mitad = float(np.hypot(ancho_px, alto_px))
        t = np.radians(angulo_deg)
        d = np.array([np.cos(t), np.sin(t)]) * mitad
        return cls([(cx - d[0], cy - d[1]), (cx + d[0], cy + d[1])], gsd_m, **kw)

    @classmethod
    def desde_geo(cls, vertices_geo, transformacion: Transformacion, gsd_m=None, **kw):
        """Eje dibujado en QGIS (coordenadas del mapa) -> píxeles del ortomosaico."""
        xy = np.asarray(vertices_geo, dtype=float)
        col, fila = transformacion.geo_a_px(xy[:, 0], xy[:, 1])
        return cls(np.column_stack([col, fila]), gsd_m or transformacion.gsd_m(), **kw)

    @classmethod
    def desde_dict(cls, d):
        return cls(d["vertices_px"], d["gsd_m"], d.get("progresiva_inicial_m", 0.0), d.get("ventana_m", 4.0))

    def a_dict(self):
        return {"vertices_px": self.vertices.tolist(), "gsd_m": self.gsd_m,
                "progresiva_inicial_m": self.progresiva_inicial_m, "ventana_m": self.ventana_m}

    # ---------------------------------------------------------------- geometría
    @property
    def longitud_m(self):
        return float(self._acum[-1] * self.gsd_m)

    def proyectar(self, x, y):
        """Proyecta puntos sobre la polilínea. Devuelve (s_px, dist_px, indice_segmento, lado_signo)."""
        px = np.atleast_1d(np.asarray(x, dtype=float))
        py = np.atleast_1d(np.asarray(y, dtype=float))
        mejor_d = np.full(px.shape, np.inf)
        mejor_s = np.zeros(px.shape)
        mejor_i = np.zeros(px.shape, dtype=int)
        mejor_cruz = np.zeros(px.shape)
        for i, (a, sv, largo) in enumerate(zip(self.vertices[:-1], self._seg, self._largo)):
            vx, vy = px - a[0], py - a[1]
            t = np.clip((vx * sv[0] + vy * sv[1]) / largo ** 2, 0.0, 1.0)
            d = np.hypot(vx - t * sv[0], vy - t * sv[1])
            mejor = d < mejor_d
            mejor_d = np.where(mejor, d, mejor_d)
            mejor_s = np.where(mejor, self._acum[i] + t * largo, mejor_s)
            mejor_i = np.where(mejor, i, mejor_i)
            # z>0: el punto queda a la derecha del sentido de avance (y de la imagen hacia abajo)
            mejor_cruz = np.where(mejor, sv[0] * vy - sv[1] * vx, mejor_cruz)
        return mejor_s, mejor_d, mejor_i, np.sign(mejor_cruz)

    def _punto_en(self, s):
        s = np.clip(s, 0.0, self._acum[-1])
        return np.interp(s, self._acum, self.vertices[:, 0]), np.interp(s, self._acum, self.vertices[:, 1])

    # ---------------------------------------------------------------- consultas
    def angulo_local_deg(self, x, y):
        """Dirección local del eje (0-180°): cuerda del eje entre s-h y s+h, con h = ventana/2."""
        s, _, _, _ = self.proyectar(x, y)
        h = (self.ventana_m / self.gsd_m) / 2.0
        xa, ya = self._punto_en(s - h)
        xb, yb = self._punto_en(s + h)
        ang = np.degrees(np.arctan2(yb - ya, xb - xa)) % 180.0
        return float(ang[0]) if np.ndim(x) == 0 else ang

    def progresiva_m(self, x, y):
        s, _, _, _ = self.proyectar(x, y)
        prog = self.progresiva_inicial_m + s * self.gsd_m
        return float(prog[0]) if np.ndim(x) == 0 else prog

    def distancia_lateral_m(self, x, y):
        _, d, _, _ = self.proyectar(x, y)
        d = d * self.gsd_m
        return float(d[0]) if np.ndim(x) == 0 else d

    def lado_via(self, x, y):
        _, _, _, signo = self.proyectar(x, y)
        lados = np.where(signo >= 0, "derecha", "izquierda")
        return str(lados[0]) if np.ndim(x) == 0 else lados

    @staticmethod
    def desviacion_deg(angulo_grieta_deg, angulo_eje_deg):
        """Ángulo agudo entre la grieta y el eje: 0 = paralela, 90 = perpendicular."""
        return abs(((angulo_grieta_deg - angulo_eje_deg) + 90.0) % 180.0 - 90.0)
