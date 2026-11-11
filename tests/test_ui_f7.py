"""F7 · UI: presentador de comparación de métodos (sin Tk) y recorrido de humo de la pestaña «Métodos» (con Tk real)."""
import pytest

from app import basedatos, logica_deteccion as ld, logica_roi as lr
from app.tareas import GestorTareas
from app.ui.presentadores.base import Contexto
from app.ui.presentadores.p_comparacion import PresentadorComparacion
from tests.test_comparacion import _forzado, e2e                          # noqa: F401
from tests.test_validacion import rois_prueba                             # noqa: F401


def _esperar(p, max_s=120):
    assert p.gestor.esperar(max_s)
    return p.sondear()


def test_metodos_distintos_y_tramo_obligatorio():
    p = PresentadorComparacion(Contexto(), GestorTareas())
    assert p.metodos_disponibles() == ["actual", "sun"]
    r = p.fijar_metodos("sun", "sun")
    assert not r.ok and "distintos" in r.texto_errores()
    assert p.fijar_metodos("actual", "sun").ok
    assert not p.comparar(None).ok and not p.iniciar(None).ok
    assert not p.ocupado


def test_comparar_lo_ya_validado_y_tablas(rois_prueba):
    tramo = _forzado(rois_prueba)
    p = PresentadorComparacion(Contexto(), GestorTareas())
    r = p.comparar(tramo)
    assert r.ok and r.advertencias and r.advertencias[0].startswith("PROVISIONAL")
    filas = dict(p.filas_metricas(r.datos))
    g_a, g_s = filas["actual|global"], filas["sun|global"]
    assert g_a[:2] == ("actual", "todos los comparables") and g_a[2:6] == (2, 0, 0, 4) and g_a[9] == "1.00"
    assert g_s[2:6] == (1, 1, 1, 3) and g_s[9] == "0.50" and g_s[10] == "66.7"
    assert len(filas) == 6
    assert [f[0] for f in p.filas_rendimiento(r.datos)] == ["actual", "sun"]
    assert "McNemar" in p.texto_conclusiones(r.datos)
    assert "RAM" in p.texto_advertencias(r.datos)


def test_sin_rois_de_prueba_o_sin_validacion_explica(rois_prueba):
    tramo, r = rois_prueba
    p = PresentadorComparacion(Contexto(), GestorTareas())
    res = p.comparar(tramo)
    assert not res.ok and "analice y valide" in res.texto_errores()


def test_iniciar_analiza_valida_y_compara_en_el_hilo_principal(e2e):
    ctx, eventos = Contexto(), []
    ctx.suscribir("ejecuciones", lambda *a: eventos.append("ejecuciones"))
    p = PresentadorComparacion(ctx, GestorTareas())
    assert p.iniciar(e2e).ok
    assert not p.iniciar(e2e).ok                                           # ya hay un cálculo en curso
    ev = _esperar(p)
    assert ev[-1] == ("fin",)
    assert not [e for e in ev if e[0] == "mensaje"], ev
    comp = [e for e in ev if e[0] == "comparacion"]
    assert len(comp) == 1 and p.comparacion is comp[0][1]
    c = p.comparacion
    assert c["n_unidades"] == 10 and c["mismos_params_base"] and eventos
    assert all(len(p._ids[m]) == 5 for m in ("actual", "sun"))
    assert p.progreso[0] > 0


def test_cancelar_deja_incidencias_y_no_compara(e2e):
    p = PresentadorComparacion(Contexto(), GestorTareas())
    assert p.iniciar(e2e).ok
    p.cancelar()
    ev = _esperar(p)
    assert ev[-1] == ("fin",) and not [e for e in ev if e[0] == "comparacion"]


# ------------------------------------------------------------------ Tk real
tk = pytest.importorskip("tkinter")
from tests.test_ui_f6 import v                                            # noqa: E402,F401


def test_humo_pestana_metodos(v):
    from tests.test_ui_f6 import _esperar_vista, _preparar_validacion
    assert [v.nb.tab(t, "text") for t in v.nb.tabs()][-2] == "Métodos"
    _preparar_validacion(v)
    vm = v.v_metodos
    v.nb.select(vm)
    v.update()
    v.ctx.fijar_tramo("T1")
    vm.comparar()                                                          # sin validación de 'sun': error claro
    assert "analice y valide" in vm.banner.cget("text")
    vm.v_b.set("actual")
    vm.comparar()
    assert "distintos" in vm.banner.cget("text")
    vm.v_b.set("sun")
    vm.ejecutar()
    assert vm.pres.ocupado or vm.pres.comparacion is not None
    _esperar_vista(v, vm, 180)
    assert vm.pres.comparacion is not None
    assert len(vm.t_metricas.arbol.get_children()) == 6 and len(vm.t_rend.arbol.get_children()) == 2
    texto = vm.txt.get("1.0", "end")
    assert "McNemar" in texto and "PROVISIONAL" in vm.banner.cget("text")
    assert str(vm.btn_ejecutar.cget("state")) == "normal" and str(vm.btn_cancel.cget("state")) == "disabled"
