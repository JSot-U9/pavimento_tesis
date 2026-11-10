"""F6 · UI: presentador de reportes/exportación/respaldo sin Tk y recorrido de humo con Tk real (omitido sin pantalla)."""
import os

import pytest

from app import basedatos, graficos, logica_deteccion as ld, logica_roi as lr, logica_tramos as lt
from app.tareas import gestor_de_calculos
from app.ui.presentadores.base import Contexto
from app.ui.presentadores.p_reportes import PresentadorReportes
from tests.test_exportacion import escenario_geo                          # noqa: F401
from tests.test_reportes import escenario                                 # noqa: F401
from tests.test_validacion import rois_prueba                             # noqa: F401


def _esperar(p, max_s=60):
    assert p.gestor.esperar(max_s)
    return p.sondear()


# ------------------------------------------------------------------ gráficos (corrección de F5 hallada en F6)
def test_leyenda_de_metricas_tiene_las_cuatro_aunque_la_primera_barra_sea_nd():
    met = {"provisional": False, "por_tipo": {
        "longitudinal": {k: {"valor": None, "ic95": None} for k in ("sensibilidad", "especificidad", "precision", "f1")},
        "bache": {k: {"valor": .8, "ic95": [.6, .9]} for k in ("sensibilidad", "especificidad", "precision", "f1")}}}
    fig = graficos.fig_metricas_por_tipo(met)
    assert [t.get_text() for t in fig.axes[0].get_legend().get_texts()] == ["Sensibilidad", "Especificidad", "Precisión", "F1"]
    cal = {"objetivo": "f1", "n_rois": 1, "antes": {"sensibilidad": None, "precision": .5, "f1": .6, "kappa": .4},
           "despues": {"sensibilidad": None, "precision": 1, "f1": 1, "kappa": 1}}
    assert [t.get_text() for t in graficos.fig_calibracion(cal).axes[0].get_legend().get_texts()] == ["Antes", "Después"]


# ------------------------------------------------------------------ presentador: reportes
def test_opciones_y_validaciones_del_presentador(escenario, tmp_path):
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    o = p.opciones_por_defecto()
    assert o["formatos"] == ["pdf", "xlsx", "csv"] and o["excluir_fp"] is True and o["excel_es"] is False
    r = p.vista_previa(None, o)
    assert not r.ok and "elija un tramo" in r.texto_errores()
    r = p.vista_previa("T1", {**o, "formatos": []})
    assert not r.ok and "al menos un formato" in r.texto_errores()
    r = p.iniciar("T1", o, "")
    assert not r.ok and "carpeta" in r.texto_errores().lower()
    assert not p.ocupado


def test_vista_previa_resume_el_contenido_y_avisa_provisional(escenario):
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    r = p.vista_previa("T1", {**p.opciones_por_defecto(), "autor": "Yo"})
    assert r.ok and r.advertencias and r.advertencias[0].startswith("PROVISIONAL")
    t = r.datos["texto"]
    assert "5 ejecución(es)" in t and "última validada de cada ROI de prueba" in t
    assert "fuera del conteo por ser falsos positivos: 2" in t and "Validación y estadística: incluidas" in t
    assert r.datos["datos"]["meta"]["autor"] == "Yo"


def test_generar_en_hilo_de_trabajo_progreso_y_archivos(escenario, tmp_path):
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    o = {**p.opciones_por_defecto(), "excel_es": True}
    r = p.iniciar("T1", o, str(tmp_path / "sal"))
    assert r.ok
    ev = _esperar(p)
    tipos = [e[0] for e in ev]
    assert "resultado" in tipos and tipos[-1] == "fin"
    res = p.resultado
    assert set(res["archivos"]) == {"pdf", "xlsx", "csv_detecciones", "csv_validacion"} and not res["omitidos"]
    filas = p.filas_archivos(res)
    assert len(filas) == 4 and all(f[1][2].endswith(("KB", "MB")) for f in filas)
    assert ";" in open(res["archivos"]["csv_validacion"], encoding="utf-8-sig").readline()    # Excel en español


def test_el_hilo_de_trabajo_no_toca_la_bd(escenario, tmp_path, monkeypatch):
    """La escritura corre con `datos` ya calculados: si el hilo usara la BD, esta trampa lo delataría."""
    import threading
    principal = threading.current_thread()
    real = basedatos.nueva_sesion

    def vigilante():
        assert threading.current_thread() is principal, "el hilo de trabajo abrió una sesión de BD"
        return real()
    monkeypatch.setattr(basedatos, "nueva_sesion", vigilante)
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    assert p.iniciar("T1", p.opciones_por_defecto(), str(tmp_path)).ok
    ev = _esperar(p)
    assert not [e for e in ev if e[0] == "mensaje"] and p.resultado["archivos"]


def test_cancelar_la_generacion(escenario, tmp_path):
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    assert p.iniciar("T1", p.opciones_por_defecto(), str(tmp_path)).ok
    p.cancelar()
    ev = _esperar(p)
    assert ev[-1] == ("fin",)
    assert not p.iniciar("T1", {**p.opciones_por_defecto(), "formatos": ["csv"]}, str(tmp_path)).errores.get("")  # se puede volver a lanzar
    _esperar(p)


def test_no_se_lanza_dos_veces_a_la_vez(escenario, tmp_path):
    import threading
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    ev = threading.Event()
    from app.tareas import Calculo
    p.gestor.iniciar([Calculo("larga", lambda c, pr: ev.wait(5))])
    r = p.iniciar("T1", p.opciones_por_defecto(), str(tmp_path))
    assert not r.ok and "Ya hay un cálculo en curso" in r.texto_errores()
    ev.set()
    _esperar(p)


def test_error_de_escritura_se_traduce_a_mensaje_claro(escenario, tmp_path, monkeypatch):
    from app import logica_reportes as lrep

    def falla(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(lrep, "escribir_reportes", falla)
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    assert p.iniciar("T1", p.opciones_por_defecto(), str(tmp_path)).ok
    msgs = [e for e in _esperar(p) if e[0] == "mensaje"]
    assert msgs and msgs[0][1] == "error" and "abierto en otro programa" in msgs[0][2]


# ------------------------------------------------------------------ presentador: exportación y respaldo
def test_exportar_desde_el_presentador(escenario_geo, tmp_path):
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    assert "EPSG:32719" in p.estado_georreferencia("T1")
    r = p.exportar("T1", str(tmp_path / "t.gpkg"))
    assert r.ok and r.datos["verificado"] and "verificado releyendo" in p.texto_exportacion(r.datos)
    assert "EPSG:32719" in p.texto_exportacion(r.datos)
    r = p.exportar("T1", str(tmp_path / "t.gpkg"))
    assert not r.ok and "Ya existe" in r.texto_errores()
    assert not p.exportar("T1", "").ok and not p.exportar("T1", "x.gpkg", capas=()).ok and not p.exportar(None, "x").ok
    assert p.exportar("T1", str(tmp_path / "g"), "geojson", wgs84=True, capas=("roi",)).datos["epsg"] == 4326


def test_exportar_sin_georreferencia_explica_que_hacer(rois_prueba, tmp_path):
    tramo, r = rois_prueba
    p = PresentadorReportes(Contexto(), gestor_de_calculos())
    assert "no está georreferenciado" in p.estado_georreferencia(tramo)
    res = p.exportar(tramo, str(tmp_path / "x.gpkg"))
    assert not res.ok and "Asigne un ortomosaico georreferenciado" in res.texto_errores()


def test_respaldo_desde_el_presentador(tmp_path):
    basedatos.inicializar(str(tmp_path / "d" / "p.db"))
    try:
        ctx = Contexto()
        eventos = []
        ctx.suscribir("bd", lambda *a: eventos.append("bd"))
        p = PresentadorReportes(ctx, gestor_de_calculos())
        lt.crear_tramo({"codigo": "T1"})
        assert p.filas_respaldos() == []
        r = p.crear_respaldo()
        assert r.ok and len(p.filas_respaldos()) == 1
        ruta = p.filas_respaldos()[0][0]
        lt.eliminar_tramo("T1", confirmar=True)
        assert p.verificar(ruta).ok and not p.verificar(str(tmp_path / "no.db")).ok
        assert p.restaurar(ruta).ok and eventos == ["bd"] and ctx.tramo_id is None
        assert [t["codigo"] for t in lt.listar_tramos()] == ["T1"]
        p.fijar_respaldo_automatico(False)
        assert p.respaldo_automatico is False
    finally:
        basedatos.cerrar()


def test_restaurar_se_bloquea_con_un_calculo_en_curso(tmp_path):
    import threading
    from app.tareas import Calculo
    basedatos.inicializar(str(tmp_path / "p.db"))
    try:
        p = PresentadorReportes(Contexto(), gestor_de_calculos())
        ev = threading.Event()
        p.gestor.iniciar([Calculo("larga", lambda c, pr: ev.wait(5))])
        r = p.restaurar(str(tmp_path / "x.db"))
        assert not r.ok and "cálculo en curso" in r.texto_errores()
        ev.set()
        _esperar(p)
    finally:
        basedatos.cerrar()


# ------------------------------------------------------------------ Tk real
tk = pytest.importorskip("tkinter")
from tests import humo_ui as h                                             # noqa: E402


@pytest.fixture
def v(tmp_path):
    h.preparar_demo(str(tmp_path), ruta_bd=str(tmp_path / "datos" / "demo.db"))
    from app.ui.ventana_principal import VentanaPrincipal
    try:
        w = VentanaPrincipal(ruta_bd=str(tmp_path / "datos" / "demo.db"), abrir_bd=basedatos.inicializar,
                             gestor_calculos=gestor_de_calculos(), gestor_reportes=gestor_de_calculos(),
                             geometria="1360x820")
    except tk.TclError as e:
        basedatos.cerrar()
        pytest.skip(f"sin pantalla: {e}")
    w.update()
    yield w
    try:
        w.v_reportes.cerrar()
        w.v_validacion.cerrar()
        w.v_analisis.cerrar()
        w.destroy()
    except tk.TclError:
        pass
    basedatos.cerrar()


def _esperar_vista(w, vr, max_s=60):
    import time
    t0 = time.time()
    while (vr.pres.ocupado or vr._sondeo is not None) and time.time() - t0 < max_s:
        w.update()
        time.sleep(0.05)
    w.update()


def _preparar_validacion(w):
    rois = {x["codigo"]: x for x in lr.listar_rois("T1")}
    for c in ("R01", "R03"):
        lr.cambiar_rol(rois[c]["id"], "calibracion")
    for c in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[c]["id"], "prueba")
    ld.analizar_rois("T1")
    w.ctx.emitir("rois")
    w.v_validacion.validar()
    w.update()


def test_humo_pestana_reportes_genera_archivos_desde_la_ventana(v, tmp_path, monkeypatch):
    from tkinter import messagebox
    from app.ui import dialogo_reporte
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(dialogo_reporte.DialogoVistaPrevia, "abrir", lambda self: (self.destroy(), True)[1])
    _preparar_validacion(v)
    vr = v.v_reportes
    v.nb.select(vr)
    v.update()
    assert [v.nb.tab(t, "text") for t in v.nb.tabs()][-1] == "Reportes"
    assert "no está georreferenciado" in vr.lbl_geo.cget("text")
    vr.v_carpeta.set(str(tmp_path / "salida"))
    vr.v_autor.set("Prueba")
    vr.generar()
    _esperar_vista(v, vr)
    assert len(vr.t_archivos.arbol.get_children()) == 4
    assert all(os.path.isfile(i) for i in vr.t_archivos.arbol.get_children())
    assert "PROVISIONAL" in vr.banner_rep.cget("text")
    assert str(vr.btn_gen.cget("state")) == "normal" and str(vr.btn_cancel.cget("state")) == "disabled"
    # sin carpeta: error claro en el banner, sin ejecutar nada
    vr.v_carpeta.set("")
    vr.generar()
    assert "carpeta" in vr.banner_rep.cget("text").lower() and not vr.pres.ocupado


def test_humo_exportar_a_qgis_sin_georreferencia_y_en_pixeles(v, tmp_path, monkeypatch):
    from tkinter import filedialog
    _preparar_validacion(v)
    vr = v.v_reportes
    destino = str(tmp_path / "t1.gpkg")
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: destino)
    vr.exportar()
    assert "no está georreferenciado" in vr.banner_qgis.cget("text") and not os.path.exists(destino)
    vr.v_pixeles.set(True)
    vr.exportar()
    assert os.path.exists(destino) and "verificado releyendo" in vr.banner_qgis.cget("text")
    assert "coordenadas de IMAGEN" in vr.banner_qgis.cget("text")


def test_humo_respaldo_crear_y_restaurar_desde_la_ventana(v, tmp_path, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    vr = v.v_reportes
    vr.crear_respaldo()
    assert "Respaldo creado y verificado" in vr.banner_resp.cget("text")
    filas = vr.t_resp.arbol.get_children()
    assert len(filas) == 1
    lt.crear_tramo({"codigo": "T7"})
    vr.t_resp.seleccionar(filas[0])
    vr.restaurar(False)
    v.update()
    assert "restaurada" in vr.banner_resp.cget("text")
    assert [t["codigo"] for t in lt.listar_tramos()] == ["T1"]
    assert v.ctx.tramo_id is None
    vr.t_resp.seleccionar(None)
    vr.restaurar(False)
    assert "Elija un respaldo" in vr.banner_resp.cget("text")


def test_humo_el_menu_lleva_a_la_pestana_y_la_version_es_fase_6(v):
    v.ir_a_reportes()
    v.update()
    assert v.nb.select() == str(v.v_reportes)
    from tkinter import messagebox
    textos = []
    import tkinter
    orig = messagebox.showinfo
    messagebox.showinfo = lambda t, m, **k: textos.append(m)
    try:
        v.acerca()
    finally:
        messagebox.showinfo = orig
    assert "Fase 6 de 7" in textos[0]
