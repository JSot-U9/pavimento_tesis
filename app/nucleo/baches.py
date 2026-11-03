"""
baches.py
=========
Baches: regiones compactas cuya luminosidad (L*) o croma difiere del pavimento local (CIELAB).

Indicadores (tesis, Tabla 4): presencia, longitud (m), ancho (m), área (m²), contraste respecto
al pavimento. Las dimensiones salen del rectángulo mínimo orientado (mayor = longitud, menor = ancho).
La PROFUNDIDAD no se puede obtener de una imagen RGB 2D: la severidad del bache (Ficha 3: <=2.5,
2.5-5, >5 cm) solo es la de campo, por eso severidad_prelim queda vacía.
"""
import cv2
import numpy as np
from scipy import ndimage as ndi

from app.nucleo.estructuras import Deteccion
from app.nucleo.medidas import contraste_weber
from app.nucleo.preprocesado import blur_grande, impar, mad_robusto


def detectar_baches(rgb, valido, gsd_m, p, origen=(0, 0)):
    """Devuelve la lista de baches con coordenadas GLOBALES (se suma `origen`)."""
    ox, oy = origen
    H, W = valido.shape
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (0, 0), max(1.0, 0.01 / gsd_m))
    sigma = float(np.clip(p.bache_fondo_m / gsd_m, 3, max(3, min(H, W) / 3)))
    fondo = blur_grande(lab, sigma)
    dL = lab[..., 0] - fondo[..., 0]
    dC = np.hypot(lab[..., 1] - fondo[..., 1], lab[..., 2] - fondo[..., 2])
    hay = valido.any()
    tL = max(p.bache_dL_min, 3.0 * mad_robusto(dL[valido]) if hay else 0)
    tC = max(p.bache_dC_min, 3.0 * mad_robusto(dC[valido]) if hay else 0)
    cand = ((np.abs(dL) > tL) | (dC > tC)) & valido
    croma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    cand &= ~((lab[..., 0] > p.marca_vial_L) & (croma < 12))          # excluir marcas viales
    cand = cand.astype(np.uint8)
    kw = impar(p.bache_ancho_min_m / gsd_m, 3, 151)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kw, kw)))
    kc = impar(0.05 / gsd_m, 3, 31)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc)))
    cand = ndi.binary_fill_holes(cand).astype(np.uint8)
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    n, lab_c, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    dets = []
    for i in range(1, n):
        a_m2 = st[i, cv2.CC_STAT_AREA] * gsd_m ** 2
        if a_m2 < p.bache_area_min_m2:
            continue
        x, y, w, h = (int(st[i, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                              cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        m = (lab_c[y:y + h, x:x + w] == i).astype(np.uint8)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        hull = cv2.contourArea(cv2.convexHull(c))
        solidez = float(cv2.contourArea(c) / hull) if hull > 0 else 0.0
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        mayor, menor = max(rw, rh), min(rw, rh)
        if solidez < p.bache_solidez_min or mayor == 0 or menor / mayor < p.bache_relacion_min:
            continue
        r = max(3, int(0.05 / gsd_m))
        y0, y1, x0, x1 = max(0, y - 3 * r), min(H, y + h + 3 * r), max(0, x - 3 * r), min(W, x + w + 3 * r)
        mc = (lab_c[y0:y1, x0:x1] == i)
        weber = contraste_weber(gris[y0:y1, x0:x1], mc, r, 3 * r)
        poli = cv2.approxPolyDP(c, max(1.0, 0.02 / gsd_m), True)
        dets.append(Deteccion(
            tipo="bache", x=x + ox, y=y + oy, w=w, h=h, cx=float(x + w / 2 + ox), cy=float(y + h / 2 + oy),
            longitud_m=round(mayor * gsd_m, 3), ancho_m=round(menor * gsd_m, 3), area_m2=round(a_m2, 4),
            solidez=round(solidez, 3), contraste_weber=weber, severidad_prelim=None,
            advertencia="revisar sombras, agua o reparaciones",
            geom_tipo="poligono", geom=[(int(px) + x + ox, int(py) + y + oy) for px, py in poli[:, 0, :]]))
    return dets
