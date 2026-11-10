"""Pruebas de la interfaz con Tk real. Se omiten si no hay pantalla (usar `xvfb-run -a pytest`)."""
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from app import basedatos, logica_deteccion as ld, logica_roi as lr, logica_tramos as lt        # noqa: E402
from app.nucleo.estructuras import AnalisisCancelado                                            # noqa: E402
from app.tareas import GestorTareas                                                             # noqa: E402
from tests import humo_ui as h                                                                  # noqa: E402


def _abrir(tmp_path, gestor=None):
    h.preparar_demo(str(tmp_path))
    from app.ui.ventana_principal import VentanaPrincipal
    try:
        return VentanaPrincipal(ruta_bd=":memory:", gestor=gestor, geometria="1360x820")
    except tk.TclError as e:
        basedatos.cerrar()
        pytest.skip(f"sin pantalla: {e}")


@pytest.fixture
def v(tmp_path):
    w = _abrir(tmp_path)
    w.update()
    yield w
    try:
        w.v_analisis.cerrar()
        w.destroy()
    except tk.TclError:
        pass
    basedatos.cerrar()


def test_abre_con_tramo_activo_y_formulario_cargado(v):
    assert [v.nb.tab(t, "text") for t in v.nb.tabs()] == ["Tramos", "Fichas", "Análisis", "Validación", "Estadística", "Reportes"]
    assert v.ctx.tramo_id is not None and v.combo.get().startswith("T1")
    assert v.v_tramos.form.leer()["codigo"] == "T1"                       # la ficha del tramo activo se muestra
    assert "2400 × 1400 px" in v.v_tramos.info_orto.cget("text")


def test_formulario_muestra_todos_los_errores_a_la_vez(v):
    f = v.v_tramos.form
    v.v_tramos.nuevo()
    f.poner("ancho_calzada_m", "abc")
    f.poner("n_carriles", "2.5")
    v.v_tramos.guardar()
    v.update()
    assert f._err["codigo"].cget("text") == "es obligatorio"
    assert "número" in f._err["ancho_calzada_m"].cget("text") and "entero" in f._err["n_carriles"].cget("text")
    resumen = f._resumen.cget("text")
    assert resumen.count("•") == 3 and "Código del tramo: es obligatorio" in resumen
    f.poner("codigo", "T2")                                               # corregir un campo limpia su error
    assert f._err["codigo"].cget("text") == ""


def test_visor_zoom_miniatura_y_dibujo_de_roi(v):
    v.nb.select(v.v_analisis)
    a = v.v_analisis
    assert h.esperar(v, lambda: a.visor._mini is not None, 20)
    m = a.visor.modelo
    e0 = m.escala
    a.visor.lienzo.event_generate("<Button-4>", x=300, y=200)             # rueda arriba = acercar
    v.update()
    assert m.escala > e0
    a.visor.ajustar()
    assert m.escala == pytest.approx(m.escala_ajuste())
    a.visor.fijar_modo("roi")
    h.pulsar(a.visor.lienzo, 100, 120, 260, 220)
    v.update()
    assert a.nb.select() == str(a.panel_roi)                              # el panel de ROI recibe el rectángulo
    f = a.panel_roi.form.leer()
    assert all(f[k] for k in ("x0", "y0", "x1", "y1")) and int(f["x1"]) > int(f["x0"])
    a.panel_roi.guardar()                                                  # sin código ni tipo: errores juntos
    errs = a.panel_roi.form._resumen.cget("text")
    assert "Código de la ROI: es obligatorio" in errs and "Tipo (campo)" in errs
    a.panel_roi.form.poner("codigo", "NUEVA")
    a.panel_roi.form.poner("tipo_campo", "bache")
    a.panel_roi.guardar()
    assert "NUEVA" in {r["codigo"] for r in lr.listar_rois("T1")}
    assert len(a.visor._rois) == 6


def test_dibujar_eje_en_el_visor_lo_guarda(v, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    v.nb.select(v.v_analisis)
    a = v.v_analisis
    h.esperar(v, lambda: a.visor._mini is not None, 20)
    antes = lt.obtener_eje("T1")["id"]
    a.visor.fijar_modo("eje")
    for x, y in ((120, 200), (300, 230), (500, 210)):
        h.pulsar(a.visor.lienzo, x, y)
    a.visor.lienzo.event_generate("<Return>")
    v.update()
    e = lt.obtener_eje("T1")
    assert e["id"] != antes and len(e["vertices_px"]) == 3 and e["origen"] == "manual"
    assert len(a.visor._eje) == 3 and a.visor.modo == "mover"


def test_analisis_desde_la_interfaz_y_seleccion_de_una_deteccion(v):
    v.nb.select(v.v_analisis)
    a = v.v_analisis
    h.esperar(v, lambda: a.visor._mini is not None, 20)
    roi = next(r for r in lr.listar_rois("T1") if r["codigo"] == "R04")
    a.panel_roi.tabla.seleccionar(roi["id"], notificar=True)
    v.update()
    a.alcance.set("roi")
    a.analizar()
    assert a.btn_cancelar.instate(["!disabled"]) and a.btn_analizar.instate(["disabled"])
    assert h.esperar(v, lambda: not a.pres.ocupado and a.btn_analizar.instate(["!disabled"]), 90)
    assert [d["tipo"] for d in a.pres.detecciones] == ["bache"]
    assert len(a.tabla.arbol.get_children()) == 1 and a.tabla_res.arbol.get_children()
    assert "PROVISIONALES" in a.lbl_ejec.cget("text") and "PROVISIONALES" in a.aviso_prov.cget("text")
    d = a.pres.detecciones[0]
    a.visor.ir_a_region((d["x"] - 100, d["y"] - 100, d["x"] + d["w"] + 100, d["y"] + d["h"] + 100))
    v.update()
    px, py = a.visor.modelo.imagen_a_pantalla(d["cx"], d["cy"])
    h.pulsar(a.visor.lienzo, int(px), int(py))
    v.update()
    assert a.pres.seleccion == d["id"] and a.tabla.seleccion() == d["id"]
    assert "Bache" in a.detalle.get("1.0", "end") and "ORIENTATIVA" in a.detalle.get("1.0", "end")


def test_la_interfaz_no_se_congela_y_cancelar_registra(tmp_path):
    arranco = threading.Event()

    def lenta(trabajo, cancelar, progreso):
        arranco.set()
        for i in range(400):
            progreso(i / 400, f"paso {i}")
            if cancelar.is_set():
                raise AnalisisCancelado("Análisis cancelado por el usuario")
            time.sleep(0.02)
        raise AssertionError("debía cancelarse")

    w = _abrir(tmp_path, GestorTareas(lenta))
    try:
        w.update()
        a = w.v_analisis
        w.nb.select(a)
        roi = lr.listar_rois("T1")[0]
        a.panel_roi.tabla.seleccionar(roi["id"], notificar=True)
        w.update()
        latidos = []

        def latido():
            latidos.append(time.perf_counter())
            w.after(20, latido)
        w.after(20, latido)
        t0 = time.perf_counter()
        a.alcance.set("roi")
        a.analizar()
        assert time.perf_counter() - t0 < 0.5                              # volvió enseguida
        assert h.esperar(w, lambda: a.barra.cget("value") > 0, 10) and arranco.is_set()
        n = len(latidos)
        h.esperar(w, lambda: len(latidos) >= n + 10, 5)
        huecos = [b - a_ for a_, b in zip(latidos, latidos[1:])]
        assert len(latidos) >= n + 10 and max(huecos) < 0.5                # el bucle de Tk siguió latiendo
        a.cancelar()
        assert h.esperar(w, lambda: a.btn_analizar.instate(["!disabled"]) and not a.pres.ocupado, 10)
        inc = ld.listar_ejecuciones("T1", estado="cancelada")
        assert len(inc) == 1 and "cancelado" in a.msg.cget("text").lower()
    finally:
        w.v_analisis.cerrar()
        w.destroy()
        basedatos.cerrar()


def test_dialogo_de_parametros_valida_y_aplica(v, monkeypatch):
    from app.ui import dialogo_parametros as dp
    a = v.v_analisis
    ejecutado = {}

    def falso_abrir(self):
        f = self.form
        f.poner("grieta_k_mad", "abc")
        f.poner("celdas_min", "6")
        self._aplicar()
        ejecutado["errores"] = f._resumen.cget("text")
        f.poner("grieta_k_mad", "5,5")
        self._aplicar()
        ejecutado["ok"] = self.resultado
        return self.resultado

    monkeypatch.setattr(dp._Modal, "abrir", falso_abrir)
    dp.DialogoParametros(v, a.pres)
    assert "grieta_k_mad" in ejecutado["errores"] or "k·MAD" in ejecutado["errores"]
    assert ejecutado["ok"] and a.pres.params_actuales().celdas_min == 6
    a._params_info()
    assert "2 parámetro" in a.lbl_params.cget("text")


def test_importacion_de_roi_con_vista_previa_desde_el_panel(v, tmp_path, monkeypatch):
    from app.ui import dialogo_reporte as dr
    p = tmp_path / "otras.csv"
    p.write_text("codigo_roi;tipo_campo;x;y;ancho;alto\nQ1;bache;10;10;100;100\nQ2;volcan;0;0;10;10\n", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(dr.DialogoImportar, "abrir", lambda self: (str(p), {"sistema": "auto", "si_existe": "error",
                                                                          "estricto": True, "capa": "", "epsg": ""}))
    monkeypatch.setattr(dr.DialogoInforme, "abrir", lambda self: vistos.append(self) or None)   # el usuario cancela
    v.v_analisis.panel_roi.importar()
    assert len(vistos) == 1 and len(lr.listar_rois("T1")) == 5             # la vista previa no guardó nada
