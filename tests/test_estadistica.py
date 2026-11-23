"""F5 · estadística: cada métrica se verifica contra scipy / scikit-learn / statsmodels y con casos de resultado conocido."""
import numpy as np
import pytest
from scipy import stats

skm = pytest.importorskip("sklearn.metrics")                                  # verificación independiente (opcional)
sm_mcnemar = pytest.importorskip("statsmodels.stats.contingency_tables").mcnemar
proportion_confint = pytest.importorskip("statsmodels.stats.proportion").proportion_confint

from app import logica_configuracion as cfg, logica_estadistica as le, logica_fichas as lf, logica_roi as lr
from app import logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.nucleo.estructuras import TIPOS
from tests.test_validacion import crear_ejecucion, rois_prueba   # noqa: F401  (fixture)


# ------------------------------------------------------------------ Wilson y métricas binarias
@pytest.mark.parametrize("k,n", [(0, 10), (10, 10), (3, 7), (45, 60), (1, 2), (0, 1)])
def test_wilson_igual_a_statsmodels(k, n):
    lo, hi = le.wilson(k, n)
    slo, shi = proportion_confint(k, n, alpha=0.05, method="wilson")
    assert lo == pytest.approx(slo, abs=1e-9) and hi == pytest.approx(shi, abs=1e-9)
    lo99, hi99 = le.wilson(k, n, conf=0.99)
    s99 = proportion_confint(k, n, alpha=0.01, method="wilson")
    assert (lo99, hi99) == pytest.approx(s99, abs=1e-9)


def test_wilson_sin_casos_es_none():
    assert le.wilson(0, 0) == (None, None)


def test_metricas_binarias_contra_sklearn():
    rng = np.random.default_rng(3)
    y = rng.integers(0, 2, 200)
    p = np.where(rng.random(200) < 0.8, y, 1 - y)                     # ~80 % de acierto
    vp, fp = int(((y == 1) & (p == 1)).sum()), int(((y == 0) & (p == 1)).sum())
    fn, vn = int(((y == 1) & (p == 0)).sum()), int(((y == 0) & (p == 0)).sum())
    m = le.metricas_binarias(vp, fp, fn, vn)
    assert m["sensibilidad"]["valor"] == pytest.approx(skm.recall_score(y, p))
    assert m["especificidad"]["valor"] == pytest.approx(skm.recall_score(y, p, pos_label=0))
    assert m["precision"]["valor"] == pytest.approx(skm.precision_score(y, p))
    assert m["exactitud"]["valor"] == pytest.approx(skm.accuracy_score(y, p))
    assert m["f1"]["valor"] == pytest.approx(skm.f1_score(y, p))
    lo, hi = proportion_confint(vp, vp + fn, method="wilson")
    assert m["sensibilidad"]["ic95"] == pytest.approx([lo, hi]) and m["sensibilidad"]["n"] == vp + fn
    assert m["advertencias"] == []


def test_division_por_cero_devuelve_none_no_cero():
    m = le.metricas_binarias(0, 0, 0, 5)                                # no hay positivos ni detecciones
    assert m["sensibilidad"]["valor"] is None and m["sensibilidad"]["ic95"] is None
    assert m["precision"]["valor"] is None and m["f1"]["valor"] is None
    assert m["especificidad"]["valor"] == 1.0 and m["exactitud"]["valor"] == 1.0
    assert any("sensibilidad" in a and "denominador 0" in a for a in m["advertencias"])
    assert le.metricas_binarias(0, 0, 0, 0)["exactitud"]["valor"] is None


def test_n_pequeno_advierte_que_el_ic_no_es_fiable():
    m = le.metricas_binarias(3, 0, 1, 2)
    assert any("sensibilidad" in a and "no es fiable" in a for a in m["advertencias"])
    assert m["sensibilidad"]["ic95"] is not None                         # se calcula, pero se advierte
    assert not any("exactitud" in a for a in m["advertencias"])          # n = 6 >= 5


def test_bootstrap_f1_contiene_el_valor_y_es_reproducible():
    u = [(1, 0, 0, 0)] * 8 + [(0, 0, 1, 0)] * 2 + [(0, 1, 0, 0)] * 2 + [(0, 0, 0, 1)] * 8
    f1 = le.f1_de(8, 2, 2)
    ic = le.ic_f1_bootstrap(u)
    assert ic[0] <= f1 <= ic[1] and ic == le.ic_f1_bootstrap(u) and 0 <= ic[0] < ic[1] <= 1
    assert le.ic_f1_bootstrap([(1, 0, 0, 0)]) is None
    assert le.ic_f1_bootstrap([(0, 0, 0, 1)] * 5) is None                # F1 no definido


# ------------------------------------------------------------------ kappa y matriz de confusión
def test_kappa_uno_y_cero_conocidos():
    ref = ["a", "b", "a", "b", "a", "b"]
    k1 = le.kappa(ref, ref, umbral=0.6)
    assert k1["kappa"] == pytest.approx(1.0) and k1["concordante"] is True and k1["interpretacion"] == "casi perfecta"
    k0 = le.kappa([0, 0, 1, 1], [0, 1, 0, 1], etiquetas=[0, 1], umbral=0.6)       # acuerdo = azar
    assert k0["kappa"] == pytest.approx(0.0) and k0["concordante"] is False
    kn = le.kappa([0, 0, 1, 1], [1, 1, 0, 0], etiquetas=[0, 1])                    # desacuerdo total
    assert kn["kappa"] == pytest.approx(-1.0) and kn["interpretacion"] == "pobre"


def test_kappa_no_definido_es_none():
    k = le.kappa([1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1], etiquetas=[0, 1])           # pe = 1
    assert k["kappa"] is None and k["concordante"] is None
    assert le.kappa([], [], etiquetas=[0, 1])["kappa"] is None


def test_kappa_contra_sklearn_sin_pesos_y_con_pesos():
    rng = np.random.default_rng(11)
    y = rng.integers(0, 3, 120)
    p = np.where(rng.random(120) < 0.65, y, rng.integers(0, 3, 120))
    et = ["Baja", "Media", "Alta"]
    a, b = [et[i] for i in y], [et[i] for i in p]
    assert le.kappa(a, b, et)["kappa"] == pytest.approx(skm.cohen_kappa_score(a, b, labels=et))
    for w, sk in (("lineal", "linear"), ("cuadratico", "quadratic")):
        assert le.kappa(a, b, et, pesos=w)["kappa"] == pytest.approx(skm.cohen_kappa_score(a, b, labels=et, weights=sk))
    k = le.kappa(a, b, et)
    assert 0 < k["se"] < 0.2 and k["ic95"][0] < k["kappa"] < k["ic95"][1]


def test_umbral_de_concordancia_sale_de_configuracion(bd):
    ref = [0] * 10 + [1] * 10
    pred = ref[:]
    pred[0], pred[10] = 1, 0                                                          # kappa = 0.8
    assert le.kappa(ref, pred)["concordante"] is True                                 # umbral por defecto 0.60
    cfg.establecer("umbral_concordancia", 0.9)
    k = le.kappa(ref, pred)
    assert k["umbral"] == 0.9 and k["concordante"] is False


def test_matriz_de_confusion_contra_sklearn():
    ref = ["bache", "sano", "longitudinal", "bache", "sano", "transversal"]
    pred = ["bache", "bache", "longitudinal", "sano", "sano", "longitudinal"]
    et = ["longitudinal", "transversal", "piel_cocodrilo", "bache", "sano"]
    mc = le.matriz_confusion(ref, pred, et)
    assert mc["matriz"] == skm.confusion_matrix(ref, pred, labels=et).tolist() and mc["n"] == 6
    assert le.matriz_confusion(["x", "bache"], ["bache", "bache"], et)["descartados"] == 1


def test_kappa_de_conteos_equivale_a_sklearn():
    k = le.kappa_de_conteos(8, 2, 3, 7)
    y = [1] * 8 + [0] * 2 + [1] * 3 + [0] * 7
    p = [1] * 8 + [1] * 2 + [0] * 3 + [0] * 7
    assert k["kappa"] == pytest.approx(skm.cohen_kappa_score(y, p))


# ------------------------------------------------------------------ error de medidas
def test_error_con_sesgo_conocido_y_bland_altman():
    ref = np.array([10.0, 12, 15, 20, 25, 30])
    d = np.array([1.0, 2, 3, 2, 1, 3])                                                 # sesgo exacto = 2
    r = le.error_medidas(ref, ref + d)
    assert r["sesgo"] == pytest.approx(2.0) and r["mae"] == pytest.approx(2.0)
    assert r["rmse"] == pytest.approx(np.sqrt((d ** 2).mean()))
    ba = r["bland_altman"]
    sd = d.std(ddof=1)
    assert ba["sesgo"] == pytest.approx(2.0) and ba["sd"] == pytest.approx(sd)
    assert ba["loa_inf"] == pytest.approx(2 - 1.96 * sd, abs=2e-3) and ba["loa_sup"] == pytest.approx(2 + 1.96 * sd, abs=2e-3)
    tcrit = stats.t.ppf(0.975, 5)
    assert ba["ic_sesgo"] == pytest.approx([2 - tcrit * sd / np.sqrt(6), 2 + tcrit * sd / np.sqrt(6)])
    assert ba["medias"] == pytest.approx(((2 * ref + d) / 2).tolist())
    assert r["sesgo_rel_pct"] == pytest.approx(100 * 2.0 / ref.mean())


def test_error_correlaciones_y_prueba_t_contra_scipy():
    rng = np.random.default_rng(5)
    ref = rng.uniform(5, 50, 25)
    est = ref + 1.5 + rng.normal(0, 1.0, 25)
    r = le.error_medidas(ref, est)
    assert r["pearson"]["r"] == pytest.approx(stats.pearsonr(ref, est)[0])
    assert r["pearson"]["p"] == pytest.approx(stats.pearsonr(ref, est)[1])
    assert r["spearman"]["rho"] == pytest.approx(stats.spearmanr(ref, est)[0])
    w, p = stats.shapiro(est - ref)
    assert r["normalidad"]["W"] == pytest.approx(w) and r["normalidad"]["p"] == pytest.approx(p) and r["normalidad"]["normal"]
    assert r["prueba"]["nombre"].startswith("t de Student")
    assert r["prueba"]["p"] == pytest.approx(stats.ttest_rel(est, ref)[1])
    assert r["prueba"]["p"] < 0.05                                                      # el sesgo de 1.5 es detectable


def test_error_elige_wilcoxon_si_las_diferencias_no_son_normales():
    rng = np.random.default_rng(9)
    ref = rng.uniform(5, 50, 40)
    d = rng.exponential(2.0, 40)                                                         # asimétrica
    est = ref + d
    assert stats.shapiro(d)[1] < 0.05
    r = le.error_medidas(ref, est)
    assert r["normalidad"]["normal"] is False and r["prueba"]["nombre"].startswith("Wilcoxon")
    assert r["prueba"]["p"] == pytest.approx(stats.wilcoxon(est, ref)[1])


def test_error_casos_limite():
    assert le.error_medidas([], [])["sesgo"] is None
    r2 = le.error_medidas([1, 2], [2, 3])
    assert r2["sesgo"] == 1 and r2["bland_altman"] is None and any("n = 2" in a for a in r2["advertencias"])
    r = le.error_medidas([1, 2, 3, 4], [3, 4, 5, 6])                                     # diferencia constante
    assert r["sesgo"] == 2 and r["bland_altman"]["sd"] == 0 and r["prueba"] is None
    assert any("diferencias son iguales" in a for a in r["advertencias"])
    rc = le.error_medidas([5, 5, 5, 5], [4, 6, 5, 7])
    assert rc["pearson"] is None and any("constante" in a for a in rc["advertencias"])
    rn = le.error_medidas([1, np.nan, 3, 4], [2, 5, 4, np.nan])                          # descarta no finitos
    assert rn["n"] == 2
    assert le.error_medidas([0, 0, 0], [1, 2, 3])["sesgo_rel_pct"] is None
    with pytest.raises(ErrorValidacion):
        le.error_medidas([1, 2], [1])


# ------------------------------------------------------------------ McNemar
@pytest.mark.parametrize("b,c", [(3, 9), (0, 7), (10, 10), (30, 12), (5, 5), (40, 20)])
def test_mcnemar_contra_statsmodels(b, c):
    tabla = [[20, b], [c, 15]]
    r = le.mcnemar(b, c)
    sm = sm_mcnemar(tabla, exact=(b + c < 25), correction=True)
    assert r["p"] == pytest.approx(sm.pvalue, abs=1e-9)
    assert r["metodo"].startswith("exacto") == (b + c < 25)


def test_mcnemar_sin_discordantes():
    r = le.mcnemar(0, 0)
    assert r["p"] is None and r["metodo"] is None and r["advertencias"]


# ------------------------------------------------------------------ consultas sobre la BD
def _fijar_validacion(tramo, r, provisional=True, metodo="actual", acierta=None):
    """Una ejecución por ROI; `acierta` = {codigo: [tipos detectados]}. Devuelve ids y guarda Validacion."""
    acierta = acierta or {}
    ids = []
    for cod, roi in r.items():
        dets = [{"tipo": t} for t in acierta.get(cod, [])]
        ids.append(crear_ejecucion(tramo, roi, dets, provisional=provisional, metodo=metodo))
    return ids


def test_metricas_validacion_por_tipo_contra_conteo_manual(rois_prueba):
    tramo, r = rois_prueba
    # campo: R01 transversal, R02 longitudinal, R03 cocodrilo, R04 bache, R05 sano
    ids = _fijar_validacion(tramo, r, acierta={"R01": ["transversal"], "R02": [], "R03": ["piel_cocodrilo", "bache"],
                                               "R04": ["bache"], "R05": ["bache"]})
    lv.evaluar(tramo, ids)
    m = le.metricas_validacion(tramo=tramo)
    assert m["provisional"] is True and m["n_rois"] == 5 and any("PROVISIONAL" in a for a in m["advertencias"])
    b = m["por_tipo"]["bache"]                      # bache: ref en R04; detectado en R03 (FP), R04 (VP), R05 (FP)
    assert (b["vp"], b["fp"], b["fn"], b["vn"]) == (1, 2, 0, 2)
    assert b["sensibilidad"]["valor"] == 1.0 and b["precision"]["valor"] == pytest.approx(1 / 3)
    assert b["especificidad"]["valor"] == pytest.approx(0.5) and b["f1"]["valor"] == pytest.approx(0.5)
    lg = m["por_tipo"]["longitudinal"]              # R02 no detectada: FN; sin FP
    assert (lg["vp"], lg["fp"], lg["fn"], lg["vn"]) == (0, 0, 1, 4)
    assert lg["sensibilidad"]["valor"] == 0.0 and lg["precision"]["valor"] is None and lg["f1"]["valor"] == 0.0
    g = m["global"]
    tot = [m["por_tipo"][t] for t in TIPOS]
    assert g["vp"] == sum(x["vp"] for x in tot) and g["unidades"] == 20
    assert any("n = 1" in a or "n = 4" in a for a in m["advertencias"])        # n pequeño advertido
    assert m["umbral_concordancia"] == 0.60 and b["kappa"]["concordante"] in (True, False)


def test_metricas_validacion_exige_validacion_guardada_y_solo_prueba(rois_prueba):
    tramo, r = rois_prueba
    with pytest.raises(ErrorValidacion):
        le.metricas_validacion(tramo=tramo)
    with pytest.raises(ErrorValidacion):
        le.metricas_validacion()
    lr.cambiar_rol(r["R03"]["id"], "calibracion")
    ids = _fijar_validacion(tramo, r, provisional=False, acierta={"R01": ["transversal"]})
    lv.evaluar(tramo, ids)
    m = le.metricas_validacion(tramo=tramo)
    assert m["n_rois"] == 4 and m["provisional"] is False and not any("PROVISIONAL" in a for a in m["advertencias"])


def test_comparar_ejecuciones_mcnemar_unidades_comunes(rois_prueba):
    tramo, r = rois_prueba
    mejores = {"R01": ["transversal"], "R02": ["longitudinal"], "R03": ["piel_cocodrilo"], "R04": ["bache"]}
    peores = {"R01": ["transversal"], "R02": [], "R03": [], "R04": ["bache"], "R05": ["bache"]}
    ia = _fijar_validacion(tramo, r, acierta=mejores, metodo="actual")
    ib = _fijar_validacion(tramo, r, acierta=peores, metodo="sun")
    lv.evaluar(tramo, ia)
    lv.evaluar(tramo, ib)
    c = le.comparar_ejecuciones(ia, ib)
    assert c["n_unidades"] == 20 and (c["solo_a_acierta"], c["solo_b_acierta"]) == (3, 0)
    assert c["ambos_aciertan"] == 17 and c["ambos_fallan"] == 0
    assert c["mcnemar"]["p"] == pytest.approx(sm_mcnemar([[17, 3], [0, 0]], exact=True).pvalue)
    assert c["exactitud_a"] == 1.0 and c["exactitud_b"] == pytest.approx(17 / 20)
    assert c["metodos"] == [["actual"], ["sun"]] and c["provisional"] is True
    assert c["advertencias"] == [] or all("PROVISIONAL" in a for a in c["advertencias"] if "pares" not in a)
    sub = le.comparar_ejecuciones(ia, ib, tipo="longitudinal")
    assert sub["n_unidades"] == 5 and (sub["solo_a_acierta"], sub["solo_b_acierta"]) == (1, 0)
    with pytest.raises(ErrorValidacion):
        le.comparar_ejecuciones(ia[:1], ib[1:2])                    # sin unidades comunes


def test_concordancia_de_tipo_por_roi(rois_prueba):
    tramo, r = rois_prueba
    ids = _fijar_validacion(tramo, r, acierta={"R01": ["transversal"], "R02": ["transversal"],
                                               "R03": ["piel_cocodrilo"], "R04": [], "R05": []})
    c = le.concordancia_tipo(ids, tramo)
    mc = c["matriz"]
    i = {e: n for n, e in enumerate(mc["etiquetas"])}
    assert mc["matriz"][i["transversal"]][i["transversal"]] == 1
    assert mc["matriz"][i["longitudinal"]][i["transversal"]] == 1             # confundida
    assert mc["matriz"][i["bache"]][i["sano"]] == 1 and mc["matriz"][i["sano"]][i["sano"]] == 1
    assert c["n_rois"] == 5 and c["provisional"] is True
    assert le.tipo_predicho([]) == "sano"
    assert le.tipo_predicho([{"tipo": "bache", "area_m2": 1}, {"tipo": "longitudinal", "area_m2": 0.1},
                             {"tipo": "longitudinal", "area_m2": 0.1}]) == "longitudinal"


def test_concordancia_de_severidad_observadores_y_python(rois_prueba):
    tramo, r = rois_prueba
    i1 = lf.crear("inspeccion", {"fecha": "2026-05-01", "observador": 1}, tramo)
    i2 = lf.crear("inspeccion", {"fecha": "2026-05-02", "observador": 2}, tramo)
    sev = {"R01": ("Baja", "Baja"), "R02": ("Media", "Media"), "R03": ("Alta", "Media"), "R04": ("Alta", "Alta")}
    cod = {"R01": "GTR", "R02": "GLO", "R03": "GPC", "R04": "HUE"}
    for k, (s1, s2) in sev.items():
        lf.registrar_patologia(i1["id"], {"codigo": cod[k], "roi_id": r[k]["id"]}, severidad={"nivel": s1})
        lf.registrar_patologia(i2["id"], {"codigo": cod[k], "roi_id": r[k]["id"]}, severidad={"nivel": s2})
    eid = [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal", "severidad_prelim": "Baja"}]),
           crear_ejecucion(tramo, r["R02"], [{"tipo": "longitudinal", "severidad_prelim": "Alta"},
                                             {"tipo": "longitudinal", "severidad_prelim": "no resoluble (ancho < 2 px)"}]),
           crear_ejecucion(tramo, r["R03"], [{"tipo": "piel_cocodrilo"}])]
    c = le.concordancia_severidad(eid, tramo)
    ko = c["observadores"]
    et = ["Baja", "Media", "Alta"]
    a, b = ["Baja", "Media", "Alta", "Alta"], ["Baja", "Media", "Media", "Alta"]
    assert ko["kappa"] == pytest.approx(skm.cohen_kappa_score(a, b, labels=et, weights="linear"))
    assert ko["n"] == 4 and any("n = 4" in x for x in c["advertencias"])
    kp = c["python"]                                          # R01 Baja/Baja, R02 Media/Alta; R03 sin severidad de Python
    assert kp["n"] == 2 and kp["matriz"]["matriz"][1][2] == 1
    assert any("ORIENTATIVA" in x for x in c["advertencias"]) and c["provisional"] is True
    assert any("sin par" in x for x in c["advertencias"])
    sin_nada = le.concordancia_severidad(None, tramo)
    assert sin_nada["python"] is None and sin_nada["observadores"] is not None


def test_error_de_medidas_contra_ficha_4(rois_prueba):
    tramo, r = rois_prueba
    i1 = lf.crear("inspeccion", {"fecha": "2026-05-01", "observador": 1}, tramo)
    campo = {"R01": ("GTR", {"longitud_m": 3.0, "ancho_prom_mm": 2.0, "area_m2": 0.01}),
             "R02": ("GLO", {"longitud_m": 5.0, "ancho_prom_mm": 3.0, "area_m2": 0.02}),
             "R04": ("HUE", {"area_m2": 0.50, "ancho_prom_mm": 600.0, "longitud_m": 0.9}),
             "R03": ("GPC", {"area_m2": 1.2, "longitud_m": 6.0})}
    for k, (c, g) in campo.items():
        lf.registrar_patologia(i1["id"], {"codigo": c, "roi_id": r[k]["id"]}, geometria=g)
    py = {"R01": [{"tipo": "transversal", "longitud_m": 3.3, "ancho_mm": 2.5, "area_m2": 0.012}],
          "R02": [{"tipo": "longitudinal", "longitud_m": 4.0, "ancho_mm": 3.0, "area_m2": 0.018}],
          "R03": [{"tipo": "piel_cocodrilo", "longitud_m": 6.5, "area_m2": 1.0}],
          "R04": [{"tipo": "bache", "longitud_m": 1.0, "area_m2": 0.55}]}
    ids = []
    for k, roi in r.items():
        ids.append(crear_ejecucion(tramo, roi, py.get(k, [])))
    with lv.basedatos.nueva_sesion() as s:                        # el ancho del bache se guarda en metros (0.62 m)
        from app.modelos import Deteccion
        d = s.query(Deteccion).filter(Deteccion.tipo == "bache").one()
        d.ancho_m = 0.62
    out = le.error_de_medidas(ids, tramo)
    L = out["global"]["longitud_m"]
    assert L["n"] == 4 and L["sesgo"] == pytest.approx(np.mean([0.3, -1.0, 0.5, 0.1]))
    assert L["rmse"] == pytest.approx(np.sqrt(np.mean(np.square([0.3, -1.0, 0.5, 0.1]))))
    A = out["global"]["ancho_mm"]                                  # grietas en mm y bache 0.62 m -> 620 mm
    assert A["n"] == 3 and A["sesgo"] == pytest.approx(np.mean([0.5, 0.0, 20.0]))
    assert out["por_tipo"]["bache"]["area_m2"]["sesgo"] == pytest.approx(0.05)
    assert out["provisional"] is True and any("n = 4" in x or "n = 3" in x for x in out["advertencias"])


def test_tablas_de_conteo_y_porcentaje_de_area(rois_prueba):
    tramo, r = rois_prueba
    ids = [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal", "longitud_m": 2.0, "ancho_mm": 2.0, "area_m2": 0.01},
                                             {"tipo": "transversal", "longitud_m": 1.0, "ancho_mm": 4.0, "area_m2": 0.01}]),
           crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "area_m2": 0.36}]),
           crear_ejecucion(tramo, r["R03"], [{"tipo": "piel_cocodrilo", "area_m2": 0.5, "longitud_m": 4.0}])]
    t = le.tablas_conteo(ids, tramo)
    tr = t["totales"]["transversal"]
    assert tr["n"] == 2 and tr["longitud_m"] == pytest.approx(3.0) and tr["area_m2"] == pytest.approx(0.02)
    # áreas: R01 330x1000 px, R04 400x360 px, R03 500x450 px a 0.5 cm/px
    a = (330 * 1000 + 400 * 360 + 500 * 450) * 0.005 ** 2
    assert t["area_analizada_m2"] == pytest.approx(a)
    assert tr["pct_area_afectada"] == pytest.approx(100 * 0.02 / a)
    fila_r01 = next(f for f in t["por_roi"] if f["roi"] == "R01")
    assert fila_r01["ancho_medio_mm"] == 3.0 and fila_r01["ancho_max_mm"] == 4.0
    assert fila_r01["pct_area_afectada"] == pytest.approx(100 * 0.02 / (330 * 1000 * 0.005 ** 2))
    assert len(t["tablas"]["tabla2"]) == 1 and len(t["tablas"]["tabla3"]) == 1 and len(t["tablas"]["tabla4"]) == 1
    assert t["totales"]["longitudinal"] == {"n": 0, "longitud_m": 0.0, "area_m2": 0.0, "pct_area_afectada": 0.0,
                                             "rois_con_tipo": 0}
    assert t["provisional"] is True
    assert le.tablas_conteo(ids[0], rol="prueba")["n_rois"] == 1                 # sin tramo: se deduce de la ejecución


def test_una_roi_validada_dos_veces_cuenta_una_sola_vez_por_tramo(rois_prueba):
    tramo, r = rois_prueba
    vieja = crear_ejecucion(tramo, r["R01"], [])                                   # FN
    nueva = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])            # VP
    lv.evaluar(tramo, [vieja])
    lv.evaluar(tramo, [nueva])
    assert lv.ejecuciones_validadas(tramo) == [nueva]
    m = le.metricas_validacion(tramo=tramo)
    assert m["n_rois"] == 1 and m["por_tipo"]["transversal"]["vp"] == 1 and m["por_tipo"]["transversal"]["fn"] == 0
    assert lv.ejecuciones_validadas(tramo, metodo="sun") == []


def test_comparacion_descriptiva_entre_tramos(rois_prueba):
    from app import logica_tramos as lt
    tramo, r = rois_prueba
    e = [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal", "longitud_m": 2.0, "ancho_mm": 2.0, "area_m2": 0.01},
                                           {"tipo": "transversal", "longitud_m": 4.0, "ancho_mm": 4.0, "area_m2": 0.03}]),
         crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "area_m2": 0.36}])]
    lv.evaluar(tramo, e)
    lt.crear_tramo({"codigo": "T2"})
    roi2 = lr.crear_roi("T2", {"codigo": "A1", "tipo_campo": "bache", "x0": 0, "y0": 0, "x1": 400, "y1": 400, "rol": "prueba"})
    e2 = crear_ejecucion("T2", roi2, [{"tipo": "bache", "area_m2": 0.2, "longitud_m": 0.8}], provisional=False)
    lv.evaluar("T2", [e2])
    c = le.comparacion_tramos()
    assert c["tramos"] == ["T1", "T2"] and c["provisional"] is True and len(c["filas"]) == 8
    f = next(x for x in c["filas"] if x["tramo"] == "T1" and x["tipo"] == "transversal")
    assert f["n_detecciones"] == 2 and f["n_rois_con_tipo"] == 1 and f["n_rois"] == 2
    assert f["longitud_m"]["media"] == pytest.approx(3.0) and f["longitud_m"]["sd"] == pytest.approx(2 ** 0.5)
    assert (f["ancho_mm"]["min"], f["ancho_mm"]["max"]) == (2.0, 4.0)
    a = (330 * 1000 + 400 * 360) * 0.005 ** 2
    assert f["pct_area_afectada"] == pytest.approx(100 * 0.04 / a)
    b2 = next(x for x in c["filas"] if x["tramo"] == "T2" and x["tipo"] == "bache")
    assert b2["n_detecciones"] == 1 and b2["area_m2"]["sd"] is None and b2["pct_area_afectada"] == pytest.approx(100 * 0.2 / (400 * 400 * 0.005 ** 2))
    cT1 = c["campo"][0]
    assert cT1["tipo_campo"]["transversal"] == {"n": 1, "pct": 50.0} and cT1["sin_severidad"] == 2
    assert any("sin inferencia" in x for x in c["advertencias"])
    sola = le.comparacion_tramos(["T1"])
    assert any("menos de 2" in x for x in sola["advertencias"])
    from app.logica_comun import ErrorNoEncontrado
    with pytest.raises(ErrorNoEncontrado):
        le.comparacion_tramos(["T1", "T3"])                                   # un tramo que no existe no se ignora en silencio
