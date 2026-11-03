"""Detección por tipo sobre las 5 ROI sintéticas conocidas + eje de vía con curva."""
import pytest

from app.nucleo.eje_via import EjeVia
from app.nucleo.estructuras import Deteccion
from app.nucleo.grietas import severidad_grieta
from app.nucleo.lectura import LectorArray
from app.nucleo.parametros import Params
from app.nucleo.pipeline import analizar_region
from tests.conftest import region_de
from tests.sintetico import a_uint8, asfalto, dibujar_grieta


def _en_roi(ejemplo, lector, codigo, p=None):
    return analizar_region(lector, region_de(ejemplo[1][codigo]), p or Params()).detecciones


def test_r01_transversal(ejemplo, lector_ejemplo):
    d = _en_roi(ejemplo, lector_ejemplo, "R01")
    assert [x.tipo for x in d] == ["transversal"]
    assert d[0].desv_eje_deg > 80 and d[0].ancho_mm is not None and d[0].longitud_m > 3


def test_r02_longitudinal(ejemplo, lector_ejemplo):
    d = _en_roi(ejemplo, lector_ejemplo, "R02")
    assert [x.tipo for x in d] == ["longitudinal"]
    assert d[0].desv_eje_deg < 10


def test_r03_piel_de_cocodrilo_no_reporta_ancho(ejemplo, lector_ejemplo):
    d = _en_roi(ejemplo, lector_ejemplo, "R03")
    assert [x.tipo for x in d] == ["piel_cocodrilo"]       # sus grietas no se cuentan como lineales
    z = d[0]
    assert z.ancho_mm is None and z.ancho_m is None        # el motor anterior daba 1695 mm
    assert z.n_celdas >= 4 and 1.0 < z.area_m2 < 3.5
    assert 5 < z.densidad_pct < 60 and z.longitud_m > 5 and z.celda_media_m2 > 0
    assert z.severidad_prelim is None and z.geom_tipo == "poligono" and len(z.geom) >= 3


def test_r04_bache_ancho_en_metros(ejemplo, lector_ejemplo):
    d = _en_roi(ejemplo, lector_ejemplo, "R04")
    assert [x.tipo for x in d] == ["bache"]
    b = d[0]                                               # elipse de 0.70 x 0.50 m
    assert b.ancho_mm is None and b.severidad_prelim is None
    assert b.longitud_m == pytest.approx(0.70, abs=0.1) and b.ancho_m == pytest.approx(0.50, abs=0.1)
    assert b.area_m2 == pytest.approx(0.275, abs=0.06) and b.solidez > 0.8
    assert b.contraste_weber is not None


def test_r05_pavimento_sano_sin_detecciones(ejemplo, lector_ejemplo):
    assert _en_roi(ejemplo, lector_ejemplo, "R05") == []


def test_ancho_mm_solo_en_grietas_lineales(ejemplo, lector_ejemplo):
    dets = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params()).detecciones
    for d in dets:
        if d.tipo in ("longitudinal", "transversal"):
            assert d.ancho_mm is not None and d.ancho_m is None and d.n_celdas is None
        elif d.tipo == "piel_cocodrilo":
            assert d.ancho_mm is None and d.n_celdas is not None
        else:
            assert d.ancho_mm is None and d.ancho_m is not None


def test_geometria_dentro_de_la_caja_y_acotada(ejemplo, lector_ejemplo):
    for d in analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params()).detecciones:
        assert 3 <= len(d.geom) <= 120
        xs, ys = zip(*d.geom)
        assert d.x - 1 <= min(xs) and max(xs) <= d.x + d.w + 1
        assert d.y - 1 <= min(ys) and max(ys) <= d.y + d.h + 1


def test_severidad_orientativa_segun_ficha_3():
    p, g = Params(), 0.005                       # 2 px = 10 mm
    assert severidad_grieta(None, g, p) is None
    assert severidad_grieta(5.0, g, p).startswith("no resoluble")
    assert severidad_grieta(12.0, g, p) == "Alta"                       # > 3 mm
    p2 = p.con(sev_grieta_baja_mm=15.0, sev_grieta_media_mm=30.0)       # umbrales configurables
    assert [severidad_grieta(a, g, p2) for a in (12.0, 20.0, 40.0)] == ["Baja", "Media", "Alta"]


def test_desplazada_suma_coordenadas():
    d = Deteccion("bache", 1, 2, 3, 4, 2.5, 4.0, geom=[(1, 2), (3, 4)])
    e = d.desplazada(100, 200)
    assert (e.x, e.y, e.cx, e.cy, e.geom) == (101, 202, 102.5, 204.0, [(101, 202), (103, 204)])
    assert d.x == 1


# ------------------------------------------------------------------ eje de vía con curva
def _imagen_con_curva():
    img = asfalto(1300, 1300, 7)
    for p0, p1 in (((200, 300), (500, 300)),      # A: paralela al eje horizontal  -> longitudinal
                   ((780, 900), (1020, 900)),     # B: perpendicular al eje vertical -> transversal
                   ((600, 150), (600, 450)),      # C: perpendicular al eje horizontal -> transversal
                   ((1100, 650), (1100, 1100))):  # D: paralela al eje vertical    -> longitudinal
        dibujar_grieta(img, p0, p1, 4.0, contraste=70)
    return LectorArray(a_uint8(img), gsd_cm=0.5)


def _tipo_en(dets, x, y):
    cerca = [d for d in dets if abs(d.cx - x) < 150 and abs(d.cy - y) < 150]
    assert len(cerca) == 1, f"se esperaba 1 detección cerca de ({x},{y}) y hay {len(cerca)}"
    return cerca[0].tipo


def test_clasificacion_con_eje_curvo_usa_el_angulo_local():
    lec, p = _imagen_con_curva(), Params()
    eje = EjeVia([(0, 300), (900, 300), (900, 1250)], p.gsd_m, ventana_m=0.4)
    dets = analizar_region(lec, (0, 0, 1300, 1300), p, eje=eje).detecciones
    assert _tipo_en(dets, 350, 300) == "longitudinal"
    assert _tipo_en(dets, 900, 900) == "transversal"
    assert _tipo_en(dets, 600, 300) == "transversal"
    assert _tipo_en(dets, 1100, 875) == "longitudinal"


def test_un_unico_angulo_clasifica_mal_en_la_curva():
    """Demuestra el defecto del motor anterior (eje_via_deg único = 0°): B y D salen invertidas."""
    lec, p = _imagen_con_curva(), Params()
    eje_unico = EjeVia.recto(0, 1300, 1300, p.gsd_m)
    dets = analizar_region(lec, (0, 0, 1300, 1300), p, eje=eje_unico).detecciones
    assert _tipo_en(dets, 900, 900) == "longitudinal"        # incorrecto
    assert _tipo_en(dets, 1100, 875) == "transversal"        # incorrecto


def test_progresiva_y_lado_se_completan_con_el_eje():
    lec, p = _imagen_con_curva(), Params()
    eje = EjeVia([(0, 300), (900, 300), (900, 1250)], p.gsd_m, progresiva_inicial_m=2000.0)
    dets = analizar_region(lec, (0, 0, 1300, 1300), p, eje=eje).detecciones
    assert all(d.progresiva_m is not None and d.lado_via in ("derecha", "izquierda") for d in dets)
    c = [d for d in dets if abs(d.cx - 600) < 50][0]          # grieta C a 600 px = 3 m del inicio
    assert c.progresiva_m == pytest.approx(2003.0, abs=0.3)


def test_area_px_es_consistente_con_area_m2(ejemplo, lector_ejemplo):
    for d in analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params()).detecciones:
        assert d.area_px == round(d.area_m2 / 0.005 ** 2) and d.area_px > 0
