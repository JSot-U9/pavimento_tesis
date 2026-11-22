"""
ejemplo_sintetico.py
====================
Genera el EJEMPLO SINTÉTICO del tutorial (y de las pruebas): un «ortomosaico» de 2400 × 1400 px (GSD 0.5 cm/px) con
deterioros conocidos, el CSV de ROI de campo y el eje de vía. Es determinista (semilla fija): siempre sale la misma imagen.

Calzada horizontal (eje de la vía = 0°). Contiene:
  R01 grieta transversal (casi vertical, con 2 puntos de ruptura)
  R02 grieta longitudinal (casi horizontal, con 1 punto de ruptura)
  R03 piel de cocodrilo
  R04 bache
  R05 pavimento sano

No depende de la base de datos ni de la interfaz.
"""
import os
import shutil
import sys

import cv2
import numpy as np
from scipy.spatial import cKDTree

NOMBRE_IMAGEN = "ortomosaico_sintetico.png"
NOMBRE_ROIS = "rois_ejemplo.csv"
NOMBRE_EJE = "eje_ejemplo.csv"
GSD_CM = 0.5
ALTO, ANCHO = 1400, 2400

ROIS_CSV = f"""codigo_roi,tramo,tipo_campo,severidad_campo,x,y,ancho,alto,imagen
R01,Tramo sintetico,transversal,Baja,150,80,330,1000,{NOMBRE_IMAGEN}
R02,Tramo sintetico,longitudinal,Baja,560,560,1200,300,{NOMBRE_IMAGEN}
R03,Tramo sintetico,piel de cocodrilo,Media,950,100,500,450,{NOMBRE_IMAGEN}
R04,Tramo sintetico,bache,Alta,1700,720,400,360,{NOMBRE_IMAGEN}
R05,Tramo sintetico,sano,,1500,1050,500,300,{NOMBRE_IMAGEN}
"""
EJE_CSV = "x,y\n0,700\n2400,700\n"


def imagen_rgb():
    """Devuelve el ortomosaico sintético como arreglo uint8 (alto, ancho, 3) en RGB."""
    H, W = ALTO, ANCHO
    rng = np.random.default_rng(1)
    # asfalto: grano + gradiente de iluminación suave
    base = rng.normal(0, 7, (H, W)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 1.2) * 2.0
    yy, xx = np.mgrid[0:H, 0:W]
    ilum = 105 + 18 * np.sin(xx / 700.0) + 10 * np.cos(yy / 500.0)
    gray = ilum + base
    tinte = np.array([1.0, 0.98, 0.95], np.float32)          # leve tinte cálido (sin parecer vegetación)
    img = np.dstack([gray * t for t in tinte])

    def oscurecer(mask, delta):
        m = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.8)
        for c in range(3):
            img[..., c] -= delta * m

    def polilinea(pts, grosor):
        m = np.zeros((H, W), np.uint8)
        cv2.polylines(m, [np.array(pts, np.int32)], False, 1, grosor)
        return m

    # R01: transversal (vertical ligeramente inclinada), 2 huecos de ~6 px
    t = polilinea([(300, 120), (310, 400), (296, 700), (305, 1000)], 5)
    t[395:402, :] = 0
    t[690:697, :] = 0
    oscurecer(t, 70)
    # R02: longitudinal (horizontal), con un hueco
    lg = polilinea([(620, 700), (1000, 690), (1400, 706), (1700, 698)], 4)
    lg[:, 1180:1186] = 0
    oscurecer(lg, 65)
    # R03: piel de cocodrilo (Voronoi, celdas de ~15-20 cm)
    x0, y0, x1, y1 = 1000, 150, 1400, 500
    semillas = np.column_stack([rng.uniform(x0, x1, 130), rng.uniform(y0, y1, 130)])
    tree = cKDTree(semillas)
    gx, gy = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    d, _ = tree.query(np.column_stack([gx.ravel(), gy.ravel()]), k=2)
    borde = ((d[:, 1] - d[:, 0]) < 2.2).reshape(gx.shape)
    mm = np.zeros((H, W), np.uint8)
    mm[y0:y1, x0:x1] = borde
    oscurecer(mm, 60)
    # R04: bache (elipse oscura con textura gruesa)
    bm = np.zeros((H, W), np.uint8)
    cv2.ellipse(bm, (1900, 900), (70, 50), 15, 0, 360, 1, -1)
    bm_s = cv2.GaussianBlur(bm.astype(np.float32), (0, 0), 2.0)
    tex = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 2.5) * 40
    for c in range(3):
        img[..., c] += bm_s * (-48 + tex)
    return np.clip(img, 0, 255).astype(np.uint8)


def carpeta_incluida():
    """Carpeta `ejemplo/` que viaja con el proyecto (junto a main.py; en el ejecutable, dentro del paquete) o None si
    falta alguno de sus tres archivos."""
    raiz = getattr(sys, "_MEIPASS", None) or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    c = os.path.join(raiz, "ejemplo")
    ok = all(os.path.isfile(os.path.join(c, n)) for n in (NOMBRE_IMAGEN, NOMBRE_ROIS, NOMBRE_EJE))
    return c if ok else None


def obtener(destino):
    """Deja los tres archivos del ejemplo en `destino`: los copia de la carpeta `ejemplo/` del proyecto y, si esa carpeta
    no está o está incompleta, los genera (salen idénticos). Devuelve sus rutas."""
    origen = carpeta_incluida()
    if origen is None or os.path.abspath(origen) == os.path.abspath(destino):
        return generar(destino) if origen is None else _rutas(destino)
    os.makedirs(destino, exist_ok=True)
    for n in (NOMBRE_IMAGEN, NOMBRE_ROIS, NOMBRE_EJE):
        shutil.copyfile(os.path.join(origen, n), os.path.join(destino, n))
    return _rutas(destino)


def _rutas(carpeta):
    return {"ortomosaico": os.path.join(carpeta, NOMBRE_IMAGEN), "rois": os.path.join(carpeta, NOMBRE_ROIS),
            "eje": os.path.join(carpeta, NOMBRE_EJE)}


def generar(carpeta):
    """Escribe los tres archivos del ejemplo en `carpeta` (se crea si no existe). Devuelve sus rutas."""
    os.makedirs(carpeta, exist_ok=True)
    png = os.path.join(carpeta, NOMBRE_IMAGEN)
    if not cv2.imwrite(png, cv2.cvtColor(imagen_rgb(), cv2.COLOR_RGB2BGR)):
        raise OSError(f"No se pudo escribir {png}")
    rutas = _rutas(carpeta)
    for clave, texto in (("rois", ROIS_CSV), ("eje", EJE_CSV)):
        with open(rutas[clave], "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
    return rutas
