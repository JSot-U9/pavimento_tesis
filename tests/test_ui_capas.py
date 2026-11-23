"""Reglas de capas de la F4: las vistas no importan modelos ni sesiones; solo llaman a logica_*."""
import ast
import os

RAIZ = os.path.join(os.path.dirname(__file__), "..", "app")
PROHIBIDOS = ("app.modelos", "sqlalchemy", "app.basedatos", "app.nueva_sesion")


def _importados(ruta):
    arbol = ast.parse(open(ruta, encoding="utf-8").read())
    mods = []
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            mods += [(a.name, n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods.append((n.module or "", n.lineno))
            mods += [(f"{n.module}.{a.name}", n.lineno) for a in n.names]
    return mods


def _archivos(sub):
    for d, _, fs in os.walk(os.path.join(RAIZ, sub)):
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def test_ui_no_importa_modelos_basedatos_ni_sqlalchemy():
    malos = [(os.path.relpath(r, RAIZ), m, l) for r in _archivos("ui") for m, l in _importados(r)
             if any(m == p or m.startswith(p + ".") for p in PROHIBIDOS)]
    assert not malos, malos


def test_ui_no_usa_nueva_sesion():
    for r in _archivos("ui"):
        for n in ast.walk(ast.parse(open(r, encoding="utf-8").read())):
            assert not (isinstance(n, ast.Attribute) and n.attr == "nueva_sesion"), r
            assert not (isinstance(n, ast.Name) and n.id == "nueva_sesion"), r


def test_presentadores_y_modelo_del_visor_no_usan_tk():
    sin_tk = [r for r in _archivos("ui/presentadores")] + [os.path.join(RAIZ, "ui", "visor_modelo.py"),
                                                           os.path.join(RAIZ, "ui", "imagen_visor.py")]
    for r in sin_tk:
        assert not [m for m, _ in _importados(r) if m == "tkinter" or m.startswith("tkinter.")], r


def test_nucleo_y_logica_no_importan_la_ui():
    for sub in ("nucleo",):
        for r in _archivos(sub):
            assert not [m for m, _ in _importados(r) if m.startswith("app.ui") or m == "app.tareas"], r
    for f in os.listdir(RAIZ):
        if f.startswith("logica_"):
            assert not [m for m, _ in _importados(os.path.join(RAIZ, f)) if m.startswith("app.ui")], f
