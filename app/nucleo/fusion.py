"""
fusion.py
=========
Cada tesela mide SOLO dentro de su núcleo (sin solapar con las vecinas), de modo que una grieta o
una zona de piel de cocodrilo que cruza el borde entre dos teselas sale en dos PIEZAS. Este módulo:

  1. marca por qué bordes internos fue cortada cada pieza (`marcar_bordes`);
  2. une las piezas que se tocan a ambos lados del mismo borde (`fusionar`): suma longitud y área,
     pondera el ancho por longitud, y recalcula tipo (orientación local) y geometría.

Se fusionan solo grietas lineales con grietas lineales, y piel de cocodrilo con piel de cocodrilo.
Los baches no se cortan (se asignan a la tesela de su centroide).
"""
import math

import cv2
import numpy as np

from app.nucleo.estructuras import TIPOS_GRIETA
from app.nucleo.eje_via import EjeVia
from app.nucleo.grietas import MAX_PUNTOS_GEOM, severidad_grieta

TOL_PX = 12          # holgura (px) para considerar que dos piezas se tocan en el borde
FUSIONABLES = TIPOS_GRIETA + ("piel_cocodrilo",)


def marcar_bordes(d, nucleo, region):
    """Anota en `d.bordes_corte` los bordes internos del núcleo (x0,y0,x1,y1) que la pieza toca.

    Un borde es 'interno' si no coincide con el borde de la región analizada."""
    if d.tipo not in FUSIONABLES:
        return
    x0, y0, x1, y1 = nucleo
    rx0, ry0, rx1, ry1 = region
    if x0 > rx0 and d.x <= x0 + 1:
        d.bordes_corte.append(("v", x0, -1))          # la pieza queda DESPUÉS de la línea x = x0
    if x1 < rx1 and d.x + d.w >= x1 - 1:
        d.bordes_corte.append(("v", x1, +1))          # queda ANTES de la línea x = x1
    if y0 > ry0 and d.y <= y0 + 1:
        d.bordes_corte.append(("h", y0, -1))
    if y1 < ry1 and d.y + d.h >= y1 - 1:
        d.bordes_corte.append(("h", y1, +1))


def _puntos_en_linea(d, borde):
    """Intervalo [lo, hi] (a lo largo de la línea) de los puntos de la pieza a <= TOL_PX de ella."""
    eje, coord, _ = borde
    pts = np.asarray(d.geom, dtype=float)
    cerca = pts[np.abs(pts[:, 0 if eje == "v" else 1] - coord) <= TOL_PX]
    if len(cerca) == 0:
        return None
    t = cerca[:, 1 if eje == "v" else 0]
    return float(t.min()), float(t.max())


def _se_tocan(a, b, borde_a, borde_b):
    ia, ib = _puntos_en_linea(a, borde_a), _puntos_en_linea(b, borde_b)
    if ia is None or ib is None:
        return False
    return ia[0] - TOL_PX <= ib[1] and ib[0] - TOL_PX <= ia[1]


def _grupos(dets):
    """Union-find sobre las piezas que se tocan a ambos lados de un mismo borde."""
    padre = list(range(len(dets)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, a in enumerate(dets):
        for j in range(i + 1, len(dets)):
            b = dets[j]
            if (a.tipo == "piel_cocodrilo") != (b.tipo == "piel_cocodrilo"):
                continue
            for ba in a.bordes_corte:
                for bb in b.bordes_corte:
                    if ba[:2] == bb[:2] and ba[2] == -bb[2] and _se_tocan(a, b, ba, bb):
                        padre[raiz(i)] = raiz(j)
    grupos = {}
    for i in range(len(dets)):
        grupos.setdefault(raiz(i), []).append(dets[i])
    return list(grupos.values())


def _ponderado(piezas, atributo, peso):
    vals = [(getattr(d, atributo), getattr(d, peso)) for d in piezas if getattr(d, atributo) is not None]
    tot = sum(w for _, w in vals)
    return sum(v * w for v, w in vals) / tot if vals and tot > 0 else None


def _bordes_restantes(piezas):
    """Bordes que quedan abiertos: los que aparecen con un solo signo dentro del grupo."""
    todos = [b for d in piezas for b in d.bordes_corte]
    return [b for b in todos if (b[0], b[1], -b[2]) not in todos]


def _unir(piezas, p, eje):
    base = max(piezas, key=lambda d: d.longitud_m if d.tipo != "piel_cocodrilo" else d.area_m2)
    m = base.desplazada(0, 0)
    x0, y0 = min(d.x for d in piezas), min(d.y for d in piezas)
    x1, y1 = max(d.x + d.w for d in piezas), max(d.y + d.h for d in piezas)
    m.x, m.y, m.w, m.h = x0, y0, x1 - x0, y1 - y0
    m.longitud_m = round(sum(d.longitud_m for d in piezas), 3)
    m.area_m2 = round(sum(d.area_m2 for d in piezas), 5)
    m.bordes_corte = _bordes_restantes(piezas)
    adv = {d.advertencia for d in piezas if d.advertencia}
    m.advertencia = "; ".join(sorted(adv))
    if base.tipo == "piel_cocodrilo":
        _unir_cocodrilo(m, piezas)
    else:
        _unir_grieta(m, piezas, p, eje)
    return m


def _unir_cocodrilo(m, piezas):
    m.n_celdas = sum(d.n_celdas or 0 for d in piezas)
    m.celda_media_m2 = round(_ponderado(piezas, "celda_media_m2", "n_celdas") or 0.0, 4)
    m.densidad_pct = round(_ponderado(piezas, "densidad_pct", "area_m2") or 0.0, 1)
    pts = np.array([q for d in piezas for q in d.geom], dtype=np.int32)
    hull = cv2.convexHull(pts)[:, 0, :]
    m.geom, m.geom_tipo = [(int(a), int(b)) for a, b in hull], "poligono_aprox"   # envolvente convexa
    m.cx, m.cy = float(m.x + m.w / 2), float(m.y + m.h / 2)


def _unir_grieta(m, piezas, p, eje):
    ancho = _ponderado(piezas, "ancho_mm", "longitud_m")
    m.ancho_mm = None if ancho is None else round(ancho, 1)
    m.area_m2 = round(m.longitud_m * (m.ancho_mm or 0.0) / 1000.0, 5)
    m.contraste_weber = None if (w := _ponderado(piezas, "contraste_weber", "longitud_m")) is None else round(w, 3)
    m.ramificada = any(bool(d.ramificada) for d in piezas)
    m.severidad_prelim = severidad_grieta(m.ancho_mm, p.gsd_m, p)
    pts = np.array([q for d in piezas for q in d.geom], dtype=float)
    centro = pts.mean(0)
    _, evec = np.linalg.eigh(np.cov((pts - centro).T) + 1e-9 * np.eye(2))
    vx, vy = evec[:, 1]
    orden = np.argsort(pts[:, 0] * vx + pts[:, 1] * vy)
    idx = orden[np.linspace(0, len(orden) - 1, min(len(orden), MAX_PUNTOS_GEOM)).astype(int)]
    m.geom, m.geom_tipo = [(int(pts[i, 0]), int(pts[i, 1])) for i in idx], "polilinea_aprox"
    # centroide ponderado por longitud, y tipo según la orientación local del eje
    m.cx = float(_ponderado(piezas, "cx", "longitud_m"))
    m.cy = float(_ponderado(piezas, "cy", "longitud_m"))
    ang = math.degrees(math.atan2(vy, vx)) % 180.0
    ang_eje = float(eje.angulo_local_deg(m.cx, m.cy))
    m.angulo_img_deg, m.angulo_eje_deg = round(ang, 1), round(ang_eje, 1)
    m.desv_eje_deg = round(EjeVia.desviacion_deg(ang, ang_eje), 1)
    m.tipo = "longitudinal" if m.desv_eje_deg <= p.tol_orient_deg else "transversal"
    m.metodo_ancho = max(piezas, key=lambda d: d.longitud_m).metodo_ancho


def fusionar(detecciones, p, eje):
    """Devuelve las detecciones con las piezas cortadas por bordes de tesela ya unidas.

    Después aplica los mínimos de piel de cocodrilo (celdas y área) sobre las zonas COMPLETAS y
    limpia las marcas internas. Las piezas sin cortes pasan sin cambios."""
    aislada = [d for d in detecciones if d.tipo not in FUSIONABLES or not d.bordes_corte]
    cortadas = [d for d in detecciones if d.tipo in FUSIONABLES and d.bordes_corte]
    salida = list(aislada)
    for grupo in _grupos(cortadas):
        salida.append(grupo[0].desplazada(0, 0) if len(grupo) == 1 else _unir(grupo, p, eje))
    final = []
    for d in salida:
        d.bordes_corte = []
        if d.tipo == "piel_cocodrilo" and (d.n_celdas < p.celdas_min or d.area_m2 < p.zona_min_m2):
            continue
        final.append(d)
    return final
