#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detección de deterioros en pavimentos flexibles a partir de imágenes RGB (UAV).

Programa asociado al plan de tesis:
  "Metodología para la detección de deterioros y fallas estructurales en pavimentos
   flexibles de zonas altoandinas mediante bandas RGB y procesamiento en Python"

Qué hace (siguiendo las etapas 6-7 del plan de recolección y el plan de análisis):
  1. Calidad de imagen: nitidez, brillo, saturación, resolución (cm/px) y cobertura (%).
  2. Región de interés (ROI): máscara de calzada válida (sin NoData ni vegetación) y
     ROI de campo (CSV) con margen de contexto.
  3. Preprocesamiento: normalización de iluminación (I - gauss(I) + media, como Sun, 2009).
  4. Estadísticos RGB por ROI (media, mínimo, máximo, desviación estándar) y textura GLCM
     (contraste, homogeneidad, correlación, energía, entropía).
  5. Segmentación y medición de:
       - grietas longitudinales / transversales (longitud m, ancho mm, orientación, contraste)
       - piel de cocodrilo (área m², n.º de celdas, densidad de grietas)
       - baches (n.º, longitud, ancho, área m²)
  6. Validación contra la inspección de campo: VP, FP, FN, concordancia (%), precisión,
     sensibilidad, F1 y kappa de Cohen.

Salidas (carpeta -o):
  calidad_imagen.csv · detecciones.csv · caracteristicas_roi.csv
  validacion_roi.csv · validacion_resumen.csv · parametros.json · anotadas/*.png

Uso básico:
  python pavimento_rgb.py ortomosaico.tif --gsd 0.5 --rois rois.csv --tramo "Av. Argentina" -o salida

Dependencias: numpy, opencv-python, scipy, scikit-image, pandas  (rasterio opcional)
"""

import argparse
import json
import math
import os
import sys
import unicodedata
from dataclasses import dataclass, asdict, fields

import cv2
import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

try:                                    # skimage >= 0.19
    from skimage.feature import graycomatrix, graycoprops
except ImportError:                     # versiones antiguas
    from skimage.feature import greycomatrix as graycomatrix, greycoprops as graycoprops

TIPOS = ("longitudinal", "transversal", "piel_cocodrilo", "bache")
COLORES = {                              # RGB para las imágenes anotadas
    "longitudinal": (0, 120, 255),
    "transversal": (255, 40, 40),
    "piel_cocodrilo": (255, 165, 0),
    "bache": (255, 0, 255),
}


# =============================================================================
# Parámetros (todos modificables con --param clave=valor)
# =============================================================================
@dataclass
class Params:
    gsd_cm: float = 0.5                  # resolución espacial (cm/píxel)
    eje_via_deg: float = 0.0             # ángulo del eje de la vía en la imagen (0 = horizontal, 90 = vertical)
    tol_orient_deg: float = 45.0         # |ángulo - eje| <= tol -> longitudinal; si no, transversal

    # calidad de imagen
    nitidez_min: float = 20.0            # varianza del Laplaciano mínima
    brillo_min: float = 40.0
    brillo_max: float = 215.0
    saturados_max: float = 0.05          # fracción máxima de píxeles saturados

    # máscara de calzada
    exg_veg: float = 25.0                # índice ExG (2G-R-B) por encima del cual es vegetación

    # preprocesamiento
    iluminacion_sigma_m: float = 0.5     # escala del fondo de iluminación a restar

    # grietas
    grieta_kernel_m: float = 0.06        # tamaño del black-hat (> ancho máximo de grieta)
    grieta_k_mad: float = 4.5            # umbral = mediana + k * MAD del black-hat
    grieta_contraste_min: float = 8.0    # umbral mínimo (niveles de gris)
    grieta_cierre_m: float = 0.03        # cierre morfológico: une puntos de ruptura menores a esto
    grieta_long_min_m: float = 0.15      # longitud mínima de una grieta
    grieta_en_cocodrilo: float = 0.5     # fracción dentro de zona de cocodrilo para excluirla de las lineales

    # piel de cocodrilo (celdas < 0.3 m de lado, FHWA/ASTM D6433)
    celda_min_m2: float = 0.0004
    celda_max_m2: float = 0.09
    celda_union_m: float = 0.08          # distancia máxima para agrupar celdas en una zona
    celdas_min: int = 4                  # mínimo de celdas por zona
    zona_min_m2: float = 0.05

    # baches
    bache_fondo_m: float = 0.75          # escala del fondo local de referencia
    bache_dL_min: float = 18.0           # diferencia mínima de luminosidad (escala 0-255)
    bache_dC_min: float = 14.0           # diferencia mínima de croma
    bache_ancho_min_m: float = 0.12      # ancho mínimo (la apertura elimina grietas)
    bache_area_min_m2: float = 0.03
    bache_solidez_min: float = 0.6
    bache_relacion_min: float = 0.25     # eje menor / eje mayor
    marca_vial_L: float = 190.0          # L > este valor y croma bajo: marca vial, se excluye


def _odd(n, lo, hi):
    n = int(round(n))
    n = max(lo, min(hi, n))
    return n if n % 2 == 1 else n + 1


def blur_grande(img, sigma):
    """Gaussiana de sigma grande (usa reducción previa para ser rápida)."""
    h, w = img.shape[:2]
    s = max(1, min(int(sigma // 6), min(h, w) // 8))
    if s > 1:
        small = cv2.resize(img, None, fx=1.0 / s, fy=1.0 / s, interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), max(sigma / s, 0.5))
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(img, (0, 0), max(sigma, 0.5))


def mad_robusto(x):
    x = np.asarray(x, dtype=np.float32).ravel()
    if x.size == 0:
        return 0.0
    return float(np.median(np.abs(x - np.median(x))) * 1.4826)


# =============================================================================
# Lectura de imágenes
# =============================================================================
def leer_imagen(path):
    """Devuelve (rgb uint8, nodata bool). Admite JPG/PNG/TIF; usa alfa como NoData si existe."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"No se pudo leer la imagen: {path}")
    if img.dtype == np.uint16:
        img = (img / 257.0).astype(np.uint8)
    elif img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    nodata = None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        nodata = img[..., 3] == 0
        img = img[..., :3]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)       # OpenCV lee en BGR
    return rgb, nodata


def leer_georreferencia(path):
    """(gsd_cm, transform) de un GeoTIFF si rasterio está instalado y el CRS es métrico."""
    try:
        import rasterio
    except ImportError:
        return None, None
    try:
        with rasterio.open(path) as ds:
            t = ds.transform
            if ds.crs is not None and ds.crs.is_projected:
                return abs(t.a) * 100.0, t
            return None, t
    except Exception:
        return None, None


# =============================================================================
# 1-2. Calidad de imagen y máscara de calzada
# =============================================================================
def mascara_valida(rgb, p, nodata_ext=None, mascara_via=None):
    """valid = calzada utilizable (sin NoData, sin vegetación, dentro de la máscara externa)."""
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    nodata = (r == 0) & (g == 0) & (b == 0)
    nodata = cv2.morphologyEx(nodata.astype(np.uint8), cv2.MORPH_OPEN,
                              np.ones((5, 5), np.uint8)).astype(bool)
    if nodata_ext is not None:
        nodata |= nodata_ext
    veg = (2 * g - r - b) > p.exg_veg
    veg = cv2.morphologyEx(veg.astype(np.uint8), cv2.MORPH_OPEN,
                           np.ones((3, 3), np.uint8)).astype(bool)
    valid = ~nodata & ~veg
    if mascara_via is not None:
        valid &= mascara_via
    return valid, nodata


def evaluar_calidad(rgb, valid, nodata, p):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    cy, cx = h // 2, w // 2
    hh, ww = min(h, 2000) // 2, min(w, 2000) // 2           # recorte central para la nitidez
    sub = gray[cy - hh:cy + hh, cx - ww:cx + ww]
    vs = valid[cy - hh:cy + hh, cx - ww:cx + ww]
    lap = cv2.Laplacian(sub, cv2.CV_64F)
    nitidez = float(lap[vs].var()) if vs.any() else 0.0
    gv = gray[valid]
    brillo = float(gv.mean()) if gv.size else 0.0
    sat = float(((gv <= 5) | (gv >= 250)).mean()) if gv.size else 1.0
    cobertura = float(100.0 * (~nodata).mean())
    adecuada = (nitidez >= p.nitidez_min and p.brillo_min <= brillo <= p.brillo_max
                and sat <= p.saturados_max)
    adv = []
    if nitidez < p.nitidez_min:
        adv.append("imagen poco nítida")
    if not (p.brillo_min <= brillo <= p.brillo_max):
        adv.append("brillo fuera de rango")
    if sat > p.saturados_max:
        adv.append("exceso de píxeles saturados")
    if p.gsd_cm > 0.5:
        adv.append("GSD > 5 mm/px: grietas finas (< 10 mm) pueden no resolverse")
    return {
        "calidad": "Adecuada" if adecuada else "No adecuada",
        "nitidez_lap_var": round(nitidez, 2), "brillo_medio": round(brillo, 1),
        "fraccion_saturada": round(sat, 4), "resolucion_cm_px": p.gsd_cm,
        "cobertura_pct": round(cobertura, 2), "calzada_util_pct": round(100.0 * valid.mean(), 2),
        "advertencias": "; ".join(adv),
    }


# =============================================================================
# 3. Preprocesamiento
# =============================================================================
def preprocesar(gray, valid, p):
    """Normaliza la iluminación: I - gauss(I) + media (Sun, 2009, cap. 3)."""
    g = gray.astype(np.float32)
    media = float(g[valid].mean()) if valid.any() else float(g.mean())
    g = np.where(valid, g, media)                       # evita bordes falsos fuera de la calzada
    sigma = max(5.0, p.iluminacion_sigma_m / (p.gsd_cm / 100.0))
    sigma = min(sigma, max(3.0, min(g.shape) / 3.0))
    fondo = blur_grande(g, sigma)
    return np.clip(g - fondo + media, 0, 255).astype(np.uint8)


# =============================================================================
# 4. Estadísticos RGB y textura GLCM
# =============================================================================
def estadisticos_rgb(rgb, valid):
    out = {}
    for i, c in enumerate("RGB"):
        v = rgb[..., i][valid] if valid.any() else rgb[..., i].ravel()
        out[f"{c}_media"] = round(float(v.mean()), 2)
        out[f"{c}_min"] = int(v.min())
        out[f"{c}_max"] = int(v.max())
        out[f"{c}_desv"] = round(float(v.std()), 2)
    return out


def textura_glcm(gray, niveles=32):
    h, w = gray.shape
    if h > 2000 or w > 2000:                            # recorte central para acotar el costo
        y0, x0 = max(0, h // 2 - 1000), max(0, w // 2 - 1000)
        gray = gray[y0:y0 + 2000, x0:x0 + 2000]
    q = (gray.astype(np.uint16) * niveles // 256).astype(np.uint8)
    glcm = graycomatrix(q, distances=[1, 3], angles=[0, np.pi / 4, np.pi / 2, 3 * np.pi / 4],
                        levels=niveles, symmetric=True, normed=True)
    props = {n: float(graycoprops(glcm, n).mean())
             for n in ("contrast", "homogeneity", "correlation", "energy", "dissimilarity")}
    pl = np.where(glcm > 0, glcm, 1.0)
    entropia = float(-(glcm * np.log2(pl)).sum(axis=(0, 1)).mean())
    return {"tex_contraste": round(props["contrast"], 3),
            "tex_homogeneidad": round(props["homogeneity"], 4),
            "tex_correlacion": round(props["correlation"], 4),
            "tex_energia": round(props["energy"], 4),
            "tex_disimilitud": round(props["dissimilarity"], 3),
            "tex_entropia": round(entropia, 3)}


# =============================================================================
# 5a. Grietas longitudinales y transversales
# =============================================================================
def longitud_esqueleto_px(sub):
    """Longitud de un esqueleto 8-conexo: 1 por enlace ortogonal, raíz(2) por diagonal aislada."""
    s = sub.astype(bool)
    h = np.count_nonzero(s[:, :-1] & s[:, 1:])
    v = np.count_nonzero(s[:-1, :] & s[1:, :])
    d1 = s[:-1, :-1] & s[1:, 1:] & ~(s[:-1, 1:] | s[1:, :-1])
    d2 = s[:-1, 1:] & s[1:, :-1] & ~(s[:-1, :-1] | s[1:, 1:])
    return h + v + math.sqrt(2.0) * (np.count_nonzero(d1) + np.count_nonzero(d2))


def segmentar_grietas(gray_norm, valid, gsd_m, p):
    """Black-hat (detecta líneas oscuras) + umbral robusto + cierre de puntos de ruptura + esqueleto."""
    g = cv2.GaussianBlur(gray_norm, (0, 0), 1.0)
    k = _odd(p.grieta_kernel_m / gsd_m, 5, 61)
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))).astype(np.float32)
    v = bh[valid] if valid.any() else bh.ravel()
    umbral = max(float(np.median(v)) + p.grieta_k_mad * mad_robusto(v), p.grieta_contraste_min)
    m = ((bh > umbral) & valid).astype(np.uint8)
    # quitar ruido puntual
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = st[:, cv2.CC_STAT_AREA] >= 8
    keep[0] = False
    m = keep[lab].astype(np.uint8)
    # unir huecos (puntos de ruptura) con cierre morfológico
    gap = int(np.clip(round(p.grieta_cierre_m / gsd_m), 1, 8))
    closed = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1)))
    sk = skeletonize(closed > 0)
    return closed, sk


def analizar_grietas(sk, closed, zona, gray, gsd_m, p):
    n, lab, st, _ = cv2.connectedComponentsWithStats(sk.astype(np.uint8), connectivity=8)
    dt = cv2.distanceTransform(closed, cv2.DIST_L2, 3)
    H, W = sk.shape
    kernel_nb = np.ones((3, 3), np.float32)
    dets, comps = [], []
    for i in range(1, n):
        x, y, w, h, a = (int(t) for t in st[i])
        if a < 3:
            continue
        sub = lab[y:y + h, x:x + w] == i
        long_m = longitud_esqueleto_px(sub) * gsd_m
        if long_m < p.grieta_long_min_m:
            continue
        if zona is not None and zona[y:y + h, x:x + w][sub].mean() >= p.grieta_en_cocodrilo:
            continue                                            # pertenece a una zona de cocodrilo
        ys, xs = np.nonzero(sub)
        pts = np.stack([xs, ys], 1).astype(np.float64)
        pts -= pts.mean(0)
        ev, evec = np.linalg.eigh(np.cov(pts.T) + 1e-9 * np.eye(2))
        vx, vy = evec[:, 1]
        ang = math.degrees(math.atan2(vy, vx)) % 180.0          # ángulo en la imagen (y hacia abajo)
        delta = abs(((ang - p.eje_via_deg) + 90.0) % 180.0 - 90.0)   # 0 = paralela al eje, 90 = perpendicular
        tipo = "longitudinal" if delta <= p.tol_orient_deg else "transversal"
        # ancho: 2*dt-1 sobre el esqueleto
        ancho_px = max(1.0, 2.0 * float(dt[y:y + h, x:x + w][sub].mean()) - 1.0)
        ancho_mm = ancho_px * gsd_m * 1000.0
        # ramificación (n.º de grupos de uniones)
        nb = cv2.filter2D(sub.astype(np.float32), -1, kernel_nb, borderType=cv2.BORDER_CONSTANT) - 1
        junc = (nb >= 3) & sub
        n_junc = int(cv2.connectedComponents(junc.astype(np.uint8), connectivity=8)[0] - 1)
        # contraste de Weber: pavimento circundante vs centro de la grieta (gris original)
        r_in = int(ancho_px / 2) + 2
        r_out = r_in + max(4, int(ancho_px))
        y0, y1 = max(0, y - r_out), min(H, y + h + r_out)
        x0, x1 = max(0, x - r_out), min(W, x + w + r_out)
        skc = np.zeros((y1 - y0, x1 - x0), np.uint8)
        skc[y - y0:y - y0 + h, x - x0:x - x0 + w][sub] = 1
        se = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        anillo = (cv2.dilate(skc, se(r_out)) > 0) & ~(cv2.dilate(skc, se(r_in)) > 0)
        g = gray[y0:y1, x0:x1]
        weber = None
        if anillo.any():
            f = float(g[anillo].mean())
            if f > 0:
                weber = round((f - float(g[skc > 0].mean())) / f, 3)
        # severidad preliminar según ancho (criterio ASTM D6433: <10 mm, 10-76 mm, >76 mm)
        sev = "Baja" if ancho_mm < 10 else ("Media" if ancho_mm <= 76 else "Alta")
        adv = "ancho menor que 2 px (límite de resolución)" if ancho_px < 2 else ""
        dets.append({
            "tipo": tipo, "x": x, "y": y, "w": w, "h": h,
            "cx": float(xs.mean() + x), "cy": float(ys.mean() + y),
            "longitud_m": round(long_m, 3), "ancho_mm": round(ancho_mm, 1),
            "area_m2": round(long_m * ancho_mm / 1000.0, 5),
            "angulo_img_deg": round(ang, 1), "desv_eje_deg": round(delta, 1),
            "contraste_weber": weber, "ramificada": n_junc >= 2,
            "severidad_prelim": sev, "advertencia": adv,
        })
        comps.append((tipo, x, y, sub))
    return dets, comps


# =============================================================================
# 5b. Piel de cocodrilo
# =============================================================================
def detectar_piel_cocodrilo(closed, gsd_m, p):
    """Celdas = regiones sin grieta completamente rodeadas por grietas, de tamaño tipo bloque (< 0.3 m)."""
    H, W = closed.shape
    inv = (closed == 0).astype(np.uint8)
    n, lab, st, cent = cv2.connectedComponentsWithStats(inv, connectivity=4)
    area_m2 = st[:, cv2.CC_STAT_AREA] * gsd_m ** 2
    toca_borde = ((st[:, cv2.CC_STAT_LEFT] == 0) | (st[:, cv2.CC_STAT_TOP] == 0) |
                  (st[:, cv2.CC_STAT_LEFT] + st[:, cv2.CC_STAT_WIDTH] >= W) |
                  (st[:, cv2.CC_STAT_TOP] + st[:, cv2.CC_STAT_HEIGHT] >= H))
    ok = (area_m2 >= p.celda_min_m2) & (area_m2 <= p.celda_max_m2) & ~toca_borde
    ok[0] = False
    ids = np.nonzero(ok)[0]
    zona_total = np.zeros((H, W), bool)
    dets = []
    if ids.size < p.celdas_min:
        return dets, zona_total
    celdas = ok[lab].astype(np.uint8)
    k = _odd(p.celda_union_m / gsd_m, 3, 61)
    zona = cv2.morphologyEx(celdas, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    nz, zlab, zst, _ = cv2.connectedComponentsWithStats(zona, connectivity=8)
    cx = np.clip(np.round(cent[ids, 0]).astype(int), 0, W - 1)
    cy = np.clip(np.round(cent[ids, 1]).astype(int), 0, H - 1)
    zl = zlab[cy, cx]
    for j in range(1, nz):
        sel = zl == j
        n_cel = int(sel.sum())
        a_m2 = float(zst[j, cv2.CC_STAT_AREA]) * gsd_m ** 2
        if n_cel < p.celdas_min or a_m2 < p.zona_min_m2:
            continue
        x, y, w, h = (int(zst[j, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                               cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        zmask = zlab[y:y + h, x:x + w] == j
        zona_total[y:y + h, x:x + w] |= zmask
        dens = float((closed[y:y + h, x:x + w][zmask] > 0).mean())
        cel_media = float(area_m2[ids[sel]].mean())
        # severidad preliminar (propuesta; calibrar con la Ficha 5 de campo)
        if n_cel < 6 or cel_media > 0.06:
            sev = "Baja"
        elif cel_media < 0.015 and dens > 0.35:
            sev = "Alta"
        else:
            sev = "Media"
        dets.append({
            "tipo": "piel_cocodrilo", "x": x, "y": y, "w": w, "h": h,
            "cx": float(x + w / 2), "cy": float(y + h / 2),
            "longitud_m": round(max(w, h) * gsd_m, 3), "ancho_mm": round(min(w, h) * gsd_m * 1000, 1),
            "area_m2": round(a_m2, 4), "n_celdas": n_cel,
            "celda_media_m2": round(cel_media, 4), "densidad_grietas": round(dens, 3),
            "severidad_prelim": sev, "advertencia": "",
        })
    return dets, zona_total


# =============================================================================
# 5c. Baches
# =============================================================================
def detectar_baches(rgb, valid, gsd_m, p):
    """Regiones compactas cuya luminosidad/croma difiere del pavimento local. La profundidad NO se
    puede obtener de una imagen RGB 2D (requiere medición de campo)."""
    H, W = valid.shape
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (0, 0), max(1.0, 0.01 / gsd_m))
    sigma = float(np.clip(p.bache_fondo_m / gsd_m, 3, max(3, min(H, W) / 3)))
    fondo = blur_grande(lab, sigma)
    dL = lab[..., 0] - fondo[..., 0]
    dC = np.hypot(lab[..., 1] - fondo[..., 1], lab[..., 2] - fondo[..., 2])
    tL = max(p.bache_dL_min, 3.0 * mad_robusto(dL[valid]) if valid.any() else 0)
    tC = max(p.bache_dC_min, 3.0 * mad_robusto(dC[valid]) if valid.any() else 0)
    cand = ((np.abs(dL) > tL) | (dC > tC)) & valid
    croma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    cand &= ~((lab[..., 0] > p.marca_vial_L) & (croma < 12))      # excluir marcas viales
    cand = cand.astype(np.uint8)
    kw = _odd(p.bache_ancho_min_m / gsd_m, 3, 151)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kw, kw)))
    kc = _odd(0.05 / gsd_m, 3, 31)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc)))
    cand = ndi.binary_fill_holes(cand).astype(np.uint8)
    n, lab_c, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    dets, contornos = [], []
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
        dets.append({
            "tipo": "bache", "x": x, "y": y, "w": w, "h": h,
            "cx": float(x + w / 2), "cy": float(y + h / 2),
            "longitud_m": round(mayor * gsd_m, 3), "ancho_mm": round(menor * gsd_m * 1000, 1),
            "area_m2": round(a_m2, 4), "solidez": round(solidez, 3),
            "severidad_prelim": "requiere profundidad de campo",
            "advertencia": "revisar sombras, agua o reparaciones",
        })
        contornos.append(c + np.array([[[x, y]]]))
    return dets, contornos


# =============================================================================
# Análisis de una ventana (ROI con margen, o tesela del escaneo)
# =============================================================================
def analizar_ventana(rgb, valid, p):
    gsd_m = p.gsd_cm / 100.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gn = preprocesar(gray, valid, p)
    closed, sk = segmentar_grietas(gn, valid, gsd_m, p)
    cocodrilo, zona = detectar_piel_cocodrilo(closed, gsd_m, p)
    lineales, comps = analizar_grietas(sk, closed, zona, gray, gsd_m, p)
    baches, contornos = detectar_baches(rgb, valid, gsd_m, p)
    # imagen anotada de la ventana
    vis = rgb.copy()
    cz, _ = cv2.findContours(zona.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    esp = max(2, int(round(0.012 / gsd_m)))
    cv2.drawContours(vis, cz, -1, COLORES["piel_cocodrilo"], esp)
    cv2.drawContours(vis, contornos, -1, COLORES["bache"], esp)
    for tipo, x, y, sub in comps:
        m = cv2.dilate(sub.astype(np.uint8), np.ones((esp, esp), np.uint8)) > 0
        reg = vis[y:y + sub.shape[0], x:x + sub.shape[1]]
        # dilatación recortada al tamaño de la caja
        reg[m[:reg.shape[0], :reg.shape[1]]] = COLORES[tipo]
    return lineales + cocodrilo + baches, vis


def _en_nucleo(d, x0, y0, x1, y1):
    return x0 <= d["cx"] < x1 and y0 <= d["cy"] < y1


def procesar_ventana(rgb, valid, x0, y0, x1, y1, margen_px, p):
    """Analiza [x0,x1)x[y0,y1) con margen de contexto y devuelve las detecciones cuyo centro cae dentro."""
    H, W = valid.shape
    ex0, ey0 = max(0, x0 - margen_px), max(0, y0 - margen_px)
    ex1, ey1 = min(W, x1 + margen_px), min(H, y1 + margen_px)
    sub_rgb, sub_valid = rgb[ey0:ey1, ex0:ex1], valid[ey0:ey1, ex0:ex1]
    if sub_valid.sum() < 100:
        return [], None
    dets, vis = analizar_ventana(sub_rgb, sub_valid, p)
    out = []
    for d in dets:
        d = dict(d)
        d["x"] += ex0
        d["y"] += ey0
        d["cx"] += ex0
        d["cy"] += ey0
        if _en_nucleo(d, x0, y0, x1, y1):
            out.append(d)
    return out, (vis, (ex0, ey0))


# =============================================================================
# Validación contra la inspección de campo
# =============================================================================
def normalizar_tipo(txt):
    if txt is None or (isinstance(txt, float) and math.isnan(txt)):
        return None
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().lower().strip()
    if "long" in t:
        return "longitudinal"
    if "trans" in t:
        return "transversal"
    if "cocod" in t or "fatiga" in t:
        return "piel_cocodrilo"
    if "bache" in t or "pothole" in t:
        return "bache"
    if "sano" in t or "ninguno" in t or "sin_dano" in t:
        return "sano"
    return t


def etiqueta_dominante(tipos_con_long):
    """Etiqueta única por ROI: bache > piel de cocodrilo > grieta con mayor longitud total."""
    if not tipos_con_long:
        return "sano"
    if "bache" in tipos_con_long:
        return "bache"
    if "piel_cocodrilo" in tipos_con_long:
        return "piel_cocodrilo"
    return max(("longitudinal", "transversal"), key=lambda t: tipos_con_long.get(t, 0.0))


def kappa_cohen(y_true, y_pred):
    etiquetas = sorted(set(y_true) | set(y_pred))
    n = len(y_true)
    if n == 0:
        return float("nan")
    po = sum(a == b for a, b in zip(y_true, y_pred)) / n
    pe = sum((y_true.count(e) / n) * (y_pred.count(e) / n) for e in etiquetas)
    return float((po - pe) / (1 - pe)) if pe < 1 else 1.0


def validar(df_roi):
    """df_roi: una fila por ROI con 'tipo_campo' y 'tipos_detectados' (set)."""
    filas = []
    tot = {"VP": 0, "FP": 0, "FN": 0, "VN": 0}
    for t in TIPOS:
        vp = fp = fn = vn = 0
        for _, r in df_roi.iterrows():
            campo, det = r["tipo_campo"], r["tipos_detectados"]
            real, pred = (campo == t), (t in det)
            vp += real and pred
            fn += real and not pred
            fp += (not real) and pred
            vn += (not real) and not pred
        filas.append(_metricas(t, vp, fp, fn, vn))
        tot["VP"] += vp; tot["FP"] += fp; tot["FN"] += fn; tot["VN"] += vn
    filas.append(_metricas("GLOBAL", tot["VP"], tot["FP"], tot["FN"], tot["VN"]))
    y_t = list(df_roi["tipo_campo"])
    y_p = list(df_roi["etiqueta_python"])
    glob = filas[-1]
    glob["kappa_cohen"] = round(kappa_cohen(y_t, y_p), 3)
    glob["exactitud_etiqueta_pct"] = round(100.0 * np.mean([a == b for a, b in zip(y_t, y_p)]), 1)
    return pd.DataFrame(filas)


def _metricas(nombre, vp, fp, fn, vn):
    div = lambda a, b: round(a / b, 4) if b else None
    return {"tipo": nombre, "VP": int(vp), "FP": int(fp), "FN": int(fn), "VN": int(vn),
            "precision": div(vp, vp + fp), "sensibilidad": div(vp, vp + fn),
            "F1": div(2 * vp, 2 * vp + fp + fn),
            "concordancia_pct": None if (vp + fp + fn) == 0 else round(100.0 * vp / (vp + fp + fn), 1)}


# =============================================================================
# Procesamiento de una imagen completa
# =============================================================================
def cargar_rois(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    falt = {"codigo_roi", "x", "y", "ancho", "alto"} - set(df.columns)
    if falt:
        raise ValueError(f"Faltan columnas en el CSV de ROI: {sorted(falt)}")
    if "tipo_campo" in df.columns:
        df["tipo_campo"] = df["tipo_campo"].map(normalizar_tipo)
    return df


def procesar_imagen(path, p, df_rois, escaneo, margen_m, tramo, mascara_path, tesela, out_dir, geo_t):
    nombre = os.path.basename(path)
    rgb, nodata_ext = leer_imagen(path)
    H, W = rgb.shape[:2]
    mv = None
    if mascara_path:
        mk = cv2.imread(mascara_path, cv2.IMREAD_GRAYSCALE)
        if mk is None or mk.shape != (H, W):
            raise ValueError("La máscara de vía debe ser una imagen del mismo tamaño que el ortomosaico.")
        mv = mk > 127
    valid, nodata = mascara_valida(rgb, p, nodata_ext, mv)
    cal = evaluar_calidad(rgb, valid, nodata, p)
    cal.update({"imagen": nombre, "tramo": tramo, "ancho_px": W, "alto_px": H})
    margen_px = int(round(margen_m / (p.gsd_cm / 100.0)))

    vis_full = rgb.copy()
    dets_all, filas_roi = [], []
    rois_img = None
    if df_rois is not None:
        rois_img = df_rois
        if "imagen" in df_rois.columns:
            rois_img = df_rois[df_rois["imagen"].astype(str).map(os.path.basename) == nombre]

    # ---- modo ROI -----------------------------------------------------------------------------
    rois_rects = []
    if rois_img is not None and len(rois_img):
        for _, r in rois_img.iterrows():
            x0, y0 = int(r["x"]), int(r["y"])
            x1, y1 = min(W, x0 + int(r["ancho"])), min(H, y0 + int(r["alto"]))
            if x1 <= x0 or y1 <= y0:
                print(f"  [aviso] ROI {r['codigo_roi']} fuera de la imagen; se omite.", file=sys.stderr)
                continue
            rois_rects.append((x0, y0, x1, y1))
            dets, vis_info = procesar_ventana(rgb, valid, x0, y0, x1, y1, margen_px, p)
            if vis_info is not None:
                vis, (ex0, ey0) = vis_info
                vis_full[y0:y1, x0:x1] = vis[y0 - ey0:y1 - ey0, x0 - ex0:x1 - ex0]
            cv2.rectangle(vis_full, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 0), max(2, int(0.01 / (p.gsd_cm / 100))))
            cv2.putText(vis_full, str(r["codigo_roi"]), (x0 + 5, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (255, 255, 0), 2)
            for d in dets:
                d.update({"origen": "roi", "codigo_roi": r["codigo_roi"]})
            dets_all += dets
            # características del ROI (exactamente la caja marcada, sin margen)
            crop, vcrop = rgb[y0:y1, x0:x1], valid[y0:y1, x0:x1]
            fila = {"imagen": nombre, "tramo": r.get("tramo", tramo), "codigo_roi": r["codigo_roi"],
                    "tipo_campo": r.get("tipo_campo"), "severidad_campo": r.get("severidad_campo"),
                    "x": x0, "y": y0, "ancho_px": x1 - x0, "alto_px": y1 - y0,
                    "area_roi_m2": round((x1 - x0) * (y1 - y0) * (p.gsd_cm / 100) ** 2, 3)}
            fila.update(estadisticos_rgb(crop, vcrop))
            fila.update(textura_glcm(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)))
            long_por_tipo = {}
            for d in dets:
                long_por_tipo[d["tipo"]] = long_por_tipo.get(d["tipo"], 0.0) + d["longitud_m"]
            fila["tipos_detectados"] = set(long_por_tipo)
            fila["etiqueta_python"] = etiqueta_dominante(long_por_tipo)
            for t in TIPOS:
                fila[f"n_{t}"] = sum(1 for d in dets if d["tipo"] == t)
            filas_roi.append(fila)

    # ---- modo escaneo (toda la imagen por teselas) ----------------------------------------------
    if escaneo or not rois_rects:
        for ty in range(0, H, tesela):
            for tx in range(0, W, tesela):
                x1, y1 = min(W, tx + tesela), min(H, ty + tesela)
                dets, vis_info = procesar_ventana(rgb, valid, tx, ty, x1, y1, margen_px, p)
                if vis_info is None:
                    continue
                if not rois_rects:      # solo pinta si no hay ROI (para no pisar las ROI ya pintadas)
                    vis, (ex0, ey0) = vis_info
                    vis_full[ty:y1, tx:x1] = vis[ty - ey0:y1 - ey0, tx - ex0:x1 - ex0]
                for d in dets:
                    dentro = any(a <= d["cx"] < c and b <= d["cy"] < e for a, b, c, e in rois_rects)
                    if dentro:
                        continue        # ya registrada en modo ROI
                    d.update({"origen": "escaneo", "codigo_roi": "fuera_de_ROI" if rois_rects else ""})
                    dets_all.append(d)

    for i, d in enumerate(dets_all, 1):
        d["id_deterioro"] = f"{os.path.splitext(nombre)[0]}_{i:04d}"
        d["imagen"] = nombre
        d["tramo"] = tramo
        if geo_t is not None:
            d["x_geo"], d["y_geo"] = geo_t * (d["cx"], d["cy"])

    os.makedirs(os.path.join(out_dir, "anotadas"), exist_ok=True)
    esc = min(1.0, 4000.0 / max(H, W))
    salida = cv2.resize(vis_full, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA) if esc < 1 else vis_full
    cv2.imwrite(os.path.join(out_dir, "anotadas", os.path.splitext(nombre)[0] + "_anotada.png"),
                cv2.cvtColor(salida, cv2.COLOR_RGB2BGR))
    return cal, dets_all, filas_roi


# =============================================================================
# CLI
# =============================================================================
def aplicar_param_extra(p, items):
    tipos = {f.name: f.type for f in fields(Params)}
    for it in items or []:
        k, _, v = it.partition("=")
        if k not in tipos:
            raise SystemExit(f"Parámetro desconocido: {k}. Disponibles: {', '.join(tipos)}")
        setattr(p, k, (int if tipos[k] in (int, "int") else float)(v))


def listar_imagenes(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(os.path.join(a, f) for f in os.listdir(a)
                          if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")))
        else:
            out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser(description="Detección de deterioros en pavimentos flexibles con imágenes RGB.")
    ap.add_argument("imagenes", nargs="+", help="imágenes u ortomosaicos (o carpetas)")
    ap.add_argument("-o", "--out", default="salida", help="carpeta de salida")
    ap.add_argument("--gsd", type=float, help="resolución espacial en cm/píxel (si es GeoTIFF proyectado se lee solo)")
    ap.add_argument("--rois", help="CSV de ROI de campo: codigo_roi,x,y,ancho,alto[,tipo_campo,severidad_campo,tramo,imagen]")
    ap.add_argument("--escaneo", action="store_true", help="además de las ROI, analizar toda la imagen")
    ap.add_argument("--eje-via", type=float, default=0.0, help="ángulo del eje de la vía en la imagen (grados)")
    ap.add_argument("--tramo", default="", help="nombre del tramo")
    ap.add_argument("--margen-roi", type=float, default=1.0, help="margen de contexto alrededor de cada ROI (m)")
    ap.add_argument("--tesela", type=int, default=1600, help="tamaño de tesela del escaneo (px)")
    ap.add_argument("--mascara-via", help="PNG del mismo tamaño (blanco = calzada) para delimitar la ROI de la vía")
    ap.add_argument("--param", action="append", metavar="CLAVE=VALOR", help="sobrescribe un parámetro (ver Params)")
    a = ap.parse_args()

    imgs = listar_imagenes(a.imagenes)
    os.makedirs(a.out, exist_ok=True)
    df_rois = cargar_rois(a.rois) if a.rois else None

    cals, dets, rois = [], [], []
    for path in imgs:
        p = Params(eje_via_deg=a.eje_via)
        gsd_geo, geo_t = (None, None)
        if path.lower().endswith((".tif", ".tiff")):
            gsd_geo, geo_t = leer_georreferencia(path)
        g = a.gsd if a.gsd else gsd_geo
        if not g:
            raise SystemExit("Indica la resolución con --gsd (cm/píxel); no se pudo leer del archivo.")
        p.gsd_cm = float(g)
        aplicar_param_extra(p, a.param)
        print(f"Procesando {os.path.basename(path)}  (GSD = {p.gsd_cm} cm/px)")
        c, d, r = procesar_imagen(path, p, df_rois, a.escaneo, a.margen_roi, a.tramo,
                                  a.mascara_via, a.tesela, a.out, geo_t)
        cals.append(c); dets += d; rois += r
        print(f"  calidad: {c['calidad']} | detecciones: {len(d)}")

    pd.DataFrame(cals).to_csv(os.path.join(a.out, "calidad_imagen.csv"), index=False, encoding="utf-8-sig")
    cols = ["id_deterioro", "imagen", "tramo", "origen", "codigo_roi", "tipo", "longitud_m", "ancho_mm",
            "area_m2", "desv_eje_deg", "angulo_img_deg", "contraste_weber", "ramificada", "n_celdas",
            "celda_media_m2", "densidad_grietas", "solidez", "severidad_prelim", "advertencia",
            "x", "y", "w", "h", "cx", "cy", "x_geo", "y_geo"]
    df_d = pd.DataFrame(dets)
    if len(df_d):
        df_d = df_d.reindex(columns=[c for c in cols if c in df_d.columns])
    df_d.to_csv(os.path.join(a.out, "detecciones.csv"), index=False, encoding="utf-8-sig")

    if rois:
        df_r = pd.DataFrame(rois)
        df_r_out = df_r.copy()
        df_r_out["tipos_detectados"] = df_r_out["tipos_detectados"].map(lambda s: ",".join(sorted(s)))
        df_r_out.to_csv(os.path.join(a.out, "caracteristicas_roi.csv"), index=False, encoding="utf-8-sig")
        if df_r["tipo_campo"].notna().any():
            dv = df_r[df_r["tipo_campo"].notna()]
            res = validar(dv)
            res.to_csv(os.path.join(a.out, "validacion_resumen.csv"), index=False, encoding="utf-8-sig")
            dv_out = dv[["imagen", "codigo_roi", "tipo_campo", "etiqueta_python", "tipos_detectados"]].copy()
            dv_out["tipos_detectados"] = dv_out["tipos_detectados"].map(lambda s: ",".join(sorted(s)))
            dv_out["coincide"] = dv_out["tipo_campo"] == dv_out["etiqueta_python"]
            dv_out.to_csv(os.path.join(a.out, "validacion_roi.csv"), index=False, encoding="utf-8-sig")
            print("\n=== Validación (ROI de campo vs. Python) ===")
            print(res.to_string(index=False))

    with open(os.path.join(a.out, "parametros.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(p), f, indent=2, ensure_ascii=False)
    print(f"\nResultados en: {a.out}/")


if __name__ == "__main__":
    main()
