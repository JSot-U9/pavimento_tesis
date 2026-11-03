"""
cocodrilo.py
============
Piel de cocodrilo: celdas = regiones sin grieta rodeadas por grietas, de tamaño tipo bloque
(< 0.3 m de lado, FHWA / ASTM D6433); se agrupan en zonas y se exigen >= `celdas_min` celdas.

Indicadores (tesis, Tabla 3): presencia, área afectada (m²), longitud representativa de grietas (m),
densidad o concentración del patrón de grietas (%), n.º de celdas.
NO se reporta ancho: una zona de cocodrilo no tiene un 'ancho de grieta' (el motor anterior
daba valores como 1695 mm, que eran el lado menor de la caja de la zona).

Supuesto: 'longitud representativa de grietas' = longitud total de grietas (esqueleto) dentro de
la zona. La severidad no se estima: los criterios de la Ficha 3 son cualitativos (fisuras finas /
inicio de desprendimiento / hundimientos) y no se pueden derivar de una imagen RGB 2D.
"""
import cv2
import numpy as np

from app.nucleo.estructuras import Deteccion
from app.nucleo.medidas import longitud_esqueleto_px
from app.nucleo.preprocesado import impar


def _celdas(cerrada, gsd_m, p):
    """Etiqueta las regiones libres de grieta y devuelve (ids_celdas, etiquetas, centroides, areas_m2)."""
    H, W = cerrada.shape
    libre = (cerrada == 0).astype(np.uint8)
    n, lab, st, cent = cv2.connectedComponentsWithStats(libre, connectivity=4)
    area = st[:, cv2.CC_STAT_AREA] * gsd_m ** 2
    toca_borde = ((st[:, cv2.CC_STAT_LEFT] == 0) | (st[:, cv2.CC_STAT_TOP] == 0) |
                  (st[:, cv2.CC_STAT_LEFT] + st[:, cv2.CC_STAT_WIDTH] >= W) |
                  (st[:, cv2.CC_STAT_TOP] + st[:, cv2.CC_STAT_HEIGHT] >= H))
    ok = (area >= p.celda_min_m2) & (area <= p.celda_max_m2) & ~toca_borde
    ok[0] = False
    return np.nonzero(ok)[0], ok, lab, cent, area


def _zonas(zona, cx, cy):
    """Etiqueta las zonas y asigna a cada celda su zona (0 = ninguna)."""
    nz, zlab, zst, _ = cv2.connectedComponentsWithStats(zona, connectivity=8)
    return nz, zlab, zst, zlab[cy, cx]


def _mascara_exclusion(shape, nz, zlab, zst, zona_de_celda, gsd_m, p):
    """Zonas COMPLETAS de la ventana (con celdas y área suficientes): sirve para no contar como grietas
    lineales las grietas que forman la piel de cocodrilo, aunque la medición se recorte al núcleo."""
    mascara = np.zeros(shape, bool)
    for j in range(1, nz):
        if (zona_de_celda == j).sum() >= p.celdas_min and zst[j, cv2.CC_STAT_AREA] * gsd_m ** 2 >= p.zona_min_m2:
            mascara |= zlab == j
    # las grietas que bordean la zona (anillo exterior de celdas) también son piel de cocodrilo:
    # se dilata la zona en la distancia de unión de celdas para incluirlas
    r = max(1, int(round(p.celda_union_m / gsd_m / 2)))
    return cv2.dilate(mascara.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0


def _deteccion_de_zona(j, zlab, zst, area, ids, sel, cerrada, esqueleto, gsd_m, origen):
    ox, oy = origen
    x, y, w, h = (int(zst[j, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                           cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    zmask = zlab[y:y + h, x:x + w] == j
    densidad = float((cerrada[y:y + h, x:x + w][zmask] > 0).mean())
    long_m = longitud_esqueleto_px(esqueleto[y:y + h, x:x + w] & zmask) * gsd_m
    contornos, _ = cv2.findContours(zmask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = cv2.approxPolyDP(max(contornos, key=cv2.contourArea), max(1.0, 0.02 / gsd_m), True)
    return Deteccion(
        tipo="piel_cocodrilo", x=x + ox, y=y + oy, w=w, h=h, cx=float(x + w / 2 + ox), cy=float(y + h / 2 + oy),
        longitud_m=round(long_m, 3), ancho_mm=None, area_m2=round(float(zst[j, cv2.CC_STAT_AREA]) * gsd_m ** 2, 4),
        n_celdas=int(sel.sum()), celda_media_m2=round(float(area[ids[sel]].mean()), 4),
        densidad_pct=round(100.0 * densidad, 1), severidad_prelim=None,
        geom_tipo="poligono", geom=[(int(px) + x + ox, int(py) + y + oy) for px, py in c[:, 0, :]])


def detectar_piel_cocodrilo(cerrada, esqueleto, gsd_m, p, origen=(0, 0), nucleo=None):
    """Devuelve (detecciones, mascara_zona). Coordenadas GLOBALES (se suma `origen`).

    mascara_zona = zonas completas de la ventana (para excluir sus grietas del conteo lineal).

    nucleo=(x0,y0,x1,y1) en coordenadas de la ventana: las detecciones se miden solo dentro de ese
    rectángulo (zonas recortadas; cuentan las celdas con centroide dentro) para que teselas vecinas
    no se solapen. Con núcleo, los mínimos de celdas/área se aplican DESPUÉS de fusionar las piezas
    cortadas (fusion.py); sin núcleo se aplican aquí."""
    H, W = cerrada.shape
    ids, ok, lab, cent, area = _celdas(cerrada, gsd_m, p)
    if ids.size == 0 or (nucleo is None and ids.size < p.celdas_min):
        return [], np.zeros((H, W), bool)
    k = impar(p.celda_union_m / gsd_m, 3, 61)
    zona = cv2.morphologyEx(ok[lab].astype(np.uint8), cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cx = np.clip(np.round(cent[ids, 0]).astype(int), 0, W - 1)
    cy = np.clip(np.round(cent[ids, 1]).astype(int), 0, H - 1)
    nz, zlab, zst, zdc = _zonas(zona, cx, cy)
    exclusion = _mascara_exclusion((H, W), nz, zlab, zst, zdc, gsd_m, p)
    if nucleo is not None:                                  # medir solo dentro del núcleo
        recorte = np.zeros_like(zona)
        recorte[nucleo[1]:nucleo[3], nucleo[0]:nucleo[2]] = 1
        nz, zlab, zst, zdc = _zonas(zona & recorte, cx, cy)
    dets = []
    for j in range(1, nz):
        sel = zdc == j
        a_m2 = float(zst[j, cv2.CC_STAT_AREA]) * gsd_m ** 2
        if not sel.any() or (nucleo is None and (sel.sum() < p.celdas_min or a_m2 < p.zona_min_m2)):
            continue
        dets.append(_deteccion_de_zona(j, zlab, zst, area, ids, sel, cerrada, esqueleto, gsd_m, origen))
    return dets, exclusion
