"""
logica_estadistica.py
=====================
Estadística comparativa de la validación (F5). Dos capas:

  1. FUNCIONES PURAS (sin BD): `wilson`, `metricas_binarias`, `kappa`, `matriz_confusion`, `error_medidas`,
     `mcnemar`, `ic_f1_bootstrap`. Se verifican en las pruebas contra scipy / scikit-learn / statsmodels.
  2. CONSULTAS sobre la BD: `metricas_validacion`, `concordancia_tipo`, `concordancia_severidad`,
     `error_de_medidas`, `tablas_conteo`, `comparar_ejecuciones`. Devuelven dicts (JSON-friendly) que la
     vista y el PDF de F6 reutilizan.

Convenciones
------------
* DIVISIÓN POR CERO → `None` (nunca 0): sensibilidad sin positivos de referencia, kappa con pe = 1, etc.
* IC 95 % de Wilson para proporciones (sensibilidad, especificidad, precisión, exactitud); el de F1 es
  bootstrap percentil sobre las unidades (ROI, tipo). Con n < 5 el IC se calcula pero se ADVIERTE que no es fiable.
* Kappa: IC aproximado (error estándar asintótico de Cohen) solo para la versión sin ponderar.
  Umbral de concordancia aceptable = `Configuracion['umbral_concordancia']` (por defecto 0.60, CONFIRMAR con el asesor).
* Error de medidas: sesgo = estimado − referencia (Python − campo). La prueba pareada es t si los diferencias
  pasan Shapiro-Wilk (p >= 0.05) y Wilcoxon en otro caso; con n < 3 no se calcula.
* Severidad de Python (`severidad_prelim`) es ORIENTATIVA; solo existe para grietas lineales.
* Todo lo derivado de ejecuciones con parámetros provisionales lleva `provisional=True`.
"""
import math

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import select

from app import basedatos, logica_configuracion as cfg, logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.modelos import CatalogoPatologia, EjecucionAnalisis, Geometria, Patologia, ROI
from app.nucleo.estructuras import TIPOS, TIPOS_GRIETA

N_MIN_IC = 5
NIVELES = ("Baja", "Media", "Alta")
TIPOS_Y_SANO = TIPOS + ("sano",)


def _f(x):
    return None if x is None else float(x)


def _div(a, b):
    return None if b == 0 else a / b


# ===================================================================================== proporciones
def wilson(k, n, conf=0.95):
    """Intervalo de Wilson para k éxitos de n. (None, None) si n == 0."""
    if n <= 0:
        return (None, None)
    z = stats.norm.ppf(0.5 + conf / 2.0)
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centro - mitad), min(1.0, centro + mitad))


def _prop(k, n, conf):
    lo, hi = wilson(k, n, conf)
    return {"valor": _f(_div(k, n)), "ic95": None if lo is None else [lo, hi], "n": int(n)}


def f1_de(vp, fp, fn):
    return _f(_div(2 * vp, 2 * vp + fp + fn))


def metricas_binarias(vp, fp, fn, vn, conf=0.95):
    """Sensibilidad, especificidad, precisión, exactitud (con IC de Wilson) y F1 de una tabla 2x2.
    Cada métrica: {'valor', 'ic95', 'n'} (n = denominador). `advertencias`: IC no fiables (n < 5)."""
    vp, fp, fn, vn = (int(v) for v in (vp, fp, fn, vn))
    m = {"sensibilidad": _prop(vp, vp + fn, conf), "especificidad": _prop(vn, vn + fp, conf),
         "precision": _prop(vp, vp + fp, conf), "exactitud": _prop(vp + vn, vp + fp + fn + vn, conf),
         "f1": {"valor": f1_de(vp, fp, fn), "ic95": None, "n": vp + fp + fn + vn}}
    adv = []
    for nombre, v in m.items():
        if nombre == "f1":
            continue
        if v["n"] == 0:
            adv.append(f"{nombre}: sin casos (denominador 0), no se calcula")
        elif v["n"] < N_MIN_IC:
            adv.append(f"{nombre}: n = {v['n']} < {N_MIN_IC}, el IC no es fiable")
    return {"vp": vp, "fp": fp, "fn": fn, "vn": vn, **m, "advertencias": adv}


def ic_f1_bootstrap(unidades, n_boot=2000, conf=0.95, semilla=12345):
    """IC percentil del F1 remuestreando las unidades [(vp, fp, fn, vn), ...] con reemplazo.
    None si hay menos de 2 unidades o el F1 no es calculable en casi ninguna réplica."""
    u = np.asarray(unidades, dtype=float).reshape(-1, 4)
    if len(u) < 2:
        return None
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(u), size=(n_boot, len(u)))
    s = u[idx].sum(axis=1)                                   # (n_boot, 4)
    den = 2 * s[:, 0] + s[:, 1] + s[:, 2]
    ok = den > 0
    if ok.sum() < 0.5 * n_boot:
        return None
    f1 = 2 * s[ok, 0] / den[ok]
    a = (1 - conf) / 2
    return [float(np.quantile(f1, a)), float(np.quantile(f1, 1 - a))]


# ===================================================================================== kappa
def _interpretar(k):
    if k is None:
        return None
    for tope, txt in ((0.0, "pobre"), (0.20, "leve"), (0.40, "aceptable"), (0.60, "moderada"), (0.80, "sustancial")):
        if k <= tope:
            return txt
    return "casi perfecta"


def matriz_confusion(ref, pred, etiquetas):
    """Matriz [referencia][predicción] con las `etiquetas` dadas (los valores fuera de ellas se descartan y se cuentan)."""
    et = list(etiquetas)
    pos = {e: i for i, e in enumerate(et)}
    m = np.zeros((len(et), len(et)), dtype=int)
    fuera = 0
    for a, b in zip(ref, pred):
        if a in pos and b in pos:
            m[pos[a], pos[b]] += 1
        else:
            fuera += 1
    return {"etiquetas": et, "matriz": m.tolist(), "n": int(m.sum()), "descartados": fuera}


def kappa_de_matriz(m, pesos=None):
    """Kappa de Cohen desde una matriz de confusión. pesos: None | 'lineal' | 'cuadratico' (ordinales)."""
    m = np.asarray(m, dtype=float)
    n = m.sum()
    if n == 0:
        return {"kappa": None, "po": None, "pe": None, "n": 0, "ic95": None, "se": None}
    k = m.shape[0]
    fila, col = m.sum(1) / n, m.sum(0) / n
    if pesos is None:
        w = 1.0 - np.eye(k)
    else:
        i = np.arange(k)
        d = np.abs(i[:, None] - i[None, :]) / max(k - 1, 1)
        w = d if pesos == "lineal" else d ** 2
    po = float((w * m / n).sum())
    pe = float((w * np.outer(fila, col)).sum())
    if pesos is None:
        po, pe = 1 - po, 1 - pe                                    # acuerdo observado / esperado
        kap = _div(po - pe, 1 - pe)
        se = None if kap is None else math.sqrt(po * (1 - po) / (n * (1 - pe) ** 2))
        ic = None if se is None else [kap - 1.96 * se, kap + 1.96 * se]
        return {"kappa": _f(kap), "po": po, "pe": pe, "n": int(n), "se": se, "ic95": ic}
    kap = None if pe == 0 else 1 - po / pe
    return {"kappa": _f(kap), "po": 1 - po, "pe": 1 - pe, "n": int(n), "se": None, "ic95": None}


def _umbral(umbral=None):
    """Umbral de concordancia: el dado, o el de Configuracion, o (sin BD inicializada) el valor por defecto."""
    if umbral is not None:
        return float(umbral)
    try:
        return float(cfg.obtener("umbral_concordancia"))
    except basedatos.ErrorBD:
        return float(cfg.DEFAULTS["umbral_concordancia"])


def kappa(ref, pred, etiquetas=None, pesos=None, umbral=None):
    """Kappa de Cohen entre dos clasificaciones (listas de igual largo). None si no es calculable (pe = 1)."""
    ref, pred = list(ref), list(pred)
    if len(ref) != len(pred):
        raise ErrorValidacion({"kappa": "las dos clasificaciones deben tener el mismo número de casos"})
    et = list(etiquetas) if etiquetas is not None else sorted(set(ref) | set(pred), key=str)
    mc = matriz_confusion(ref, pred, et)
    r = kappa_de_matriz(mc["matriz"], pesos)
    r.update(pesos=pesos, interpretacion=_interpretar(r["kappa"]), matriz=mc)
    u = _umbral(umbral)
    r["umbral"] = float(u)
    r["concordante"] = None if r["kappa"] is None else bool(r["kappa"] >= u)
    r["advertencias"] = ([] if r["n"] >= N_MIN_IC else [f"n = {r['n']} < {N_MIN_IC}: el kappa no es fiable"])
    return r


def kappa_de_conteos(vp, fp, fn, vn, umbral=None):
    """Kappa binario (presencia) desde VP/FP/FN/VN: referencia = campo, predicción = Python."""
    return kappa([1] * vp + [0] * fp + [1] * fn + [0] * vn, [1] * vp + [1] * fp + [0] * fn + [0] * vn,
                 etiquetas=[0, 1], umbral=umbral)


# ===================================================================================== error de medidas
def error_medidas(ref, est, conf=0.95):
    """Error de una medida (`est` de Python vs `ref` de campo, pareadas). Sesgo = est − ref."""
    ref, est = np.asarray(ref, float), np.asarray(est, float)
    if ref.shape != est.shape:
        raise ErrorValidacion({"medidas": "referencia y estimación deben tener el mismo número de pares"})
    ok = np.isfinite(ref) & np.isfinite(est)
    ref, est = ref[ok], est[ok]
    n = len(ref)
    out = {"n": n, "sesgo": None, "sesgo_rel_pct": None, "mae": None, "rmse": None, "bland_altman": None,
           "pearson": None, "spearman": None, "normalidad": None, "prueba": None, "advertencias": []}
    if n == 0:
        out["advertencias"].append("sin pares de medidas")
        return out
    d = est - ref
    out.update(sesgo=float(d.mean()), mae=float(np.abs(d).mean()), rmse=float(math.sqrt((d ** 2).mean())),
               sesgo_rel_pct=_f(_div(d.mean(), ref.mean()) * 100 if ref.mean() != 0 else None))
    if n < 3:
        out["advertencias"].append(f"n = {n} < 3: sin Bland-Altman, correlación ni prueba pareada")
        return out
    sd = float(d.std(ddof=1))
    t = stats.t.ppf(0.5 + conf / 2, n - 1)
    z = stats.norm.ppf(0.5 + conf / 2)
    out["bland_altman"] = {"sesgo": float(d.mean()), "sd": sd, "loa_inf": float(d.mean() - z * sd),
                           "loa_sup": float(d.mean() + z * sd),
                           "ic_sesgo": [float(d.mean() - t * sd / math.sqrt(n)), float(d.mean() + t * sd / math.sqrt(n))],
                           "medias": ((ref + est) / 2).tolist(), "diferencias": d.tolist()}
    if ref.std() > 0 and est.std() > 0:
        r, p = stats.pearsonr(ref, est)
        rho, ps = stats.spearmanr(ref, est)
        out["pearson"], out["spearman"] = {"r": float(r), "p": float(p)}, {"rho": float(rho), "p": float(ps)}
    else:
        out["advertencias"].append("una de las series es constante: correlación no definida")
    if sd == 0:
        out["advertencias"].append("todas las diferencias son iguales: prueba pareada no definida")
        return out
    w, pn = stats.shapiro(d)
    normal = bool(pn >= 0.05)
    out["normalidad"] = {"test": "Shapiro-Wilk (diferencias)", "W": float(w), "p": float(pn), "normal": normal}
    if normal:
        s, p = stats.ttest_rel(est, ref)
        out["prueba"] = {"nombre": "t de Student pareada", "estadistico": float(s), "p": float(p)}
    elif np.all(d == 0):
        out["prueba"] = None
    else:
        s, p = stats.wilcoxon(est, ref)
        out["prueba"] = {"nombre": "Wilcoxon de rangos con signo", "estadistico": float(s), "p": float(p)}
    if n < N_MIN_IC:
        out["advertencias"].append(f"n = {n} < {N_MIN_IC}: pruebas poco potentes")
    return out


# ===================================================================================== McNemar
def mcnemar(b, c):
    """McNemar para discordantes b (A acierta, B falla) y c (A falla, B acierta).
    Exacto (binomial bilateral) si b + c < 25; si no, χ² con corrección de continuidad. p = None si b + c = 0."""
    b, c = int(b), int(c)
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "metodo": None, "estadistico": None, "p": None,
                "advertencias": ["no hay pares discordantes: no hay diferencia que probar"]}
    if n < 25:
        p = float(stats.binomtest(min(b, c), n, 0.5).pvalue)
        return {"b": b, "c": c, "metodo": "exacto (binomial)", "estadistico": float(min(b, c)), "p": p,
                "advertencias": []}
    chi = (abs(b - c) - 1) ** 2 / n
    return {"b": b, "c": c, "metodo": "χ² con corrección de continuidad", "estadistico": float(chi),
            "p": float(stats.chi2.sf(chi, 1)), "advertencias": []}


# ===================================================================================== consultas: validación
def _filas_validacion(ejecucion_ids, tramo, rol, metodo="actual"):
    """Filas guardadas de las ejecuciones dadas o, con `tramo`, de la última ejecución validada de cada ROI
    (así una ROI validada varias veces cuenta UNA vez)."""
    if ejecucion_ids is None and tramo is None:
        raise ErrorValidacion({"ejecucion": "indique ejecuciones o un tramo"})
    if ejecucion_ids is None:
        ejecucion_ids = lv.ejecuciones_validadas(tramo, metodo, rol or "prueba")
    filas = []
    for e in ([ejecucion_ids] if isinstance(ejecucion_ids, int) else ejecucion_ids):
        filas += lv.listar_validacion(ejecucion_id=e)
    filas = [f for f in filas if rol is None or f["rol"] == rol]
    if not filas:
        raise ErrorValidacion({"validacion": "no hay validación guardada para esa selección; ejecute la validación primero"})
    return filas


def _provisional(filas):
    return any(f["provisional"] for f in filas)


def metricas_validacion(ejecucion_ids=None, tramo=None, rol="prueba", conf=0.95, n_boot=2000, metodo="actual"):
    """Métricas por tipo y globales (agrupando todas las unidades) desde `Validacion`.
    Solo ROI de prueba por defecto. Incluye kappa de presencia (campo vs Python) y concordancia aceptable."""
    filas = _filas_validacion(ejecucion_ids, tramo, rol, metodo)
    adv = []
    por_tipo = {}
    for t in TIPOS:
        u = [(f["vp"], f["fp"], f["fn"], f["vn"]) for f in filas if f["tipo"] == t]
        s = np.asarray(u, int).sum(axis=0) if u else np.zeros(4, int)
        m = metricas_binarias(*s, conf=conf)
        m["f1"]["ic95"] = ic_f1_bootstrap(u, n_boot=n_boot, conf=conf)
        m["kappa"] = kappa_de_conteos(*[int(v) for v in s])
        m["unidades"] = len(u)
        por_tipo[t] = m
        adv += [f"{t}: {a}" for a in m["advertencias"]]
    u_all = [(f["vp"], f["fp"], f["fn"], f["vn"]) for f in filas]
    s = np.asarray(u_all, int).sum(axis=0)
    glob = metricas_binarias(*s, conf=conf)
    glob["f1"]["ic95"] = ic_f1_bootstrap(u_all, n_boot=n_boot, conf=conf)
    glob["kappa"] = kappa_de_conteos(*[int(v) for v in s])
    glob["unidades"] = len(u_all)
    prov = _provisional(filas)
    if prov:
        adv.insert(0, "PROVISIONAL: resultados con parámetros sin calibrar con datos reales; no son evidencia final.")
    modos = {f.get("solape") is not None for f in filas}
    return {"rol": rol, "provisional": prov, "conf": conf, "n_rois": len({f["roi_id"] for f in filas}),
            "por_tipo": por_tipo, "global": glob, "umbral_concordancia": float(cfg.obtener("umbral_concordancia")),
            "usa_geometria": True in modos, "advertencias": adv}


def comparar_ejecuciones(ejecuciones_a, ejecuciones_b, tipo=None, rol="prueba"):
    """McNemar entre dos conjuntos de ejecuciones (p. ej. método 'actual' vs 'sun') sobre las MISMAS unidades
    (ROI de prueba, tipo) ya validadas. Acierto de una unidad = VP o VN."""
    fa = _filas_validacion(ejecuciones_a, None, rol)
    fb = _filas_validacion(ejecuciones_b, None, rol)
    if tipo is not None:
        fa, fb = [f for f in fa if f["tipo"] == tipo], [f for f in fb if f["tipo"] == tipo]
    ua = {(f["roi_id"], f["tipo"]): bool(f["vp"] or f["vn"]) for f in fa}
    ub = {(f["roi_id"], f["tipo"]): bool(f["vp"] or f["vn"]) for f in fb}
    comunes = sorted(set(ua) & set(ub))
    adv = []
    if set(ua) != set(ub):
        adv.append(f"solo {len(comunes)} unidades están en ambos conjuntos (A: {len(ua)}, B: {len(ub)}); se comparan esas")
    if not comunes:
        raise ErrorValidacion({"comparacion": "no hay unidades (ROI, tipo) en común entre ambas ejecuciones"})
    a_ok = sum(1 for k in comunes if ua[k] and ub[k])
    b = sum(1 for k in comunes if ua[k] and not ub[k])
    c = sum(1 for k in comunes if not ua[k] and ub[k])
    ambos_mal = sum(1 for k in comunes if not ua[k] and not ub[k])
    r = mcnemar(b, c)
    ha, hb = {f["params_huella"] for f in fa}, {f["params_huella"] for f in fb}
    ma, mb = {f["metodo"] for f in fa}, {f["metodo"] for f in fb}
    prov = _provisional(fa) or _provisional(fb)
    if prov:
        adv.append("PROVISIONAL: al menos una de las ejecuciones usó parámetros sin calibrar.")
    if len(comunes) < 10:
        adv.append(f"solo {len(comunes)} unidades: la prueba tiene muy poca potencia")
    return {"tipo": tipo, "n_unidades": len(comunes), "ambos_aciertan": a_ok, "solo_a_acierta": b,
            "solo_b_acierta": c, "ambos_fallan": ambos_mal, "exactitud_a": a_ok / len(comunes) + b / len(comunes),
            "exactitud_b": a_ok / len(comunes) + c / len(comunes), "mcnemar": r,
            "metodos": [sorted(ma), sorted(mb)], "huellas": [sorted(ha), sorted(hb)], "provisional": prov,
            "advertencias": adv + r["advertencias"]}


# ===================================================================================== consultas: tipo y severidad
def _datos_roi(ejecucion_ids, tramo, rol):
    """{roi_id: {'roi': dict, 'dets': [..], 'ejecucion': dict}} de las ROI de `rol` con ejecución."""
    from app import logica_deteccion as ld, logica_roi
    rois = {r["id"]: r for r in logica_roi.listar_rois(tramo)
            if rol is None or r["rol"] == rol} if tramo is not None else None
    out, provisional = {}, False
    for e in ([ejecucion_ids] if isinstance(ejecucion_ids, int) else ejecucion_ids):
        ej = ld.obtener_ejecucion(e)
        if rois is None:
            from app import logica_roi as lr
            rois = {r["id"]: r for r in lr.listar_rois(ej["tramo_id"]) if rol is None or r["rol"] == rol}
        provisional = provisional or ej["provisional"]
        for rid, r in rois.items():
            if lv._cubre(ej, r):
                out[rid] = {"roi": r, "dets": ld.listar_detecciones(e, roi_id=rid), "ejecucion": ej}
    return out, provisional


def tipo_predicho(dets):
    """Tipo dominante de Python en una ROI: el de más detecciones (empate: mayor área, luego orden de TIPOS);
    'sano' si no hay detecciones. SUPUESTO para comparar un único tipo por ROI."""
    if not dets:
        return "sano"
    cuenta = {}
    for d in dets:
        c = cuenta.setdefault(d["tipo"], [0, 0.0])
        c[0] += 1
        c[1] += d.get("area_m2") or 0.0
    return max(cuenta, key=lambda t: (cuenta[t][0], cuenta[t][1], -TIPOS.index(t)))


def concordancia_tipo(ejecucion_ids, tramo=None, rol="prueba"):
    """Matriz de confusión y kappa (multiclase) del TIPO por ROI: `tipo_campo` vs tipo dominante de Python."""
    datos, prov = _datos_roi(ejecucion_ids, tramo, rol)
    if not datos:
        raise ErrorValidacion({"rois": "no hay ROI con ejecución para esa selección"})
    ref = [d["roi"]["tipo_campo"] for d in datos.values()]
    pred = [tipo_predicho(d["dets"]) for d in datos.values()]
    k = kappa(ref, pred, etiquetas=TIPOS_Y_SANO)
    adv = list(k["advertencias"])
    if prov:
        adv.insert(0, "PROVISIONAL: parámetros sin calibrar con datos reales.")
    return {"kappa": k, "matriz": k["matriz"], "provisional": prov, "n_rois": len(ref), "advertencias": adv}


def _severidad_oficial(roi_id):
    """{observador: nivel más alto registrado en la ROI} (SUPUESTO: con varias patologías, la peor)."""
    from app import logica_fichas as lf
    por_obs = {}
    for s in lf.severidades_roi(roi_id):
        por_obs[s["observador"]] = max(por_obs.get(s["observador"], s["nivel"]), s["nivel"], key=NIVELES.index)
    return por_obs


def _severidad_python(dets):
    """Peor severidad orientativa entre las grietas lineales con ancho resoluble; None si no hay."""
    niv = [d["severidad_prelim"] for d in dets if d["tipo"] in TIPOS_GRIETA and d.get("severidad_prelim") in NIVELES]
    return max(niv, key=NIVELES.index) if niv else None


def concordancia_severidad(ejecucion_ids=None, tramo=None, rol="prueba", pesos="lineal"):
    """(a) Observador 1 vs 2 (oficial, por ROI) y (b) oficial (obs. 1) vs severidad_prelim de Python (ORIENTATIVA).
    (a) usa todas las ROI del tramo con ambos observadores (la fiabilidad entre observadores no es de 'prueba').
    Kappa ponderado (lineal por defecto: Baja < Media < Alta)."""
    from app import logica_roi
    adv = []
    if tramo is None:
        raise ErrorValidacion({"tramo": "indique el tramo"})
    obs_pares, py_pares = [], []
    for r in logica_roi.listar_rois(tramo):
        sev = _severidad_oficial(r["id"])
        if 1 in sev and 2 in sev:
            obs_pares.append((sev[1], sev[2]))
    res = {"observadores": None, "python": None, "provisional": False}
    if obs_pares:
        k = kappa([a for a, _ in obs_pares], [b for _, b in obs_pares], etiquetas=NIVELES, pesos=pesos)
        res["observadores"] = k
        adv += [f"observadores: {a}" for a in k["advertencias"]]
    else:
        adv.append("no hay ROI con severidad de los dos observadores")
    if ejecucion_ids:
        datos, prov = _datos_roi(ejecucion_ids, tramo, rol)
        sin = 0
        for rid, d in datos.items():
            s1 = _severidad_oficial(rid).get(1)
            sp = _severidad_python(d["dets"])
            if s1 is None or sp is None:
                sin += 1
                continue
            py_pares.append((s1, sp))
        if py_pares:
            k = kappa([a for a, _ in py_pares], [b for _, b in py_pares], etiquetas=NIVELES, pesos=pesos)
            res["python"] = k
            adv += [f"Python: {a}" for a in k["advertencias"]]
        if sin:
            adv.append(f"{sin} ROI sin par de severidad (sin ficha del observador 1 o sin grieta resoluble en Python)")
        res["provisional"] = prov
        adv.append("La severidad de Python es ORIENTATIVA (solo grietas lineales, por ancho); la oficial es la de campo.")
        if prov:
            adv.insert(0, "PROVISIONAL: parámetros sin calibrar con datos reales.")
    res["advertencias"] = adv
    return res


# ===================================================================================== consultas: medidas
def _campo_medidas(roi_id, tipo):
    """Ficha 4 de la ROI para un tipo: longitud (suma m), área (suma m²), ancho (media mm) o None si no hay."""
    with basedatos.nueva_sesion() as s:
        q = (select(Geometria).join(Patologia, Patologia.id == Geometria.patologia_id)
             .join(CatalogoPatologia, CatalogoPatologia.codigo == Patologia.codigo)
             .where(Patologia.roi_id == roi_id, Patologia.presencia.is_(True), CatalogoPatologia.tipo_motor == tipo))
        gs = list(s.scalars(q))
        if not gs:
            return None
        suma = lambda vs: float(sum(vs)) if vs else None
        anchos = [g.ancho_prom_mm for g in gs if g.ancho_prom_mm is not None]
        return {"longitud_m": suma([g.longitud_m for g in gs if g.longitud_m is not None]),
                "area_m2": suma([g.area_m2 for g in gs if g.area_m2 is not None]),
                "ancho_mm": float(np.mean(anchos)) if anchos else None}


def _python_medidas(dets):
    anchos = [d["ancho_mm"] if d.get("ancho_mm") is not None else (d["ancho_m"] * 1000.0 if d.get("ancho_m") else None)
              for d in dets]
    anchos = [a for a in anchos if a is not None]
    return {"longitud_m": float(sum(d["longitud_m"] or 0.0 for d in dets)),
            "area_m2": float(sum(d["area_m2"] or 0.0 for d in dets)),
            "ancho_mm": float(np.mean(anchos)) if anchos else None}


def error_de_medidas(ejecucion_ids, tramo=None, rol="prueba"):
    """Error de longitud (m), ancho (mm) y área (m²) contra la Ficha 4, por variable y por tipo.
    Pares por (ROI, tipo): solo donde la ficha 4 tiene el dato Y Python detectó el tipo (SUPUESTO: se comparan
    medidas de deterioros hallados; los no detectados ya cuentan como FN en la validación).
    Ancho de baches: Python da metros, se convierte a mm (la ficha lo guarda siempre en mm)."""
    datos, prov = _datos_roi(ejecucion_ids, tramo, rol)
    if not datos:
        raise ErrorValidacion({"rois": "no hay ROI con ejecución para esa selección"})
    pares = []
    for rid, d in datos.items():
        for t in TIPOS:
            dets = [x for x in d["dets"] if x["tipo"] == t]
            campo = _campo_medidas(rid, t)
            if not dets or campo is None:
                continue
            py = _python_medidas(dets)
            for v in ("longitud_m", "ancho_mm", "area_m2"):
                if campo[v] is not None and py[v] is not None:
                    pares.append({"roi_id": rid, "roi": d["roi"]["codigo"], "tipo": t, "variable": v,
                                  "campo": campo[v], "python": py[v]})
    df = pd.DataFrame(pares, columns=["roi_id", "roi", "tipo", "variable", "campo", "python"])
    out, adv = {"global": {}, "por_tipo": {}, "pares": pares}, []
    for v in ("longitud_m", "ancho_mm", "area_m2"):
        sub = df[df.variable == v]
        out["global"][v] = error_medidas(sub.campo.values, sub.python.values)
        adv += [f"{v}: {a}" for a in out["global"][v]["advertencias"]]
        for t in TIPOS:
            st = sub[sub.tipo == t]
            if len(st):
                out["por_tipo"].setdefault(t, {})[v] = error_medidas(st.campo.values, st.python.values)
    if df.empty:
        adv.append("no hay pares: faltan medidas de la Ficha 4 (Geometría) para las ROI detectadas")
    if prov:
        adv.insert(0, "PROVISIONAL: parámetros sin calibrar con datos reales.")
    out.update(provisional=prov, advertencias=adv)
    return out


# ===================================================================================== consultas: tablas 2-4
def _unidades_fp(ejecuciones):
    """{(ejecucion_id, roi_id, tipo)} de las unidades guardadas como falso positivo (Validacion.fp = 1)."""
    return {(f["ejecucion_id"], f["roi_id"], f["tipo"]) for e in ejecuciones for f in lv.listar_validacion(ejecucion_id=e)
            if f["fp"]}


def tablas_conteo(ejecucion_ids, tramo=None, rol=None, excluir_fp=False):
    """Conteos, longitud, área y % de área afectada por ROI y tipo, y totales por tipo (Tablas 2-4 del cap. 3.2).
    % área afectada = Σ área_m2 detectada / área analizada (ROI o región de la ejecución) × 100.
    SUPUESTO: las regiones analizadas no se solapan entre sí (si lo hacen el % se subestima).
    `excluir_fp=True` (decisión del tesista, 8-nov): las detecciones de unidades (ROI, tipo) validadas como FALSO
    POSITIVO NO entran al conteo; siguen registradas en `Validacion` y en la tabla de detecciones."""
    datos, prov = _datos_roi(ejecucion_ids, tramo, rol) if tramo is not None else _datos_roi_ej(ejecucion_ids, rol)
    if not datos:
        raise ErrorValidacion({"rois": "no hay ROI con ejecución para esa selección"})
    fp_excluidos = 0
    if excluir_fp:
        fp = _unidades_fp({d["ejecucion"]["id"] for d in datos.values()})
        for rid, d in datos.items():
            antes = len(d["dets"])
            d["dets"] = [x for x in d["dets"] if (d["ejecucion"]["id"], rid, x["tipo"]) not in fp]
            fp_excluidos += antes - len(d["dets"])
    filas = []
    area_por_roi = {}
    for rid, d in datos.items():
        r, e = d["roi"], d["ejecucion"]
        gsd = float(e["params_json"]["gsd_cm"]) / 100.0
        area_roi = (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) * gsd ** 2
        area_por_roi[rid] = area_roi
        for t in TIPOS:
            ds = [x for x in d["dets"] if x["tipo"] == t]
            if not ds:
                continue
            anchos = [x["ancho_mm"] for x in ds if x.get("ancho_mm") is not None]
            filas.append({"roi": r["codigo"], "roi_id": rid, "rol": r["rol"], "tipo": t, "n": len(ds),
                          "longitud_m": sum(x["longitud_m"] or 0 for x in ds),
                          "ancho_medio_mm": float(np.mean(anchos)) if anchos else None,
                          "ancho_max_mm": max(anchos) if anchos else None,
                          "ancho_medio_m": (float(np.mean([x["ancho_m"] for x in ds if x.get("ancho_m")]))
                                            if t == "bache" and any(x.get("ancho_m") for x in ds) else None),
                          "area_m2": sum(x["area_m2"] or 0 for x in ds),
                          "pct_area_afectada": 100.0 * sum(x["area_m2"] or 0 for x in ds) / area_roi,
                          "densidad_media_pct": (float(np.mean([x["densidad_pct"] for x in ds if x.get("densidad_pct") is not None]))
                                                 if t == "piel_cocodrilo" and any(x.get("densidad_pct") is not None for x in ds) else None)})
    df = pd.DataFrame(filas)
    area_total = float(sum(area_por_roi.values()))
    totales = {}
    for t in TIPOS:
        sub = df[df.tipo == t] if not df.empty else df
        n = int(sub.n.sum()) if len(sub) else 0
        a = float(sub.area_m2.sum()) if len(sub) else 0.0
        totales[t] = {"n": n, "longitud_m": float(sub.longitud_m.sum()) if len(sub) else 0.0, "area_m2": a,
                      "pct_area_afectada": _f(_div(100.0 * a, area_total)), "rois_con_tipo": int(len(sub))}
    adv = ["PROVISIONAL: parámetros sin calibrar con datos reales."] if prov else []
    if fp_excluidos:
        adv.append(f"{fp_excluidos} detecciones de unidades validadas como falso positivo no entran al conteo "
                   f"(siguen registradas en la validación).")
    tablas = {"tabla2": [f for f in filas if f["tipo"] in TIPOS_GRIETA], "tabla3": [f for f in filas if f["tipo"] == "piel_cocodrilo"],
              "tabla4": [f for f in filas if f["tipo"] == "bache"]}
    return {"por_roi": filas, "totales": totales, "area_analizada_m2": area_total, "n_rois": len(datos),
            "tablas": tablas, "provisional": prov, "advertencias": adv, "excluye_fp": bool(excluir_fp),
            "fp_excluidos": fp_excluidos}


def _datos_roi_ej(ejecucion_ids, rol):
    from app import logica_deteccion as ld
    ids = [ejecucion_ids] if isinstance(ejecucion_ids, int) else list(ejecucion_ids)
    tramos = {ld.obtener_ejecucion(i)["tramo_id"] for i in ids}
    if len(tramos) != 1:
        raise ErrorValidacion({"ejecucion": "las ejecuciones deben ser del mismo tramo"})
    return _datos_roi(ids, tramos.pop(), rol)


# ===================================================================================== comparación descriptiva entre tramos
def _desc(valores):
    v = [float(x) for x in valores if x is not None]
    if not v:
        return {"n": 0, "media": None, "min": None, "max": None, "sd": None}
    return {"n": len(v), "media": float(np.mean(v)), "min": min(v), "max": max(v),
            "sd": float(np.std(v, ddof=1)) if len(v) > 1 else None}


def comparacion_tramos(tramos=None, metodo="actual", rol="prueba"):
    """Estadística DESCRIPTIVA comparativa entre tramos (plan de tesis 5.5, «tercer lugar»: frecuencia de cada tipo,
    severidad, dimensiones y área afectada, SIN inferencia). Por tramo y tipo de Python: ROI analizadas y con el
    tipo, nº de detecciones, longitud / ancho (mm) / área (m²) con media, mín., máx. y DE, área total y % de área
    afectada. `campo`: frecuencias absolutas y relativas del tipo de campo y de la severidad oficial (obs. 1).
    Usa, por tramo, la última ejecución validada de cada ROI del `rol`."""
    from app import logica_tramos
    codigos = list(tramos) if tramos else [x["codigo"] for x in logica_tramos.listar_tramos()]
    filas, campo, adv, prov = [], [], [], False
    for c in codigos:
        ids = lv.ejecuciones_validadas(c, metodo, rol)
        if not ids:
            adv.append(f"{c}: sin ejecuciones validadas (rol '{rol}', método '{metodo}'); se omite")
            continue
        datos, p = _datos_roi(ids, c, rol)
        prov = prov or p
        area_total = 0.0
        for d in datos.values():
            g = float(d["ejecucion"]["params_json"]["gsd_cm"]) / 100.0
            r = d["roi"]
            area_total += (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) * g ** 2
        for tipo in TIPOS:
            dets = [x for d in datos.values() for x in d["dets"] if x["tipo"] == tipo]
            n_roi_tipo = sum(1 for d in datos.values() if any(x["tipo"] == tipo for x in d["dets"]))
            area = sum(x["area_m2"] or 0.0 for x in dets)
            filas.append({"tramo": c, "tipo": tipo, "n_rois": len(datos), "n_rois_con_tipo": n_roi_tipo,
                          "pct_rois_con_tipo": 100.0 * n_roi_tipo / len(datos), "n_detecciones": len(dets),
                          "longitud_m": _desc(x["longitud_m"] for x in dets),
                          "ancho_mm": _desc(x["ancho_mm"] if x.get("ancho_mm") is not None else
                                            (x["ancho_m"] * 1000.0 if x.get("ancho_m") else None) for x in dets),
                          "area_m2": _desc(x["area_m2"] for x in dets), "area_total_m2": area,
                          "pct_area_afectada": _f(_div(100.0 * area, area_total))})
        tipos_c = [d["roi"]["tipo_campo"] for d in datos.values()]
        sev = [_severidad_oficial(rid).get(1) for rid in datos]
        n = len(datos)
        campo.append({"tramo": c, "n_rois": n,
                      "tipo_campo": {t: {"n": tipos_c.count(t), "pct": 100.0 * tipos_c.count(t) / n} for t in TIPOS_Y_SANO},
                      "severidad": {s: {"n": sev.count(s), "pct": 100.0 * sev.count(s) / n} for s in NIVELES},
                      "sin_severidad": sev.count(None)})
    if len(campo) < 2:
        adv.append("hay menos de 2 tramos con validación: no hay nada que comparar todavía")
    adv.insert(0, "Comparación DESCRIPTIVA entre tramos, sin inferencia estadística (plan de tesis, 5.5).")
    if prov:
        adv.insert(0, "PROVISIONAL: parámetros sin calibrar con datos reales.")
    return {"tramos": [c["tramo"] for c in campo], "filas": filas, "campo": campo, "metodo": metodo, "rol": rol,
            "provisional": prov, "advertencias": adv}
