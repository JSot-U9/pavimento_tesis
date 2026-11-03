import threading

import numpy as np
import pytest

from app.nucleo import pipeline
from app.nucleo.estructuras import AnalisisCancelado
from app.nucleo.lectura import LectorArray
from app.nucleo.parametros import Params
from app.nucleo.pipeline import analizar_region, registrar_metodo


def test_region_completa_detecta_los_cuatro_tipos(ejemplo, lector_ejemplo):
    res = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params())
    assert {d.tipo for d in res.detecciones} == {"longitudinal", "transversal", "piel_cocodrilo", "bache"}
    assert res.calidad.adecuada and res.metodo == "actual" and res.params_huella == Params().huella()
    assert all(d.progresiva_m is not None for d in res.detecciones)


def test_sin_eje_advierte_que_se_asumio_horizontal(lector_ejemplo):
    res = analizar_region(lector_ejemplo, (0, 0, 800, 800), Params())
    assert any("eje de vía" in a for a in res.advertencias)


def test_resultado_estable_al_cambiar_el_tamano_de_tesela(lector_ejemplo):
    p = Params()
    grande = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), p, tesela_px=1600)
    assert grande.n_teselas == 2
    for t in (1000, 600):
        chica = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), p, tesela_px=t)
        assert chica.n_teselas > grande.n_teselas
        # las piezas cortadas por bordes de tesela se unen: mismas detecciones y mismas medidas
        assert sorted(d.tipo for d in chica.detecciones) == sorted(d.tipo for d in grande.detecciones)
        for a in grande.detecciones:
            b = [d for d in chica.detecciones if d.tipo == a.tipo][0]
            assert b.longitud_m == pytest.approx(a.longitud_m, rel=0.03)
            assert b.area_m2 == pytest.approx(a.area_m2, rel=0.03)
            assert b.n_celdas == a.n_celdas or abs((b.n_celdas or 0) - (a.n_celdas or 0)) <= 2
            if a.ancho_mm:
                assert b.ancho_mm == pytest.approx(a.ancho_mm, abs=1.0)
            assert (b.x, b.y) == pytest.approx((a.x, a.y), abs=3)
            assert b.bordes_corte == []


def test_tesela_demasiado_pequena_se_rechaza(lector_ejemplo):
    with pytest.raises(ValueError, match="al menos 512"):
        analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), tesela_px=300)


def test_progreso_es_creciente_y_llega_a_uno(lector_ejemplo):
    marcas = []
    analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), tesela_px=800,
                    progreso=lambda f, t: marcas.append((f, t)))
    fr = [f for f, _ in marcas]
    assert fr == sorted(fr) and fr[-1] == 1.0 and len(fr) == 6


def test_cancelar_detiene_entre_teselas():
    leidas = []

    class Contador(LectorArray):
        def leer(self, *a):
            leidas.append(a)
            return super().leer(*a)

    rgb = np.full((1000, 3000, 3), 100, np.uint8)
    ev = threading.Event()
    lec = Contador(rgb, gsd_cm=0.5)
    with pytest.raises(AnalisisCancelado):
        analizar_region(lec, (0, 0, 3000, 1000), Params(), tesela_px=600, cancelar=ev,
                        progreso=lambda f, t: ev.set())       # cancela tras la primera tesela
    assert len(leidas) == 1


def test_metodo_desconocido_da_mensaje_claro(lector_ejemplo):
    with pytest.raises(ValueError, match="'sun'.*Disponibles: actual"):
        analizar_region(lector_ejemplo, (0, 0, 500, 500), Params(), metodo="sun")


def test_registrar_metodo_nuevo(lector_ejemplo, monkeypatch):
    monkeypatch.setitem(pipeline.METODOS, "nulo", lambda rgb, valido, p, eje, origen, nucleo=None: [])
    registrar_metodo("nulo2", lambda rgb, valido, p, eje, origen, nucleo=None: [])
    res = analizar_region(lector_ejemplo, (0, 0, 800, 800), Params(), metodo="nulo")
    assert res.detecciones == [] and res.metodo == "nulo"
    pipeline.METODOS.pop("nulo2")


def test_region_invalida(lector_ejemplo):
    with pytest.raises(ValueError, match="demasiado pequeña o queda fuera"):
        analizar_region(lector_ejemplo, (5000, 5000, 6000, 6000), Params())
    with pytest.raises(ValueError, match="tesela_px = 10"):
        analizar_region(lector_ejemplo, (0, 0, 800, 800), Params(), tesela_px=10)


def test_gsd_distinto_al_del_archivo_advierte(ejemplo):
    lec = LectorArray(ejemplo[0][:600, :600], gsd_cm=1.0)
    res = analizar_region(lec, (0, 0, 600, 600), Params())
    assert any("cm/px" in a for a in res.advertencias)


def test_mascara_de_via_excluye_lo_que_queda_fuera(ejemplo, lector_ejemplo):
    via = np.zeros((1400, 2400, 3), np.uint8)
    via[:, 1200:] = 255                                       # solo la mitad derecha es calzada
    res = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), mascara_via=LectorArray(via))
    assert res.detecciones and all(d.cx > 1150 for d in res.detecciones)
    assert any(d.tipo == "bache" for d in res.detecciones)


def test_no_hay_calzada_analizable_en_una_region_vacia():
    lec = LectorArray(np.zeros((400, 400, 3), np.uint8), gsd_cm=0.5)
    res = analizar_region(lec, (0, 0, 400, 400), Params())
    assert res.detecciones == [] and not res.calidad.adecuada
