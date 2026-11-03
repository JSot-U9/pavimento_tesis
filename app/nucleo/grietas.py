"""
grietas.py
==========
Método ACTUAL de detección de grietas (black-hat + umbral robusto mediana + k·MAD):

  1. black-hat morfológico (resalta líneas oscuras) sobre el gris normalizado
  2. umbral robusto (mediana + k·MAD) -> máscara PREVIA (se conserva para medir)
  3. cierre morfológico -> une puntos de ruptura; esqueleto -> longitud y orientación
  4. ancho: perfil de gris a media altura (ver medidas.py), NO la máscara cerrada
  5. orientación: se compara con la dirección LOCAL del eje de vía (eje_via.EjeVia)
"""
import math

import cv2
import numpy as np
from skimage.morphology import skeletonize

from app.nucleo.estructuras import Deteccion
from app.nucleo.eje_via import EjeVia
from app.nucleo.medidas import (ancho_por_distancia, ancho_por_perfil, contraste_weber,
                                longitud_esqueleto_px)
from app.nucleo.preprocesado import impar, mad_robusto

MAX_PUNTOS_GEOM = 120


def segmentar_grietas(gris_norm, valido, gsd_m, p):
    """Devuelve (previa, cerrada, esqueleto): máscara antes del cierre, después, y su esqueleto."""
    g = cv2.GaussianBlur(gris_norm, (0, 0), 1.0)
    k = impar(p.grieta_kernel_m / gsd_m, 5, 61)
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))).astype(np.float32)
    v = bh[valido] if valido.any() else bh.ravel()
    umbral = max(float(np.median(v)) + p.grieta_k_mad * mad_robusto(v), p.grieta_contraste_min)
    m = ((bh > umbral) & valido).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)       # quita ruido puntual
    keep = st[:, cv2.CC_STAT_AREA] >= 8
    keep[0] = False
    previa = keep[lab].astype(np.uint8)
    hueco = int(np.clip(round(p.grieta_cierre_m / gsd_m), 1, 8))
    cerrada = cv2.morphologyEx(previa, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * hueco + 1, 2 * hueco + 1)))
    return previa, cerrada, skeletonize(cerrada > 0)


def severidad_grieta(ancho_mm, gsd_m, p):
    """Severidad ORIENTATIVA según el criterio de la Ficha 3 (grietas longitudinales: <=1 mm baja,
    1-3 mm media, >3 mm alta). Con un ancho menor a 2 px no es medible. La oficial es la de campo."""
    if ancho_mm is None:
        return None
    if ancho_mm < 2 * gsd_m * 1000.0:
        return "no resoluble (ancho < 2 px)"
    if ancho_mm <= p.sev_grieta_baja_mm:
        return "Baja"
    return "Media" if ancho_mm <= p.sev_grieta_media_mm else "Alta"


def _geometria(xs, ys, vx, vy, origen_x, origen_y):
    """Puntos del esqueleto ordenados a lo largo de su eje principal y submuestreados."""
    orden = np.argsort(xs * vx + ys * vy)
    idx = orden[np.linspace(0, len(orden) - 1, min(len(orden), MAX_PUNTOS_GEOM)).astype(int)]
    return [(int(xs[i]) + origen_x, int(ys[i]) + origen_y) for i in idx]


def _ramificada(sub):
    vecinos = cv2.filter2D(sub.astype(np.float32), -1, np.ones((3, 3), np.float32),
                           borderType=cv2.BORDER_CONSTANT) - 1
    union = (vecinos >= 3) & sub
    return int(cv2.connectedComponents(union.astype(np.uint8), connectivity=8)[0] - 1) >= 2


def analizar_grietas(esq, previa, cerrada, zona, gris, gris_norm, gsd_m, p, eje: EjeVia, origen=(0, 0)):
    """Mide cada grieta del esqueleto. Las coordenadas de salida son GLOBALES (se suma `origen`).

    `origen` es la posición (x, y) de la esquina de esta ventana en el ortomosaico; sirve para
    consultar el ángulo local del eje en coordenadas globales."""
    ox, oy = origen
    n, lab, st, _ = cv2.connectedComponentsWithStats(esq.astype(np.uint8), connectivity=8)
    H, W = esq.shape
    suave = cv2.GaussianBlur(gris_norm.astype(np.float32), (0, 0), p.ancho_suavizado_px) \
        if p.ancho_suavizado_px > 0 else gris_norm.astype(np.float32)
    salida = []
    for i in range(1, n):
        x, y, w, h, a = (int(t) for t in st[i])
        if a < 3:
            continue
        sub = lab[y:y + h, x:x + w] == i
        long_m = longitud_esqueleto_px(sub) * gsd_m
        if long_m < p.grieta_long_min_m:
            continue
        if zona is not None and zona[y:y + h, x:x + w][sub].mean() >= p.grieta_en_cocodrilo:
            continue                                         # pertenece a una zona de piel de cocodrilo
        ys, xs = np.nonzero(sub)
        pts = np.stack([xs, ys], 1).astype(np.float64)
        centro = pts.mean(0)
        _, evec = np.linalg.eigh(np.cov((pts - centro).T) + 1e-9 * np.eye(2))
        vx, vy = evec[:, 1]
        ang = math.degrees(math.atan2(vy, vx)) % 180.0       # ángulo en la imagen (y hacia abajo)
        cx, cy = float(centro[0] + x), float(centro[1] + y)
        ang_eje = float(eje.angulo_local_deg(cx + ox, cy + oy))
        desv = EjeVia.desviacion_deg(ang, ang_eje)
        tipo = "longitudinal" if desv <= p.tol_orient_deg else "transversal"

        # ancho: perfil de gris (principal) o distancia sobre la máscara previa (respaldo)
        gpts = np.stack([xs + x, ys + y], 1).astype(np.float64)
        ancho_px, n_perf = ancho_por_perfil(suave, gpts, p, gsd_m)
        metodo = "perfil_gris"
        if ancho_px is None:
            ancho_px = ancho_por_distancia(previa, gpts.astype(int))
            metodo = "distancia_mascara"
        if ancho_px is None:
            ancho_mm, metodo = None, "no_medible"
        else:
            ancho_mm = ancho_px * gsd_m * 1000.0
        adv = "ancho menor que 2 px (límite de resolución)" if (ancho_px is not None and ancho_px < 2) else ""

        r_in = int((ancho_px or 2) / 2) + 2
        r_out = r_in + max(4, int(ancho_px or 2))
        y0, y1, x0, x1 = max(0, y - r_out), min(H, y + h + r_out), max(0, x - r_out), min(W, x + w + r_out)
        skc = np.zeros((y1 - y0, x1 - x0), np.uint8)
        skc[y - y0:y - y0 + h, x - x0:x - x0 + w][sub] = 1
        weber = contraste_weber(gris[y0:y1, x0:x1], skc, r_in, r_out)

        salida.append(Deteccion(
            tipo=tipo, x=x + ox, y=y + oy, w=w, h=h, cx=cx + ox, cy=cy + oy,
            longitud_m=round(long_m, 3),
            ancho_mm=None if ancho_mm is None else round(ancho_mm, 1),
            area_m2=round(long_m * (ancho_mm or 0.0) / 1000.0, 5),
            angulo_img_deg=round(ang, 1), angulo_eje_deg=round(ang_eje, 1), desv_eje_deg=round(desv, 1),
            contraste_weber=weber, ramificada=_ramificada(sub),
            severidad_prelim=severidad_grieta(ancho_mm, gsd_m, p),
            metodo_ancho=metodo, advertencia=adv,
            geom_tipo="polilinea_aprox", geom=_geometria(xs + x, ys + y, vx, vy, ox, oy)))
    return salida
