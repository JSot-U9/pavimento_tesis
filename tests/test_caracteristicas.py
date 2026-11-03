import numpy as np
import pytest

from app.nucleo.calidad import mascara_valida
from app.nucleo.caracteristicas import caracteristicas_region, estadisticos_rgb, textura_glcm
from app.nucleo.lectura import LectorArray
from app.nucleo.parametros import Params


def test_estadisticos_rgb_de_una_imagen_conocida():
    rgb = np.zeros((10, 10, 3), np.uint8)
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = 100, 120, 80
    e = estadisticos_rgb(rgb, np.ones((10, 10), bool))
    assert (e["R_media"], e["G_media"], e["B_media"]) == (100, 120, 80)
    assert e["R_desv"] == 0 and e["G_min"] == e["G_max"] == 120


def test_estadisticos_usan_solo_la_calzada_valida():
    rgb = np.full((10, 10, 3), 100, np.uint8)
    rgb[:5] = 250
    valido = np.zeros((10, 10), bool)
    valido[5:] = True
    assert estadisticos_rgb(rgb, valido)["R_media"] == 100


def test_textura_uniforme_vs_ruidosa():
    rng = np.random.default_rng(0)
    plana = textura_glcm(np.full((64, 64), 120, np.uint8))
    ruido = textura_glcm(rng.integers(0, 256, (64, 64), dtype=np.uint8))
    assert plana["tex_contraste"] == 0 and plana["tex_energia"] == pytest.approx(1.0)
    assert ruido["tex_contraste"] > 10 and ruido["tex_entropia"] > plana["tex_entropia"]


def test_caracteristicas_de_una_roi(ejemplo, lector_ejemplo):
    p = Params()
    c = caracteristicas_region(lector_ejemplo, (1500, 1050, 2000, 1350),
                               lambda rgb, nd: mascara_valida(rgb, p, nd))
    assert 80 < c["R_media"] < 140 and c["R_media"] >= c["B_media"]       # asfalto con tinte cálido
    assert {"tex_contraste", "tex_homogeneidad", "tex_entropia"} <= set(c)
    assert isinstance(LectorArray, type)
