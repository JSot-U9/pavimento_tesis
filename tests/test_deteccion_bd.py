"""De punta a punta: CSV de ROI -> BD -> análisis -> detecciones guardadas -> consultas."""
import threading

import numpy as np
import pytest

from app import basedatos, logica_configuracion as cfg, logica_deteccion as ld, logica_importacion as li
from app import logica_roi as lr, logica_tramos as lt
from app.logica_comun import ErrorValidacion
from app.modelos import Deteccion
from app.nucleo.estructuras import AnalisisCancelado
from app.nucleo.parametros import Params
from tests.test_importacion import CSV_LEGADO, _csv


@pytest.fixture
def con_rois(tramo, tmp_path):
    assert li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))["creados"] == 5
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    return tramo


def test_analisis_por_roi_guarda_lo_esperado(con_rois):
    ejec = ld.analizar_rois(con_rois)
    assert len(ejec) == 5 and all(e["estado"] == "completada" and e["alcance"] == "roi" for e in ejec)
    rois = {r["id"]: r for r in lr.listar_rois(con_rois)}
    por_codigo = {rois[e["roi_id"]]["codigo"]: ld.listar_detecciones(e["id"]) for e in ejec}
    assert [d["tipo"] for d in por_codigo["R01"]] == ["transversal"]
    assert [d["tipo"] for d in por_codigo["R02"]] == ["longitudinal"]
    assert [d["tipo"] for d in por_codigo["R03"]] == ["piel_cocodrilo"]
    assert [d["tipo"] for d in por_codigo["R04"]] == ["bache"]
    assert por_codigo["R05"] == []
    t, b, z = por_codigo["R01"][0], por_codigo["R04"][0], por_codigo["R03"][0]
    assert t["ancho_mm"] and t["ancho_m"] is None and t["roi_id"] and t["progresiva_m"] is not None
    assert t["desv_eje_deg"] > 80 and t["lado_via"] in ("derecha", "izquierda")
    assert b["ancho_m"] and b["ancho_mm"] is None and b["pct_area_afectada"] == pytest.approx(
        100 * b["area_m2"] / (400 * 360 * 0.005 ** 2), rel=0.01)
    assert z["ancho_mm"] is None and z["n_celdas"] >= 4 and z["densidad_pct"] and isinstance(z["geom_px"], list)
    assert z["este"] is None                                           # PNG sin georreferencia


def test_ejecucion_es_reproducible_y_marca_provisional_y_calidad(con_rois):
    base = Params().con(grieta_k_mad=5.0)
    cfg.guardar_params_base(base)
    roi = lr.listar_rois(con_rois)[0]
    e = ld.analizar(con_rois, roi_id=roi["id"])
    assert e["provisional"] is True and e["preprocesamiento"] == "Sí" and e["metodo"] == "actual"
    assert e["calidad"] == "Adecuada" and e["resolucion_cm_px"] == pytest.approx(0.5) and e["duracion_s"] >= 0
    p = ld.parametros_de_ejecucion(e["id"])
    assert p == base.con(gsd_cm=0.5) and p.huella() == e["params_huella"] and e["params_version"] == 2   # F7: esquema v2
    # tras cambiar la configuración, la ejecución vieja conserva sus parámetros
    cfg.guardar_params_base(Params().con(grieta_k_mad=3.0), calibrado=True)
    e2 = ld.analizar(con_rois, roi_id=roi["id"])
    assert e2["provisional"] is False and ld.parametros_de_ejecucion(e["id"]).grieta_k_mad == 5.0
    assert [x["id"] for x in ld.listar_ejecuciones(con_rois)] == [e2["id"], e["id"]]
    c = ld.caracteristicas_de(e["id"])
    assert len(c) == 1 and {"R_media", "G_desv", "B_max", "tex_entropia"} <= set(c[0]) and c[0]["roi_id"] == roi["id"]


def test_tramo_completo_asigna_la_roi_mas_pequena_que_contiene_el_centroide(con_rois):
    lr.crear_roi(con_rois, {"codigo": "GRANDE", "tipo_campo": "sano", "x0": 0, "y0": 0, "x1": 2400, "y1": 1400})
    e = ld.analizar(con_rois)
    assert e["alcance"] == "tramo" and e["roi_id"] is None and (e["x1"], e["y1"]) == (2400, 1400)
    cod = {r["id"]: r["codigo"] for r in lr.listar_rois(con_rois)}
    dets = ld.listar_detecciones(e["id"])
    asign = {d["tipo"]: cod[d["roi_id"]] for d in dets if d["roi_id"]}
    assert asign == {"transversal": "R01", "longitudinal": "R02", "piel_cocodrilo": "R03", "bache": "R04"}
    assert all(d["pct_area_afectada"] is not None for d in dets)
    assert set(ld.resumen_ejecucion(e["id"])) == {"transversal", "longitudinal", "piel_cocodrilo", "bache"}
    assert ld.listar_detecciones(e["id"], tipo="bache")[0]["roi_id"] is not None
    assert not ld.caracteristicas_de(e["id"])                          # solo se calculan por ROI


def test_ventana_libre(con_rois):
    e = ld.analizar(con_rois, region=(1750, 650, 2300, 1150))
    assert e["alcance"] == "ventana" and [d["tipo"] for d in ld.listar_detecciones(e["id"])] == ["bache"]


def test_cancelar_registra_incidencia_y_no_guarda_detecciones(con_rois):
    ev = threading.Event()
    ev.set()
    with pytest.raises(AnalisisCancelado):
        ld.analizar(con_rois, cancelar=ev)
    inc = ld.listar_ejecuciones(con_rois, estado="cancelada")
    assert len(inc) == 1 and inc[0]["calidad"] is None
    with basedatos.nueva_sesion() as s:
        assert s.query(Deteccion).count() == 0


def test_patron_de_hilos_calcula_en_hilo_y_guarda_en_el_principal(con_rois):
    roi = lr.listar_rois(con_rois)[1]
    trabajo = ld.preparar_analisis(con_rois, roi_id=roi["id"])
    salida, avances = {}, []
    hilo = threading.Thread(target=lambda: salida.update(r=ld.ejecutar_trabajo(trabajo, progreso=lambda f, t: avances.append(f))))
    hilo.start()
    hilo.join(120)
    assert not hilo.is_alive() and avances and avances[-1] == 1.0
    e = ld.guardar_resultado(trabajo, salida["r"])
    assert e["n_detecciones"] == 1 and trabajo.etiqueta == "R02"


def test_errores_de_preparacion(tramo, bd):
    with pytest.raises(ErrorValidacion, match="no disponible"):
        ld.preparar_analisis(tramo, metodo="inexistente")
    lt.crear_tramo({"codigo": "T3"})
    with pytest.raises(ErrorValidacion, match="sin ortomosaico|no tiene ortomosaico"):
        ld.preparar_analisis("T3")
    r = lr.crear_roi(tramo, {"codigo": "R", "tipo_campo": "bache", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
    with pytest.raises(ErrorValidacion, match="no ambos"):
        ld.preparar_analisis(tramo, roi_id=r["id"], region=(0, 0, 50, 50))
    with pytest.raises(ErrorValidacion, match="Ninguna|No hay ROI"):
        ld.analizar_rois(tramo, rol="prueba")


def test_ortomosaico_movido_da_mensaje_claro(con_rois, png_ejemplo, tmp_path):
    lt.actualizar_tramo(con_rois, {"observaciones": "x"})
    lt.asignar_ortomosaico(con_rois, png_ejemplo, gsd_cm=0.5)
    from app.modelos import Tramo
    with basedatos.nueva_sesion() as s:
        s.query(Tramo).one().ortomosaico_ruta = str(tmp_path / "no_existe.png")
    with pytest.raises(ErrorValidacion, match="No se encuentra el ortomosaico"):
        ld.preparar_analisis(con_rois)


def test_geotiff_guarda_coordenadas_del_mapa(bd, ejemplo, tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    ruta = str(tmp_path / "ej.tif")
    with rasterio.open(ruta, "w", driver="GTiff", width=2400, height=1400, count=3, dtype="uint8", crs="EPSG:32719",
                       transform=from_origin(177000.0, 8503000.0, 0.005, 0.005), tiled=True, blockxsize=256, blockysize=256) as d:
        d.write(np.moveaxis(ejemplo[0], -1, 0))
    lt.crear_tramo({"codigo": "G"})
    lt.asignar_ortomosaico("G", ruta)
    lr.crear_roi("G", {"codigo": "R04", "tipo_campo": "bache", "x0": 1700, "y0": 720, "x1": 2100, "y1": 1080})
    e = ld.analizar("G", roi_id=lr.listar_rois("G")[0]["id"])
    d = ld.listar_detecciones(e["id"])[0]
    assert d["este"] == pytest.approx(177000 + d["cx"] * 0.005) and d["norte"] == pytest.approx(8503000 - d["cy"] * 0.005)
    assert e["resolucion_cm_px"] == pytest.approx(0.5)


def test_eliminar_ejecucion_borra_sus_detecciones(con_rois):
    e = ld.analizar(con_rois, roi_id=lr.listar_rois(con_rois)[3]["id"])
    ld.eliminar_ejecucion(e["id"])
    with basedatos.nueva_sesion() as s:
        assert s.query(Deteccion).count() == 0
