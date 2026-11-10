"""F5 · calibración: búsqueda por coordenadas, nunca toca ROI de prueba, guarda solo con confirmación."""
import threading

import pytest

from app import logica_calibracion as lc, logica_configuracion as cfg, logica_deteccion as ld, logica_roi as lr
from app import logica_tramos as lt
from app.logica_comun import ErrorValidacion
from app.nucleo.estructuras import AnalisisCancelado
from app.nucleo.parametros import Params
from tests.test_importacion import CSV_LEGADO, _csv


# ------------------------------------------------------------------ búsqueda pura con óptimo conocido
def _evaluador_sintetico(optimo):
    """Tabla (vp, fp, fn, vn) que mejora cuanto más cerca está grieta_k_mad de `optimo` (sin tocar el motor)."""
    def ev(p):
        err = abs(p.grieta_k_mad - optimo)
        vp = max(0, 10 - int(round(err * 2)))
        return (vp, 10 - vp, 10 - vp, 10)
    return ev


def test_candidatos_acotados_sin_repetir_y_enteros():
    c = lc.candidatos("grieta_k_mad", 4.5)
    assert c[0] == 4.5 and len(c) == len(set(c)) and all(2.0 <= v <= 10.0 for v in c)
    assert lc.candidatos("grieta_k_mad", 9.5)[-1] == 10.0                      # recortado al límite
    ci = lc.candidatos("celdas_min", 4)
    assert all(isinstance(v, int) for v in ci) and all(2 <= v <= 12 for v in ci)


def test_busqueda_encuentra_el_optimo_de_la_rejilla_y_es_determinista():
    base = Params()
    r = lc.busqueda_coordenada(_evaluador_sintetico(6.3), base, ["grieta_k_mad"], "f1")
    assert r["puntaje_despues"] > r["puntaje_antes"]
    assert abs(r["params"].grieta_k_mad - 6.3) < abs(base.grieta_k_mad - 6.3)
    assert r == lc.busqueda_coordenada(_evaluador_sintetico(6.3), base, ["grieta_k_mad"], "f1")


def test_sin_mejora_no_cambia_nada_y_empates_conservan_el_valor_actual():
    base = Params()
    r = lc.busqueda_coordenada(_evaluador_sintetico(base.grieta_k_mad), base, ["grieta_k_mad"], "f1")
    assert r["params"] == base and r["puntaje_despues"] == r["puntaje_antes"]
    plano = lc.busqueda_coordenada(lambda p: (5, 1, 1, 5), base, ["grieta_k_mad", "bache_dL_min"], "kappa")
    assert plano["params"] == base


def test_tope_de_evaluaciones_y_cancelacion():
    base = Params()
    r = lc.busqueda_coordenada(_evaluador_sintetico(9.0), base, ["grieta_k_mad", "bache_dL_min"], max_evaluaciones=3)
    assert r["agotado"] is True and r["evaluaciones"] == 3
    ev = threading.Event()
    ev.set()
    with pytest.raises(AnalisisCancelado):
        lc.busqueda_coordenada(_evaluador_sintetico(9.0), base, ["grieta_k_mad"], cancelar=ev)
    avances = []
    lc.busqueda_coordenada(_evaluador_sintetico(6.0), base, ["grieta_k_mad"], progreso=lambda f, t: avances.append(f))
    assert avances and all(0 <= a < 1 for a in avances)


def test_puntaje_f1_y_kappa_no_definido_es_menos_uno():
    assert lc.puntaje((8, 2, 2, 8), "f1") == pytest.approx(0.8)
    assert lc.puntaje((0, 0, 0, 5), "f1") == -1.0
    assert lc.puntaje((5, 0, 0, 5), "kappa") == pytest.approx(1.0)
    assert lc.puntaje((5, 0, 0, 0), "kappa") == -1.0                            # pe = 1


# ------------------------------------------------------------------ con el motor real
@pytest.fixture
def con_calibracion(tramo, tmp_path):
    from app import logica_importacion as li
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    return tramo


def test_calibrar_valida_entradas_y_roles(con_calibracion):
    tramo = con_calibracion
    with pytest.raises(ErrorValidacion) as e:
        lc.calibrar(tramo)                                                      # ninguna ROI de calibración
    assert "calibracion" in e.value.errores["rois"]
    r = lr.listar_rois(tramo)[0]
    lr.cambiar_rol(r["id"], "calibracion")
    for kw in ({"parametros": ["gsd_cm"]}, {"parametros": ["tol_orient_deg"]}, {"objetivo": "x"},
               {"max_evaluaciones": 0}, {"parametros": ["no_existe"]}):
        with pytest.raises(ErrorValidacion):
            lc.calibrar(tramo, **kw)


def test_calibrar_bloquea_solape_con_prueba(con_calibracion):
    tramo = con_calibracion
    rois = {r["codigo"]: r for r in lr.listar_rois(tramo)}
    lr.cambiar_rol(rois["R04"]["id"], "prueba")
    lr.cambiar_rol(rois["R05"]["id"], "calibracion")                            # R05 se pisa con R04
    with pytest.raises(ErrorValidacion) as e:
        lc.calibrar(tramo, parametros=["grieta_k_mad"], max_evaluaciones=1)
    assert "R04" in e.value.errores["rois"]


def test_calibrar_mejora_params_malos_sin_tocar_prueba_ni_guardar(con_calibracion, monkeypatch):
    tramo = con_calibracion
    rois = {r["codigo"]: r for r in lr.listar_rois(tramo)}
    for cod in ("R01", "R03"):                                                  # R01 transversal, R03 piel de cocodrilo (no tocan a R02/R04)
        lr.cambiar_rol(rois[cod]["id"], "calibracion")
    for cod in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[cod]["id"], "prueba")
    visitadas = []
    orig = ld.preparar_analisis
    monkeypatch.setattr(ld, "preparar_analisis", lambda tr, roi_id=None, **kw: (visitadas.append(roi_id), orig(tr, roi_id=roi_id, **kw))[1])
    malo = Params().con(grieta_contraste_min=30.0, grieta_k_mad=10.0)                # umbrales demasiado exigentes (F1 = 0.8 en calibración)
    antes_cfg = cfg.todas()
    r = lc.calibrar(tramo, parametros=["grieta_k_mad"], max_pasadas=1, params_base=malo, factores=(0.5, 0.7))
    assert set(visitadas) <= {rois["R01"]["id"], rois["R03"]["id"]}              # JAMÁS una ROI de prueba
    assert all(rois[c]["id"] not in visitadas for c in ("R02", "R04", "R05"))
    assert r["n_rois"] == 2 and r["rois"] == ["R01", "R03"] and r["provisional"] and not r["guardado"]
    assert r["antes"]["f1"] == pytest.approx(0.8) and r["despues"]["f1"] > r["antes"]["f1"]
    assert r["cambios"]["grieta_k_mad"]["antes"] == 10.0 and r["cambios"]["grieta_k_mad"]["despues"] < 10.0
    assert r["params_despues"]["grieta_k_mad"] < r["params_antes"]["grieta_k_mad"]
    assert r["params_despues"]["grieta_contraste_min"] == 30.0                    # lo no elegido no se toca
    assert any("solo 2 ROI" in a for a in r["advertencias"])
    assert cfg.todas() == antes_cfg                                              # no guardó nada
    assert ld.listar_ejecuciones(tramo) == []                                    # ni ejecuciones


def test_aplicar_calibracion_solo_con_confirmacion(con_calibracion):
    tramo = con_calibracion
    lr.cambiar_rol(lr.listar_rois(tramo)[0]["id"], "calibracion")
    nuevo = Params().con(grieta_contraste_min=6.0)
    res = {"n_rois": 1, "params_despues": nuevo.a_dict()}
    with pytest.raises(ErrorValidacion):
        lc.aplicar_calibracion(res)
    with pytest.raises(ErrorValidacion):
        lc.aplicar_calibracion({"n_rois": 0, "params_despues": nuevo.a_dict()}, confirmar=True)
    assert cfg.es_provisional(nuevo) is True and cfg.params_base() == Params()
    out = lc.aplicar_calibracion(res, confirmar=True)
    assert out["guardado"] and out["provisional"] is False and out["huella"] == nuevo.huella()
    assert cfg.params_base().grieta_contraste_min == 6.0
    j = ld.preparar_analisis(tramo, roi_id=lr.listar_rois(tramo)[0]["id"])
    assert j.provisional is False and j.params.grieta_contraste_min == 6.0       # el análisis ya no es PROVISIONAL
    assert ld.preparar_analisis(tramo, roi_id=lr.listar_rois(tramo)[0]["id"], params=Params()).provisional is True


def test_parametros_calibrables_son_provisionales_con_limites(bd):
    nombres = {x["nombre"] for x in lc.parametros_calibrables()}
    assert set(lc.PARAMETROS_POR_DEFECTO) <= nombres <= set(Params.provisionales())
    assert not ({"gsd_cm", "tol_orient_deg", "sev_grieta_baja_mm"} & nombres)
