import numpy as np
import pytest

from app import logica_fichas as lf
from app import logica_importacion as li
from app import logica_roi as lr
from app import logica_tramos as lt
from app.crs import convertir
from app.logica_comun import ErrorValidacion
from app.geovector import ErrorFormatoGeo
from tests.utiles_geo import escribir_geojson, escribir_gpkg

CSV_LEGADO = """codigo_roi;tipo_campo;severidad_campo;x;y;ancho;alto
R01;transversal;Baja;150;80;330;1000
R02;Longitudinal;baja;560;560;1200;300
R03;Piel de cocodrilo;Media;950;100;500;450
R04;hueco;Alta;1700;720;400;360
R05;sano;;1500;1050;500;300
"""


def _csv(tmp_path, texto, nombre="d.csv", enc="utf-8"):
    r = tmp_path / nombre
    r.write_bytes(texto.encode(enc))
    return str(r)


# ------------------------------------------------------------------ ROI desde CSV (px)
def test_csv_legado_en_px_con_punto_y_coma_y_tipos_en_texto_libre(tramo, tmp_path):
    rep = li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    assert (rep["creados"], rep["errores"], rep["aplicado"]) == (5, [], True)
    rois = {r["codigo"]: r for r in lr.listar_rois(tramo)}
    assert rois["R02"]["tipo_campo"] == "longitudinal" and rois["R03"]["tipo_campo"] == "piel_cocodrilo"
    assert rois["R04"]["tipo_campo"] == "bache" and rois["R05"]["severidad_campo"] is None
    assert (rois["R01"]["x0"], rois["R01"]["x1"], rois["R01"]["y1"]) == (150, 480, 1080)
    assert rois["R01"]["origen"] == "csv"


def test_csv_windows_1252_con_tildes_y_coma_decimal(tramo, tmp_path):
    txt = "codigo,tipo,observaciones,x,y,ancho,alto\nR1,bache,ñandú sobre la calzada,10.5,20,100,100\n"
    rep = li.importar_rois(tramo, _csv(tmp_path, txt, enc="cp1252"))
    assert rep["creados"] == 1 and lr.listar_rois(tramo)[0]["observaciones"] == "ñandú sobre la calzada"


def test_estricto_simular_y_parcial(tramo, tmp_path):
    malo = CSV_LEGADO + "R06;volcan;Baja;0;0;100;100\nR01;bache;;0;0;50;50\n"
    ruta = _csv(tmp_path, malo)
    rep = li.importar_rois(tramo, ruta)                                   # estricto: no importa nada
    assert rep["aplicado"] is False and lr.listar_rois(tramo) == []
    assert [e["fila"] for e in rep["errores"]] == [7, 8] and "volcan" in rep["errores"][0]["mensaje"]
    assert "ya existe" in rep["errores"][1]["mensaje"]                    # duplicado dentro del mismo archivo
    rep = li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO, "ok.csv"), simular=True)
    assert rep["simulado"] and rep["creados"] == 5 and not rep["aplicado"] and lr.listar_rois(tramo) == []
    rep = li.importar_rois(tramo, ruta, estricto=False)                   # parcial: válidas sí, con errores informados
    assert rep["creados"] == 5 and len(rep["errores"]) == 2 and rep["aplicado"] and len(lr.listar_rois(tramo)) == 5


def test_si_existe(tramo, tmp_path):
    ruta = _csv(tmp_path, CSV_LEGADO)
    li.importar_rois(tramo, ruta)
    assert li.importar_rois(tramo, ruta)["errores"]                      # por defecto: error
    assert li.importar_rois(tramo, ruta, si_existe="omitir")["omitidos"] == 5
    cambio = _csv(tmp_path, "codigo_roi;tipo_campo;x;y;ancho;alto\nR01;bache;100;100;200;200\n", "c.csv")
    rep = li.importar_rois(tramo, cambio, si_existe="actualizar")
    r01 = [r for r in lr.listar_rois(tramo) if r["codigo"] == "R01"][0]
    assert rep["actualizados"] == 1 and (r01["tipo_campo"], r01["x0"], r01["x1"]) == ("bache", 100, 300)
    assert len(lr.listar_rois(tramo)) == 5
    with pytest.raises(ErrorValidacion):
        li.importar_rois(tramo, ruta, si_existe="x")


def test_columnas_faltantes_y_roles(tramo, tmp_path):
    rep = li.importar_rois(tramo, _csv(tmp_path, "codigo,tipo\nR1,bache\n"))
    assert "faltan columnas" in rep["errores"][0]["mensaje"]
    rep = li.importar_rois(tramo, _csv(tmp_path, "codigo,tipo,x,y,ancho,alto\nR1,bache,0,0,50,50\n", "b.csv"), rol="calibracion")
    assert lr.listar_rois(tramo)[0]["rol"] == "calibracion"
    with pytest.raises(ErrorValidacion, match="vacío"):               # archivo ilegible: excepción, no informe
        li.importar_rois(tramo, _csv(tmp_path, "", "v.csv"))


# ------------------------------------------------------------------ ROI desde capas georreferenciadas
def _rect_geo(e0, n_top, ancho_m, alto_m):
    return [(e0, n_top), (e0 + ancho_m, n_top), (e0 + ancho_m, n_top - alto_m), (e0, n_top - alto_m), (e0, n_top)]


def test_geojson_en_wgs84_se_convierte_a_pixeles(tramo_geo, tmp_path):
    # ROI = píxeles (200..600, 100..500) a 0.5 cm/px, origen (177000, 8503000)
    anillo = _rect_geo(177000 + 200 * 0.005, 8503000 - 100 * 0.005, 400 * 0.005, 400 * 0.005)
    lon, lat = convertir([p[0] for p in anillo], [p[1] for p in anillo], 32719, 4326)
    ruta = str(tmp_path / "r.geojson")
    escribir_geojson(ruta, [({"codigo_roi": "G1", "tipo_campo": "bache", "severidad_campo": "Alta"},
                             {"type": "Polygon", "coordinates": [[[float(a), float(b)] for a, b in zip(lon, lat)]]})])
    rep = li.importar_rois(tramo_geo, ruta)
    assert rep["creados"] == 1 and rep["errores"] == []
    r = lr.listar_rois(tramo_geo)[0]
    assert (r["x0"], r["y0"], r["x1"], r["y1"]) == pytest.approx((200, 100, 600, 500), abs=1) and r["origen"] == "geojson"
    assert r["poligono_px"] is None                                       # rectángulo exacto: no hace falta polígono


def test_gpkg_en_utm_y_poligono_rotado_advierte(tramo_geo, tmp_path):
    rect = _rect_geo(177000 + 100 * 0.005, 8503000 - 100 * 0.005, 0.5, 0.5)
    cx, cy = np.mean([p[0] for p in rect[:4]]), np.mean([p[1] for p in rect[:4]])
    t = np.radians(35)
    rot = [(cx + (x - cx) * np.cos(t) - (y - cy) * np.sin(t), cy + (x - cx) * np.sin(t) + (y - cy) * np.cos(t)) for x, y in rect]
    ruta = str(tmp_path / "r.gpkg")
    escribir_gpkg(ruta, "rois", 32719, [({"codigo": "P1", "tipo": "bache"}, ("poligono", rect)),
                                         ({"codigo": "P2", "tipo": "bache"}, ("poligono", rot))])
    rep = li.importar_rois(tramo_geo, ruta)
    assert rep["creados"] == 2 and any("rotada" in a and "fila 2" in a for a in rep["advertencias"])
    rois = {r["codigo"]: r for r in lr.listar_rois(tramo_geo)}
    assert (rois["P1"]["x0"], rois["P1"]["y0"], rois["P1"]["x1"], rois["P1"]["y1"]) == (100, 100, 200, 200)
    assert rois["P2"]["poligono_px"] is not None and rois["P2"]["poligono_geo"] is not None
    assert (rois["P2"]["x1"] - rois["P2"]["x0"]) > 100                    # rectángulo envolvente de la rotación


def test_csv_con_coordenadas_del_mapa(tramo_geo, tmp_path):
    txt = "codigo,tipo,este_min,norte_min,este_max,norte_max\nC1,bache,177001.0,8502997.5,177002.0,8502998.5\n"
    rep = li.importar_rois(tramo_geo, _csv(tmp_path, txt))
    r = lr.listar_rois(tramo_geo)[0]
    assert rep["creados"] == 1 and (r["x0"], r["y0"], r["x1"], r["y1"]) == (200, 300, 400, 500)


def test_capa_sin_crs_se_asume_en_el_del_ortomosaico_pero_geojson_sin_crs_es_wgs84(tramo_geo, tmp_path):
    anillo = _rect_geo(177001.0, 8502999.0, 1.0, 1.0)
    ruta = str(tmp_path / "u.geojson")
    escribir_geojson(ruta, [({"codigo": "U1", "tipo": "bache"}, {"type": "Polygon", "coordinates": [[list(p) for p in anillo]]})], epsg=32719)
    assert li.importar_rois(tramo_geo, ruta)["creados"] == 1
    ruta2 = str(tmp_path / "w.geojson")                                   # coordenadas UTM sin 'crs' = 4326 inválido
    escribir_geojson(ruta2, [({"codigo": "U2", "tipo": "bache"}, {"type": "Polygon", "coordinates": [[list(p) for p in anillo]]})])
    rep = li.importar_rois(tramo_geo, ruta2)
    assert rep["aplicado"] is False and rep["errores"]
    rep = li.importar_rois(tramo_geo, ruta2, epsg_archivo=32719)           # el usuario lo corrige
    assert rep["creados"] == 1


def test_capa_geo_sobre_tramo_sin_georreferencia(tramo, tmp_path):
    ruta = str(tmp_path / "g.geojson")
    escribir_geojson(ruta, [({"codigo": "A", "tipo": "bache"}, {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})])
    rep = li.importar_rois(tramo, ruta)
    assert rep["aplicado"] is False and "georreferenciado" in rep["errores"][0]["mensaje"]
    px = str(tmp_path / "px.geojson")                                     # en píxeles sí se puede
    escribir_geojson(px, [({"codigo": "A", "tipo": "bache"}, {"type": "Polygon", "coordinates": [[[10, 10], [60, 10], [60, 60], [10, 60], [10, 10]]]})], epsg=32719)
    rep = li.importar_rois(tramo, px, sistema="px")
    assert rep["creados"] == 1 and lr.listar_rois(tramo)[0]["x1"] == 60


def test_formato_no_soportado(tramo, tmp_path):
    with pytest.raises(ErrorFormatoGeo):
        li.importar_rois(tramo, str(tmp_path / "x.shp"))


# ------------------------------------------------------------------ eje
def test_eje_desde_csv_px_y_desde_geojson_wgs84(tramo_geo, tmp_path):
    e = li.importar_eje(tramo_geo, _csv(tmp_path, "x;y\n0;700\n1200,5;710\n2400;700\n"), progresiva_inicial_m=50)
    assert e["vertices_px"][1] == [1200.5, 710.0] and e["origen"] == "csv" and e["progresiva_inicial_m"] == 50
    linea = [(177000.0, 8502996.5), (177006.0, 8502996.4), (177012.0, 8502996.5)]
    lon, lat = convertir([p[0] for p in linea], [p[1] for p in linea], 32719, 4326)
    ruta = str(tmp_path / "e.geojson")
    escribir_geojson(ruta, [({}, {"type": "LineString", "coordinates": [[float(a), float(b)] for a, b in zip(lon, lat)]})])
    e = li.importar_eje(tramo_geo, ruta)
    assert e["vertices_px"][1] == pytest.approx([1200.0, 720.0], abs=0.01) and e["origen"] == "geojson"
    escribir_geojson(ruta, [({}, {"type": "LineString", "coordinates": [[0, 0], [1, 1]]})] * 2)
    with pytest.raises(ErrorValidacion, match="exactamente 1 línea"):
        li.importar_eje(tramo_geo, ruta)


# ------------------------------------------------------------------ fichas
def test_fichas_csv_vuelos_condiciones_y_catalogo(tramo, tmp_path):
    v = "tramo;codigo;fecha;altura_m;traslape_frontal_pct;Operador\nT1;V1;15/07/2026;30,5;80;Julio\nT1;V2;2026-07-16;40;75;Julio\n"
    rep = li.importar_fichas("vuelo", _csv(tmp_path, v))
    assert rep["creados"] == 2 and not rep["advertencias"]
    vuelos = lf.listar("vuelo", tramo)
    assert vuelos[0]["altura_m"] == 30.5 and vuelos[0]["operador"] == "Julio"
    c = "vuelo,temperatura_c,humedad_pct,hora\nV1,12,55,09:30\n"
    assert li.importar_fichas("condicion", _csv(tmp_path, c, "c.csv"), tramo=tramo)["creados"] == 1
    assert lf.listar("condicion")[0]["vuelo_id"] == vuelos[0]["id"]
    bad = li.importar_fichas("condicion", _csv(tmp_path, "vuelo,temperatura_c\nV9,5\n", "c2.csv"), tramo=tramo)
    assert "no existe el vuelo" in bad["errores"][0]["mensaje"]
    cat = "codigo,nombre,grupo,tipo_motor\nPA,Pulimiento,Superficie,\nHUE,Hueco,x,bache\n"
    rep = li.importar_fichas("catalogo", _csv(tmp_path, cat, "k.csv"), si_existe="omitir")
    assert (rep["creados"], rep["omitidos"]) == (1, 1)
    rep = li.importar_fichas("vuelo", _csv(tmp_path, "tramo,codigo,operador,extra\nT1,V1,Ana,zzz\n", "u.csv"), si_existe="actualizar")
    assert rep["actualizados"] == 1 and any("extra" in a for a in rep["advertencias"])
    assert lf.listar("vuelo", tramo)[0]["operador"] == "Ana" and lf.listar("vuelo", tramo)[0]["altura_m"] == 30.5
    with pytest.raises(ErrorValidacion, match="solo se importa desde CSV"):
        li.importar_fichas("vuelo", str(tmp_path / "z.geojson"), tramo=tramo)


def test_gcp_desde_capa_de_puntos(tramo_geo, tmp_path):
    lon, lat = convertir(177003.0, 8502996.0, 32719, 4326)
    ruta = str(tmp_path / "gcp.geojson")
    escribir_geojson(ruta, [({"codigo": "G1", "tipo": "control", "precision_m": 0.02}, {"type": "Point", "coordinates": [float(lon), float(lat)]})])
    rep = li.importar_fichas("gcp", ruta, tramo=tramo_geo)
    g = lf.listar("gcp")[0]
    assert rep["creados"] == 1 and (g["este"], g["norte"]) == pytest.approx((177003.0, 8502996.0), abs=1e-3)
    rep = li.importar_fichas("gcp", ruta)
    assert not rep["aplicado"] and "indique el tramo" in rep["errores"][0]["mensaje"]


def test_patologias_csv_con_roi_geometria_y_severidad(tramo, tmp_path):
    lr.crear_roi(tramo, {"codigo": "R1", "tipo_campo": "longitudinal", "x0": 0, "y0": 0, "x1": 100, "y1": 100})
    i = lf.crear("inspeccion", {"responsable": "Julio"}, tramo)["id"]
    txt = ("codigo;roi;progresiva_m;lado;longitud_m;ancho_prom_mm;ancho_max_mm;severidad;criterio\n"
           "GLO;R1;3,2;derecha;2,1;3;5;Alta;ancho > 3 mm\nHUE;;5;izquierda;;;;;\n")
    rep = li.importar_patologias(i, _csv(tmp_path, txt))
    assert rep["creados"] == 2 and rep["errores"] == []
    p = lf.listar_patologias(i)
    assert p[0]["roi_id"] and p[0]["severidad"]["nivel"] == "Alta" and p[0]["geometria"]["ancho_max_mm"] == 5
    assert p[1]["severidad"] is None and p[1]["geometria"] is None
    rep = li.importar_patologias(i, _csv(tmp_path, "codigo,roi\nGLO,R9\nQQQ,\n", "m.csv"))
    assert [e["fila"] for e in rep["errores"]] == [2, 3] and len(lf.listar_patologias(i)) == 2
