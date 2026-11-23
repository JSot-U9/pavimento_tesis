"""
Recorrido de humo de la interfaz con datos sintéticos (lo usan `tests/test_ui_humo.py` y
`scripts/captura_pantallas.py`). Requiere pantalla (real o xvfb): `xvfb-run -a python scripts/captura_pantallas.py`.
"""
import os
import time

import cv2

from app import basedatos, logica_fichas, logica_importacion, logica_roi, logica_tramos
from tests.sintetico import ortomosaico_ejemplo

CSV_ROI = """codigo_roi;tipo_campo;severidad_campo;x;y;ancho;alto
R01;transversal;Baja;150;80;330;1000
R02;Longitudinal;baja;560;560;1200;300
R03;Piel de cocodrilo;Media;950;100;500;450
R04;hueco;Alta;1700;720;400;360
R05;sano;;1500;1050;500;300
"""


def preparar_demo(carpeta, ruta_bd=":memory:"):
    """BD con un tramo T1 (ortomosaico sintético 2400x1400 a 0.5 cm/px), eje, 5 ROI y fichas de ejemplo."""
    basedatos.inicializar(ruta_bd)
    rgb, _ = ortomosaico_ejemplo()
    png = os.path.join(carpeta, "ortomosaico_demo.png")
    cv2.imwrite(png, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    csv = os.path.join(carpeta, "rois.csv")
    with open(csv, "w", encoding="utf-8") as f:
        f.write(CSV_ROI)
    logica_tramos.crear_tramo({"codigo": "T1", "via": "Vía de prueba (sintética)", "ubicacion": "Cusco",
                               "progresiva_ini_m": 0, "progresiva_fin_m": 12, "ancho_calzada_m": 7,
                               "n_carriles": 2})
    logica_tramos.asignar_ortomosaico("T1", png, gsd_cm=0.5)
    logica_tramos.definir_eje("T1", [(0, 700), (2400, 700)])
    logica_importacion.importar_rois("T1", csv)
    logica_roi.asignar_roles("T1", 0.5, 42)
    logica_fichas.crear("vuelo", {"codigo": "V1", "fecha": "2026-10-20", "dron": "DJI Mavic 3", "altura_m": 20,
                                  "gsd_cm": 0.5}, "T1")
    insp = logica_fichas.crear("inspeccion", {"fecha": "2026-10-21", "responsable": "J. Sotelo", "observador": 1}, "T1")
    roi = logica_roi.listar_rois("T1")[0]
    logica_fichas.registrar_patologia(insp["id"], {"codigo": "GTR", "progresiva_m": 3.2, "roi_id": roi["id"]},
                                      {"longitud_m": 5, "ancho_prom_mm": 4}, {"nivel": "Alta"})
    return png, csv


def esperar(ventana, cond, timeout=60.0):
    fin = time.time() + timeout
    while time.time() < fin:
        ventana.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def pulsar(lienzo, x, y, x2=None, y2=None, doble=False):
    """Clic (o arrastre) con el botón izquierdo sobre el Canvas, con eventos reales de Tk."""
    lienzo.event_generate("<Motion>", x=x, y=y)
    lienzo.event_generate("<ButtonPress-1>", x=x, y=y)
    if x2 is not None:
        for k in range(1, 6):
            lienzo.event_generate("<B1-Motion>", x=x + (x2 - x) * k // 5, y=y + (y2 - y) * k // 5, state=0x100)
    lienzo.event_generate("<ButtonRelease-1>", x=x2 if x2 is not None else x, y=y2 if y2 is not None else y)
    if doble:
        lienzo.event_generate("<Double-Button-1>", x=x, y=y)
    lienzo.update()


def captura(ventana, ruta):
    from PIL import ImageGrab
    ventana.update_idletasks()
    ventana.update()
    x, y, w, h = ventana.winfo_rootx(), ventana.winfo_rooty(), ventana.winfo_width(), ventana.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY")).save(ruta)
    return ruta
