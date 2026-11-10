"""F6 · exportación a QGIS: GeoPackage (sqlite3 + WKB) releído con leer_gpkg y con pyogrio/geopandas; GeoJSON; CRS; casos límite."""
import json
import os
import sqlite3

import numpy as np
import pytest

from app import geovector as gv, logica_exportacion as lx, logica_tramos as lt, logica_validacion as lv
from app.crs import convertir
from app.nucleo.geo import Transformacion
from tests.test_validacion import crear_ejecucion, rois_prueba   # noqa: F401  (fixture)

TR = Transformacion.norte_arriba(177000.0, 8503000.0, 0.005)       # 0.5 cm/px, UTM 19S


def _linea(x0, y0, n=5, paso=10):
    return [[x0 + i * paso, y0 + i * 2] for i in range(n)]


def _poligono(x0, y0, w=40, h=30):
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]


@pytest.fixture
def escenario_geo(rois_prueba):
    """T1 georreferenciado (EPSG 32719), eje, 5 ROI de prueba y detecciones con geometría; validado."""
    tramo, r = rois_prueba
    with lt.basedatos.nueva_sesion() as s:                          # georreferencia sin tocar el resto
        t = s.get(lt.Tramo, lt._resolver(s, tramo).id)
        t.transformacion, t.epsg = list(TR), 32719
    lt.definir_eje(tramo, [[200, 100], [220, 600], [260, 1000]])
    py = {"R01": [{"tipo": "transversal", "geom_px": _linea(160, 200), "geom_tipo": "polilinea_aprox",
                   "longitud_m": 3.3, "ancho_mm": 2.5, "area_m2": 0.012, "severidad_prelim": "Baja"}],
          "R02": [],
          "R03": [{"tipo": "piel_cocodrilo", "geom_px": _poligono(960, 110), "geom_tipo": "poligono", "area_m2": 1.0},
                  {"tipo": "bache", "geom_px": _poligono(1000, 200, 20, 20), "geom_tipo": "poligono", "area_m2": 0.2}],
          "R04": [{"tipo": "bache", "geom_px": _poligono(1710, 730, 50, 50), "geom_tipo": "poligono", "area_m2": 0.55}],
          "R05": [{"tipo": "bache", "geom_px": _poligono(1510, 1060, 30, 30), "geom_tipo": "poligono", "area_m2": 0.3}]}
    ids = [crear_ejecucion(tramo, roi, py[k]) for k, roi in r.items()]
    lv.evaluar(tramo, ids)
    return tramo, r, ids


def _xy(px, off=0.0):
    return tuple(float(v) for v in TR.px_a_geo(px[0] + off, px[1] + off))


# ------------------------------------------------------------------ GeoPackage
def test_gpkg_releido_con_leer_gpkg_coordenadas_crs_y_atributos(escenario_geo, tmp_path):
    tramo, r, _ = escenario_geo
    res = lx.exportar_gpkg(tramo, str(tmp_path / "t1.gpkg"))
    assert res["verificado"] is True and res["epsg"] == 32719
    assert res["capas"] == {"detecciones": 5, "roi": 5, "eje_via": 1}
    assert sorted(gv.listar_capas_gpkg(res["archivos"]["gpkg"])) == ["detecciones", "eje_via", "roi"]
    det = gv.leer_gpkg(res["archivos"]["gpkg"], "detecciones")
    assert det.epsg == 32719 and len(det.features) == 5
    f = next(x for x in det.features if x["props"]["roi"] == "R01")
    assert f["geom"]["tipo"] == "LineString"
    esperado = [_xy(p, 0.5) for p in _linea(160, 200)]
    assert np.allclose(f["geom"]["coords"], esperado, atol=1e-6)
    assert f["props"]["longitud_m"] == pytest.approx(3.3) and f["props"]["severidad_prelim"] == "Baja"
    assert f["props"]["estado_validacion"] == "VP" and f["props"]["incluida_en_conteo"] == 1
    assert f["props"]["provisional"] == 1 and f["props"]["tipo"] == "transversal"
    baches = {x["props"]["roi"]: x for x in det.features if x["props"]["tipo"] == "bache"}
    assert baches["R03"]["props"]["estado_validacion"] == "FP" and baches["R03"]["props"]["incluida_en_conteo"] == 0
    assert baches["R04"]["props"]["incluida_en_conteo"] == 1
    pol = baches["R04"]["geom"]
    assert pol["tipo"] == "Polygon" and pol["coords"][0][0] == pol["coords"][0][-1] and len(pol["coords"][0]) == 5


def test_gpkg_capa_roi_y_eje_en_el_crs_del_ortomosaico(escenario_geo, tmp_path):
    tramo, r, _ = escenario_geo
    ruta = str(tmp_path / "t1.gpkg")
    lx.exportar_gpkg(tramo, ruta)
    rois = {x["props"]["codigo"]: x for x in gv.leer_gpkg(ruta, "roi").features}
    r01 = r["R01"]
    esp = [_xy((r01["x0"], r01["y0"])), _xy((r01["x1"], r01["y0"])), _xy((r01["x1"], r01["y1"])), _xy((r01["x0"], r01["y1"])),
           _xy((r01["x0"], r01["y0"]))]
    assert np.allclose(rois["R01"]["geom"]["coords"][0], esp, atol=1e-6)
    p = rois["R01"]["props"]
    assert p["tipo_campo"] == "transversal" and p["rol"] == "prueba" and p["n_detecciones"] == 1
    assert p["area_m2"] == pytest.approx(330 * 1000 * 0.005 ** 2) and rois["R03"]["props"]["n_fp"] == 1
    eje = gv.leer_gpkg(ruta, "eje_via").features[0]
    assert eje["geom"]["tipo"] == "LineString" and np.allclose(eje["geom"]["coords"][0], _xy((200, 100)), atol=1e-6)
    longitud = sum(np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip([[200, 100], [220, 600]], [[220, 600], [260, 1000]]))
    assert eje["props"]["longitud_m"] == pytest.approx(
        sum(np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in [([200, 100], [220, 600]), ([220, 600], [260, 1000])]) * 0.005)
    assert longitud > 0


def test_gpkg_estructura_ogc_application_id_tablas_y_srs(escenario_geo, tmp_path):
    ruta = str(tmp_path / "t1.gpkg")
    lx.exportar_gpkg(escenario_geo[0], ruta)
    con = sqlite3.connect(ruta)
    assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47
    assert con.execute("PRAGMA user_version").fetchone()[0] == 10300
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    srs = {r[0]: r for r in con.execute("SELECT srs_id, organization, organization_coordsys_id, definition FROM gpkg_spatial_ref_sys")}
    assert {-1, 0, 4326, 32719} <= set(srs)
    assert srs[32719][1:3] == ("EPSG", 32719) and "UTM zone 19S" in srs[32719][3] and '"central_meridian",-69' in srs[32719][3]
    assert 'false_northing",10000000' in srs[32719][3]
    gc = con.execute("SELECT table_name, geometry_type_name, srs_id FROM gpkg_geometry_columns ORDER BY 1").fetchall()
    assert gc == [("detecciones", "GEOMETRY", 32719), ("eje_via", "LINESTRING", 32719), ("roi", "POLYGON", 32719)]
    mnx, mny, mxx, mxy = con.execute("SELECT min_x,min_y,max_x,max_y FROM gpkg_contents WHERE table_name='roi'").fetchone()
    assert 177000 < mnx < mxx < 177020 and 8502990 < mny < mxy < 8503000
    blob = con.execute("SELECT geom FROM roi LIMIT 1").fetchone()[0]
    assert blob[:2] == b"GP" and blob[2] == 0 and blob[3] & 1 == 1 and (blob[3] >> 1) & 7 == 1
    con.close()
    assert not os.path.exists(ruta + ".tmp")


def test_gpkg_se_lee_con_pyogrio_y_geopandas(escenario_geo, tmp_path):
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("pyogrio")
    ruta = str(tmp_path / "t1.gpkg")
    lx.exportar_gpkg(escenario_geo[0], ruta)
    import pyogrio
    assert sorted(c[0] for c in pyogrio.list_layers(ruta)) == ["detecciones", "eje_via", "roi"]
    det = gpd.read_file(ruta, layer="detecciones")
    assert det.crs.to_epsg() == 32719 and len(det) == 5 and det.geometry.is_valid.all()
    assert set(det.geom_type) == {"LineString", "Polygon"}
    assert det.loc[det.roi == "R01", "longitud_m"].iloc[0] == pytest.approx(3.3)
    assert det.incluida_en_conteo.astype(bool).sum() == 3
    roi = gpd.read_file(ruta, layer="roi")
    assert roi.crs.to_epsg() == 32719 and roi.geometry.is_valid.all()
    r01 = roi[roi.codigo == "R01"].geometry.iloc[0]
    assert r01.area == pytest.approx(330 * 0.005 * 1000 * 0.005)            # 1.65 m × 5 m
    assert gpd.read_file(ruta, layer="eje_via").geometry.iloc[0].length > 0


def test_gpkg_otro_crs_de_salida_4326(escenario_geo, tmp_path):
    ruta = str(tmp_path / "w.gpkg")
    res = lx.exportar_gpkg(escenario_geo[0], ruta, epsg_salida=4326)
    assert res["epsg"] == 4326
    eje = gv.leer_gpkg(ruta, "eje_via")
    assert eje.epsg == 4326
    lon, lat = eje.features[0]["geom"]["coords"][0]
    e, n = TR.px_a_geo(200, 100)
    lon2, lat2 = convertir(e, n, 32719, 4326)
    assert lon == pytest.approx(float(lon2), abs=1e-9) and lat == pytest.approx(float(lat2), abs=1e-9)
    assert -75 < lon < -70 and -15 < lat < -12                                # Cusco


def test_gpkg_crs_no_convertible_se_rechaza(escenario_geo, tmp_path):
    with pytest.raises(lx.ErrorExportacion, match="No se puede convertir"):
        lx.exportar_gpkg(escenario_geo[0], str(tmp_path / "x.gpkg"), epsg_salida=24891)


def test_gpkg_solo_conteo_omite_los_falsos_positivos(escenario_geo, tmp_path):
    ruta = str(tmp_path / "c.gpkg")
    res = lx.exportar_gpkg(escenario_geo[0], ruta, solo_conteo=True)
    assert res["capas"]["detecciones"] == 3
    assert {f["props"]["estado_validacion"] for f in gv.leer_gpkg(ruta, "detecciones").features} == {"VP"}


def test_gpkg_capas_elegidas_y_nombres_invalidos(escenario_geo, tmp_path):
    ruta = str(tmp_path / "e.gpkg")
    res = lx.exportar_gpkg(escenario_geo[0], ruta, capas=("eje_via",))
    assert res["capas"] == {"eje_via": 1} and gv.listar_capas_gpkg(ruta) == ["eje_via"]
    with pytest.raises(lx.ErrorExportacion, match="capas no válidas"):
        lx.exportar_gpkg(escenario_geo[0], str(tmp_path / "z.gpkg"), capas=("puntos",))


def test_gpkg_no_reemplaza_sin_confirmar_y_con_confirmar_si(escenario_geo, tmp_path):
    ruta = str(tmp_path / "t.gpkg")
    lx.exportar_gpkg(escenario_geo[0], ruta)
    with pytest.raises(lx.ErrorExportacion, match="Ya existe"):
        lx.exportar_gpkg(escenario_geo[0], ruta)
    lx.exportar_gpkg(escenario_geo[0], ruta, sobrescribir=True, capas=("roi",))
    assert gv.listar_capas_gpkg(ruta) == ["roi"]


def test_gpkg_archivo_abierto_en_otro_programa(escenario_geo, tmp_path, monkeypatch):
    def falla(a, b):
        raise PermissionError(13, "denegado")
    monkeypatch.setattr(lx.os, "replace", falla)
    with pytest.raises(lx.ErrorExportacion, match="abierto en otro programa"):
        lx.exportar_gpkg(escenario_geo[0], str(tmp_path / "t.gpkg"))
    assert not (tmp_path / "t.gpkg.tmp").exists()


def test_gpkg_se_detecta_una_relectura_distinta(escenario_geo, tmp_path, monkeypatch):
    original = lx.blob_gpkg
    monkeypatch.setattr(lx, "blob_gpkg", lambda g, s: original(
        {**g, "coords": [(x + 1.0, y) for x, y in g["coords"]]} if g["tipo"] == "LineString" else g, s))
    # las coordenadas escritas ya no coinciden con las preparadas: la verificación lo debe notar
    with pytest.raises(lx.ErrorExportacion, match="no coincide"):
        lx.exportar_gpkg(escenario_geo[0], str(tmp_path / "m.gpkg"))


# ------------------------------------------------------------------ sin georreferencia
def test_sin_georreferencia_se_rechaza_con_mensaje_claro(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "geom_px": _poligono(1710, 730), "geom_tipo": "poligono"}])
    with pytest.raises(lx.ErrorExportacion, match="no está georreferenciado"):
        lx.exportar_gpkg(tramo, str(tmp_path / "x.gpkg"))


def test_sin_georreferencia_modo_pixeles_con_crs_indefinido(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "geom_px": _poligono(1710, 730), "geom_tipo": "poligono"}])
    ruta = str(tmp_path / "px.gpkg")
    res = lx.exportar_gpkg(tramo, ruta, permitir_pixeles=True, capas=("detecciones", "roi"))
    assert res["epsg"] is None and any("coordenadas de IMAGEN" in a for a in res["advertencias"])
    f = gv.leer_gpkg(ruta, "detecciones").features[0]
    assert tuple(f["geom"]["coords"][0][0]) == (1710.5, -730.5)
    con = sqlite3.connect(ruta)
    assert con.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name='roi'").fetchone()[0] == -1


def test_georreferenciado_sin_epsg_pide_el_epsg(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    with lt.basedatos.nueva_sesion() as s:
        s.get(lt.Tramo, lt._resolver(s, tramo).id).transformacion = list(TR)
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "geom_px": _poligono(1710, 730), "geom_tipo": "poligono"}])
    with pytest.raises(lx.ErrorExportacion, match="no se conoce su EPSG"):
        lx.exportar_gpkg(tramo, str(tmp_path / "x.gpkg"))


def test_deteccion_sin_geometria_usa_la_caja_envolvente(escenario_geo, tmp_path):
    tramo, r, _ = escenario_geo
    crear_ejecucion(tramo, r["R04"], [{"tipo": "bache", "geom_px": None, "geom_tipo": None}])
    res = lx.exportar_gpkg(tramo, str(tmp_path / "s.gpkg"), ejecucion_ids=[max(lv.ejecuciones_validadas(tramo)) + 1])
    assert any("caja envolvente" in a for a in res["advertencias"])


def test_sin_nada_que_exportar(rois_prueba, tmp_path):
    from app import logica_tramos as lt2
    lt2.crear_tramo({"codigo": "T3"})
    with pytest.raises(lx.ErrorExportacion, match="no está georreferenciado"):
        lx.exportar_gpkg("T3", str(tmp_path / "x.gpkg"), permitir_pixeles=False)
    with pytest.raises(lx.ErrorExportacion, match="nada que exportar"):
        lx.exportar_gpkg("T3", str(tmp_path / "x.gpkg"), permitir_pixeles=True, capas=("eje_via",))


# ------------------------------------------------------------------ GeoJSON
def test_geojson_con_crs_del_ortomosaico(escenario_geo, tmp_path):
    res = lx.exportar_geojson(escenario_geo[0], str(tmp_path / "gj"))
    assert set(res["archivos"]) == {"detecciones", "roi", "eje_via"} and res["epsg"] == 32719
    datos = json.load(open(res["archivos"]["detecciones"], encoding="utf-8"))
    assert datos["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::32719" and len(datos["features"]) == 5
    capa = gv.leer_geojson(res["archivos"]["roi"])
    assert capa.epsg == 32719 and len(capa.features) == 5 and capa.features[0]["props"]["rol"] == "prueba"
    det = gv.leer_geojson(res["archivos"]["detecciones"])
    f = next(x for x in det.features if x["props"]["roi"] == "R01")
    assert np.allclose(f["geom"]["coords"], [_xy(p, 0.5) for p in _linea(160, 200)], atol=1e-3)
    assert f["props"]["incluida_en_conteo"] is True


def test_geojson_en_wgs84_sin_miembro_crs_y_se_lee_con_geopandas(escenario_geo, tmp_path):
    res = lx.exportar_geojson(escenario_geo[0], str(tmp_path / "w"), epsg_salida=4326, capas=("roi",))
    datos = json.load(open(res["archivos"]["roi"], encoding="utf-8"))
    assert "crs" not in datos and res["epsg"] == 4326
    gpd = pytest.importorskip("geopandas")
    g = gpd.read_file(res["archivos"]["roi"])
    assert g.crs.to_epsg() == 4326 and len(g) == 5 and g.geometry.is_valid.all()
    gp = pytest.importorskip("geopandas").read_file(lx.exportar_geojson(
        escenario_geo[0], str(tmp_path / "u"), capas=("roi",))["archivos"]["roi"])
    assert gp.crs.to_epsg() == 32719


def test_geojson_no_reemplaza_sin_confirmar(escenario_geo, tmp_path):
    lx.exportar_geojson(escenario_geo[0], str(tmp_path), capas=("eje_via",))
    with pytest.raises(lx.ErrorExportacion, match="Ya existe"):
        lx.exportar_geojson(escenario_geo[0], str(tmp_path), capas=("eje_via",))
    lx.exportar_geojson(escenario_geo[0], str(tmp_path), capas=("eje_via",), sobrescribir=True)


def test_exportar_formato_desconocido(escenario_geo, tmp_path):
    with pytest.raises(lx.ErrorExportacion, match="formato desconocido"):
        lx.exportar(escenario_geo[0], str(tmp_path), "shp")


# ------------------------------------------------------------------ WKB contra el decodificador del programa
@pytest.mark.parametrize("geom", [
    {"tipo": "Point", "coords": (177001.25, 8502999.5)},
    {"tipo": "LineString", "coords": [(0.0, 0.0), (1.5, 2.5), (3.0, -1.0)]},
    {"tipo": "Polygon", "coords": [[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 0.0)], [(1.0, 0.5), (2.0, 0.5), (1.0, 1.0), (1.0, 0.5)]]},
])
def test_wkb_ida_y_vuelta_con_geovector(geom):
    assert gv.decodificar_wkb(lx.wkb(geom)) == geom
    assert gv.decodificar_geometria_gpkg(lx.blob_gpkg(geom, 32719)) == geom


def test_wkb_tipo_no_soportado():
    with pytest.raises(lx.ErrorExportacion):
        lx.wkb({"tipo": "MultiPoint", "coords": []})


def test_poligono_abierto_se_cierra():
    assert lx._ring([(0, 0), (1, 0), (1, 1)])[-1] == (0, 0)
    assert lx._ring([(0, 0), (1, 0), (0, 0)]) == [(0, 0), (1, 0), (0, 0)]
