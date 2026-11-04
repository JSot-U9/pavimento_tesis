"""
visor_modelo.py
===============
Geometría del visor SIN Tk (se prueba sin pantalla): zoom, desplazamiento, conversión píxel de pantalla <->
píxel del ortomosaico, región visible y búsqueda de la detección bajo el cursor.

Convención: `escala` = píxeles de pantalla por píxel del ortomosaico; (ox, oy) = coordenadas del ortomosaico
que caen en la esquina superior izquierda de la vista.
"""
import math
from typing import Iterable, List, Optional, Sequence, Tuple

ESCALA_MAX = 16.0
ZOOM_PASO = 1.25


class ModeloVisor:
    def __init__(self, ancho: int, alto: int, vw: int = 800, vh: int = 600):
        if ancho < 1 or alto < 1:
            raise ValueError("El ortomosaico debe tener tamaño positivo")
        self.ancho, self.alto = int(ancho), int(alto)
        self.vw, self.vh = max(1, int(vw)), max(1, int(vh))
        self.escala, self.ox, self.oy = 1.0, 0.0, 0.0
        self.ajustar()

    # ---------------------------------------------------------------- escala
    def escala_ajuste(self) -> float:
        return min(self.vw / self.ancho, self.vh / self.alto)

    def escala_min(self) -> float:
        return min(self.escala_ajuste(), 1.0)

    def _limitar_escala(self, e):
        return max(self.escala_min(), min(ESCALA_MAX, e))

    def limitar(self):
        """Mantiene la imagen dentro de la vista (centrada si es más pequeña que ella)."""
        for eje in ("x", "y"):
            total, vista = (self.ancho, self.vw) if eje == "x" else (self.alto, self.vh)
            visible = vista / self.escala
            o = self.ox if eje == "x" else self.oy
            o = (total - visible) / 2.0 if visible >= total else max(0.0, min(o, total - visible))
            if eje == "x":
                self.ox = o
            else:
                self.oy = o

    def ajustar(self):
        self.escala = self.escala_ajuste()
        self.ox = self.oy = 0.0
        self.limitar()

    def redimensionar(self, vw: int, vh: int):
        """Cambia el tamaño de la vista conservando el centro."""
        cx, cy = self.pantalla_a_imagen(self.vw / 2.0, self.vh / 2.0)
        self.vw, self.vh = max(1, int(vw)), max(1, int(vh))
        self.escala = self._limitar_escala(self.escala)
        self.centrar_en(cx, cy)

    def zoom(self, factor: float, px: Optional[float] = None, py: Optional[float] = None):
        """Acerca/aleja manteniendo fijo el punto de pantalla (px, py) (por defecto, el centro)."""
        px = self.vw / 2.0 if px is None else px
        py = self.vh / 2.0 if py is None else py
        self.zoom_a(self.escala * factor, px, py)

    def zoom_a(self, escala: float, px: Optional[float] = None, py: Optional[float] = None):
        px = self.vw / 2.0 if px is None else px
        py = self.vh / 2.0 if py is None else py
        x, y = self.pantalla_a_imagen(px, py)
        self.escala = self._limitar_escala(escala)
        self.ox, self.oy = x - px / self.escala, y - py / self.escala
        self.limitar()

    def desplazar(self, dx_pantalla: float, dy_pantalla: float):
        self.ox -= dx_pantalla / self.escala
        self.oy -= dy_pantalla / self.escala
        self.limitar()

    def centrar_en(self, x: float, y: float):
        self.ox, self.oy = x - self.vw / (2.0 * self.escala), y - self.vh / (2.0 * self.escala)
        self.limitar()

    def enfocar_region(self, region: Sequence[float], margen: float = 0.15):
        """Encuadra un rectángulo del ortomosaico (con margen relativo)."""
        x0, y0, x1, y1 = region
        w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
        e = min(self.vw / (w * (1 + 2 * margen)), self.vh / (h * (1 + 2 * margen)))
        self.escala = self._limitar_escala(e)
        self.centrar_en((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    # ---------------------------------------------------------------- conversiones
    def pantalla_a_imagen(self, px: float, py: float) -> Tuple[float, float]:
        return self.ox + px / self.escala, self.oy + py / self.escala

    def imagen_a_pantalla(self, x: float, y: float) -> Tuple[float, float]:
        return (x - self.ox) * self.escala, (y - self.oy) * self.escala

    def region_visible(self) -> Tuple[int, int, int, int]:
        """Rectángulo entero del ortomosaico que se ve (recortado a la imagen)."""
        x0 = max(0, int(math.floor(self.ox)))
        y0 = max(0, int(math.floor(self.oy)))
        x1 = min(self.ancho, int(math.ceil(self.ox + self.vw / self.escala)))
        y1 = min(self.alto, int(math.ceil(self.oy + self.vh / self.escala)))
        return x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)

    def salida_de_region(self, region) -> Tuple[int, int]:
        """Tamaño en píxeles de pantalla con que se dibuja `region`."""
        x0, y0, x1, y1 = region
        return max(1, int(round((x1 - x0) * self.escala))), max(1, int(round((y1 - y0) * self.escala)))

    def posicion_de_region(self, region) -> Tuple[int, int]:
        x, y = self.imagen_a_pantalla(region[0], region[1])
        return int(round(x)), int(round(y))

    def region_a_pantalla(self, region) -> Tuple[float, float, float, float]:
        x0, y0 = self.imagen_a_pantalla(region[0], region[1])
        x1, y1 = self.imagen_a_pantalla(region[2], region[3])
        return x0, y0, x1, y1

    def interseca(self, bbox) -> bool:
        vx0, vy0 = self.ox, self.oy
        vx1, vy1 = self.ox + self.vw / self.escala, self.oy + self.vh / self.escala
        return not (bbox[2] < vx0 or bbox[0] > vx1 or bbox[3] < vy0 or bbox[1] > vy1)

    # ---------------------------------------------------------------- plan de lectura
    def necesita_fuente(self, escala_mini: Optional[float]) -> bool:
        """¿Basta la miniatura para dibujar la vista actual? Si la miniatura no es de resolución completa y la
        vista la supera en detalle, hay que leer la zona visible del archivo."""
        if escala_mini is None:
            return True
        return escala_mini < 1.0 and self.escala > escala_mini * 1.001


def escala_miniatura(ancho: int, alto: int, max_pixeles: int = 4_000_000) -> float:
    """Escala (≤ 1) de la miniatura: como mucho `max_pixeles` píxeles, sea cual sea la forma de la imagen
    (una vía de 100 000 × 2 000 px da una miniatura de ~14 000 × 280)."""
    return min(1.0, math.sqrt(max_pixeles / float(ancho * alto)))


# ------------------------------------------------------------------------------------ dibujo
def normalizar_rect(p1, p2, ancho, alto) -> Tuple[int, int, int, int]:
    """Dos esquinas (px del ortomosaico, cualquier orden) -> (x0, y0, x1, y1) enteros recortados a la imagen."""
    x0, x1 = sorted((p1[0], p2[0]))
    y0, y1 = sorted((p1[1], p2[1]))
    return (int(round(max(0, x0))), int(round(max(0, y0))), int(round(min(ancho, x1))), int(round(min(alto, y1))))


def limpiar_polilinea(vertices: Iterable[Sequence[float]], tol: float = 1.0) -> List[Tuple[float, float]]:
    """Quita vértices consecutivos repetidos (un doble clic añade el último dos veces)."""
    out: List[Tuple[float, float]] = []
    for x, y in vertices:
        if not out or math.hypot(x - out[-1][0], y - out[-1][1]) > tol:
            out.append((float(x), float(y)))
    return out


# ------------------------------------------------------------------------------------ selección
def dist_punto_segmento(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def punto_en_poligono(px, py, pts) -> bool:
    dentro = False
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        if (ay > py) != (by > py) and px < (bx - ax) * (py - ay) / (by - ay) + ax:
            dentro = not dentro
    return dentro


def distancia_a_deteccion(det: dict, x: float, y: float) -> float:
    """Distancia (px del ortomosaico) de un punto a la detección; 0 si cae dentro de un polígono / caja."""
    geom = det.get("geom") or []
    x0, y0, x1, y1 = det["bbox"]
    if det.get("geom_tipo") == "polilinea_aprox" and len(geom) >= 2:
        return min(dist_punto_segmento(x, y, *geom[i], *geom[i + 1]) for i in range(len(geom) - 1))
    if det.get("geom_tipo") == "poligono" and len(geom) >= 3:
        if punto_en_poligono(x, y, geom):
            return 0.0
        return min(dist_punto_segmento(x, y, *geom[i], *geom[(i + 1) % len(geom)]) for i in range(len(geom)))
    if len(geom) == 1:
        return math.hypot(x - geom[0][0], y - geom[0][1])
    dx = max(x0 - x, 0, x - x1)
    dy = max(y0 - y, 0, y - y1)
    return math.hypot(dx, dy)


def deteccion_en_punto(dets: Iterable[dict], x: float, y: float, tol: float) -> Optional[int]:
    """Id de la detección bajo el punto (a lo sumo a `tol` px del ortomosaico). Las líneas (grietas) tienen
    prioridad sobre las zonas (son un blanco fino dentro de una zona grande); entre zonas gana la que contiene
    el punto y, a igual distancia, la de menor caja. None si no hay ninguna."""
    mejor, clave = None, None
    for d in dets:
        x0, y0, x1, y1 = d["bbox"]
        if x < x0 - tol or x > x1 + tol or y < y0 - tol or y > y1 + tol:
            continue
        dist = distancia_a_deteccion(d, x, y)
        if dist > tol:
            continue
        es_linea = d.get("geom_tipo") == "polilinea_aprox"
        k = (0 if es_linea else 1, round(dist, 3), (x1 - x0) * (y1 - y0))
        if clave is None or k < clave:
            mejor, clave = d["id"], k
    return mejor
