import pytest

from app import logica_configuracion as cfg
from app import logica_fichas as lf
from app import logica_tramos as lt
from app.logica_comun import ErrorNoEncontrado, ErrorValidacion
from app.nucleo.parametros import Params


def test_crear_tramo_valida_y_calcula_longitud(bd):
    t = lt.crear_tramo({"codigo": "T1", "progresiva_ini_m": "1000", "progresiva_fin_m": "2000,5", "n_carriles": "2"})
    assert t["longitud_m"] == pytest.approx(1000.5) and t["n_carriles"] == 2
    with pytest.raises(ErrorValidacion, match="ya existe"):
        lt.crear_tramo({"codigo": "T1"})
    with pytest.raises(ErrorValidacion) as e:
        lt.crear_tramo({"codigo": "", "n_carriles": 0, "ancho_calzada_m": "abc", "foo": 1})
    assert set(e.value.errores) == {"codigo", "n_carriles", "ancho_calzada_m", "foo"}      # todos los errores juntos
    with pytest.raises(ErrorValidacion, match="mayor que la progresiva inicial"):
        lt.crear_tramo({"codigo": "T9", "progresiva_ini_m": 10, "progresiva_fin_m": 5})


def test_advierte_longitud_incoherente(bd):
    r = lt.crear_tramo({"codigo": "T1", "progresiva_ini_m": 0, "progresiva_fin_m": 1000, "longitud_m": 4360})
    assert any("difiere" in a for a in r["advertencias"])


def test_actualizar_listar_eliminar_tramo(tramo):
    r = lt.actualizar_tramo(tramo, {"via": "Nueva"})
    assert r["via"] == "Nueva" and lt.obtener_tramo("T1")["via"] == "Nueva"
    lt.crear_tramo({"codigo": "T2"})
    with pytest.raises(ErrorValidacion, match="ya existe"):
        lt.actualizar_tramo("T2", {"codigo": "T1"})
    assert [t["codigo"] for t in lt.listar_tramos()] == ["T1", "T2"]
    lt.definir_eje("T1", [(0, 0), (100, 0)])
    with pytest.raises(ErrorValidacion, match="datos asociados"):
        lt.eliminar_tramo("T1")
    lt.eliminar_tramo("T1", confirmar=True)
    lt.eliminar_tramo("T2")
    with pytest.raises(ErrorNoEncontrado):
        lt.obtener_tramo("T1")


def test_asignar_ortomosaico(tramo):
    t = lt.obtener_tramo(tramo)
    assert (t["ancho_px"], t["alto_px"], t["gsd_cm"]) == (2400, 1400, 0.5)
    assert t["transformacion"] is None


def test_ortomosaico_png_exige_gsd(bd, png_ejemplo):
    lt.crear_tramo({"codigo": "T1"})
    with pytest.raises(ErrorValidacion, match="resolución"):
        lt.asignar_ortomosaico("T1", png_ejemplo)


def test_ortomosaico_geotiff_trae_gsd_transformacion_y_epsg(tramo_geo):
    t = lt.obtener_tramo(tramo_geo)
    assert t["epsg"] == 32719 and t["gsd_cm"] == pytest.approx(0.5)
    assert t["transformacion"][2] == 177000.0 and t["transformacion"][5] == 8503000.0


def test_eje_en_px_y_en_geo(tramo_geo):
    e = lt.definir_eje(tramo_geo, [(177000.0, 8503000.0 - 3.5), (177012.0, 8503000.0 - 3.5)], sistema="geo")
    assert e["vertices_px"] == [[0.0, 700.0], [2400.0, 700.0]] and e["vertices_geo"][0][0] == 177000.0
    assert lt.eje_nucleo(tramo_geo).longitud_m == pytest.approx(12.0)
    e2 = lt.definir_eje(tramo_geo, [(0, 0), (10, 10)])
    assert lt.obtener_eje(tramo_geo)["id"] == e2["id"]                  # vigente = el último


def test_eje_invalido(tramo):
    with pytest.raises(ErrorValidacion, match="al menos 2"):
        lt.definir_eje(tramo, [(0, 0)])
    with pytest.raises(ErrorValidacion, match="georreferenciado"):
        lt.definir_eje(tramo, [(0, 0), (1, 1)], sistema="geo")
    with pytest.raises(ErrorValidacion):
        lt.definir_eje(tramo, [(5, 5), (5, 5)])
    assert any("fuera" in a for a in lt.definir_eje(tramo, [(0, 0), (5000, 0)])["advertencias"])


# ------------------------------------------------------------------ fichas
def test_esquema_y_crud_de_vuelo(tramo):
    assert {c["nombre"] for c in lf.esquema_ficha("vuelo")} >= {"codigo", "altura_m", "traslape_frontal_pct"}
    v = lf.crear("vuelo", {"codigo": "V1", "fecha": "15/07/2026", "hora_inicio": "09:30", "altura_m": "30,5"}, tramo)
    assert str(v["fecha"]) == "2026-07-15" and v["altura_m"] == 30.5
    with pytest.raises(ErrorValidacion, match="ya existe"):
        lf.crear("vuelo", {"codigo": "V1"}, tramo)
    with pytest.raises(ErrorValidacion, match="≤ 100"):
        lf.actualizar("vuelo", v["id"], {"traslape_frontal_pct": 120})
    assert lf.actualizar("vuelo", v["id"], {"dron": "Mavic 3"})["dron"] == "Mavic 3"
    assert len(lf.listar("vuelo", tramo)) == 1
    lf.eliminar("vuelo", v["id"])
    assert lf.listar("vuelo") == []


def test_condicion_y_gcp_enlazan_vuelo_del_mismo_tramo(tramo):
    lt.crear_tramo({"codigo": "T2"})
    v2 = lf.crear("vuelo", {"codigo": "V9"}, "T2")
    with pytest.raises(ErrorValidacion, match="vuelo"):
        lf.crear("gcp", {"codigo": "G1", "vuelo_id": v2["id"]}, tramo)
    v1 = lf.crear("vuelo", {"codigo": "V1"}, tramo)
    g = lf.crear("gcp", {"codigo": "G1", "vuelo_id": v1["id"], "este": 177000, "norte": 8500000, "usado_ortomosaico": "Sí"}, tramo)
    assert g["usado_ortomosaico"] is True
    c = lf.crear("condicion", {"vuelo_id": v1["id"], "temperatura_c": 12, "humedad_pct": 55}, tramo)
    assert c["vuelo_id"] == v1["id"]
    lf.eliminar("vuelo", v1["id"])                                   # SET NULL: la condición y el GCP permanecen
    assert lf.obtener_ficha("gcp", g["id"])["vuelo_id"] is None


def test_catalogo(bd):
    nuevo = lf.crear("catalogo", {"codigo": "pa", "nombre": "Pulimiento de agregados", "tipo_motor": "bache"})
    assert nuevo["codigo"] == "PA" and nuevo["activo"] is True
    with pytest.raises(ErrorValidacion, match="no es válido"):
        lf.crear("catalogo", {"codigo": "X", "nombre": "x", "tipo_motor": "otro"})
    with pytest.raises(ErrorValidacion, match="no se puede cambiar"):
        lf.actualizar("catalogo", nuevo["id"], {"codigo": "ZZ"})


def test_patologia_con_geometria_y_severidad(tramo):
    from app import logica_roi
    roi = logica_roi.crear_roi(tramo, {"codigo": "R1", "tipo_campo": "longitudinal", "x0": 0, "y0": 0, "x1": 100, "y1": 100})
    i1 = lf.crear("inspeccion", {"fecha": "2026-07-16", "responsable": "Julio"}, tramo)
    i2 = lf.crear("inspeccion", {"observador": 2}, tramo)
    assert i1["observador"] == 1
    p = lf.registrar_patologia(i1["id"], {"codigo": "glo", "progresiva_m": 3.2, "lado": "Derecha", "roi_id": roi["id"]},
                               geometria={"longitud_m": 2.1, "ancho_prom_mm": 3, "ancho_max_mm": 5},
                               severidad={"nivel": "alta", "criterio": "ancho > 3 mm"})
    assert p["codigo"] == "GLO" and p["lado"] == "derecha" and p["severidad"]["nivel"] == "Alta"
    assert p["severidad"]["observador"] == 1 and p["geometria"]["ancho_max_mm"] == 5
    lf.registrar_patologia(i2["id"], {"codigo": "GLO", "roi_id": roi["id"]}, severidad={"nivel": "Media"})
    sev = lf.severidades_roi(roi["id"])
    assert [(s["observador"], s["nivel"]) for s in sev] == [(1, "Alta"), (2, "Media")]


def test_patologia_reglas(tramo):
    i = lf.crear("inspeccion", {}, tramo)["id"]
    with pytest.raises(ErrorValidacion, match="catálogo"):
        lf.registrar_patologia(i, {"codigo": "ZZZ"})
    with pytest.raises(ErrorValidacion, match="presencia"):
        lf.registrar_patologia(i, {"codigo": "GLO", "presencia": "No"}, severidad={"nivel": "Baja"})
    with pytest.raises(ErrorValidacion, match="máximo"):
        lf.registrar_patologia(i, {"codigo": "GLO"}, geometria={"ancho_prom_mm": 5, "ancho_max_mm": 2})
    with pytest.raises(ErrorValidacion, match="otro tramo|no existe"):
        lf.registrar_patologia(i, {"codigo": "GLO", "roi_id": 999})
    assert lf.listar_patologias(i) == []                              # nada quedó a medias (transacción)
    p = lf.registrar_patologia(i, {"codigo": "GLO"}, severidad={"nivel": "Baja"})
    lf.actualizar_patologia(p["id"], severidad={"nivel": "Alta"}, geometria={"longitud_m": 1})
    assert lf.listar_patologias(i)[0]["severidad"]["nivel"] == "Alta"
    with pytest.raises(ErrorValidacion, match="se usa"):
        lf.eliminar("catalogo", lf.listar("catalogo")[0]["id"])


# ------------------------------------------------------------------ configuración
def test_configuracion_y_provisional(bd):
    assert cfg.obtener("tesela_px") == 1600 and cfg.params_base() == Params()
    with pytest.raises(ErrorValidacion):
        cfg.establecer("tesela_px", 100)
    with pytest.raises(ErrorValidacion, match="desconocida"):
        cfg.establecer("nada", 1)
    p = Params().con(grieta_k_mad=5.0)
    cfg.guardar_params_base(p)
    assert cfg.params_base().grieta_k_mad == 5.0 and cfg.es_provisional(p)
    cfg.guardar_params_base(p, calibrado=True)
    assert not cfg.es_provisional(p) and not cfg.es_provisional(p.con(gsd_cm=0.3))   # gsd no cuenta
    assert cfg.es_provisional(p.con(grieta_k_mad=4.0))
