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
    h.preparar_demo(tmp)
    from app.ui.ventana_principal import VentanaPrincipal
    v = VentanaPrincipal(ruta_bd="datos/pavimento.db", geometria="1440x880")
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
    v.cerrar()
    return out


if __name__ == "__main__":
    for r in main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "capturas")):
        print(r)
