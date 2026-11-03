"""
pipeline.py
===========
Orquesta el análisis de una región del ortomosaico (un ROI o el tramo completo) por TESELAS:

    para cada tesela: leer ventana con margen -> calidad -> detectar SOLO dentro del núcleo ->
    liberar la memoria de la ventana;  al final: fusionar las piezas cortadas por bordes de tesela

Solo se mantiene en memoria una ventana a la vez, de modo que el consumo no depende de la
longitud del ortomosaico (criterio: 100 000 x 2 000 px sin superar ~2 GB).

El método de detección es seleccionable: `METODOS` mapea un nombre a una función
    f(rgb, valido, params, eje, origen, nucleo=None) -> list[Deteccion]
`nucleo` = (x0, y0, x1, y1) en coordenadas de la ventana: solo debe medirse dentro de él.
'actual' (black-hat + MAD) está aquí; 'sun' se registrará desde sun.py (Fase 7).

El margen de contexto evita efectos de borde en el procesamiento (iluminación, black-hat), pero no
se mide en él: así las teselas no se solapan y no hay conteo doble. Las grietas y zonas de piel de
cocodrilo cortadas por un borde se unen después (fusion.py); los baches se asignan a la tesela de
su centroide. Límite: una grieta que casi roza el borde puede quedar con un fragmento < 15 cm
(grieta_long_min_m) que se descarta antes de poder unirse.
"""
import math

import cv2
import numpy as np

from app.nucleo.baches import detectar_baches
from app.nucleo.calidad import AcumuladorCalidad, consolidar, mascara_valida
from app.nucleo.cocodrilo import detectar_piel_cocodrilo
from app.nucleo.eje_via import EjeVia
from app.nucleo.estructuras import AnalisisCancelado, ResultadoAnalisis
from app.nucleo.fusion import fusionar, marcar_bordes
from app.nucleo.grietas import analizar_grietas, segmentar_grietas
from app.nucleo.parametros import Params
from app.nucleo.preprocesado import preprocesar


def _metodo_actual(rgb, valido, p, eje, origen, nucleo=None):
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gris_norm = preprocesar(gris, valido, p)
    previa, cerrada, esq = segmentar_grietas(gris_norm, valido, p.gsd_m, p)
    cocodrilo, zona = detectar_piel_cocodrilo(cerrada, esq, p.gsd_m, p, origen, nucleo)
    if nucleo is not None:                       # el esqueleto se recorta al núcleo (sin solapes)
        recorte = np.zeros(esq.shape, bool)
        recorte[nucleo[1]:nucleo[3], nucleo[0]:nucleo[2]] = True
        esq = esq & recorte
    lineales = analizar_grietas(esq, previa, cerrada, zona, gris, gris_norm, p.gsd_m, p, eje, origen)
    baches = detectar_baches(rgb, valido, p.gsd_m, p, origen)
    return lineales + cocodrilo + baches


METODOS = {"actual": _metodo_actual}


def registrar_metodo(nombre, funcion):
    """Permite que otros módulos (sun.py) agreguen un método de detección seleccionable."""
    METODOS[nombre] = funcion


def analizar_ventana(rgb, valido, p: Params, eje: EjeVia, origen=(0, 0), metodo="actual", nucleo=None):
    """Detecta en UNA ventana ya cargada. `origen` = esquina (x, y) de la ventana en el ortomosaico;
    `nucleo` = rectángulo (x0,y0,x1,y1) de la ventana donde se mide (por defecto, toda)."""
    if metodo not in METODOS:
        raise ValueError(f"Método de detección desconocido o aún no disponible: '{metodo}'. "
                         f"Disponibles: {', '.join(sorted(METODOS))}")
    return METODOS[metodo](rgb, valido, p, eje, origen, nucleo)


def _recortar_region(region, lector):
    x0, y0, x1, y1 = (int(round(v)) for v in region)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(lector.ancho, x1), min(lector.alto, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ValueError(f"La región {region} es demasiado pequeña o queda fuera del ortomosaico "
                         f"({lector.ancho}x{lector.alto} px)")
    return x0, y0, x1, y1


def analizar_region(lector, region, p: Params, eje: EjeVia = None, margen_m=1.0, tesela_px=1600,
                    metodo="actual", mascara_via=None, cancelar=None, progreso=None):
    """Analiza `region` = (x0, y0, x1, y1) en píxeles del ortomosaico y devuelve un ResultadoAnalisis.

    cancelar: threading.Event; si se activa, lanza AnalisisCancelado entre teselas.
    progreso: función f(fraccion 0-1, texto) llamada tras cada tesela."""
    if metodo not in METODOS:
        raise ValueError(f"Método de detección desconocido o aún no disponible: '{metodo}'. "
                         f"Disponibles: {', '.join(sorted(METODOS))}")
    p.validar()
    margen = int(math.ceil(margen_m / p.gsd_m))
    minimo = max(512, 2 * margen)
    if tesela_px < minimo:
        raise ValueError(f"tesela_px = {tesela_px} es demasiado pequeña: debe ser al menos {minimo} px "
                         f"(el doble del margen de contexto de {margen_m} m)")
    rx0, ry0, rx1, ry1 = _recortar_region(region, lector)
    advertencias = []
    if lector.gsd_cm and abs(lector.gsd_cm - p.gsd_cm) / p.gsd_cm > 0.02:
        advertencias.append(f"el ortomosaico indica {lector.gsd_cm:.3f} cm/px pero Params.gsd_cm = {p.gsd_cm}; "
                            f"se usa Params.gsd_cm")
    if eje is None:
        eje = EjeVia.recto(0.0, lector.ancho, lector.alto, p.gsd_m, ventana_m=p.eje_ventana_m)
        advertencias.append("no se indicó eje de vía: se asumió horizontal (0°); en vías con curvas "
                            "la clasificación longitudinal/transversal no es confiable")
    xs = list(range(rx0, rx1, tesela_px))
    ys = list(range(ry0, ry1, tesela_px))
    total = len(xs) * len(ys)
    acum, detecciones, hechas = AcumuladorCalidad(), [], 0

    for ty in ys:
        for tx in xs:
            if cancelar is not None and cancelar.is_set():
                raise AnalisisCancelado("Análisis cancelado por el usuario")
            tx1, ty1 = min(tx + tesela_px, rx1), min(ty + tesela_px, ry1)
            wx0, wy0 = max(0, tx - margen), max(0, ty - margen)
            wx1, wy1 = min(lector.ancho, tx1 + margen), min(lector.alto, ty1 + margen)
            rgb, nodata = lector.leer(wx0, wy0, wx1, wy1)
            via = None
            if mascara_via is not None:
                via = mascara_via.leer(wx0, wy0, wx1, wy1)[0][..., 0] > 127
            valido, nodata_m = mascara_valida(rgb, p, nodata, via)
            cy0, cx0 = ty - wy0, tx - wx0                        # núcleo dentro de la ventana
            sl = (slice(cy0, cy0 + (ty1 - ty)), slice(cx0, cx0 + (tx1 - tx)))
            acum.agregar(rgb[sl], valido[sl], nodata_m[sl])
            if valido.sum() >= 100:
                nucleo = (cx0, cy0, cx0 + (tx1 - tx), cy0 + (ty1 - ty))
                for d in analizar_ventana(rgb, valido, p, eje, (wx0, wy0), metodo, nucleo):
                    if tx <= d.cx < tx1 and ty <= d.cy < ty1:
                        marcar_bordes(d, (tx, ty, tx1, ty1), (rx0, ry0, rx1, ry1))
                        detecciones.append(d)
            del rgb, nodata, valido, nodata_m, via
            hechas += 1
            if progreso is not None:
                progreso(hechas / total, f"tesela {hechas}/{total}")

    detecciones = fusionar(detecciones, p, eje)
    _completar_posicion(detecciones, eje, p)
    return ResultadoAnalisis(detecciones=detecciones, calidad=consolidar(acum, p),
                             region=(rx0, ry0, rx1, ry1), n_teselas=total, params_huella=p.huella(),
                             metodo=metodo, advertencias=advertencias)


def _completar_posicion(detecciones, eje, p):
    """Asigna progresiva (m), lado de la vía y área en píxeles a cada detección."""
    for d in detecciones:
        d.area_px = int(round(d.area_m2 / p.gsd_m ** 2))
        d.progresiva_m = round(eje.progresiva_m(d.cx, d.cy), 2)
        d.lado_via = eje.lado_via(d.cx, d.cy)
