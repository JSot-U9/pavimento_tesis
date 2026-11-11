"""
Recorre la interfaz con datos sintéticos y guarda capturas en `capturas/`.
Uso (sin pantalla):  xvfb-run -a -s "-screen 0 1440x900x24" python scripts/captura_pantallas.py [carpeta]
"""
import os
import sys
import tempfile

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from tests import humo_ui as h                                   # noqa: E402


def main(salida):
    os.makedirs(salida, exist_ok=True)
    tmp = tempfile.mkdtemp()
    ruta_bd = os.path.join(tmp, "datos", "pavimento.db")          # BD en archivo (el respaldo de F6 lo exige)
    h.preparar_demo(tmp, ruta_bd=ruta_bd)
    from app import basedatos
    from app.ui.ventana_principal import VentanaPrincipal
    v = VentanaPrincipal(ruta_bd=ruta_bd, abrir_bd=basedatos.inicializar, geometria="1440x880")
    v.update()
    out = []

    def cap(nombre):
        out.append(h.captura(v, os.path.join(salida, nombre)))

    cap("01_tramos.png")
    v.v_tramos.nuevo()
    v.v_tramos.form.poner("ancho_calzada_m", "abc")
    v.v_tramos.form.poner("n_carriles", "2.5")
    v.v_tramos.guardar()
    cap("01b_tramos_errores_de_validacion.png")
    v.v_tramos.tabla.seleccionar(1, notificar=True)
    v.update()
    v.nb.select(v.v_fichas)
    cap("02_fichas_vuelos.png")
    insp = v.v_fichas.nametowidget(v.v_fichas.winfo_children()[0])
    insp.select(len(insp.tabs()) - 1)
    v.update()
    v.v_fichas.insp.tabla.seleccionar(1, notificar=True)
    cap("03_fichas_inspecciones.png")
    v.nb.select(v.v_analisis)
    a = v.v_analisis
    h.esperar(v, lambda: a.visor._mini is not None, 30)
    v.update()
    cap("04_analisis_visor_rois.png")
    ids = {r["codigo"]: r["id"] for r in a.panel_roi.rois}
    for cod, iid in (("R04", ids["R04"]), ("R02", ids["R02"])):
        a.panel_roi.tabla.seleccionar(iid, notificar=True)
        v.update()                                   # <<TreeviewSelect>> se entrega de forma asíncrona
        a.alcance.set("roi")
        a.analizar()
        h.esperar(v, lambda: not a.pres.ocupado and a.btn_analizar.instate(["!disabled"]), 90)
        v.update()
    a.nb.select(a.panel_roi)
    cap("05_analisis_resultados.png")
    d = a.pres.detecciones[0]["id"]
    a.tabla.seleccionar(d, notificar=True)
    v.update()
    cap("06_analisis_seleccion.png")
    a.nb.select(0)
    v.update()
    cap("07_analisis_panel.png")
    # diálogo de informe de importación (vista previa con errores y advertencias)
    from app.ui import dialogo_reporte as dr
    from app.ui.presentadores.p_roi import PresentadorROI
    csv = os.path.join(tmp, "otras.csv")
    open(csv, "w", encoding="utf-8").write(
        "codigo_roi;tipo_campo;x;y;ancho;alto\nQ1;bache;10;10;100;100\nQ2;volcan;0;0;10;10\nR01;bache;5;5;50;50\n")
    inf = PresentadorROI(a.ctx).importar(1, csv, {"estricto": False}, simular=True).datos
    dlg = dr.DialogoInforme(v, inf, confirmable=True)
    dlg.geometry("+%d+%d" % (v.winfo_rootx() + 300, v.winfo_rooty() + 200))
    v.update()
    out.append(h.captura(dlg, os.path.join(salida, "08_importacion_vista_previa.png")))
    dlg.destroy()
    _fase5(v, a, out, salida)
    _fase6(v, out, salida, tmp)
    _fase7(v, out, salida)
    v.cerrar()
    return out


def _fase5(v, a, out, salida):
    """F5: validación, referencias, calibración y estadística con datos sintéticos (ejecuciones reales del motor)."""
    from tkinter import messagebox

    from app import logica_configuracion as cfg, logica_deteccion as ld, logica_fichas as lf, logica_roi as lr
    from app.nucleo.parametros import Params

    def cap(nombre, w=v):
        out.append(h.captura(w, os.path.join(salida, nombre)))

    rois = {r["codigo"]: r for r in lr.listar_rois("T1")}
    for c in ("R01", "R03"):
        lr.cambiar_rol(rois[c]["id"], "calibracion")
    for c in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[c]["id"], "prueba")
    # fichas: Ficha 4 (medidas de campo) y severidad de dos observadores
    i1 = lf.crear("inspeccion", {"fecha": "2026-10-22", "observador": 1}, "T1")
    i2 = lf.crear("inspeccion", {"fecha": "2026-10-23", "observador": 2}, "T1")
    campo = {"R02": ("GLO", {"longitud_m": 5.8, "ancho_prom_mm": 3.0, "area_m2": 0.02}, "Media", "Media"),
             "R04": ("HUE", {"longitud_m": 1.9, "ancho_prom_mm": 1800.0, "area_m2": 0.6}, "Alta", "Media")}
    for c, (cod, g, s1, s2) in campo.items():
        lf.registrar_patologia(i1["id"], {"codigo": cod, "roi_id": rois[c]["id"]}, g, {"nivel": s1})
        lf.registrar_patologia(i2["id"], {"codigo": cod, "roi_id": rois[c]["id"]}, severidad={"nivel": s2})
    ld.analizar_rois("T1")
    v.ctx.emitir("rois")
    vv = v.v_validacion
    v.nb.select(vv)
    v.update()
    vv.validar()
    cap("09_validacion.png")
    vv.nb.select(1)
    v.update()
    vv.t_rois.seleccionar(rois["R02"]["id"], notificar=True)
    vv.txt_puntos.insert("1.0", "560,700\n1760,700")
    vv._agregar_geom()
    cap("10_validacion_referencias.png")
    # calibración con umbrales deliberadamente malos
    cfg.guardar_params_base(Params().con(grieta_contraste_min=30.0, grieta_k_mad=10.0))
    vv.nb.select(2)
    vv._sel_params = {"grieta_k_mad"}
    vv.pasadas.set("1")
    vv.evals.set("6")
    vv.calibrar()
    h.esperar(v, lambda: not vv.pc.ocupado and vv.pc.resultado is not None, 120)
    h.esperar(v, lambda: str(vv.btn_guardar.cget("state")) == "normal", 10)
    v.update()
    cap("11_calibracion.png")
    cfg.guardar_params_base(Params())                                          # no se confirma: vuelve a lo provisional
    ve = v.v_estadistica
    v.nb.select(ve)
    ve.refrescar()
    ve.calcular()
    v.update()
    cap("12_estadistica_metricas.png")
    ve.nb.select(ve.p_conc)
    ve.p_conc.combo.current(0)
    ve.p_conc.pintar_figura()
    v.update()
    cap("13_estadistica_concordancia.png")
    ve.nb.select(ve.p_med)
    v.update()
    cap("14_estadistica_medidas.png")
    ve.nb.select(3)
    v.update()
    cap("15_estadistica_tablas.png")


def _fase6(v, out, salida, tmp):
    """F6: pestaña Reportes (vista previa, generación de PDF/XLSX/CSV, exportación a QGIS, respaldo) y el PDF generado."""
    import subprocess
    from tkinter import filedialog, messagebox

    from app.ui import dialogo_reporte as dr

    def cap(nombre, w=v):
        out.append(h.captura(w, os.path.join(salida, nombre)))

    vr = v.v_reportes
    v.nb.select(vr)
    vr.v_autor.set("Autor de ejemplo")
    vr.v_inst.set("UNSAAC")
    vr.v_carpeta.set(os.path.join(tmp, "reportes"))
    v.update()
    r = vr.pres.vista_previa(v.ctx.tramo_id, vr._opciones())
    d = r.datos["datos"]
    dlg = dr.DialogoVistaPrevia(v, r.datos["texto"], d["conclusiones"], d["advertencias"], "Informe PDF, Libro Excel, CSV")
    dlg.geometry("+%d+%d" % (v.winfo_rootx() + 300, v.winfo_rooty() + 100))
    v.update()
    out.append(h.captura(dlg, os.path.join(salida, "16_reportes_vista_previa.png")))
    dlg.destroy()
    dr.DialogoVistaPrevia.abrir = lambda self: (self.destroy(), True)[1]
    messagebox.askyesno = lambda *a, **k: True
    vr.generar()
    h.esperar(v, lambda: not vr.pres.ocupado and vr._sondeo is None, 90)
    v.update()
    vr.crear_respaldo()
    filedialog.asksaveasfilename = lambda *a, **k: os.path.join(tmp, "t1.gpkg")
    vr.v_pixeles.set(True)
    vr.exportar()
    v.update()
    cap("17_reportes_pestana.png")
    pdf = vr.pres.resultado["archivos"].get("pdf") if vr.pres.resultado else None
    if pdf:
        try:
            subprocess.run(["pdftoppm", "-r", "70", "-png", "-f", "1", "-l", "6", pdf,
                            os.path.join(salida, "18_informe_pdf")], check=True)
            out.append(os.path.join(salida, "18_informe_pdf-*.png"))
        except (OSError, subprocess.CalledProcessError):
            pass


def _fase7(v, out, salida):
    """F7: pestaña Métodos: analiza y valida con 'actual' y 'sun' sobre las ROI de prueba y compara."""
    from app import logica_roi as lr
    rois = {x["codigo"]: x for x in lr.listar_rois(v.ctx.tramo_id)}
    for c in ("R02", "R04", "R05"):
        lr.cambiar_rol(rois[c]["id"], "prueba")
    vm = v.v_metodos
    v.nb.select(vm)
    v.update()
    vm.ejecutar()
    h.esperar(v, lambda: not vm.pres.ocupado and vm._sondeo is None, 180)
    v.update()
    out.append(h.captura(v, os.path.join(salida, "19_metodos_comparacion.png")))


if __name__ == "__main__":
    for r in main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "capturas")):
        print(r)
