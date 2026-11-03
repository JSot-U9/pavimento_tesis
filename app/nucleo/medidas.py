"""
medidas.py
==========
Medidas geométricas y de contraste sobre máscaras y esqueletos.

ANCHO DE GRIETA (corrige la sobreestimación del motor anterior)
  El método anterior medía el ancho como 2·dist-1 sobre la máscara DESPUÉS del cierre morfológico,
  cuyo borde depende del umbral del black-hat y se ensancha con el desenfoque. Ahora:
    1. Por cada punto del esqueleto (uno cada `ancho_paso_px`) se extrae el PERFIL de gris
       perpendicular a la grieta.
    2. El ancho es la distancia entre los dos cruces a MEDIA ALTURA entre el fondo y el mínimo
       (FWHM): no depende de ningún umbral de segmentación.
    3. Un perfil de caja (ancho w) desenfocado con gaussiana sigma ensancha el FWHM; se invierte
       ese modelo analítico para recuperar w (`ancho_sigma_px`; 0 = no corregir).
    4. El resultado es la MEDIANA de los perfiles (robusta a texturas y cruces).
  Si no hay perfiles válidos se usa, como respaldo, la transformada de distancia sobre la máscara
  PREVIA al cierre (metodo_ancho = 'distancia_mascara').
  Límite físico: por debajo de ~2 px el ancho no es medible (se advierte).
"""
import math
from functools import lru_cache

import cv2
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.special import erf


def longitud_esqueleto_px(sub):
    """Longitud de un esqueleto 8-conexo: 1 por enlace ortogonal, raíz(2) por diagonal aislada."""
    s = sub.astype(bool)
    h = np.count_nonzero(s[:, :-1] & s[:, 1:])
    v = np.count_nonzero(s[:-1, :] & s[1:, :])
    d1 = s[:-1, :-1] & s[1:, 1:] & ~(s[:-1, 1:] | s[1:, :-1])
    d2 = s[:-1, 1:] & s[1:, :-1] & ~(s[:-1, :-1] | s[1:, 1:])
    return h + v + math.sqrt(2.0) * (np.count_nonzero(d1) + np.count_nonzero(d2))


def _elipse(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def contraste_weber(gris, mascara, r_in, r_out):
    """Contraste de Weber (fondo - objeto)/fondo: media del anillo [r_in, r_out] alrededor de la
    máscara frente a la media dentro de ella. `gris` y `mascara` deben ser del mismo recorte."""
    m = mascara.astype(np.uint8)
    anillo = (cv2.dilate(m, _elipse(r_out)) > 0) & ~(cv2.dilate(m, _elipse(r_in)) > 0)
    if not anillo.any() or not m.any():
        return None
    fondo = float(gris[anillo].mean())
    if fondo <= 0:
        return None
    return round((fondo - float(gris[m > 0].mean())) / fondo, 3)


# ---------------------------------------------------------------------------- ancho de grieta
@lru_cache(maxsize=32)
def _tabla_fwhm(sigma):
    """FWHM de una caja de ancho w convolucionada con gaussiana sigma, para w en una rejilla.
    Devuelve (w, fwhm) ordenados (el FWHM es monótono creciente con w)."""
    x = np.linspace(-40, 40, 16001)
    ws = np.concatenate([np.arange(0.2, 2.0, 0.1), np.arange(2.0, 30.5, 0.25)])
    fw = np.empty_like(ws)
    for i, w in enumerate(ws):
        f = 0.5 * (erf((x + w / 2) / (sigma * math.sqrt(2))) - erf((x - w / 2) / (sigma * math.sqrt(2))))
        mitad = f.max() / 2
        dentro = x[f >= mitad]
        fw[i] = dentro[-1] - dentro[0]
    return ws, np.maximum.accumulate(fw)


def corregir_difuminado(fwhm_px, sigma_px):
    """Ancho real de una caja cuyo FWHM medido (tras desenfoque sigma) es `fwhm_px`."""
    if sigma_px <= 0:
        return fwhm_px
    ws, fw = _tabla_fwhm(round(float(sigma_px), 3))
    if fwhm_px <= fw[0]:
        return float(ws[0])
    return float(np.interp(fwhm_px, fw, ws))


def _fwhm_perfil(prof, ts, contraste_min):
    """Ancho a media altura de un perfil con un valle oscuro central (px), o None si no es válido."""
    borde = np.abs(ts) > 0.6 * ts.max()
    fondo = float(np.median(prof[borde]))
    centro = np.abs(ts) <= 3.0
    k = int(np.argmin(np.where(centro, prof, np.inf)))
    vmin = prof[k]
    if fondo - vmin < contraste_min:
        return None
    mitad = (fondo + vmin) / 2.0
    j = k
    while j > 0 and prof[j] < mitad:
        j -= 1
    if prof[j] < mitad:
        return None
    izq = ts[j] + (mitad - prof[j]) / (prof[j + 1] - prof[j]) * (ts[j + 1] - ts[j])
    j = k
    while j < len(prof) - 1 and prof[j] < mitad:
        j += 1
    if prof[j] < mitad:
        return None
    der = ts[j - 1] + (mitad - prof[j - 1]) / (prof[j] - prof[j - 1]) * (ts[j] - ts[j - 1])
    return float(der - izq)


def ancho_por_perfil(gris_suave, puntos_xy, p, gsd_m):
    """Mediana (px) del ancho FWHM de perfiles perpendiculares a lo largo de la grieta.

    gris_suave: gris normalizado (float32) ya suavizado; puntos_xy: (n,2) esqueleto de UNA grieta,
    en las coordenadas de `gris_suave`. Devuelve (ancho_px | None, n_perfiles)."""
    pts = np.asarray(puntos_xy, dtype=float)
    if len(pts) < 4:
        return None, 0
    semi = int(math.ceil(p.ancho_semi_perfil_m / gsd_m / 2.0)) + 3
    ts = np.arange(-semi, semi + 0.01, 0.5)
    arbol = cKDTree(pts)
    anchos = []
    for i in range(0, len(pts), p.ancho_paso_px):
        vecinos = pts[arbol.query_ball_point(pts[i], 6)]
        if len(vecinos) < 4:
            continue
        c = vecinos - vecinos.mean(0)
        _, evec = np.linalg.eigh(np.cov(c.T) + 1e-9 * np.eye(2))
        tx, ty = evec[:, 1]                                   # tangente (eje principal)
        nx, ny = -ty, tx                                      # normal
        perfil = ndi.map_coordinates(gris_suave, [pts[i][1] + ts * ny, pts[i][0] + ts * nx],
                                     order=1, mode="nearest")
        w = _fwhm_perfil(perfil, ts, p.ancho_contraste_min)
        if w is not None:
            anchos.append(w)
    if len(anchos) < 3:
        return None, len(anchos)
    return corregir_difuminado(float(np.median(anchos)), p.ancho_sigma_px), len(anchos)


def ancho_por_distancia(mascara_previa, puntos_xy):
    """Respaldo: 2·dist-0.5 sobre la máscara PREVIA al cierre, solo en el esqueleto que cae dentro de ella.
    (2·dist-1 es exacto para anchos impares y subestima 1 px los pares; 2·dist-0.5 acota el error a ±0.5 px.)"""
    dt = cv2.distanceTransform(mascara_previa.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    pts = np.asarray(puntos_xy, dtype=int)
    vals = dt[pts[:, 1], pts[:, 0]]
    vals = vals[vals > 0]
    if vals.size == 0:
        return None
    return max(1.0, 2.0 * float(np.median(vals)) - 0.5)
