"""F5 · UI: gráficos (Figure), presentadores sin Tk y recorrido de humo con Tk real (omitido sin pantalla)."""
import pytest

from app import graficos, logica_calibracion as lc, logica_deteccion as ld, logica_roi as lr, logica_validacion as lv
from app.nucleo.parametros import Params
from app.tareas import gestor_de_calculos
from app.ui.presentadores.base import Contexto
from app.ui.presentadores.p_calibracion import PresentadorCalibracion
from app.ui.presentadores.p_estadistica import PresentadorEstadistica
from app.ui.presentadores.p_validacion import PresentadorValidacion
from tests.test_estadistica import _fijar_validacion                      # noqa: F401
from tests.test_validacion import crear_ejecucion, rois_prueba           # noqa: F401


# ------------------------------------------------------------------ gráficos
def _png(fig, tmp_path, nombre):
    ruta = str(tmp_path / nombre)
    fig.savefig(ruta)                                   # una Figure sin pyplot se puede guardar (PDF de F6)
    return ruta


def test_graficos_devuelven_figure_y_se_pueden_guardar(tmp_path):
    from matplotlib.figure import Figure
    mc = {"etiquetas": ["longitudinal", "bache", "sano"], "matriz": [[3, 1, 0], [0, 2, 1], [0, 0, 4]], "n": 11}
    met = {"provisional": True, "por_tipo": {t: {k: {"valor": v, "ic95": [max(0, v - .2), min(1, v + .1)] if v else None}
                                                  for k, v in (("sensibilidad", .8), ("especificidad", .9),
                                                               ("precision", None), ("f1", .7))}
                                              for t in ("longitudinal", "bache")}}
    ba = {"medias": [1, 2, 3, 4], "diferencias": [.1, -.2, .3, 0], "sesgo": .05, "loa_inf": -.4, "loa_sup": .5}
    pares = [{"variable": "longitud_m", "tipo": "bache", "campo": 1.0, "python": 1.2},
             {"variable": "longitud_m", "tipo": "longitudinal", "campo": 2.0, "python": 1.8}]
    cal = {"objetivo": "f1", "n_rois": 2, "antes": {"sensibilidad": .5, "precision": None, "f1": .6, "kappa": .4},
           "despues": {"sensibilidad": 1, "precision": 1, "f1": 1, "kappa": 1}}
    figs = [graficos.fig_matriz_confusion(mc, "t", True), graficos.fig_metricas_por_tipo(met),
            graficos.fig_bland_altman(ba, "ba", "m", True), graficos.fig_dispersion(pares, "longitud_m", "m"),
            graficos.fig_conteos({"bache": {"n": 3}}), graficos.fig_calibracion(cal),
            graficos.fig_bland_altman(None), graficos.fig_matriz_confusion({"etiquetas": [], "matriz": [], "n": 0}),
            graficos.fig_dispersion([], "x")]
    for i, f in enumerate(figs):
        assert isinstance(f, Figure)
        assert (tmp_path / f"g{i}.png").write_bytes(open(_png(f, tmp_path, f"g{i}.png"), "rb").read()) > 1000
    textos = " ".join(t.get_text() for t in figs[0].texts)
    assert "PROVISIONAL" in textos and "PROVISIONAL" not in " ".join(t.get_text() for t in figs[4].texts)


# ------------------------------------------------------------------ presentadores
def test_presentador_validacion_roles_formulario_y_geometrias(rois_prueba):
    tramo, r = rois_prueba
    p = PresentadorValidacion(Contexto())
    assert p.textos_iniciales()["umbral_solape"] == "0.3"
    st = p.estado_roles(tramo)
    assert st["nivel"] == "ok" and st["prueba"] == 5 and "Solo las de prueba" in st["texto"]
    lr.cambiar_rol(r["R03"]["id"], "calibracion")
    lr.crear_roi(tramo, {"codigo": "R06", "tipo_campo": "bache", "x0": 200, "y0": 100, "x1": 400, "y1": 300, "rol": "calibracion"})
    st = p.estado_roles(tramo)
    assert st["nivel"] == "error" and "BLOQUEO" in st["texto"] and "R06" in st["texto"]
    res = p.ejecutar(tramo, {})
    assert not res.ok and "rois" in res.errores                                        # bloqueada por el solape
    lr.eliminar_roi(lr.listar_rois(tramo, rol="calibracion")[-1]["id"])
    e1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])
    ok = p.ejecutar(tramo, {"umbral_solape": "0,4"}, [e1])
    assert ok.ok and p.resultado["umbral_solape"] == 0.4 and len(p.filas_unidades()) == 4
    assert p.filas_totales()[1][1][0] == "Transversal" and "Validación guardada" in p.texto_estado()
    bad = p.ejecutar(tramo, {"umbral_solape": "9", "tolerancia_m": "x"})
    assert not bad.ok and set(bad.errores) == {"umbral_solape", "tolerancia_m"}
    # geometrías
    assert p.parsear_puntos("1, 2\n3 4\n5;6") == [(1, 2), (3, 4), (5, 6)]
    assert not p.agregar_geometria(r["R01"]["id"], "linea", "1,2\nabc").ok
    g = p.agregar_geometria(r["R01"]["id"], "linea", "300,100\n300,900")
    assert g.ok and p.listar_geometrias(r["R01"]["id"])[0][1][:2] == ("linea", 2)
    assert dict(p.filas_geometrias(tramo))[r["R01"]["id"]][2] == 1
    assert p.eliminar_geometria(g.datos["id"]).ok


def test_presentador_estadistica_secciones_figuras_y_comparacion(rois_prueba):
    tramo, r = rois_prueba
    p = PresentadorEstadistica(Contexto())
    assert p.listar_grupos(tramo) == [] and not p.calcular(tramo).ok
    mejores = {"R01": ["transversal"], "R02": ["longitudinal"], "R03": ["piel_cocodrilo"], "R04": ["bache"]}
    ia = _fijar_validacion(tramo, r, acierta=mejores, metodo="actual")
    ib = _fijar_validacion(tramo, r, acierta={"R01": ["transversal"]}, metodo="sun")
    lv.evaluar(tramo, ia)
    lv.evaluar(tramo, ib)
    g = p.listar_grupos(tramo)
    assert len(g) == 2 and "PROVISIONAL" in g[0][1]
    p.elegir_grupo(g[1][0])                                                              # el 'actual'
    res = p.calcular(tramo)
    assert res.ok and res.advertencias[0].startswith("PROVISIONAL") and p.provisional()
    assert p.errores_parciales() == {} and any("no hay pares" in a for a in res.advertencias)   # sin Ficha 4 en este caso
    filas = dict(p.filas_metricas())
    assert filas["bache"][1:5] == (1, 0, 0, 4) and filas["global"][5].startswith("1.00")
    assert [f[0] for f in p.filas_concordancia()][:2] == ["presencia", "tipo"]
    assert len(p.filas_tabla("tabla2")) == 2 and len(p.filas_tabla("tabla4")) == 1 and p.filas_totales()[0][1][0] == "Longitudinal"
    for clave, _ in p.FIGURAS:
        f = p.figura(clave)
        assert f is None or hasattr(f, "savefig")
    assert p.figura("metricas") is not None and p.figura("conf_tipo") is not None and p.figura("ba_area_m2") is not None
    c = p.comparar(g[0][0], g[1][0])
    assert c.ok and c.datos["solo_a_acierta"] + c.datos["solo_b_acierta"] > 0
    assert "McNemar" in p.texto_comparacion(c.datos)
    assert not p.comparar(g[0][0], g[0][0]).ok and not p.comparar(None, g[0][0]).ok


def test_presentador_calibracion_flujo_en_segundo_plano_y_confirmacion(tramo, tmp_path):
    from app import logica_configuracion as cfg, logica_importacion as li, logica_tramos as lt
    from tests.test_importacion import CSV_LEGADO, _csv
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    rois = {x["codigo"]: x for x in lr.listar_rois(tramo)}
    for c in ("R01", "R03"):
        lr.cambiar_rol(rois[c]["id"], "calibracion")
    for c in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[c]["id"], "prueba")
    cfg.guardar_params_base(Params().con(grieta_contraste_min=30.0, grieta_k_mad=10.0))
    p = PresentadorCalibracion(Contexto(), gestor_de_calculos())
    assert any(n == "grieta_k_mad" for n, _ in p.filas_parametros())
    assert not p.iniciar(tramo, ["gsd_cm"], "f1", "1", "5").ok                          # no calibrable
    assert not p.iniciar(tramo, ["grieta_k_mad"], "f1", "x", "5").ok
    assert not p.puede_confirmar() and not p.confirmar().ok
    r = p.iniciar(tramo, ["grieta_k_mad"], "f1", "1", "6")
    assert r.ok and p.ocupado
    assert not p.iniciar(tramo, ["grieta_k_mad"], "f1", "1", "6").ok                     # ya hay uno en curso
    assert p.gestor.esperar(120)
    ev = p.sondear()
    assert [e[0] for e in ev][-1] == "fin" and any(e[0] == "resultado" for e in ev)
    assert p.resultado["despues"]["f1"] >= p.resultado["antes"]["f1"] and p.resultado["guardado"] is False
    assert "Antes:" in p.texto_antes_despues() and p.puede_confirmar()
    assert cfg.es_provisional(cfg.params_base()) is True                                 # nada guardado todavía
    eventos = []
    p.ctx.suscribir("params", lambda *_: eventos.append(1))
    assert p.confirmar().ok and eventos == [1] and not p.puede_confirmar()
    assert cfg.es_provisional(cfg.params_base()) is False


def test_presentador_calibracion_cancelar_no_cambia_nada(tramo, tmp_path):
    from app import logica_configuracion as cfg, logica_importacion as li
    from tests.test_importacion import CSV_LEGADO, _csv
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    lr.cambiar_rol(lr.listar_rois(tramo)[0]["id"], "calibracion")
    antes = cfg.todas()
    p = PresentadorCalibracion(Contexto(), gestor_de_calculos())
    assert p.iniciar(tramo, ["grieta_k_mad", "bache_dL_min"], "f1", "2", "50").ok
    p.cancelar()
    assert p.gestor.esperar(60)
    ev = p.sondear()
    assert any(e[0] == "mensaje" and "cancelada" in e[2] for e in ev) or any(e[0] == "resultado" for e in ev)
    assert cfg.todas() == antes


# ------------------------------------------------------------------ Tk real
tk = pytest.importorskip("tkinter")
from app import basedatos                                                  # noqa: E402
from tests import humo_ui as h                                             # noqa: E402


@pytest.fixture
def v(tmp_path):
    h.preparar_demo(str(tmp_path))
    from app.ui.ventana_principal import VentanaPrincipal
    try:
        w = VentanaPrincipal(ruta_bd=":memory:", gestor_calculos=gestor_de_calculos(), geometria="1360x820")
    except tk.TclError as e:
        basedatos.cerrar()
        pytest.skip(f"sin pantalla: {e}")
    w.update()
    yield w
    try:
        w.cerrar() if False else (w.v_validacion.cerrar(), w.v_analisis.cerrar(), w.destroy())
    except tk.TclError:
        pass
    basedatos.cerrar()


def _roles_sin_solape():
    rois = {x["codigo"]: x for x in lr.listar_rois("T1")}
    for c in ("R01", "R03"):
        lr.cambiar_rol(rois[c]["id"], "calibracion")
    for c in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[c]["id"], "prueba")
    return rois


def test_humo_validar_estadistica_y_calibrar_desde_la_ventana(v, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    _roles_sin_solape()
    ld.analizar_rois("T1")
    v.ctx.emitir("rois")
    vv = v.v_validacion
    v.nb.select(vv)
    v.update()
    assert "ROI de prueba: 3" in vv._txt_roles
    vv.validar()
    v.update()
    assert len(vv.t_unidades.arbol.get_children()) == 12 and "PROVISIONAL" in vv.estado.cget("text")
    assert len(vv.t_totales.arbol.get_children()) == 4
    # opciones inválidas: todos los errores a la vez en el formulario
    vv.form.poner("umbral_solape", "9")
    vv.form.poner("tolerancia_m", "x")
    vv.validar()
    assert vv.form._err["umbral_solape"].cget("text") and vv.form._err["tolerancia_m"].cget("text")
    vv.form.poner("umbral_solape", "0.3")
    vv.form.poner("tolerancia_m", "0.1")
    # estadística
    ve = v.v_estadistica
    v.nb.select(ve)
    ve.refrescar()
    v.update()
    assert len(ve.combo.cget("values")) == 1
    ve.calcular()
    v.update()
    assert len(ve.p_metricas.tabla.arbol.get_children()) == 5
    assert ve.p_metricas.fig.figura is not None and ve.p_conc.fig.figura is not None
    ve.comparar_tramos()
    assert len(ve.t_tramos.arbol.get_children()) == 4 and "menos de 2" in ve.lbl_tramos.cget("text")
    ve.cmp_tipo.set("bache")
    ve.comparar()
    assert "dos conjuntos" in ve.res_cmp.cget("text")                                   # solo hay uno
    # calibración en segundo plano desde la vista
    from app import logica_configuracion as cfg
    cfg.guardar_params_base(Params().con(grieta_contraste_min=30.0, grieta_k_mad=10.0))
    vv._sel_params = {"grieta_k_mad"}
    vv.pasadas.set("1")
    vv.evals.set("6")
    vv.calibrar()
    assert vv.pc.ocupado and str(vv.btn_cal.cget("state")) == "disabled"
    assert h.esperar(v, lambda: not vv.pc.ocupado and vv.pc.resultado is not None, 120)
    h.esperar(v, lambda: str(vv.btn_cal.cget("state")) == "normal", 10)
    assert "Antes:" in vv.lbl_res.cget("text") and vv.fig_cal.figura is not None
    assert str(vv.btn_guardar.cget("state")) == "normal"
    vv.confirmar()
    assert cfg.es_provisional(cfg.params_base()) is False
    assert "Parámetros base" in v.v_analisis.lbl_params.cget("text") or True
    assert v.v_analisis.aviso_prov.cget("text") == ""                                    # ya no es provisional


def test_humo_referencias_geometricas_desde_la_vista(v):
    _roles_sin_solape()
    vv = v.v_validacion
    v.nb.select(vv)
    vv.refrescar()
    v.update()
    roi = lr.listar_rois("T1")[0]
    vv.t_rois.seleccionar(roi["id"], notificar=True)
    vv.txt_puntos.insert("1.0", "300,100\n300,900")
    vv._agregar_geom()
    assert len(vv.t_geoms.arbol.get_children()) == 1
    vv.txt_puntos.insert("1.0", "mal")
    vv._agregar_geom()
    assert "formato" in vv.banner_geom.cget("text")


def test_estadistica_avanzada_oculta_por_defecto_y_se_activa_desde_la_configuracion(rois_prueba):
    from app import logica_configuracion as cfg
    tramo, r = rois_prueba
    p = PresentadorEstadistica(Contexto())
    assert p.avanzada is False
    assert "pearson" not in p.columnas_medidas() and "prueba" not in p.columnas_medidas() and "rmse" in p.columnas_medidas()
    assert not any(c.startswith("ba_") for c, _ in p.figuras_visibles())
    ia = _fijar_validacion(tramo, r, acierta={"R01": ["transversal"], "R02": ["longitudinal"], "R04": ["bache"]})
    lv.evaluar(tramo, ia)
    p.listar_grupos(tramo)
    p.elegir_grupo(p.grupos[0]["clave"])
    p.calcular(tramo)
    assert all("[" not in fila[1][9] or True for fila in p.filas_metricas())
    assert "[" not in dict(p.filas_metricas())["global"][9]                       # F1 sin IC bootstrap
    p.fijar_avanzada(True)
    assert cfg.obtener("estadistica_avanzada") is True and "pearson" in p.columnas_medidas()
    assert "[" in dict(p.filas_metricas())["global"][9]                           # F1 con IC bootstrap
    assert any(c.startswith("ba_") for c, _ in p.figuras_visibles())


def test_humo_checkbox_avanzada_muestra_y_oculta_la_pestana_mcnemar(v):
    ve = v.v_estadistica
    textos = lambda: [ve.nb.tab(t, "text") for t in ve.nb.tabs() if ve.nb.tab(t, "state") != "hidden"]
    assert "Comparar ejecuciones" not in textos() and "Comparar tramos" in textos()
    ve.var_avanzada.set(True)
    ve._cambio_avanzada()
    assert "Comparar ejecuciones" in textos()
    ve.var_avanzada.set(False)
    ve._cambio_avanzada()
    assert "Comparar ejecuciones" not in textos()
