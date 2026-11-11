"""
logica_comparacion.py
=====================
Comparación entre métodos de detección (F7): 'actual' (black-hat + MAD) vs 'sun' (Sun, 2009).

Principio: ambos métodos se evalúan sobre las MISMAS ROI de prueba, con los MISMOS Params base (los `sun_*` solo los
usa 'sun') y contra la MISMA referencia de campo. Como 'sun' solo detecta grietas lineales, la comparación se hace
únicamente en los tipos que ambos métodos cubren (`pipeline.tipos_del_metodo`); lo demás se informa aparte.

`comparar_metodos` devuelve un dict (JSON-friendly) con:
  * `metricas`      por método, por tipo y global (F5: Wilson, kappa, F1 con IC bootstrap);
  * `mcnemar`       sobre la presencia por unidad (ROI, tipo); acierto = VP o VN;
  * `medidas`       diferencias de longitud/ancho/área ENTRE métodos en los pares (ROI, tipo) detectados por ambos
                    (sesgo = B − A, Bland-Altman, MAE, RMSE);
  * `medidas_campo` error de cada método frente a la Ficha 4 (resumen);
  * `rendimiento`   tiempo (s y s/Mpx) y RAM adicional por método;
  * `conclusiones`  frases construidas SOLO con esas cifras.

Sin Tk. Lee la BD: se llama desde el hilo principal. `ejecutar_y_validar` es la versión síncrona (consola, pruebas);
la interfaz reparte el trabajo entre el hilo de cálculo y el principal (ver ui/presentadores/p_comparacion.py).
"""
from app import logica_configuracion as cfg, logica_deteccion as ld, logica_estadistica as le, logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.nucleo import pipeline
from app.nucleo.estructuras import TIPOS
from app.nucleo.parametros import Params

AVISO_PROVISIONAL = ("PROVISIONAL: al menos un método usó parámetros sin calibrar con datos reales; la comparación "
                     "describe el procedimiento, no es evidencia final.")
VARIABLES = (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²"))
N_MIN_MCNEMAR = 10


def _num(v, nd=2):
    return "n/d" if v is None else f"{v:.{nd}f}"


def ejecutar_y_validar(tramo, metodos=("actual", "sun"), rol="prueba", params=None, cancelar=None, progreso=None):
    """Analiza las ROI de `rol` con cada método (mismos Params) y guarda la validación de cada uno.
    Síncrono y en el hilo que lo llame (escribe en la BD). Devuelve {metodo: {'ejecuciones': [...], 'validacion': dict}}."""
    out = {}
    for k, m in enumerate(metodos):
        sub = None if progreso is None else (lambda f, t, k=k, m=m: progreso((k + f) / len(metodos), f"{m}: {t}"))
        ejecs = ld.analizar_rois(tramo, rol=rol, metodo=m, params=params, cancelar=cancelar, progreso=sub)
        val = lv.evaluar(tramo, ejecucion_ids=[e["id"] for e in ejecs], rol=rol, metodo=m)
        out[m] = {"ejecuciones": ejecs, "validacion": val}
    return out


# ===================================================================================== piezas
def _filas(ids, rol):
    filas = []
    for i in ids:
        filas += [f for f in lv.listar_validacion(ejecucion_id=i) if f["rol"] == rol]
    return filas


def _unidades(filas):
    return {(f["roi_id"], f["tipo"]): f for f in filas}


def _metricas(filas, tipos, conf, n_boot):
    por_tipo, todas = {}, []
    for t in tipos:
        u = [(f["vp"], f["fp"], f["fn"], f["vn"]) for f in filas if f["tipo"] == t]
        s = [sum(c) for c in zip(*u)] if u else [0, 0, 0, 0]
        m = le.metricas_binarias(*s, conf=conf)
        m["f1"]["ic95"] = le.ic_f1_bootstrap(u, n_boot=n_boot, conf=conf) if u else None
        m["kappa"] = le.kappa_de_conteos(*s)
        m["unidades"] = len(u)
        por_tipo[t] = m
        todas += u
    s = [sum(c) for c in zip(*todas)] if todas else [0, 0, 0, 0]
    g = le.metricas_binarias(*s, conf=conf)
    g["f1"]["ic95"] = le.ic_f1_bootstrap(todas, n_boot=n_boot, conf=conf) if todas else None
    g["kappa"] = le.kappa_de_conteos(*s)
    g["unidades"] = len(todas)
    return {"por_tipo": por_tipo, "global": g}


def _acierto(f):
    return bool(f["vp"] or f["vn"])


def _mcnemar(ua, ub, claves):
    b = sum(1 for k in claves if _acierto(ua[k]) and not _acierto(ub[k]))
    c = sum(1 for k in claves if not _acierto(ua[k]) and _acierto(ub[k]))
    ambos = sum(1 for k in claves if _acierto(ua[k]) and _acierto(ub[k]))
    r = le.mcnemar(b, c)
    return {"n": len(claves), "ambos_aciertan": ambos, "solo_a": b, "solo_b": c,
            "ambos_fallan": len(claves) - ambos - b - c, **{k: r[k] for k in ("metodo", "estadistico", "p")},
            "advertencias": r["advertencias"]}


def _medidas_entre(ea_por_roi, eb_por_roi, rois, tipos):
    """Pares (ROI, tipo) detectados por AMBOS métodos: medida de A (referencia) y de B (estimación)."""
    pares = []
    for rid in rois:
        for t in tipos:
            da = [d for d in ld.listar_detecciones(ea_por_roi[rid], roi_id=rid) if d["tipo"] == t]
            db = [d for d in ld.listar_detecciones(eb_por_roi[rid], roi_id=rid) if d["tipo"] == t]
            if not da or not db:
                continue
            ma, mb = le._python_medidas(da), le._python_medidas(db)
            for v, _n, _u in VARIABLES:
                if ma[v] is not None and mb[v] is not None:
                    pares.append({"roi_id": rid, "tipo": t, "variable": v, "a": ma[v], "b": mb[v],
                                  "n_a": len(da), "n_b": len(db)})
    out = {"pares": pares, "global": {}, "por_tipo": {}}
    for v, _n, _u in VARIABLES:
        sel = [p for p in pares if p["variable"] == v]
        out["global"][v] = le.error_medidas([p["a"] for p in sel], [p["b"] for p in sel])
        for t in tipos:
            st = [p for p in sel if p["tipo"] == t]
            if st:
                out["por_tipo"].setdefault(t, {})[v] = le.error_medidas([p["a"] for p in st], [p["b"] for p in st])
    return out


def _resumen_campo(ids, tramo, rol):
    try:
        r = le.error_de_medidas(ids, tramo, rol)
    except ErrorValidacion:
        return None
    return {v: {k: r["global"][v][k] for k in ("n", "sesgo", "mae", "rmse")} for v, _n, _u in VARIABLES}


def _rendimiento(ids):
    r = ld.rendimiento_de(ids)
    seg = [x["duracion_s"] for x in r.values() if x["duracion_s"] is not None]
    mpx = sum(x["mpx"] for x in r.values() if x["duracion_s"] is not None)
    adic = [x["ram_adicional_mb"] for x in r.values() if x["ram_adicional_mb"] is not None]
    pico = [x["ram_pico_mb"] for x in r.values() if x["ram_pico_mb"] is not None]
    total = float(sum(seg)) if seg else None
    return {"n_ejecuciones": len(r), "segundos": total, "mpx": mpx,
            "s_por_mpx": (total / mpx) if total is not None and mpx > 0 else None,
            "ram_adicional_max_mb": max(adic) if adic else None, "ram_pico_max_mb": max(pico) if pico else None,
            "n_con_ram": len(adic)}


def _ratio(b, a):
    return None if a in (None, 0) or b is None else b / a


# ===================================================================================== función principal
def comparar_metodos(tramo, metodo_a="actual", metodo_b="sun", rol="prueba", ids_a=None, ids_b=None, conf=0.95,
                     n_boot=500):
    """Compara dos métodos con la última ejecución VALIDADA de cada ROI de `rol` (o las ejecuciones indicadas).
    Lanza ErrorValidacion si alguno no tiene validación guardada (ejecute `ejecutar_y_validar` o valide cada uno)."""
    if metodo_a == metodo_b:
        raise ErrorValidacion({"metodo": "elija dos métodos distintos"})
    for m in (metodo_a, metodo_b):
        if m not in pipeline.METODOS:
            raise ErrorValidacion({"metodo": f"método '{m}' no disponible. Disponibles: {', '.join(sorted(pipeline.METODOS))}"})
    ids = {}
    for m, dado in ((metodo_a, ids_a), (metodo_b, ids_b)):
        ids[m] = list(dado) if dado else lv.ejecuciones_validadas(tramo, m, rol)
        if not ids[m]:
            raise ErrorValidacion({"validacion": f"no hay validación guardada del método '{m}' en las ROI de {rol}: "
                                                 f"analice y valide con ese método primero"})
    fa, fb = _filas(ids[metodo_a], rol), _filas(ids[metodo_b], rol)
    adv = []
    tipos = [t for t in TIPOS if t in pipeline.tipos_del_metodo(metodo_a) and t in pipeline.tipos_del_metodo(metodo_b)]
    if not tipos:
        raise ErrorValidacion({"tipos": "los métodos no tienen ningún tipo de deterioro en común"})
    rois_a, rois_b = {f["roi_id"] for f in fa}, {f["roi_id"] for f in fb}
    rois = sorted(rois_a & rois_b)
    if not rois:
        raise ErrorValidacion({"rois": "los métodos no tienen ninguna ROI validada en común"})
    if rois_a != rois_b:
        adv.append(f"Solo {len(rois)} ROI están validadas con ambos métodos (A: {len(rois_a)}, B: {len(rois_b)}); "
                   f"se comparan esas")
    fa = [f for f in fa if f["roi_id"] in rois and f["tipo"] in tipos]
    fb = [f for f in fb if f["roi_id"] in rois and f["tipo"] in tipos]
    ua, ub = _unidades(fa), _unidades(fb)
    claves = sorted(set(ua) & set(ub))
    nombres = {f["roi_id"]: f["roi_codigo"] for f in fa}

    metricas = {metodo_a: _metricas(fa, tipos, conf, n_boot), metodo_b: _metricas(fb, tipos, conf, n_boot)}
    mc = {"global": _mcnemar(ua, ub, claves),
          "por_tipo": {t: _mcnemar(ua, ub, [k for k in claves if k[1] == t]) for t in tipos}}
    if len(claves) < N_MIN_MCNEMAR:
        adv.append(f"Solo {len(claves)} unidades (ROI × tipo): McNemar tiene muy poca potencia; no permite concluir "
                   f"equivalencia ni superioridad.")

    ej_a = {f["roi_id"]: f["ejecucion_id"] for f in fa}
    ej_b = {f["roi_id"]: f["ejecucion_id"] for f in fb}
    medidas = _medidas_entre(ej_a, ej_b, rois, tipos)
    if not medidas["pares"]:
        adv.append("Ningún par (ROI, tipo) fue detectado por ambos métodos: no hay diferencias de medidas que calcular.")

    ejs = {m: [ld.obtener_ejecucion(i) for i in sorted(set(f["ejecucion_id"] for f in (fa if m == metodo_a else fb)))]
           for m in (metodo_a, metodo_b)}
    nucleo = {m: {Params.desde_dict(e["params_json"]).huella_nucleo() for e in ejs[m]} for m in ejs}
    mismos = len(nucleo[metodo_a] | nucleo[metodo_b]) == 1
    if not mismos:
        adv.append("Los métodos NO usaron los mismos Params base (los campos no-`sun_*` difieren entre ejecuciones): "
                   "la comparación no es limpia. Reanalice con los mismos parámetros.")
    provisional = any(e["provisional"] for m in ejs for e in ejs[m]) or any(
        cfg.es_provisional(Params.desde_dict(e["params_json"]), m) for m in ejs for e in ejs[m])
    if provisional:
        adv.insert(0, AVISO_PROVISIONAL)
    solo = {m: [t for t in pipeline.tipos_del_metodo(m) if t not in tipos] for m in (metodo_a, metodo_b)}
    if any(solo.values()):
        adv.append("Tipos que solo detecta uno de los métodos (no entran en la comparación): " +
                   "; ".join(f"{m}: {', '.join(v)}" for m, v in solo.items() if v))

    rend = {m: _rendimiento([e["id"] for e in ejs[m]]) for m in ejs}
    rend["razon_tiempo"] = _ratio(rend[metodo_b]["s_por_mpx"], rend[metodo_a]["s_por_mpx"])
    rend["razon_ram"] = _ratio(rend[metodo_b]["ram_adicional_max_mb"], rend[metodo_a]["ram_adicional_max_mb"])
    if any(rend[m]["n_con_ram"] < rend[m]["n_ejecuciones"] for m in ejs):
        adv.append("Parte de las ejecuciones no tiene medición de RAM (anteriores a la F7 o sistema sin medición).")
    adv.append("La RAM se mide como aumento del RSS del proceso durante el análisis: es aproximada (ver rendimiento.py); "
               "para una medición rigurosa use «python -m scripts.comparar_rendimiento».")

    comp = {"tramo": tramo, "rol": rol, "metodos": [metodo_a, metodo_b], "tipos": tipos, "rois": [nombres[r] for r in rois],
            "n_unidades": len(claves), "metricas": metricas, "mcnemar": mc, "medidas": medidas,
            "medidas_campo": {metodo_a: _resumen_campo(ids[metodo_a], tramo, rol),
                              metodo_b: _resumen_campo(ids[metodo_b], tramo, rol)},
            "rendimiento": rend, "mismos_params_base": mismos, "provisional": provisional,
            "ejecuciones": {m: [e["id"] for e in ejs[m]] for m in ejs},
            "huellas": {m: sorted({e["params_huella"] for e in ejs[m]}) for m in ejs}, "advertencias": adv}
    comp["conclusiones"] = conclusiones(comp)
    return comp


# ===================================================================================== conclusiones (solo cifras)
def _pct(v):
    return "n/d" if v is None else f"{100 * v:.1f} %"


def conclusiones(c):
    """Frases construidas SOLO con las cifras del dict `c`. Nunca declaran un método «mejor» sin mostrar el número."""
    a, b = c["metodos"]
    out = []
    if c["provisional"]:
        out.append(AVISO_PROVISIONAL)
    out.append(f"Se compararon '{a}' y '{b}' en {c['n_unidades']} unidades (ROI × tipo) de {len(c['rois'])} ROI de "
               f"{c['rol']}, solo en los tipos que ambos detectan: {', '.join(c['tipos'])}.")
    gm = {m: c["metricas"][m]["global"] for m in (a, b)}
    for m in (a, b):
        g = gm[m]
        out.append(f"'{m}': sensibilidad {_num(g['sensibilidad']['valor'])}, especificidad {_num(g['especificidad']['valor'])}, "
                   f"precisión {_num(g['precision']['valor'])}, F1 {_num(g['f1']['valor'])}, concordancia "
                   f"{_pct(g['exactitud']['valor'])}, kappa {_num(g['kappa']['kappa'])} "
                   f"(VP {g['vp']}, FP {g['fp']}, FN {g['fn']}, VN {g['vn']}).")
    fa, fb = gm[a]["f1"]["valor"], gm[b]["f1"]["valor"]
    if fa is not None and fb is not None:
        d = fb - fa
        if abs(d) < 1e-9:
            out.append(f"El F1 global es igual en ambos métodos ({fa:.2f}).")
        else:
            mejor = b if d > 0 else a
            out.append(f"El F1 global es mayor en '{mejor}' (diferencia {abs(d):.2f}: {a} {fa:.2f}, {b} {fb:.2f}).")
    m = c["mcnemar"]["global"]
    if m["p"] is None:
        out.append("McNemar: no hay unidades discordantes; ambos métodos acertaron y fallaron en las mismas unidades.")
    else:
        sig = "hay" if m["p"] < 0.05 else "no hay"
        out.append(f"McNemar sobre {m['n']} unidades: {m['solo_a']} las acierta solo '{a}' y {m['solo_b']} solo '{b}' "
                   f"(p = {m['p']:.3f}, {m['metodo']}); {sig} diferencia significativa al 5 %.")
    if m["n"] < N_MIN_MCNEMAR:
        out.append(f"Con {m['n']} unidades la prueba tiene muy poca potencia: no permite concluir equivalencia ni "
                   f"superioridad.")
    for v, nombre, u in VARIABLES:
        e = c["medidas"]["global"][v]
        if e["n"]:
            ba = e.get("bland_altman")
            lim = (f"; límites de acuerdo {_num(ba['loa_inf'], 3)} a {_num(ba['loa_sup'], 3)} {u}" if ba else "")
            out.append(f"{nombre}: en {e['n']} pares (ROI, tipo) detectados por ambos, '{b}' − '{a}' tiene sesgo "
                       f"{_num(e['sesgo'], 3)} {u}, MAE {_num(e['mae'], 3)} {u}{lim}.")
    ra, rb = c["rendimiento"][a], c["rendimiento"][b]
    if ra["s_por_mpx"] is not None and rb["s_por_mpx"] is not None:
        r = c["rendimiento"]["razon_tiempo"]
        out.append(f"Tiempo de cómputo: '{a}' {_num(ra['s_por_mpx'], 2)} s/Mpx y '{b}' {_num(rb['s_por_mpx'], 2)} s/Mpx"
                   + (f" ('{b}' tarda {r:.2f} veces lo de '{a}')." if r is not None else "."))
    if ra["ram_adicional_max_mb"] is not None and rb["ram_adicional_max_mb"] is not None:
        out.append(f"RAM adicional máxima (aproximada): '{a}' {_num(ra['ram_adicional_max_mb'], 0)} MB y '{b}' "
                   f"{_num(rb['ram_adicional_max_mb'], 0)} MB.")
    return out


def filas_resumen(c):
    """[(clave, texto)] para mostrar en pantalla."""
    return [("conclusion", t) for t in c["conclusiones"]]
