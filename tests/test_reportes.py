"""F6 · reportes: PDF (texto extraíble), XLSX (openpyxl), CSV; FP excluidos del conteo pero registrados; conclusiones solo con cifras."""
import csv
import os

import pytest

from app import logica_configuracion as cfg, logica_estadistica as le, logica_fichas as lf, logica_reportes as lrep
from app import logica_validacion as lv
from app.reportes_tablas import columnas
from app.logica_comun import ErrorValidacion
from app.nucleo.estructuras import TIPOS
from tests.test_validacion import crear_ejecucion, rois_prueba   # noqa: F401  (fixture)

openpyxl = pytest.importorskip("openpyxl")
pypdf = pytest.importorskip("pypdf")
pytest.importorskip("reportlab")


@pytest.fixture
def escenario(rois_prueba):
    """5 ROI de prueba validadas. Campo: R01 transversal, R02 longitudinal, R03 piel, R04 bache, R05 sano.
    Python: R01 transversal (VP) · R02 nada (FN) · R03 piel (VP) + bache (FP) · R04 bache (VP) · R05 bache (FP)."""
    tramo, r = rois_prueba
    i1 = lf.crear("inspeccion", {"fecha": "2026-05-01", "responsable": "JF", "observador": 1}, tramo)
    for k, (c, g, sev) in {"R01": ("GTR", {"longitud_m": 3.0, "ancho_prom_mm": 2.0, "area_m2": 0.01}, "Baja"),
                           "R02": ("GLO", {"longitud_m": 5.0, "ancho_prom_mm": 3.0, "area_m2": 0.02}, "Media"),
                           "R04": ("HUE", {"area_m2": 0.50, "ancho_prom_mm": 600.0, "longitud_m": 0.9}, "Alta")}.items():
        lf.registrar_patologia(i1["id"], {"codigo": c, "roi_id": r[k]["id"]}, geometria=g, severidad={"nivel": sev})
    lf.crear("vuelo", {"codigo": "V1", "fecha": "2026-05-02", "dron": "DJI Mavic 3", "altura_m": 20, "gsd_cm": 0.5}, tramo)
    py = {"R01": [{"tipo": "transversal", "longitud_m": 3.3, "ancho_mm": 2.5, "area_m2": 0.012, "severidad_prelim": "Baja"}],
          "R02": [],
          "R03": [{"tipo": "piel_cocodrilo", "longitud_m": 6.5, "area_m2": 1.0},
                  {"tipo": "bache", "longitud_m": 0.3, "area_m2": 0.2}],
          "R04": [{"tipo": "bache", "longitud_m": 1.0, "area_m2": 0.55}],
          "R05": [{"tipo": "bache", "longitud_m": 0.4, "area_m2": 0.3}]}
    ids = [crear_ejecucion(tramo, roi, py[k]) for k, roi in r.items()]
    lv.evaluar(tramo, ids)
    return tramo, r, ids


def _texto_pdf(ruta):
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(ruta).pages)


# ------------------------------------------------------------------ recopilación y conteo sin FP
def test_los_fp_no_entran_al_conteo_pero_quedan_registrados(escenario):
    tramo, r, ids = escenario
    d = lrep.recopilar(tramo)
    tb = d["tablas"]
    assert tb["totales"]["bache"]["n"] == 1                       # solo R04 (VP); R03 y R05 son FP
    assert tb["fp_excluidos"] == 2 and tb["excluye_fp"] is True
    bach = [x for x in d["detecciones"] if x["tipo"] == "bache"]
    assert len(bach) == 3                                         # las 3 siguen registradas
    assert sorted((x["roi"], x["estado_validacion"], x["incluida_en_conteo"]) for x in bach) == [
        ("R03", "FP", False), ("R04", "VP", True), ("R05", "FP", False)]
    d2 = lrep.recopilar(tramo, excluir_fp=False)
    assert d2["tablas"]["totales"]["bache"]["n"] == 3
    assert any("falso positivo" in a for a in tb["advertencias"])


def test_validacion_guardada_no_cambia_por_excluir_fp(escenario):
    tramo, _, _ = escenario
    a = le.metricas_validacion(tramo=tramo)["global"]
    lrep.recopilar(tramo)
    b = le.metricas_validacion(tramo=tramo)["global"]
    assert (a["vp"], a["fp"], a["fn"], a["vn"]) == (b["vp"], b["fp"], b["fn"], b["vn"])
    assert a["fp"] == 2 and a["fn"] == 1


def test_recopilar_sin_ejecuciones_da_error_claro(rois_prueba):
    with pytest.raises(ErrorValidacion, match="no tiene ejecuciones completadas"):
        lrep.recopilar(rois_prueba[0])


def test_sin_validacion_no_hay_conclusiones_de_desempeno(rois_prueba):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "area_m2": 0.5}])
    d = lrep.recopilar(tramo)
    assert d["meta"]["validado"] is False and d["meta"]["origen_ejecuciones"] == "ultimas"
    txt = " ".join(d["conclusiones"])
    assert "no emite conclusiones sobre el desempeño" in txt and "sensibilidad" not in txt and "Kappa" not in txt
    assert d["validacion"]["metricas"] is None and "validacion" in d["secciones_omitidas"]


def test_conclusiones_solo_con_cifras_calculadas(escenario):
    tramo, _, _ = escenario
    d = lrep.recopilar(tramo)
    c = d["conclusiones"]
    assert c[0].startswith("PROVISIONAL")
    g = le.metricas_validacion(tramo=tramo)["global"]
    assert any(f"sensibilidad {g['sensibilidad']['valor']:.2f}" in x for x in c)
    assert any("Kappa de presencia" in x and ("alcanza" in x or "no alcanza" in x) and "0.60" in x for x in c)
    assert any("No entran al conteo 2 detecciones" in x for x in c)
    assert not any(p in " ".join(c).lower() for p in ("excelente", "adecuado", "recomienda", "demuestra"))


# ------------------------------------------------------------------ PDF
def test_pdf_se_genera_se_reabre_y_tiene_texto_extraible(escenario, tmp_path):
    tramo, _, _ = escenario
    res = lrep.generar(tramo, str(tmp_path), formatos=("pdf",), autor="Autor Prueba", institucion="UNSAAC")
    assert res["omitidos"] == {} and res["provisional"] is True
    rd = pypdf.PdfReader(res["archivos"]["pdf"])
    assert len(rd.pages) >= 5
    t = _texto_pdf(res["archivos"]["pdf"])
    for s in ("Informe del tramo T1", "Autor Prueba", "PROVISIONAL", "Datos del tramo (Ficha 1)", "Tabla 4. Baches por ROI",
              "Conclusiones", "Métricas por tipo", "Kappa", "R04", "DJI Mavic 3", "Parámetros utilizados"):
        assert s in t, s
    assert "Página 1 de" in t and "Concordancia (%) = (VP + VN) / total" in t
    # imágenes de las Figure (conteos, métricas, matriz, dispersión) incrustadas
    n_img = sum(len(p.images) for p in rd.pages)
    assert n_img >= 4


def test_pdf_cifras_de_la_tabla_4_coinciden_con_la_bd(escenario, tmp_path):
    tramo, _, _ = escenario
    res = lrep.generar(tramo, str(tmp_path), formatos=("pdf",))
    t = _texto_pdf(res["archivos"]["pdf"])
    tb = le.tablas_conteo(lv.ejecuciones_validadas(tramo), tramo, "prueba", excluir_fp=True)
    f = tb["tablas"]["tabla4"][0]
    assert f["roi"] == "R04" and f["n"] == 1
    assert f"{f['area_m2']:.3f}" in t


def test_pdf_sin_validacion_dice_que_no_se_genera_esa_seccion(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "area_m2": 0.5}])
    res = lrep.generar(tramo, str(tmp_path), formatos=("pdf",))
    t = _texto_pdf(res["archivos"]["pdf"])
    assert "No hay validación guardada" in t and "Métricas por tipo" not in t


def test_pdf_con_caracteres_fuera_de_winansi_no_falla(escenario, tmp_path):
    tramo, _, _ = escenario
    d = lrep.recopilar(tramo, titulo="Tesis ≥ ρ ñ → “comillas”", autor="Ángel Núñez")
    ruta = lrep.generar_pdf(d, str(tmp_path / "x.pdf"))
    t = _texto_pdf(ruta)
    assert "Ángel Núñez" in t and ">= rho" in t


# ------------------------------------------------------------------ XLSX
def test_xlsx_una_hoja_por_tabla_con_filtros_y_sin_formulas(escenario, tmp_path):
    tramo, _, _ = escenario
    res = lrep.generar(tramo, str(tmp_path), formatos=("xlsx",))
    wb = openpyxl.load_workbook(res["archivos"]["xlsx"])
    esperadas = {"Resumen", "Detecciones", "Resumen por tipo", "Tabla 2 Grietas", "Tabla 3 Piel cocodrilo", "Tabla 4 Baches",
                 "Validación", "Métricas", "Concordancia", "Medidas", "Calidad de imagen", "Parámetros", "Ficha 1 Tramo",
                 "Ficha 5 Vuelo", "Fichas 2-4 Patologías"}
    assert esperadas <= set(wb.sheetnames)
    for ws in wb.worksheets:
        for fila in ws.iter_rows():
            for c in fila:
                assert c.data_type != "f", f"fórmula en {ws.title}!{c.coordinate}"
        if ws.title != "Resumen":
            assert ws.auto_filter.ref and ws.freeze_panes
            assert "PROVISIONAL" in str(ws["A2"].value)
    ws = wb["Detecciones"]
    enc = [c.value for c in ws[5]]
    assert "Incluida en el conteo" in enc and "Estado de validación" in enc
    filas = list(ws.iter_rows(min_row=6, values_only=True))
    assert len(filas) == 5                                         # 1+0+2+1+1 detecciones
    i_inc, i_est = enc.index("Incluida en el conteo"), enc.index("Estado de validación")
    assert sorted(f[i_est] for f in filas if f[i_inc] == "No") == ["FP", "FP"]
    v = wb["Validación"]
    assert v.max_row - 5 == 20                                     # 5 ROI × 4 tipos
    m = wb["Métricas"]
    cab = [c.value for c in m[5]]
    glob = next(r for r in m.iter_rows(min_row=6, values_only=True) if r[0] == "Todos los tipos")
    g = le.metricas_validacion(tramo=tramo)["global"]
    assert glob[cab.index("Sensibilidad")] == pytest.approx(g["sensibilidad"]["valor"])
    assert glob[cab.index("Sens. IC95 inf.")] == pytest.approx(g["sensibilidad"]["ic95"][0])


def test_xlsx_texto_que_parece_formula_se_guarda_como_texto(escenario, tmp_path):
    tramo, r, _ = escenario
    lf.crear("vuelo", {"codigo": "V2", "observaciones": "=SUMA(A1:A2)"}, tramo)
    d = lrep.recopilar(tramo)
    ruta = lrep.generar_xlsx(d, str(tmp_path / "f.xlsx"))
    ws = openpyxl.load_workbook(ruta)["Ficha 5 Vuelo"]
    vals = [c for fila in ws.iter_rows(min_row=6) for c in fila if c.value == "=SUMA(A1:A2)"]
    assert vals and vals[0].data_type == "s"


def test_xlsx_sin_validacion_omite_las_hojas_de_estadistica(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "area_m2": 0.5}])
    res = lrep.generar(tramo, str(tmp_path), formatos=("xlsx",))
    wb = openpyxl.load_workbook(res["archivos"]["xlsx"])
    assert "Métricas" not in wb.sheetnames and "Validación" not in wb.sheetnames and "Detecciones" in wb.sheetnames


def test_xlsx_estadistica_avanzada_agrega_columnas(escenario, tmp_path):
    tramo, _, _ = escenario
    d0 = lrep.recopilar(tramo)
    c0 = [c[1] for c in columnas(d0, "medidas")]
    assert "Pearson r" not in c0
    cfg.establecer("estadistica_avanzada", True)
    d1 = lrep.recopilar(tramo)
    c1 = [c[1] for c in columnas(d1, "medidas")]
    assert "Pearson r" in c1 and d1["meta"]["avanzada"] is True
    ruta = lrep.generar_xlsx(d1, str(tmp_path / "a.xlsx"))
    assert "Pearson r" in [c.value for c in openpyxl.load_workbook(ruta)["Medidas"][5]]


# ------------------------------------------------------------------ CSV
def test_csv_utf8_con_bom_y_separador_punto_y_coma(escenario, tmp_path):
    tramo, _, _ = escenario
    d = lrep.recopilar(tramo)
    a = lrep.generar_csv_detecciones(d, str(tmp_path / "a.csv"))
    b = lrep.generar_csv_detecciones(d, str(tmp_path / "b.csv"), separador=";", decimal=",")
    assert open(a, "rb").read(3) == b"\xef\xbb\xbf" and open(b, "rb").read(3) == b"\xef\xbb\xbf"
    fa = list(csv.DictReader(open(a, encoding="utf-8-sig", newline="")))
    fb = list(csv.DictReader(open(b, encoding="utf-8-sig", newline=""), delimiter=";"))
    assert len(fa) == len(fb) == 5
    x = next(f for f in fa if f["ROI"] == "R01")
    y = next(f for f in fb if f["ROI"] == "R01")
    assert x["Longitud (m)"] == "3.3" and y["Longitud (m)"] == "3,3"
    assert x["Incluida en el conteo"] == "Sí" and x["Estado de validación"] == "VP"
    assert sum(1 for f in fa if f["Incluida en el conteo"] == "No") == 2
    assert "Estado de validación" in open(b, encoding="utf-8-sig").readline()
    assert open(b, encoding="utf-8-sig").readline().count(";") == len(fb[0]) - 1


def test_csv_validacion_una_celda_por_unidad(escenario, tmp_path):
    tramo, _, _ = escenario
    ruta = lrep.generar_csv_validacion(lrep.recopilar(tramo), str(tmp_path / "v.csv"))
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig", newline="")))
    assert len(filas) == 20
    for f in filas:
        assert int(f["VP"]) + int(f["FP"]) + int(f["FN"]) + int(f["VN"]) == 1
        assert f["Resultado"] == [c for c in ("VP", "FP", "FN", "VN") if f[c] == "1"][0]
    assert sum(int(f["FP"]) for f in filas) == 2 and sum(int(f["FN"]) for f in filas) == 1


def test_csv_separadores_incompatibles_se_rechazan(escenario, tmp_path):
    d = lrep.recopilar(escenario[0])
    with pytest.raises(lrep.ErrorReporte, match="no pueden ser el mismo"):
        lrep.generar_csv_detecciones(d, str(tmp_path / "x.csv"), separador=",", decimal=",")
    with pytest.raises(lrep.ErrorReporte, match="separador"):
        lrep.generar_csv_detecciones(d, str(tmp_path / "x.csv"), separador="|")


# ------------------------------------------------------------------ orquestación y errores
def test_generar_todo_y_nombres_de_archivo(escenario, tmp_path):
    tramo, _, _ = escenario
    res = lrep.generar(tramo, str(tmp_path / "salida" / "sub"))
    assert set(res["archivos"]) == {"pdf", "xlsx", "csv_detecciones", "csv_validacion"} and not res["omitidos"]
    for ruta in res["archivos"].values():
        assert os.path.getsize(ruta) > 500 and os.path.basename(ruta).startswith("informe_T1_")


def test_formato_desconocido_o_vacio(escenario, tmp_path):
    d = lrep.recopilar(escenario[0])
    with pytest.raises(lrep.ErrorReporte, match="desconocido"):
        lrep.escribir_reportes(d, str(tmp_path), ("doc",))
    with pytest.raises(lrep.ErrorReporte, match="al menos un formato"):
        lrep.escribir_reportes(d, str(tmp_path), ())


def test_archivo_abierto_o_sin_permiso_se_informa_sin_perder_los_demas(escenario, tmp_path, monkeypatch):
    d = lrep.recopilar(escenario[0])
    original = lrep.generar_xlsx

    def falla(datos, ruta):
        raise PermissionError(13, "denegado")
    monkeypatch.setattr(lrep, "generar_xlsx", falla)
    res = lrep.escribir_reportes(d, str(tmp_path), ("pdf", "xlsx"))
    assert "pdf" in res["archivos"] and "xlsx" in res["omitidos"] and "abierto en otro programa" in res["omitidos"]["xlsx"]
    monkeypatch.setattr(lrep, "generar_xlsx", original)


def test_carpeta_de_destino_invalida(escenario, tmp_path):
    d = lrep.recopilar(escenario[0])
    archivo = tmp_path / "no_es_carpeta"
    archivo.write_text("x")
    with pytest.raises(lrep.ErrorReporte, match="carpeta de destino"):
        lrep.escribir_reportes(d, str(archivo / "sub"), ("csv",))


def test_ejecucion_de_otro_tramo_se_rechaza(escenario):
    from app import logica_tramos as lt
    tramo, r, ids = escenario
    lt.crear_tramo({"codigo": "T9"})
    with pytest.raises(ErrorValidacion, match="no pertenece al tramo T9"):
        lrep.recopilar("T9", ejecucion_ids=ids[:1])


def test_progreso_y_cancelacion(escenario, tmp_path):
    import threading
    d = lrep.recopilar(escenario[0])
    marcas = []
    ev = threading.Event()
    ev.set()
    res = lrep.escribir_reportes(d, str(tmp_path), ("pdf", "csv"), cancelar=ev, progreso=lambda f, m: marcas.append(f))
    assert res["archivos"] == {} and set(res["omitidos"].values()) == {"cancelado"}
    marcas = []
    res = lrep.escribir_reportes(d, str(tmp_path), ("csv",), progreso=lambda f, m: marcas.append((f, m)))
    assert marcas[0][0] == 0.0 and marcas[-1] == (1.0, "Listo") and len(res["archivos"]) == 2
