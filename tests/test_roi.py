import pytest

from app import logica_roi as lr
from app import logica_tramos as lt
from app.logica_comun import ErrorValidacion

R = lambda c, t, x0, y0, x1, y1, **kw: {"codigo": c, "tipo_campo": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1, **kw}


def test_crear_roi_basico_y_progresivas_desde_eje(tramo):
    lt.definir_eje(tramo, [(0, 700), (2400, 700)], progresiva_inicial_m=100.0)
    r = lr.crear_roi(tramo, R("R1", "transversal", 200, 100, 600, 500, severidad_campo="media"))
    assert r["rol"] == "sin_asignar" and r["origen"] == "manual" and r["severidad_campo"] == "Media"
    assert (r["progresiva_ini_m"], r["progresiva_fin_m"]) == (101.0, 103.0)      # 200..600 px a 0.5 cm/px
    assert lr.area_m2(r, 0.5) == pytest.approx(400 * 400 * 0.005 ** 2)


def test_tipo_sale_del_catalogo_y_conflicto_advierte(tramo):
    r = lr.crear_roi(tramo, {"codigo": "R1", "patologia_codigo": "hue", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
    assert r["tipo_campo"] == "bache" and r["patologia_codigo"] == "HUE"
    r = lr.crear_roi(tramo, R("R2", "longitudinal", 0, 0, 50, 50, patologia_codigo="HUE"))
    assert any("equivale" in a for a in r["advertencias"])
    with pytest.raises(ErrorValidacion, match="tipo_campo"):
        lr.crear_roi(tramo, {"codigo": "R3", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
    with pytest.raises(ErrorValidacion, match="catálogo"):
        lr.crear_roi(tramo, R("R4", "bache", 0, 0, 50, 50, patologia_codigo="ZZZ"))


def test_reglas_de_region(tramo):
    with pytest.raises(ErrorValidacion, match="al menos 8"):
        lr.crear_roi(tramo, R("A", "bache", 0, 0, 5, 50))
    with pytest.raises(ErrorValidacion, match="fuera del ortomosaico"):
        lr.crear_roi(tramo, R("B", "bache", 3000, 0, 3100, 50))
    r = lr.crear_roi(tramo, R("C", "bache", 2300, 1300, 2600, 1500))
    assert (r["x1"], r["y1"]) == (2400, 1400) and any("recortó" in a for a in r["advertencias"])
    with pytest.raises(ErrorValidacion, match="ya existe"):
        lr.crear_roi(tramo, R("C", "bache", 0, 0, 50, 50))
    with pytest.raises(ErrorValidacion, match="dentro del ortomosaico"):
        lr.actualizar_roi(r["id"], {"x1": 9999})


def test_actualizar_region_recalcula_progresivas(tramo):
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    r = lr.crear_roi(tramo, R("R1", "bache", 0, 600, 200, 800))
    n = lr.actualizar_roi(r["id"], {"x0": 400, "x1": 800})
    assert n["progresiva_ini_m"] == 2.0 and n["progresiva_fin_m"] == 4.0
    assert lr.listar_rois(tramo, tipo="bache")[0]["codigo"] == "R1" and lr.listar_rois(tramo, rol="prueba") == []


def test_asignar_roles_estratificado_reproducible(tramo):
    for i in range(6):
        lr.crear_roi(tramo, R(f"B{i}", "bache", i * 100, 0, i * 100 + 50, 50))
    for i in range(3):
        lr.crear_roi(tramo, R(f"L{i}", "longitudinal", i * 100, 200, i * 100 + 50, 250))
    lr.crear_roi(tramo, R("S0", "sano", 0, 400, 50, 450))
    r = lr.asignar_roles(tramo, 0.5, semilla=7)
    assert r["por_tipo"]["bache"] == {"calibracion": 3, "prueba": 3}
    assert r["por_tipo"]["longitudinal"] == {"calibracion": 2, "prueba": 1}
    assert r["por_tipo"]["sano"] == {"calibracion": 0, "prueba": 1} and any("sano" in a for a in r["advertencias"])
    asign = {x["codigo"]: x["rol"] for x in lr.listar_rois(tramo)}
    lr.asignar_roles(tramo, 0.5, semilla=7, reasignar=True)
    assert {x["codigo"]: x["rol"] for x in lr.listar_rois(tramo)} == asign        # misma semilla -> mismo reparto
    lr.asignar_roles(tramo, 0.5, semilla=8, reasignar=True)
    assert {x["codigo"]: x["rol"] for x in lr.listar_rois(tramo)} != asign
    with pytest.raises(ErrorValidacion):
        lr.asignar_roles(tramo, 1.0)


def test_asignar_no_toca_las_ya_asignadas(tramo):
    a = lr.crear_roi(tramo, R("B0", "bache", 0, 0, 50, 50, rol="prueba"))
    lr.crear_roi(tramo, R("B1", "bache", 100, 0, 150, 50))
    lr.crear_roi(tramo, R("B2", "bache", 200, 0, 250, 50))
    lr.asignar_roles(tramo, 0.5)
    assert lr.obtener_roi(a["id"])["rol"] == "prueba"


def test_solapes_calibracion_prueba(tramo):
    a = lr.crear_roi(tramo, R("A", "bache", 0, 0, 100, 100, rol="calibracion"))
    lr.crear_roi(tramo, R("B", "bache", 50, 50, 150, 150, rol="prueba"))
    lr.crear_roi(tramo, R("C", "bache", 80, 80, 120, 120, rol="calibracion"))
    todos = lr.rois_solapados(tramo)
    assert len(todos) == 3
    sol = lr.rois_solapados(tramo, solo_calibracion_vs_prueba=True)
    assert {(s["a"], s["b"]) for s in sol} == {("A", "B"), ("B", "C")}
    assert sol[0]["area_px"] == 2500 and sol[0]["fraccion_menor"] == pytest.approx(0.25)
    assert any("contaminada" in w for w in lr.asignar_roles(tramo)["advertencias"])
    assert lr.cambiar_rol(a["id"], "prueba")["rol"] == "prueba"
    with pytest.raises(ErrorValidacion):
        lr.cambiar_rol(a["id"], "otro")
