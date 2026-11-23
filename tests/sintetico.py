"""
sintetico.py
============
Generadores de imágenes SINTÉTICAS para las pruebas del núcleo (no son datos reales).

  - ortomosaico_ejemplo(): port del antiguo generar_ejemplo.py (GSD 0.5 cm/px, calzada horizontal)
    con 5 ROI conocidas: transversal, longitudinal, piel de cocodrilo, bache y pavimento sano.
  - asfalto(): fondo con grano e iluminación suave.
  - dibujar_grieta(): grieta recta de ANCHO EXACTO conocido (cobertura analítica por píxel),
    usada para verificar la medición de ancho.
  - LectorViaLarga: lector sin archivo que fabrica ventanas de una vía de 100 000 x 2 000 px
    bajo demanda (para la prueba de memoria).
"""
import cv2
import numpy as np
from scipy.spatial import cKDTree

GSD_CM = 0.5


def asfalto(alto, ancho, semilla=1, brillo=105.0):
    """Asfalto sintético: grano + gradiente de iluminación suave + leve tinte cálido (float32 RGB)."""
    rng = np.random.default_rng(semilla)
    base = cv2.GaussianBlur(rng.normal(0, 7, (alto, ancho)).astype(np.float32), (0, 0), 1.2) * 2.0
    yy, xx = np.mgrid[0:alto, 0:ancho]
    gris = brillo + 18 * np.sin(xx / 700.0) + 10 * np.cos(yy / 500.0) + base
    return np.dstack([gris * t for t in (1.0, 0.98, 0.95)]).astype(np.float32)


def _oscurecer(img, mascara, delta, sigma=0.8):
    m = cv2.GaussianBlur(mascara.astype(np.float32), (0, 0), sigma)
    for c in range(3):
        img[..., c] -= delta * m


def a_uint8(img):
    return np.clip(img, 0, 255).astype(np.uint8)


def dibujar_grieta(img, p0, p1, ancho_px, contraste=70.0, sigma_optica=0.7):
    """Dibuja una grieta recta oscura de ancho exacto `ancho_px` (puede ser fraccionario).

    La cobertura de cada píxel se calcula con la distancia al eje (modelo de caja) y luego se
    aplica un desenfoque gaussiano que imita la óptica. Un perfil de caja desenfocado conserva el
    ancho a media altura (FWHM ≈ ancho cuando ancho > 2·sigma)."""
    h, w = img.shape[:2]
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    largo2 = float(dx * dx + dy * dy)
    # solo se calcula en la caja que rodea a la grieta (la imagen puede ser enorme)
    m = int(ancho_px) + 6
    ya, yb = max(0, int(min(y0, y1)) - m), min(h, int(max(y0, y1)) + m + 1)
    xa, xb = max(0, int(min(x0, x1)) - m), min(w, int(max(x0, x1)) + m + 1)
    if ya >= yb or xa >= xb:
        return
    yy, xx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
    t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / largo2, 0, 1)
    dist = np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy))
    cobertura = np.clip(ancho_px / 2.0 - dist + 0.5, 0.0, 1.0)
    cobertura = cv2.GaussianBlur(cobertura, (0, 0), sigma_optica)
    for c in range(3):
        img[ya:yb, xa:xb, c] -= contraste * cobertura


def ortomosaico_ejemplo(semilla=1):
    """Devuelve (rgb uint8 [1400x2400], rois[dict]) equivalente al antiguo generar_ejemplo.py."""
    H, W = 1400, 2400
    rng = np.random.default_rng(semilla)
    img = asfalto(H, W, semilla)

    def poli(pts, grosor):
        m = np.zeros((H, W), np.uint8)
        cv2.polylines(m, [np.array(pts, np.int32)], False, 1, grosor)
        return m

    t = poli([(300, 120), (310, 400), (296, 700), (305, 1000)], 5)      # R01 transversal
    t[395:402, :] = 0
    t[690:697, :] = 0
    _oscurecer(img, t, 70)
    lo = poli([(620, 700), (1000, 690), (1400, 706), (1700, 698)], 4)   # R02 longitudinal
    lo[:, 1180:1186] = 0
    _oscurecer(img, lo, 65)

    x0, y0, x1, y1 = 1000, 150, 1400, 500                                # R03 piel de cocodrilo
    semillas = np.column_stack([rng.uniform(x0, x1, 130), rng.uniform(y0, y1, 130)])
    gx, gy = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    d, _ = cKDTree(semillas).query(np.column_stack([gx.ravel(), gy.ravel()]), k=2)
    mm = np.zeros((H, W), np.uint8)
    mm[y0:y1, x0:x1] = ((d[:, 1] - d[:, 0]) < 2.2).reshape(gx.shape)
    _oscurecer(img, mm, 60)

    bm = np.zeros((H, W), np.uint8)                                      # R04 bache
    cv2.ellipse(bm, (1900, 900), (70, 50), 15, 0, 360, 1, -1)
    bm_s = cv2.GaussianBlur(bm.astype(np.float32), (0, 0), 2.0)
    tex = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 2.5) * 40
    for c in range(3):
        img[..., c] += bm_s * (-48 + tex)

    rois = [
        dict(codigo_roi="R01", tipo_campo="transversal", severidad_campo="Baja", x=150, y=80, ancho=330, alto=1000),
        dict(codigo_roi="R02", tipo_campo="longitudinal", severidad_campo="Baja", x=560, y=560, ancho=1200, alto=300),
        dict(codigo_roi="R03", tipo_campo="piel_cocodrilo", severidad_campo="Media", x=950, y=100, ancho=500, alto=450),
        dict(codigo_roi="R04", tipo_campo="bache", severidad_campo="Alta", x=1700, y=720, ancho=400, alto=360),
        dict(codigo_roi="R05", tipo_campo="sano", severidad_campo=None, x=1500, y=1050, ancho=500, alto=300),
    ]
    return a_uint8(img), rois


class LectorViaLarga:
    """Lector sin archivo: fabrica ventanas de una vía larga bajo demanda (cumple la interfaz de
    LectorOrtomosaico). Cada `separacion_px` hay una grieta transversal conocida."""

    def __init__(self, ancho=100_000, alto=2_000, gsd_cm=GSD_CM, separacion_px=10_000):
        self.ancho, self.alto, self.gsd_cm = ancho, alto, gsd_cm
        self.separacion_px = separacion_px
        self.transformacion = None

    def posiciones_grietas(self):
        return list(range(self.separacion_px // 2, self.ancho, self.separacion_px))

    def leer(self, x0, y0, x1, y1):
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.ancho, x1), min(self.alto, y1)
        h, w = y1 - y0, x1 - x0
        # el grano depende de la posición de la ventana; semilla determinista
        img = asfalto(h, w, semilla=(x0 * 31 + y0) % (2 ** 31))
        for cx in self.posiciones_grietas():
            if x0 - 20 <= cx <= x1 + 20:
                dibujar_grieta(img, (cx - x0, 100 - y0), (cx - x0 + 8, 1900 - y0), 4.0, contraste=70)
        return a_uint8(img), None
