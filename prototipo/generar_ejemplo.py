#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera un "ortomosaico" sintético (GSD = 0.5 cm/px) con deterioros conocidos y el CSV de ROI de
campo correspondiente, para probar pavimento_rgb.py sin necesidad de datos reales.

Calzada horizontal (eje de la vía = 0°). Contiene:
  R01 grieta transversal (casi vertical, con 2 puntos de ruptura)
  R02 grieta longitudinal (casi horizontal)
  R03 piel de cocodrilo
  R04 bache
  R05 pavimento sano
"""
import os
import sys

import cv2
import numpy as np
from scipy.spatial import cKDTree

out = sys.argv[1] if len(sys.argv) > 1 else "ejemplo"
os.makedirs(out, exist_ok=True)
rng = np.random.default_rng(1)
H, W = 1400, 2400

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


def polilinea(pts, grosor, huecos=()):
    m = np.zeros((H, W), np.uint8)
    pts = np.array(pts, np.int32)
    cv2.polylines(m, [pts], False, 1, grosor)
    for (hx0, hx1) in huecos:                 # puntos de ruptura (columnas a borrar)
        m[:, hx0:hx1] = 0
    return m


# R01: transversal (vertical ligeramente inclinada), 2 huecos de ~6 px
t = polilinea([(300, 120), (310, 400), (296, 700), (305, 1000)], 5)
t[395:402, :] = 0
t[690:697, :] = 0
oscurecer(t, 70)
# R02: longitudinal (horizontal), con un hueco
l = polilinea([(620, 700), (1000, 690), (1400, 706), (1700, 698)], 4)
l[:, 1180:1186] = 0
oscurecer(l, 65)

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

img = np.clip(img, 0, 255).astype(np.uint8)
cv2.imwrite(os.path.join(out, "ortomosaico_sintetico.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

rois = """codigo_roi,tramo,tipo_campo,severidad_campo,x,y,ancho,alto,imagen
R01,Tramo sintetico,transversal,Baja,150,80,330,1000,ortomosaico_sintetico.png
R02,Tramo sintetico,longitudinal,Baja,560,560,1200,300,ortomosaico_sintetico.png
R03,Tramo sintetico,piel de cocodrilo,Media,950,100,500,450,ortomosaico_sintetico.png
R04,Tramo sintetico,bache,Alta,1700,720,400,360,ortomosaico_sintetico.png
R05,Tramo sintetico,sano,,1500,1050,500,300,ortomosaico_sintetico.png
"""
with open(os.path.join(out, "rois_ejemplo.csv"), "w", encoding="utf-8") as f:
    f.write(rois)
print("Generado en", out)
