"""app/tareas.py: hilo de trabajo + cola + cancelación (sin Tk ni BD)."""
import ast
import os
import threading
import time

import pytest

from app.nucleo.estructuras import AnalisisCancelado
from app.tareas import GestorTareas

RAIZ = os.path.join(os.path.dirname(__file__), "..", "app")


class T:                                   # trabajo de juguete (el gestor solo lo pasa a `ejecutar`)
    def __init__(self, n):
        self.n, self.etiqueta = n, f"T{n}"


def _todos(g, timeout=10):
    assert g.esperar(timeout), "el hilo no terminó"
    return g.sondear()


def test_resultado_progreso_y_fin_en_orden():
    hilos = []

    def ejecutar(trabajo, cancelar, progreso):
        hilos.append(threading.current_thread())
        progreso(0.5, "mitad")
        return f"res{trabajo.n}"

    g = GestorTareas(ejecutar)
    g.iniciar([T(1)])
    ms = _todos(g)
    assert [m.tipo for m in ms] == ["inicio", "progreso", "resultado", "fin"]
    assert ms[2].resultado == "res1" and ms[1].fraccion == 0.5 and ms[1].texto == "mitad"
    assert hilos[0] is not threading.main_thread() and hilos[0].daemon
    assert not g.ocupado


def test_cancelar_detiene_y_avisa():
    entro = threading.Event()

    def ejecutar(trabajo, cancelar, progreso):
        entro.set()
        while not cancelar.is_set():
            time.sleep(0.01)
        raise AnalisisCancelado("Análisis cancelado por el usuario")

    g = GestorTareas(ejecutar)
    g.iniciar([T(1), T(2), T(3)])
    assert entro.wait(5) and g.ocupado
    g.cancelar()
    assert g.cancelando
    ms = _todos(g)
    tipos = [m.tipo for m in ms]
    assert tipos == ["inicio", "cancelado", "fin"]                 # los trabajos 2 y 3 se descartan
    assert ms[1].trabajo.n == 1 and "cancelado" in ms[1].texto


def test_error_se_informa_con_detalle_y_no_mata_la_aplicacion():
    def ejecutar(trabajo, cancelar, progreso):
        raise RuntimeError("falla en el núcleo")

    g = GestorTareas(ejecutar)
    g.iniciar([T(1), T(2)])
    ms = _todos(g)
    assert [m.tipo for m in ms] == ["inicio", "error", "fin"]
    assert "RuntimeError: falla en el núcleo" == ms[1].texto and "Traceback" in ms[1].detalle
    g.iniciar([T(3)])                                              # se puede volver a usar
    assert _todos(g)[-2].tipo in ("error", "resultado")


def test_varios_trabajos_en_orden():
    g = GestorTareas(lambda t, c, p: t.n * 10)
    g.iniciar([T(1), T(2), T(3)])
    ms = _todos(g)
    assert [m.resultado for m in ms if m.tipo == "resultado"] == [10, 20, 30]
    assert [(m.indice, m.total) for m in ms if m.tipo == "inicio"] == [(1, 3), (2, 3), (3, 3)]


def test_no_se_puede_iniciar_dos_veces_a_la_vez():
    soltar = threading.Event()
    g = GestorTareas(lambda t, c, p: soltar.wait(5))
    g.iniciar([T(1)])
    with pytest.raises(RuntimeError):
        g.iniciar([T(2)])
    with pytest.raises(ValueError):
        GestorTareas(lambda *a: 0).iniciar([])
    soltar.set()
    _todos(g)


def test_sondear_une_progresos_consecutivos_y_no_bloquea():
    paso = threading.Event()

    def ejecutar(trabajo, cancelar, progreso):
        for i in range(100):
            progreso(i / 100, f"{i}")
        paso.set()
        return "ok"

    g = GestorTareas(ejecutar)
    t0 = time.perf_counter()
    assert g.sondear() == []
    assert time.perf_counter() - t0 < 0.05
    g.iniciar([T(1)])
    assert g.esperar(5)
    ms = g.sondear()
    progresos = [m for m in ms if m.tipo == "progreso"]
    assert len(progresos) == 1 and progresos[0].texto == "99"       # solo el último


def test_tareas_no_importa_tk_ni_bd():
    """Regla del proyecto: el hilo y la cola no conocen Tk, la BD ni los modelos."""
    arbol = ast.parse(open(os.path.join(RAIZ, "tareas.py"), encoding="utf-8").read())
    mods = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module)
            mods |= {f"{n.module}.{a.name}" for a in n.names}
    prohibidos = ("tkinter", "sqlalchemy", "app.basedatos", "app.modelos", "app.logica_roi", "app.logica_tramos")
    assert not [m for m in mods if any(m == p or m.startswith(p + ".") for p in prohibidos)], mods
    assert "app.logica_deteccion" in mods


def test_gestor_de_calculos_ejecuta_funciones_con_progreso_y_cancelacion():
    from app.tareas import Calculo, gestor_de_calculos

    def suma(cancelar, progreso):
        progreso(0.5, "a medias")
        return 42

    g = gestor_de_calculos()
    g.iniciar([Calculo("suma", suma)])
    assert g.esperar(5)
    tipos = [(m.tipo, m.resultado) for m in g.sondear()]
    assert ("resultado", 42) in tipos and tipos[-1][0] == "fin" and any(t == "progreso" for t, _ in tipos)

    def espera(cancelar, progreso):
        from app.nucleo.estructuras import AnalisisCancelado
        cancelar.wait(5)
        raise AnalisisCancelado("x")

    g.iniciar([Calculo("larga", espera)])
    g.cancelar()
    assert g.esperar(5)
    assert [m.tipo for m in g.sondear()][-2:] == ["cancelado", "fin"]
