"""
logica_roi.py
=============
ROI (regiones de interés) de un tramo: CRUD, progresivas automáticas desde el eje, reparto
calibración / prueba y detección de solapes.

El motor analiza el RECTÁNGULO de la ROI (x0, y0, x1, y1). Si se guarda un polígono (p. ej. importado de
QGIS) se conserva para trazabilidad, pero el análisis usa su rectángulo envolvente.
"""
import math
import random
from collections import defaultdict

from sqlalchemy import select

from app import basedatos
from app.logica_comun import Campo, ErrorValidacion, esquema, obtener, validar
from app.logica_tramos import _resolver
from app.modelos import NIVELES_SEVERIDAD, ORIGENES_ROI, ROI, ROLES_ROI, CatalogoPatologia, EjeVia
from app.nucleo import eje_via as _eje
from app.nucleo.estructuras import TIPOS

TIPOS_ROI = TIPOS + ("sano",)
LADO_MIN_PX = 8                    # el pipeline rechaza regiones menores

CAMPOS_ROI = (
    Campo("codigo", "Código de la ROI", requerido=True),
    Campo("tipo_campo", "Tipo (campo)", "opcion", opciones=TIPOS_ROI),
    Campo("patologia_codigo", "Código de patología (Ficha 2)"),
    Campo("severidad_campo", "Severidad (capa GIS)", "opcion", opciones=NIVELES_SEVERIDAD),
    Campo("x0", "X inicial", "entero", requerido=True), Campo("y0", "Y inicial", "entero", requerido=True),
    Campo("x1", "X final", "entero", requerido=True), Campo("y1", "Y final", "entero", requerido=True),
    Campo("progresiva_ini_m", "Progresiva inicial", "real"), Campo("progresiva_fin_m", "Progresiva final", "real"),
    Campo("rol", "Rol", "opcion", opciones=ROLES_ROI),
    Campo("origen", "Origen", "opcion", opciones=ORIGENES_ROI),
    Campo("observaciones", "Observaciones"),
)
_CLAVES_EXTRA = ("poligono_px", "poligono_geo")


def esquema_roi():
    return esquema(CAMPOS_ROI)


def area_m2(roi, gsd_cm):
    """Área del rectángulo de la ROI (m²)."""
    return (roi["x1"] - roi["x0"]) * (roi["y1"] - roi["y0"]) * (gsd_cm / 100.0) ** 2


def _progresivas(s, tramo, x0, y0, x1, y1):
    e = s.scalar(select(EjeVia).where(EjeVia.tramo_id == tramo.id).order_by(EjeVia.id.desc()).limit(1))
    if e is None:
        return None, None
    eje = _eje.EjeVia(e.vertices_px, (tramo.gsd_cm or 0.5) / 100.0, e.progresiva_inicial_m)
    p = eje.progresiva_m([x0, x1, x0, x1], [y0, y0, y1, y1])
    return round(float(min(p)), 2), round(float(max(p)), 2)


def _crear_roi(s, tramo, datos):
    """Crea la ROI en la sesión `s`. Devuelve (modelo, advertencias). Lo usan los importadores."""
    extra = {k: datos[k] for k in _CLAVES_EXTRA if datos.get(k) is not None}
    d = validar({k: v for k, v in datos.items() if k not in _CLAVES_EXTRA}, CAMPOS_ROI)
    adv = []
    cat = None
    if d["patologia_codigo"]:
        cat = s.scalar(select(CatalogoPatologia).where(CatalogoPatologia.codigo == d["patologia_codigo"].upper()))
        if cat is None:
            raise ErrorValidacion({"patologia_codigo": f"'{d['patologia_codigo']}' no está en el catálogo (Ficha 2)"})
        d["patologia_codigo"] = cat.codigo
    if d["tipo_campo"] is None:
        if cat is not None and cat.tipo_motor:
            d["tipo_campo"] = cat.tipo_motor
        else:
            raise ErrorValidacion({"tipo_campo": "es obligatorio (o indique un código de patología con equivalencia "
                                                 "en el motor)"})
    elif cat is not None and cat.tipo_motor and cat.tipo_motor != d["tipo_campo"]:
        adv.append(f"el código {cat.codigo} equivale a '{cat.tipo_motor}' pero el tipo indicado es '{d['tipo_campo']}'")
    if s.scalar(select(ROI.id).where(ROI.tramo_id == tramo.id, ROI.codigo == d["codigo"])):
        raise ErrorValidacion({"codigo": f"ya existe la ROI '{d['codigo']}' en este tramo"})
    x0, y0, x1, y1 = d["x0"], d["y0"], d["x1"], d["y1"]
    if tramo.ancho_px:
        cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(tramo.ancho_px, x1), min(tramo.alto_px, y1)
        if (cx0, cy0, cx1, cy1) != (x0, y0, x1, y1):
            if cx1 - cx0 < LADO_MIN_PX or cy1 - cy0 < LADO_MIN_PX:
                raise ErrorValidacion({"x0": f"la ROI queda fuera del ortomosaico ({tramo.ancho_px}x{tramo.alto_px} px)"})
            adv.append(f"la ROI sobrepasa el ortomosaico y se recortó a ({cx0}, {cy0}, {cx1}, {cy1})")
            x0, y0, x1, y1 = cx0, cy0, cx1, cy1
    if x1 - x0 < LADO_MIN_PX or y1 - y0 < LADO_MIN_PX:
        raise ErrorValidacion({"x1": f"la ROI debe medir al menos {LADO_MIN_PX} px por lado"})
    d.update(x0=x0, y0=y0, x1=x1, y1=y1)
    if d["progresiva_ini_m"] is None and d["progresiva_fin_m"] is None:
        d["progresiva_ini_m"], d["progresiva_fin_m"] = _progresivas(s, tramo, x0, y0, x1, y1)
    d["rol"] = d["rol"] or "sin_asignar"
    d["origen"] = d["origen"] or "manual"
    r = ROI(tramo_id=tramo.id, **d, **extra)
    s.add(r)
    s.flush()
    return r, adv


def crear_roi(tramo, datos):
    with basedatos.nueva_sesion() as s:
        r, adv = _crear_roi(s, _resolver(s, tramo), datos)
        return {**r.a_dict(), "advertencias": adv}


def _actualizar_roi(s, r, cambios):
    """Actualiza la ROI `r` en la sesión `s` (la usan los importadores). Devuelve dict."""
    ext = {k: cambios[k] for k in _CLAVES_EXTRA if k in cambios}
    d = validar({k: v for k, v in cambios.items() if k not in _CLAVES_EXTRA}, CAMPOS_ROI, parcial=True)
    t = r.tramo
    if "codigo" in d and d["codigo"] != r.codigo and s.scalar(
            select(ROI.id).where(ROI.tramo_id == t.id, ROI.codigo == d["codigo"])):
        raise ErrorValidacion({"codigo": f"ya existe la ROI '{d['codigo']}' en este tramo"})
    if "patologia_codigo" in d and d["patologia_codigo"]:
        if s.scalar(select(CatalogoPatologia.id).where(CatalogoPatologia.codigo == d["patologia_codigo"].upper())) is None:
            raise ErrorValidacion({"patologia_codigo": "no está en el catálogo (Ficha 2)"})
        d["patologia_codigo"] = d["patologia_codigo"].upper()
    for k in ("tipo_campo", "rol", "origen"):
        if k in d and d[k] is None:
            raise ErrorValidacion({k: "no puede quedar vacío"})
    reg = [d.get(k, getattr(r, k)) for k in ("x0", "y0", "x1", "y1")]
    if any(v is None for v in reg) or reg[2] - reg[0] < LADO_MIN_PX or reg[3] - reg[1] < LADO_MIN_PX:
        raise ErrorValidacion({"x1": f"la ROI debe medir al menos {LADO_MIN_PX} px por lado"})
    if t.ancho_px and (reg[0] < 0 or reg[1] < 0 or reg[2] > t.ancho_px or reg[3] > t.alto_px):
        raise ErrorValidacion({"x0": f"la ROI debe quedar dentro del ortomosaico ({t.ancho_px}x{t.alto_px} px)"})
    cambia_region = any(k in d for k in ("x0", "y0", "x1", "y1"))
    for k, v in {**d, **ext}.items():
        setattr(r, k, v)
    if cambia_region and "progresiva_ini_m" not in d and "progresiva_fin_m" not in d:
        r.progresiva_ini_m, r.progresiva_fin_m = _progresivas(s, t, *r.region)
    s.flush()
    return r.a_dict()




def actualizar_roi(roi_id, cambios):
    with basedatos.nueva_sesion() as s:
        return _actualizar_roi(s, obtener(s, ROI, roi_id, "ROI"), cambios)


def obtener_roi(roi_id):
    with basedatos.nueva_sesion() as s:
        return obtener(s, ROI, roi_id, "ROI").a_dict()


def listar_rois(tramo, rol=None, tipo=None):
    with basedatos.nueva_sesion() as s:
        q = select(ROI).where(ROI.tramo_id == _resolver(s, tramo).id).order_by(ROI.codigo)
        if rol:
            q = q.where(ROI.rol == rol)
        if tipo:
            q = q.where(ROI.tipo_campo == tipo)
        return [r.a_dict() for r in s.scalars(q)]


def eliminar_roi(roi_id):
    with basedatos.nueva_sesion() as s:
        s.delete(obtener(s, ROI, roi_id, "ROI"))


def cambiar_rol(roi_id, rol):
    if rol not in ROLES_ROI:
        raise ErrorValidacion({"rol": f"use uno de: {', '.join(ROLES_ROI)}"})
    with basedatos.nueva_sesion() as s:
        r = obtener(s, ROI, roi_id, "ROI")
        r.rol = rol
        return r.a_dict()


# ------------------------------------------------------------------------------------ solapes y reparto
def _interseccion(a, b):
    w = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    h = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    return max(0, w) * max(0, h)


def rois_solapados(tramo, solo_calibracion_vs_prueba=False):
    """Pares de ROI cuyos rectángulos se intersectan. Un solape entre una ROI de calibración y una de
    prueba invalida la validación (los datos de prueba influyeron en la calibración)."""
    rois = listar_rois(tramo)
    out = []
    for i, a in enumerate(rois):
        for b in rois[i + 1:]:
            if solo_calibracion_vs_prueba and {a["rol"], b["rol"]} != {"calibracion", "prueba"}:
                continue
            ar = _interseccion(a, b)
            if ar > 0:
                menor = min((a["x1"] - a["x0"]) * (a["y1"] - a["y0"]), (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))
                out.append({"a": a["codigo"], "b": b["codigo"], "area_px": ar, "fraccion_menor": ar / menor,
                            "roles": (a["rol"], b["rol"])})
    return out


def asignar_roles(tramo, proporcion_calibracion=0.5, semilla=42, reasignar=False):
    """Reparto ESTRATIFICADO (por tipo_campo) y reproducible en calibración / prueba.

    Solo toca ROI 'sin_asignar' salvo reasignar=True. Con un solo ROI de un tipo, va a 'prueba'
    (no hay con qué calibrarlo) y se advierte. Devuelve conteos por tipo y advertencias."""
    if not 0 < proporcion_calibracion < 1:
        raise ErrorValidacion({"proporcion_calibracion": "debe estar entre 0 y 1 (exclusivo)"})
    adv = []
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        rois = list(s.scalars(select(ROI).where(ROI.tramo_id == t.id).order_by(ROI.codigo)))
        grupos = defaultdict(list)
        for r in rois:
            if reasignar or r.rol == "sin_asignar":
                grupos[r.tipo_campo].append(r)
        resumen = {}
        for tipo, lista in sorted(grupos.items()):
            n = len(lista)
            random.Random(f"{semilla}:{tipo}").shuffle(lista)
            ncal = 0 if n == 1 else min(n - 1, max(1, round(n * proporcion_calibracion)))
            if n == 1:
                adv.append(f"solo hay 1 ROI de tipo '{tipo}': se asigna a prueba y no habrá calibración para ese tipo")
            for k, r in enumerate(lista):
                r.rol = "calibracion" if k < ncal else "prueba"
            resumen[tipo] = {"calibracion": ncal, "prueba": n - ncal}
        s.flush()
    sol = rois_solapados(tramo, solo_calibracion_vs_prueba=True)
    for p in sol:
        adv.append(f"las ROI {p['a']} y {p['b']} se solapan ({p['fraccion_menor']:.0%} de la menor) y están en "
                   f"calibración y prueba: la validación quedaría contaminada")
    return {"semilla": semilla, "por_tipo": resumen, "advertencias": adv}
