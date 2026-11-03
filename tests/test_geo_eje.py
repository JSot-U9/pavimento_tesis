import numpy as np
import pytest

from app.nucleo.eje_via import EjeVia
from app.nucleo.geo import Transformacion

GSD = 0.005


def test_transformacion_ida_y_vuelta():
    t = Transformacion.norte_arriba(180000.0, 8500000.0, GSD)
    x, y = t.px_a_geo(1000, 400)
    assert (float(x), float(y)) == pytest.approx((180005.0, 8499998.0))
    col, fila = t.geo_a_px(x, y)
    assert (float(col), float(fila)) == pytest.approx((1000, 400))
    assert t.gsd_m() == pytest.approx(GSD)


def test_transformacion_con_rotacion_es_invertible():
    t = Transformacion(0.0049, 0.001, 100.0, 0.001, -0.0049, 200.0)
    col, fila = t.geo_a_px(*t.px_a_geo(np.array([10.0, 500.0]), np.array([30.0, 70.0])))
    assert np.allclose(col, [10, 500]) and np.allclose(fila, [30, 70])


def test_transformacion_no_invertible():
    with pytest.raises(ValueError, match="no invertible"):
        Transformacion(0, 0, 0, 0, 0, 0).geo_a_px(1, 1)


def test_eje_recto_y_angulo():
    assert EjeVia([(0, 100), (1000, 100)], GSD).angulo_local_deg(500, 300) == pytest.approx(0.0)
    assert EjeVia([(0, 0), (500, 500)], GSD).angulo_local_deg(100, 100) == pytest.approx(45.0)
    assert EjeVia.recto(30, 2000, 1000, GSD).angulo_local_deg(1000, 500) == pytest.approx(30.0)


def test_angulo_local_cambia_en_una_curva():
    # eje horizontal, luego gira 90° hacia abajo (curva en L)
    eje = EjeVia([(0, 300), (900, 300), (900, 1200)], GSD, ventana_m=0.4)
    assert eje.angulo_local_deg(300, 300) == pytest.approx(0.0, abs=1)
    assert eje.angulo_local_deg(900, 900) == pytest.approx(90.0, abs=1)
    a = eje.angulo_local_deg(np.array([300.0, 900.0]), np.array([300.0, 900.0]))
    assert a.shape == (2,)


def test_progresiva_monotona_y_valor():
    eje = EjeVia([(0, 0), (1000, 0), (1000, 1000)], GSD, progresiva_inicial_m=1000.0)
    assert eje.longitud_m == pytest.approx(10.0)
    prog = eje.progresiva_m(np.array([0.0, 500.0, 1000.0, 1000.0]), np.array([5.0, 5.0, 5.0, 500.0]))
    assert np.all(np.diff(prog) > 0)
    assert prog[1] == pytest.approx(1000.0 + 2.5)
    assert prog[3] == pytest.approx(1000.0 + 7.5)


def test_lado_de_la_via():
    eje = EjeVia([(0, 100), (1000, 100)], GSD)       # avanza hacia +x; en la imagen +y es hacia abajo
    assert eje.lado_via(500, 200) == "derecha"
    assert eje.lado_via(500, 0) == "izquierda"
    assert eje.distancia_lateral_m(500, 200) == pytest.approx(100 * GSD)


def test_desviacion_es_angulo_agudo():
    d = EjeVia.desviacion_deg
    assert d(0, 0) == 0 and d(90, 0) == 90 and d(179, 0) == pytest.approx(1)
    assert d(10, 170) == pytest.approx(20)


def test_validaciones_y_serializacion():
    with pytest.raises(ValueError, match="al menos 2 vértices"):
        EjeVia([(0, 0)], GSD)
    with pytest.raises(ValueError, match="iguales"):
        EjeVia([(5, 5), (5, 5)], GSD)
    with pytest.raises(ValueError, match="gsd_m"):
        EjeVia([(0, 0), (1, 1)], 0)
    e = EjeVia([(0, 0), (10, 0), (10, 10)], GSD, 50.0, 3.0)
    assert EjeVia.desde_dict(e.a_dict()).a_dict() == e.a_dict()


def test_eje_desde_geo():
    t = Transformacion.norte_arriba(180000.0, 8500000.0, GSD)
    eje = EjeVia.desde_geo([(180000.0, 8499995.0), (180010.0, 8499995.0)], t)
    assert eje.vertices[0].tolist() == pytest.approx([0, 1000])
    assert eje.longitud_m == pytest.approx(10.0)
