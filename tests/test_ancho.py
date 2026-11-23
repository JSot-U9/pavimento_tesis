"""
Verificación del ancho de grieta con grietas SINTÉTICAS de ancho exacto conocido.
El motor anterior sobrestimaba ~1.2-1.6x; el método nuevo (perfil de gris a media altura) debe
quedar a <= 2 mm (< 0.4 px) para anchos >= 15 mm (3 px), con y sin bajo contraste, y a <= 2.5 mm
en el límite de 2 px (10 mm). Por debajo de 2 px el ancho no es medible y se advierte.
"""
import numpy as np
import pytest

from app.nucleo.lectura import LectorArray
from app.nucleo.medidas import ancho_por_distancia, corregir_difuminado
from app.nucleo.parametros import Params
from app.nucleo.pipeline import analizar_region
from tests.conftest import region_de
from tests.sintetico import asfalto, a_uint8, dibujar_grieta


LARGO_M = 3.7           # largo real de la grieta dibujada (740 px a 0.5 cm/px)


def _medir_todo(ancho_mm, contraste=70, p=None, semilla=3):
    """Detecta una grieta de ancho conocido. Con poco contraste una grieta puede salir en varios
    fragmentos: se devuelven todos (la prueba verifica cada uno y la longitud total)."""
    img = asfalto(500, 900, semilla)
    dibujar_grieta(img, (80, 250), (820, 262), ancho_mm / 5.0, contraste=contraste)
    res = analizar_region(LectorArray(a_uint8(img), gsd_cm=0.5), (0, 0, 900, 500), p or Params())
    gr = [d for d in res.detecciones if d.ancho_mm]
    assert gr, "no se detectó la grieta"
    return gr


def _medir(ancho_mm, contraste=70, p=None, semilla=3):
    gr = _medir_todo(ancho_mm, contraste, p, semilla)
    assert len(gr) == 1, f"se esperaba 1 grieta y hay {len(gr)}"
    return gr[0]


@pytest.mark.parametrize("ancho_mm,tol", [(15, 1.5), (20, 1.5), (25, 1.5), (40, 1.5), (60, 2.0)])
@pytest.mark.parametrize("contraste", [70, 35])
def test_ancho_conocido(ancho_mm, tol, contraste):
    gr = _medir_todo(ancho_mm, contraste)
    assert sum(d.longitud_m for d in gr) >= 0.8 * LARGO_M
    for d in gr:
        assert abs(d.ancho_mm - ancho_mm) <= tol
        assert d.metodo_ancho == "perfil_gris"


def test_limite_de_resolucion_2px():
    d = _medir(10)
    assert abs(d.ancho_mm - 10) <= 2.5          # sesgo residual conocido en el límite de 2 px


def test_menos_de_2px_se_advierte_y_no_se_clasifica_severidad():
    for d in _medir_todo(5, contraste=70):
        assert "2 px" in d.advertencia
        assert d.severidad_prelim.startswith("no resoluble")


def test_la_correccion_de_difuminado_reduce_el_sesgo_en_grietas_finas():
    con = _medir(10).ancho_mm
    sin = _medir(10, p=Params().con(ancho_sigma_px=0)).ancho_mm
    assert abs(con - 10) < abs(sin - 10)


def test_ejemplo_del_motor_anterior_ancho_real_dibujado(ejemplo, lector_ejemplo):
    """En generar_ejemplo.py las polilíneas de grosor 5 y 4 salen de 35.1 y 25.0 mm (se midió el
    área dibujada / longitud), no de 25 y 20 mm nominales. El motor anterior daba 40 y 29-31."""
    p = Params()
    r1 = [d for d in analizar_region(lector_ejemplo, region_de(ejemplo[1]["R01"]), p).detecciones if d.ancho_mm]
    r2 = [d for d in analizar_region(lector_ejemplo, region_de(ejemplo[1]["R02"]), p).detecciones if d.ancho_mm]
    assert abs(r1[0].ancho_mm - 35.1) <= 2.0
    assert abs(r2[0].ancho_mm - 25.0) <= 2.0


def test_correccion_analitica_es_monotona_y_neutra_sin_sigma():
    assert corregir_difuminado(3.0, 0) == 3.0
    vals = [corregir_difuminado(f, 0.9) for f in (2.0, 3.0, 4.0, 6.0, 10.0)]
    assert vals == sorted(vals)
    assert corregir_difuminado(10.0, 0.9) == pytest.approx(10.0, abs=0.1)   # grietas anchas casi no cambian


def test_respaldo_por_distancia_sobre_mascara_previa():
    m = np.zeros((40, 200), np.uint8)
    m[17:23, 10:190] = 1                                    # banda de 6 px
    pts = np.array([[x, 19] for x in range(20, 180)])
    assert ancho_por_distancia(m, pts) == pytest.approx(6.0, abs=1.0)
    assert ancho_por_distancia(m, np.array([[5, 5]])) is None     # esqueleto fuera de la máscara
