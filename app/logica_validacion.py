"""
logica_validacion.py
====================
Validación de las detecciones de una (o varias) ejecuciones contra la referencia de campo.

UNIDAD DE ANÁLISIS = (ROI, tipo). Para cada ROI de prueba y cada uno de los 4 tipos del motor se asigna
EXACTAMENTE UNA de las cuatro celdas (vp + fp + fn + vn = 1):

              referencia de campo: el tipo SÍ está     el tipo NO está
  detectado          VP                                     FP
  no detectado       FN                                     VN

Referencia de campo (método principal, "presencia por ROI"):
  * `ROI.tipo_campo` = tipo presente en la ROI ('sano' = ningún tipo presente).
  * `Patologia.presencia` (Ficha 2/3): una patología de la ROI cuyo código equivale (catálogo `tipo_motor`)
    al tipo y que tenga presencia=True añade ese tipo a los presentes; si TODAS las patologías de ese tipo
    en la ROI dicen presencia=False, el tipo se considera ausente aunque `tipo_campo` lo nombre.
    (SUPUESTO: la ficha manda sobre el campo `tipo_campo` de la capa GIS.)
  * Severidad oficial: `Severidad` vía `logica_fichas.severidades_roi` (se usa en logica_estadistica).

Si la ROI tiene `GeometriaReferencia` (línea/polígono digitalizado del deterioro) y el tipo evaluado es su
`tipo_campo`, se valida por SOLAPE: se rasterizan la referencia y las detecciones de ese tipo (con una
tolerancia de `tolerancia_m` alrededor de las líneas) y se calcula el coeficiente de Dice. Dice >= umbral → VP;
si no, FN (la referencia no fue encontrada con el solape exigido; SUPUESTO: una detección mal ubicada no
suma además un FP, para que cada unidad siga contando una sola vez). Sin geometría: rectángulo de la ROI,
presencia por ROI.

Solo las ROI de rol 'prueba' cuentan para la validación final (y solo ellas se guardan en `Validacion`).
Las de 'calibracion' pueden evaluarse (`guardar=False`) únicamente para calibrar. Si alguna ROI de
calibración se solapa con una de prueba, la validación se BLOQUEA (o solo advierte con
`solapes='advertir'`): los píxeles de prueba habrían influido en la calibración.

Casos límite: ROI sin detecciones (todo VN/FN según la referencia), ROI 'sano' (solo VN/FP), ROI sin
ejecución que la cubra (se omite y se avisa), solape no calculable (None, nunca 0).
Todo resultado de una ejecución con parámetros provisionales lleva `provisional=True`.
"""
import math

import cv2
import numpy as np
from sqlalchemy import delete, select

from app import basedatos, logica_configuracion as cfg, logica_roi
from app.logica_comun import Campo, ErrorNoEncontrado, ErrorValidacion, esquema, obtener, validar
from app.modelos import (CatalogoPatologia, Deteccion, EjecucionAnalisis, GeometriaReferencia, ROI, Patologia,
                         Validacion)
from app.nucleo.estructuras import TIPOS

MODOS = ("auto", "presencia")
MAX_LADO_RASTER = 1500                   # px máximos por lado de la máscara de solape


# ===================================================================================== geometría de referencia
def _puntos(puntos):
    try:
        arr = np.asarray(puntos, dtype=float)
    except (TypeError, ValueError):
        raise ErrorValidacion({"puntos_px": "debe ser una lista de pares [x, y] numéricos"}) from None
    if arr.ndim != 2 or arr.shape[1] != 2 or not np.isfinite(arr).all():
        raise ErrorValidacion({"puntos_px": "debe ser una lista de pares [x, y] numéricos y finitos"})
    return arr


def registrar_geometria_referencia(roi_id, tipo, puntos_px, origen="manual"):
    """Guarda una línea ('linea', >= 2 puntos) o un polígono ('poligono', >= 3) digitalizado dentro de la ROI
    (píxeles del ortomosaico). Puede haber varias por ROI; todas forman la referencia del `tipo_campo`."""
    if tipo not in ("linea", "poligono"):
        raise ErrorValidacion({"tipo": "use 'linea' o 'poligono'"})
    arr = _puntos(puntos_px)
    minimo = 2 if tipo == "linea" else 3
    if len(arr) < minimo:
        raise ErrorValidacion({"puntos_px": f"una {tipo} necesita al menos {minimo} puntos"})
    with basedatos.nueva_sesion() as s:
        r = obtener(s, ROI, roi_id, "ROI")
        adv = []
        dentro = (arr[:, 0] >= r.x0) & (arr[:, 0] <= r.x1) & (arr[:, 1] >= r.y0) & (arr[:, 1] <= r.y1)
        if not dentro.all():
            adv.append(f"{int((~dentro).sum())} punto(s) quedan fuera de la ROI; solo se compara lo que cae dentro")
        g = GeometriaReferencia(roi_id=roi_id, tipo=tipo, puntos_px=arr.tolist(), origen=origen)
        s.add(g)
        s.flush()
        return {**g.a_dict(), "advertencias": adv}


def listar_geometrias_referencia(roi_id):
    with basedatos.nueva_sesion() as s:
        return [g.a_dict() for g in s.scalars(
            select(GeometriaReferencia).where(GeometriaReferencia.roi_id == roi_id).order_by(GeometriaReferencia.id))]


def eliminar_geometria_referencia(geometria_id):
    with basedatos.nueva_sesion() as s:
        s.delete(obtener(s, GeometriaReferencia, geometria_id, "geometría de referencia"))


# ===================================================================================== referencia de campo
def tipos_presentes(roi, patologias):
    """Conjunto de tipos del motor presentes en la ROI según la referencia de campo.
    `roi` = dict con `tipo_campo`; `patologias` = [{'tipo_motor', 'presencia'}] de las fichas de esa ROI."""
    por_tipo = {}
    for p in patologias:
        if p.get("tipo_motor") in TIPOS:
            por_tipo.setdefault(p["tipo_motor"], []).append(bool(p["presencia"]))
    presentes = set()
    if roi["tipo_campo"] in TIPOS:
        presentes.add(roi["tipo_campo"])
    for t, marcas in por_tipo.items():
        if any(marcas):
            presentes.add(t)
        elif t in presentes:                      # todas las fichas del tipo dicen «no hay»
            presentes.discard(t)
    return presentes


# ===================================================================================== solape por máscaras
def _mascara(formas, region, escala, tol_px):
    """Máscara booleana (en la región de la ROI, reducida por `escala`) de una lista de formas
    [('linea'|'poligono', puntos)]. Las líneas se engrosan `tol_px` a cada lado (tolerancia)."""
    x0, y0, x1, y1 = region
    w, h = max(1, int(math.ceil((x1 - x0) * escala))), max(1, int(math.ceil((y1 - y0) * escala)))
    m = np.zeros((h, w), np.uint8)
    grosor = max(1, int(round(2 * tol_px * escala)) + 1)
    for tipo, pts in formas:
        p = (np.asarray(pts, float) - [x0, y0]) * escala
        p = np.round(p).astype(np.int32).reshape(-1, 1, 2)
        if len(p) == 0:
            continue
        if tipo == "poligono" and len(p) >= 3:
            cv2.fillPoly(m, [p], 1)
            if grosor > 1:
                cv2.polylines(m, [p], True, 1, grosor)
        else:
            cv2.polylines(m, [p], False, 1, grosor) if len(p) > 1 else cv2.circle(m, tuple(p[0, 0]), grosor // 2, 1, -1)
    return m.astype(bool)


def solape_dice(ref_formas, det_formas, region, tolerancia_px):
    """Coeficiente de Dice (0-1) entre la referencia y las detecciones dentro de `region`.
    None si ambas máscaras están vacías (no hay nada que comparar)."""
    x0, y0, x1, y1 = region
    escala = min(1.0, MAX_LADO_RASTER / max(x1 - x0, y1 - y0, 1))
    a = _mascara(ref_formas, region, escala, tolerancia_px)
    b = _mascara(det_formas, region, escala, tolerancia_px)
    s = int(a.sum()) + int(b.sum())
    if s == 0:
        return None
    return float(2.0 * np.logical_and(a, b).sum() / s)


def _forma_deteccion(d):
    g = d.get("geom_px") or []
    if len(g) < 2:
        return None
    return ("poligono" if (d.get("geom_tipo") or "").startswith("poligono") else "linea", g)


# ===================================================================================== núcleo puro
def clasificar_unidad(ref_presente, n_detecciones, solape=None, umbral=0.30):
    """(vp, fp, fn, vn) de UNA unidad (ROI, tipo). `solape` solo se usa si hay referencia geométrica
    (ref_presente y solape no None): con solape < umbral, la referencia cuenta como no encontrada (FN)."""
    detectada = n_detecciones > 0
    if ref_presente:
        if solape is not None:
            return (1, 0, 0, 0) if (detectada and solape >= umbral) else (0, 0, 1, 0)
        return (1, 0, 0, 0) if detectada else (0, 0, 1, 0)
    return (0, 1, 0, 0) if detectada else (0, 0, 0, 1)


def evaluar_roi(roi, tipos_ref, detecciones, geometrias, umbral, tolerancia_px, modo="auto"):
    """Filas (una por tipo) de una ROI. `detecciones` = dicts de la ejecución en esa ROI;
    `geometrias` = GeometriaReferencia de la ROI (dicts)."""
    region = (roi["x0"], roi["y0"], roi["x1"], roi["y1"])
    filas = []
    for tipo in TIPOS:
        dets = [d for d in detecciones if d["tipo"] == tipo]
        ref = tipo in tipos_ref
        geoms = [g for g in geometrias if tipo == roi["tipo_campo"]] if (modo == "auto" and ref) else []
        solape, m = None, "presencia"
        if geoms:
            ref_f = [(g["tipo"], g["puntos_px"]) for g in geoms]
            det_f = [f for f in map(_forma_deteccion, dets) if f is not None]
            solape = solape_dice(ref_f, det_f, region, tolerancia_px)
            m = "geometria"
        vp, fp, fn, vn = clasificar_unidad(ref, len(dets), solape, umbral)
        filas.append({"roi_id": roi["id"], "roi_codigo": roi["codigo"], "rol": roi["rol"], "tipo": tipo,
                      "ref_presente": ref, "n_detecciones": len(dets), "vp": vp, "fp": fp, "fn": fn, "vn": vn,
                      "solape": None if solape is None else round(solape, 4), "modo": m})
    return filas


def totales_por_tipo(filas):
    out = {t: {"vp": 0, "fp": 0, "fn": 0, "vn": 0, "n": 0} for t in TIPOS}
    for f in filas:
        o = out[f["tipo"]]
        for k in ("vp", "fp", "fn", "vn"):
            o[k] += int(f[k])
        o["n"] += 1
    return out


# ===================================================================================== carga desde BD
def _cubre(e, roi):
    if e["alcance"] == "roi":
        return e["roi_id"] == roi["id"]
    return e["x0"] <= roi["x0"] and e["y0"] <= roi["y0"] and e["x1"] >= roi["x1"] and e["y1"] >= roi["y1"]


def _comprobar_solapes(tramo, politica, adv):
    pares = logica_roi.rois_solapados(tramo, solo_calibracion_vs_prueba=True)
    if not pares:
        return []
    detalle = "; ".join(f"{p['a']}↔{p['b']} ({100 * p['fraccion_menor']:.0f} % de la menor)" for p in pares)
    if politica == "bloquear":
        raise ErrorValidacion({"rois": "hay ROI de calibración solapadas con ROI de prueba (" + detalle + "). Los píxeles "
                               "de prueba habrían influido en la calibración: corrija los rectángulos o los roles, o "
                               "use solapes='advertir' bajo su responsabilidad."})
    adv.append("ADVERTENCIA: ROI de calibración solapadas con ROI de prueba (" + detalle + "); la validación "
               "NO es independiente de la calibración.")
    return pares


def cargar_referencia(roi_ids):
    """{roi_id: {'tipos': set, 'geometrias': [...]}} desde la BD."""
    out = {}
    with basedatos.nueva_sesion() as s:
        for rid in roi_ids:
            roi = obtener(s, ROI, rid, "ROI").a_dict()
            pats = [{"tipo_motor": tm, "presencia": p.presencia}
                    for p, tm in s.execute(select(Patologia, CatalogoPatologia.tipo_motor)
                                           .join(CatalogoPatologia, CatalogoPatologia.codigo == Patologia.codigo)
                                           .where(Patologia.roi_id == rid))]
            geoms = [g.a_dict() for g in s.scalars(select(GeometriaReferencia).where(GeometriaReferencia.roi_id == rid))]
            out[rid] = {"tipos": tipos_presentes(roi, pats), "geometrias": geoms}
    return out


def evaluar(tramo, ejecucion_ids=None, rol="prueba", metodo="actual", umbral_solape=None, tolerancia_m=None,
            modo="auto", solapes="bloquear", guardar=None):
    """Evalúa las ROI de `rol` del tramo contra la referencia de campo.

    ejecucion_ids : ejecuciones a usar (id o lista). None = la última 'completada' del `metodo` que cubra cada ROI.
    rol           : 'prueba' (validación final; se guarda) o 'calibracion' (solo cálculo, para calibrar).
    guardar       : por defecto True para 'prueba' y False para 'calibracion'. Guardar 'calibracion' es un error.
    Guardar es idempotente: reemplaza las filas previas de (ejecución, ROI).
    Devuelve dict: filas, totales por tipo, provisional, advertencias, sin_ejecucion, ejecuciones."""
    if rol not in ("prueba", "calibracion"):
        raise ErrorValidacion({"rol": "use 'prueba' o 'calibracion'"})
    if modo not in MODOS:
        raise ErrorValidacion({"modo": f"use uno de: {', '.join(MODOS)}"})
    if solapes not in ("bloquear", "advertir"):
        raise ErrorValidacion({"solapes": "use 'bloquear' o 'advertir'"})
    guardar = (rol == "prueba") if guardar is None else bool(guardar)
    if guardar and rol != "prueba":
        raise ErrorValidacion({"guardar": "solo las ROI de prueba cuentan para la validación final; las de "
                                          "calibración no se guardan en Validacion"})
    umbral = float(cfg.obtener("umbral_solape") if umbral_solape is None else umbral_solape)
    tol_m = float(cfg.obtener("tolerancia_ref_m") if tolerancia_m is None else tolerancia_m)
    if not 0 < umbral <= 1:
        raise ErrorValidacion({"umbral_solape": "debe estar entre 0 y 1"})
    if tol_m < 0:
        raise ErrorValidacion({"tolerancia_m": "no puede ser negativa"})

    adv = []
    if rol == "prueba":
        _comprobar_solapes(tramo, solapes, adv)
    rois = logica_roi.listar_rois(tramo, rol=rol)
    if not rois:
        raise ErrorValidacion({"rois": f"el tramo no tiene ROI de rol '{rol}' (use asignar_roles)"})
    if isinstance(ejecucion_ids, int):
        ejecucion_ids = [ejecucion_ids]

    from app import logica_deteccion as ld
    if ejecucion_ids is None:
        ejecs = [e for e in ld.listar_ejecuciones(tramo, estado="completada") if e["metodo"] == metodo]
    else:
        ejecs = [ld.obtener_ejecucion(i) for i in ejecucion_ids]
        malas = [e["id"] for e in ejecs if e["estado"] != "completada"]
        if malas:
            raise ErrorValidacion({"ejecucion": f"la(s) ejecución(es) {malas} no está(n) completada(s)"})
    ejecs.sort(key=lambda e: e["id"], reverse=True)                      # la más reciente primero

    refs = cargar_referencia([r["id"] for r in rois])
    filas, usadas, sin_ejec = [], {}, []
    for roi in rois:
        cand = [e for e in ejecs if _cubre(e, roi)]
        if not cand:
            sin_ejec.append(roi["codigo"])
            continue
        e = cand[0]
        if len(cand) > 1 and ejecucion_ids is None:
            adv.append(f"ROI {roi['codigo']}: varias ejecuciones la cubren; se usó la más reciente (#{e['id']})")
        usadas[e["id"]] = e
        dets = ld.listar_detecciones(e["id"], roi_id=roi["id"])
        tol_px = tol_m / (float(e["params_json"].get("gsd_cm", 0.5)) / 100.0)
        for f in evaluar_roi(roi, refs[roi["id"]]["tipos"], dets, refs[roi["id"]]["geometrias"], umbral, tol_px, modo):
            filas.append({**f, "ejecucion_id": e["id"]})
    if sin_ejec:
        adv.append("ROI sin ejecución que las cubra (omitidas): " + ", ".join(sin_ejec))
    if not filas:
        raise ErrorValidacion({"ejecucion": "ninguna ejecución cubre las ROI de " + rol + "; analice primero"})
    huellas = {e["params_huella"] for e in usadas.values()}
    if len(huellas) > 1:
        adv.append("Las ejecuciones usadas tienen parámetros distintos (huellas: " + ", ".join(sorted(huellas)) + ")")
    prov = any(e["provisional"] for e in usadas.values())
    if prov:
        adv.append("PROVISIONAL: parte de las ejecuciones usó parámetros sin calibrar con datos reales; "
                   "no use estas métricas como evidencia final.")
    if guardar:
        _guardar(filas, umbral)
    return {"tramo": tramo, "rol": rol, "modo": modo, "umbral_solape": umbral, "tolerancia_m": tol_m,
            "provisional": prov, "ejecuciones": sorted(usadas), "filas": filas, "totales": totales_por_tipo(filas),
            "advertencias": adv, "sin_ejecucion": sin_ejec, "guardado": guardar}


def validar_ejecucion(ejecucion_id, **kw):
    """Valida UNA ejecución (id) en las ROI de prueba que cubre; guarda en Validacion."""
    from app import logica_deteccion as ld
    e = ld.obtener_ejecucion(ejecucion_id)
    return evaluar(e["tramo_id"], ejecucion_ids=[ejecucion_id], **kw)


def _guardar(filas, umbral):
    with basedatos.nueva_sesion() as s:
        for (eid, rid) in sorted({(f["ejecucion_id"], f["roi_id"]) for f in filas}):
            s.execute(delete(Validacion).where(Validacion.ejecucion_id == eid, Validacion.roi_id == rid))
        for f in filas:
            s.add(Validacion(ejecucion_id=f["ejecucion_id"], roi_id=f["roi_id"], tipo=f["tipo"], vp=f["vp"],
                             fp=f["fp"], fn=f["fn"], vn=f["vn"], solape=f["solape"], umbral_solape=umbral))


# ===================================================================================== consultas
def listar_validacion(ejecucion_id=None, tramo=None):
    """Filas guardadas (con código/rol de ROI y flag provisional de la ejecución)."""
    from app import logica_tramos
    with basedatos.nueva_sesion() as s:
        q = (select(Validacion, ROI.codigo, ROI.rol, ROI.tipo_campo, EjecucionAnalisis.provisional,
                    EjecucionAnalisis.metodo, EjecucionAnalisis.params_huella)
             .join(ROI, ROI.id == Validacion.roi_id).join(EjecucionAnalisis, EjecucionAnalisis.id == Validacion.ejecucion_id)
             .order_by(Validacion.ejecucion_id, ROI.codigo, Validacion.id))
        if ejecucion_id is not None:
            obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución")
            q = q.where(Validacion.ejecucion_id == ejecucion_id)
        if tramo is not None:
            q = q.where(EjecucionAnalisis.tramo_id == logica_tramos._resolver(s, tramo).id)
        return [{**v.a_dict(), "roi_codigo": c, "rol": rol, "tipo_campo": tc, "provisional": bool(pv),
                 "metodo": m, "params_huella": h} for v, c, rol, tc, pv, m, h in s.execute(q)]


def ejecuciones_validadas(tramo, metodo="actual", rol="prueba"):
    """Ids de la ejecución VALIDADA más reciente de cada ROI de `rol` (del método dado). Se usa para no contar
    dos veces una ROI validada con varias ejecuciones."""
    ultima = {}
    for f in listar_validacion(tramo=tramo):
        if f["metodo"] == metodo and f["rol"] == rol:
            ultima[f["roi_id"]] = max(ultima.get(f["roi_id"], 0), f["ejecucion_id"])
    return sorted(set(ultima.values()))


def eliminar_validacion(ejecucion_id):
    with basedatos.nueva_sesion() as s:
        obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución")
        s.execute(delete(Validacion).where(Validacion.ejecucion_id == ejecucion_id))


CAMPOS_VALIDACION = (
    Campo("umbral_solape", "Umbral de solape (Dice)", "real", minimo=0.01, maximo=1),
    Campo("tolerancia_m", "Tolerancia de ubicación", "real", minimo=0, maximo=5, unidad="m"),
    Campo("modo", "Referencia", "opcion", opciones=MODOS),
    Campo("solapes", "Solape calibración/prueba", "opcion", opciones=("bloquear", "advertir")),
)


def esquema_validacion():
    """Campos del formulario de validación (la vista los genera de aquí)."""
    return esquema(CAMPOS_VALIDACION)


def opciones_por_defecto():
    """Valores iniciales del formulario: los de Configuracion."""
    return {"umbral_solape": cfg.obtener("umbral_solape"), "tolerancia_m": cfg.obtener("tolerancia_ref_m"),
            "modo": "auto", "solapes": "bloquear"}


def leer_opciones(datos):
    """Valida los textos del formulario (TODOS los errores a la vez) y completa con los valores por defecto."""
    d = validar(datos or {}, CAMPOS_VALIDACION, parcial=True)
    return {**opciones_por_defecto(), **{k: v for k, v in d.items() if v is not None}}


def grupos_validados(tramo, rol="prueba"):
    """Conjuntos de ejecuciones validadas del tramo, agrupados por (método, parámetros). Por ROI se toma la
    ejecución más reciente del grupo. Más reciente primero. Sirve para elegir qué evaluar o comparar."""
    por_grupo = {}
    for f in listar_validacion(tramo=tramo):
        if f["rol"] != rol:
            continue
        g = por_grupo.setdefault((f["metodo"], f["params_huella"]), {"por_roi": {}, "provisional": f["provisional"]})
        g["por_roi"][f["roi_id"]] = max(g["por_roi"].get(f["roi_id"], 0), f["ejecucion_id"])
    out = []
    for (metodo, huella), g in por_grupo.items():
        ids = sorted(set(g["por_roi"].values()))
        out.append({"clave": f"{metodo}|{huella}", "metodo": metodo, "params_huella": huella,
                    "provisional": g["provisional"], "ejecuciones": ids, "n_rois": len(g["por_roi"]),
                    "ultima": max(ids)})
    return sorted(out, key=lambda x: -x["ultima"])


