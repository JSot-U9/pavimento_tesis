"""
calidad.py
==========
Máscara de calzada válida y evaluación de la calidad de imagen (Ficha 5 / tesis, indicador
'Calidad de imagen: adecuada / no adecuada', 'Resolución espacial' y 'Cobertura del tramo').

La calidad se acumula tesela a tesela (nunca sobre el ortomosaico completo) y se consolida al final:
  - nitidez  = mediana de la varianza del Laplaciano de cada tesela
  - brillo   = media sobre la calzada válida
  - saturación = fracción de píxeles <=5 o >=250
Los umbrales vienen de Params y son PROVISIONALES (calibrados con sintéticos).
"""
from dataclasses import dataclass, field
from typing import List

import cv2
import numpy as np

from app.nucleo.estructuras import Calidad

MAX_LADO_NITIDEZ = 2000          # recorte central máximo para medir la nitidez de cada tesela


def mascara_valida(rgb, p, nodata_ext=None, mascara_via=None):
    """Devuelve (valido, nodata): calzada utilizable (sin NoData, sin vegetación, dentro de la máscara)."""
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    nodata = (r == 0) & (g == 0) & (b == 0)
    nodata = cv2.morphologyEx(nodata.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)
    if nodata_ext is not None:
        nodata |= nodata_ext
    veg = (2 * g - r - b) > p.exg_veg
    veg = cv2.morphologyEx(veg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    valido = ~nodata & ~veg
    if mascara_via is not None:
        valido &= mascara_via
    return valido, nodata


@dataclass
class AcumuladorCalidad:
    n_total: int = 0
    n_nodata: int = 0
    n_valido: int = 0
    suma_brillo: float = 0.0
    n_saturado: int = 0
    nitidez: List[float] = field(default_factory=list)

    def agregar(self, rgb, valido, nodata):
        """Suma las métricas de una tesela (pasar solo su parte central, sin el margen de contexto)."""
        gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        self.n_total += gris.size
        self.n_nodata += int(nodata.sum())
        nv = int(valido.sum())
        self.n_valido += nv
        if nv == 0:
            return
        gv = gris[valido]
        self.suma_brillo += float(gv.sum())
        self.n_saturado += int(((gv <= 5) | (gv >= 250)).sum())
        h, w = gris.shape
        hh, ww = min(h, MAX_LADO_NITIDEZ) // 2, min(w, MAX_LADO_NITIDEZ) // 2
        cy, cx = h // 2, w // 2
        sub = gris[cy - hh:cy + hh, cx - ww:cx + ww]
        vs = valido[cy - hh:cy + hh, cx - ww:cx + ww]
        if vs.sum() > 100:
            self.nitidez.append(float(cv2.Laplacian(sub, cv2.CV_64F)[vs].var()))


def consolidar(acum, p) -> Calidad:
    """Convierte el acumulado en un informe de calidad según los umbrales de Params."""
    nitidez = float(np.median(acum.nitidez)) if acum.nitidez else 0.0
    brillo = acum.suma_brillo / acum.n_valido if acum.n_valido else 0.0
    sat = acum.n_saturado / acum.n_valido if acum.n_valido else 1.0
    cobertura = 100.0 * (1.0 - acum.n_nodata / acum.n_total) if acum.n_total else 0.0
    util = 100.0 * acum.n_valido / acum.n_total if acum.n_total else 0.0
    adv = []
    if acum.n_valido == 0:
        adv.append("no hay calzada analizable en la región (todo NoData o vegetación)")
    if nitidez < p.nitidez_min:
        adv.append("imagen poco nítida")
    if not (p.brillo_min <= brillo <= p.brillo_max):
        adv.append("brillo fuera de rango")
    if sat > p.saturados_max:
        adv.append("exceso de píxeles saturados")
    if p.gsd_cm > 0.5:
        adv.append("GSD > 5 mm/px: grietas finas (< 10 mm) pueden no resolverse")
    fallas = {"imagen poco nítida", "brillo fuera de rango", "exceso de píxeles saturados"}
    adecuada = acum.n_valido > 0 and not (fallas & set(adv))
    return Calidad(calidad="Adecuada" if adecuada else "No adecuada", nitidez=round(nitidez, 2),
                   brillo_medio=round(brillo, 1), fraccion_saturada=round(sat, 4),
                   resolucion_cm_px=p.gsd_cm, cobertura_pct=round(cobertura, 2),
                   calzada_util_pct=round(util, 2), advertencias=adv)
