"""F7 · comparación 'actual' vs 'sun': casos forzados con resultado conocido y recorrido de punta a punta."""
import pytest

from app import logica_comparacion as lc, logica_deteccion as ld, logica_roi as lr, logica_tramos as lt
from app import logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.nucleo import pipeline
from app.nucleo.estructuras import TIPOS_GRIETA
from app.nucleo.parametros import Params
from tests.test_validacion import crear_ejecucion, rois_prueba   # noqa: F401  (fixture)


def _forzado(rois_prueba):
    """A acierta todo; B falla R02 (FN de longitudinal) y R05 (FP de longitudinal). Medidas en R01 transversal."""
    tramo, r = rois_prueba
    for roi, dets in (("R01", [{"tipo": "transversal", "longitud_m": 4.0, "ancho_mm": 30.0, "area_m2": 0.12}]),
                      ("R02", [{"tipo": "longitudinal", "longitud_m": 5.0, "ancho_mm": 20.0, "area_m2": 0.1}]),
                      ("R05", [])):
        lv.evaluar(tramo, [crear_ejecucion(tramo, r[roi], dets, metodo="actual")])
    for roi, dets in (("R01", [{"tipo": "transversal", "longitud_m": 4.2, "ancho_mm": 28.0, "area_m2": 0.12}]),
                      ("R02", []),
                      ("R05", [{"tipo": "longitudinal", "longitud_m": 1.0, "ancho_mm": 10.0, "area_m2": 0.01}])):
        lv.evaluar(tramo, [crear_ejecucion(tramo, r[roi], dets, metodo="sun")])
    return tramo


def test_sun_declara_que_solo_detecta_grietas_lineales():
    assert pipeline.tipos_del_metodo("sun") == TIPOS_GRIETA
    assert "bache" in pipeline.tipos_del_metodo("actual")


def test_comparacion_forzada_cifras_conocidas(rois_prueba):
    tramo = _forzado(rois_prueba)
    c = lc.comparar_metodos(tramo)
    assert c["metodos"] == ["actual", "sun"] and c["tipos"] == ["longitudinal", "transversal"]
    assert c["n_unidades"] == 6 and sorted(c["rois"]) == ["R01", "R02", "R05"]
    a, b = c["metricas"]["actual"]["global"], c["metricas"]["sun"]["global"]
    assert (a["vp"], a["fp"], a["fn"], a["vn"]) == (2, 0, 0, 4) and a["f1"]["valor"] == 1.0
    assert (b["vp"], b["fp"], b["fn"], b["vn"]) == (1, 1, 1, 3) and b["f1"]["valor"] == pytest.approx(0.5)
    assert b["exactitud"]["valor"] == pytest.approx(4 / 6)
    m = c["mcnemar"]["global"]
    assert (m["n"], m["ambos_aciertan"], m["solo_a"], m["solo_b"], m["ambos_fallan"]) == (6, 4, 2, 0, 0)
    assert m["p"] == pytest.approx(0.5) and m["metodo"].startswith("exacto")
    por = c["mcnemar"]["por_tipo"]["longitudinal"]
    assert (por["solo_a"], por["solo_b"]) == (2, 0)


def test_diferencias_de_medidas_entre_metodos(rois_prueba):
    c = lc.comparar_metodos(_forzado(rois_prueba))
    e = c["medidas"]["global"]["longitud_m"]
    assert e["n"] == 1 and e["sesgo"] == pytest.approx(0.2)                 # B − A en el único par (R01, transversal)
    assert c["medidas"]["global"]["ancho_mm"]["sesgo"] == pytest.approx(-2.0)
    assert e["bland_altman"] is None and any("n = 1" in x for x in e["advertencias"])
    assert c["medidas"]["pares"][0]["tipo"] == "transversal"


def test_conclusiones_salen_de_las_cifras_y_son_prudentes(rois_prueba):
    c = lc.comparar_metodos(_forzado(rois_prueba))
    txt = "\n".join(c["conclusiones"])
    assert c["conclusiones"][0].startswith("PROVISIONAL") and c["provisional"] is True
    assert "6 unidades" in txt and "El F1 global es mayor en 'actual'" in txt and "1.00" in txt and "0.50" in txt
    assert "McNemar sobre 6 unidades: 2 las acierta solo 'actual' y 0 solo 'sun' (p = 0.500" in txt
    assert "no hay diferencia significativa" in txt
    assert "muy poca potencia" in txt                                         # n < 10: no concluye
    assert "sesgo 0.200 m" in txt


def test_sin_validacion_de_un_metodo_se_pide_validar(rois_prueba):
    tramo, r = rois_prueba
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="actual")])
    with pytest.raises(ErrorValidacion, match="método 'sun'"):
        lc.comparar_metodos(tramo)
    with pytest.raises(ErrorValidacion, match="distintos"):
        lc.comparar_metodos(tramo, "actual", "actual")
    with pytest.raises(ErrorValidacion, match="no disponible"):
        lc.comparar_metodos(tramo, "actual", "otro")


def test_parametros_base_distintos_se_advierten(rois_prueba):
    tramo, r = rois_prueba
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="actual")])
    ej = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="sun")
    from app import basedatos
    from app.modelos import EjecucionAnalisis
    p = Params(gsd_cm=0.5).con(grieta_k_mad=7.0)
    with basedatos.nueva_sesion() as s:
        e = s.get(EjecucionAnalisis, ej)
        e.params_json, e.params_huella = p.a_dict(), p.huella()
    lv.evaluar(tramo, [ej], metodo="sun")
    c = lc.comparar_metodos(tramo)
    assert c["mismos_params_base"] is False and any("NO usaron los mismos Params base" in a for a in c["advertencias"])


def test_solo_cuentan_las_roi_validadas_con_ambos(rois_prueba):
    tramo, r = rois_prueba
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="actual")])
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R02"], [{"tipo": "longitudinal"}], metodo="actual")])
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="sun")])
    c = lc.comparar_metodos(tramo)
    assert c["rois"] == ["R01"] and any("Solo 1 ROI" in a for a in c["advertencias"])


# ---------------------------------------------------------------- punta a punta con el motor real
@pytest.fixture
def e2e(tramo, tmp_path):
    from app import logica_importacion as li
    from tests.test_importacion import CSV_LEGADO, _csv
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    for x in lr.listar_rois(tramo):
        lr.cambiar_rol(x["id"], "prueba")
    return tramo


def test_e2e_ambos_metodos_misma_referencia_y_mismos_params(e2e):
    tramo = e2e
    marcas = []
    res = lc.ejecutar_y_validar(tramo, progreso=lambda f, t: marcas.append(f))
    assert set(res) == {"actual", "sun"} and marcas[-1] == pytest.approx(1.0)
    huellas = {e["params_huella"] for m in res for e in res[m]["ejecuciones"]}
    assert len(huellas) == 1                                                  # mismos Params (mismo JSON v2)
    c = lc.comparar_metodos(tramo)
    assert c["n_unidades"] == 10 and c["tipos"] == ["longitudinal", "transversal"] and c["mismos_params_base"]
    for m in ("actual", "sun"):
        g = c["metricas"][m]["global"]
        assert g["vp"] + g["fp"] + g["fn"] + g["vn"] == 10
        assert g["vp"] == 2                                                   # la transversal y la longitudinal del ejemplo
    assert c["provisional"] is True and c["conclusiones"][0].startswith("PROVISIONAL")
    # los pares de medidas son las dos grietas dibujadas; las longitudes de ambos métodos coinciden en pocos %
    pares = [p for p in c["medidas"]["pares"] if p["variable"] == "longitud_m"]
    assert len(pares) == 2
    for p in pares:
        assert p["b"] == pytest.approx(p["a"], rel=0.06)
    # rendimiento: tiempo medido y RAM (en Linux) para ambos
    for m in ("actual", "sun"):
        r = c["rendimiento"][m]
        assert r["segundos"] > 0 and r["s_por_mpx"] > 0 and r["n_ejecuciones"] == 5
    assert c["rendimiento"]["razon_tiempo"] is not None
    # 'sun' relee el ortomosaico (2 pasadas de preparación): no puede ser más rápido que 'actual' por construcción?
    # (no se afirma nada del tiempo relativo: solo que ambos son números)


def test_e2e_la_ram_queda_guardada_por_ejecucion(e2e):
    import sys
    ej = ld.analizar(e2e, roi_id=lr.listar_rois(e2e)[0]["id"], metodo="sun")
    r = ld.rendimiento_de([ej["id"]])[ej["id"]]
    assert r["duracion_s"] >= 0 and r["mpx"] > 0 and r["metodo"] == "sun"
    if sys.platform.startswith("linux"):
        assert r["ram_pico_mb"] > 0 and r["ram_adicional_mb"] >= 0


# ---------------------------------------------------------------- reportes F6 con la comparación de métodos
def test_reportes_incluyen_la_comparacion_de_metodos(rois_prueba, tmp_path):
    import openpyxl
    from pypdf import PdfReader
    from app import logica_reportes as lrep
    from app import reportes_tablas as rt
    tramo = _forzado(rois_prueba)
    d = lrep.recopilar(tramo)
    cm = d["comparacion_metodos"]
    assert cm and cm["n_unidades"] == 6
    # las tablas se construyen desde `datos`: mismas cifras que la comparación
    fm = rt.filas_tabla(d, "metodos_metricas")
    glob = [f for f in fm if f["tipo"] == "Todos los comparables"]
    assert [(f["metodo"], f["vp"], f["fp"], f["fn"], f["vn"]) for f in glob] == [("actual", 2, 0, 0, 4), ("sun", 1, 1, 1, 3)]
    assert rt.filas_tabla(d, "metodos_mcnemar")[0]["p"] == pytest.approx(0.5)
    assert any("Comparación de métodos" in c for c in d["conclusiones"])
    res = lrep.escribir_reportes(d, str(tmp_path), ("pdf", "xlsx"))
    wb = openpyxl.load_workbook(res["archivos"]["xlsx"])
    for hoja in ("Métodos Métricas", "Métodos McNemar", "Métodos Medidas", "Métodos Rendimiento"):
        assert hoja in wb.sheetnames
    ws = wb["Métodos Métricas"]
    textos = [str(c.value) for fila in ws.iter_rows() for c in fila if c.value is not None]
    assert "sun" in textos and "actual" in textos
    texto = "".join(p.extract_text() for p in PdfReader(res["archivos"]["pdf"]).pages)
    assert "Comparación de métodos" in texto and "McNemar" in texto and "PROVISIONAL" in texto


def test_el_reporte_sin_validacion_de_sun_no_trae_comparacion(rois_prueba):
    from app import logica_reportes as lrep
    tramo, r = rois_prueba
    lv.evaluar(tramo, [crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="actual")])
    d = lrep.recopilar(tramo)
    assert d["comparacion_metodos"] is None
