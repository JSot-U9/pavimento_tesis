import cv2
import numpy as np

from app.nucleo.calidad import AcumuladorCalidad, consolidar, mascara_valida
from app.nucleo.parametros import Params


def _calidad(rgb, p=None, teselas=1):
    p = p or Params()
    acum = AcumuladorCalidad()
    valido, nodata = mascara_valida(rgb, p)
    acum.agregar(rgb, valido, nodata)
    return consolidar(acum, p)


def test_imagen_sintetica_nitida_es_adecuada(ejemplo):
    # el motor anterior la marcaba 'No adecuada' (umbral de nitidez 20 con valores de ~15)
    c = _calidad(ejemplo[0])
    assert c.adecuada and c.advertencias == []
    assert c.cobertura_pct == 100.0 and c.resolucion_cm_px == 0.5


def test_desenfocada_oscura_y_sobreexpuesta_no_son_adecuadas(ejemplo):
    rgb = ejemplo[0]
    assert "imagen poco nítida" in _calidad(cv2.GaussianBlur(rgb, (0, 0), 3)).advertencias
    assert "brillo fuera de rango" in _calidad((rgb * 0.3).astype(np.uint8)).advertencias
    sobre = np.clip(rgb.astype(int) + 130, 0, 255).astype(np.uint8)
    adv = _calidad(sobre).advertencias
    assert "exceso de píxeles saturados" in adv and "brillo fuera de rango" in adv


def test_umbrales_son_configurables(ejemplo):
    estricto = Params().con(nitidez_min=50.0)
    assert not _calidad(ejemplo[0], estricto).adecuada


def test_nodata_reduce_cobertura(ejemplo):
    rgb = ejemplo[0].copy()
    rgb[:700, :, :] = 0                                  # mitad NoData
    c = _calidad(rgb)
    assert 49 < c.cobertura_pct < 51 and c.calzada_util_pct < 51


def test_todo_nodata_advierte():
    c = _calidad(np.zeros((300, 300, 3), np.uint8))
    assert not c.adecuada and any("no hay calzada" in a for a in c.advertencias)


def test_vegetacion_se_excluye_de_la_calzada_util(ejemplo):
    rgb = ejemplo[0].copy()
    rgb[:300, :, :] = (40, 160, 40)
    c = _calidad(rgb)
    assert c.calzada_util_pct < 80 and c.cobertura_pct == 100.0


def test_gsd_grueso_advierte(ejemplo):
    c = _calidad(ejemplo[0], Params().con(gsd_cm=1.0))
    assert any("GSD" in a for a in c.advertencias)


def test_acumulacion_por_teselas_equivale_a_toda_la_imagen(ejemplo):
    rgb, p = ejemplo[0], Params()
    entera = _calidad(rgb)
    acum = AcumuladorCalidad()
    for x in (0, 1200):
        sub = np.ascontiguousarray(rgb[:, x:x + 1200])
        v, nd = mascara_valida(sub, p)
        acum.agregar(sub, v, nd)
    c = consolidar(acum, p)
    assert abs(c.brillo_medio - entera.brillo_medio) < 0.5 and c.adecuada == entera.adecuada
