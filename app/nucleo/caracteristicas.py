"""
caracteristicas.py
==================
Características RGB de una región (ROI): estadísticos por banda y textura GLCM.
Equivale a la Ficha 6 SIN banda NIR ni reflectancia (el estudio es solo RGB): 'respuesta espectral'
= estadísticos de R, G, B; la textura es un descriptor adicional de apoyo.
"""
import cv2
import numpy as np
from skimage.feature import graycomatrix, graycoprops


def estadisticos_rgb(rgb, valido):
    out = {}
    for i, c in enumerate("RGB"):
        v = rgb[..., i][valido] if valido.any() else rgb[..., i].ravel()
        out[f"{c}_media"] = round(float(v.mean()), 2)
        out[f"{c}_min"] = int(v.min())
        out[f"{c}_max"] = int(v.max())
        out[f"{c}_desv"] = round(float(v.std()), 2)
    return out


def textura_glcm(gris, niveles=32):
    h, w = gris.shape
    if h > 2000 or w > 2000:                       # recorte central para acotar el costo
        y0, x0 = max(0, h // 2 - 1000), max(0, w // 2 - 1000)
        gris = gris[y0:y0 + 2000, x0:x0 + 2000]
    q = (gris.astype(np.uint16) * niveles // 256).astype(np.uint8)
    glcm = graycomatrix(q, distances=[1, 3], angles=[0, np.pi / 4, np.pi / 2, 3 * np.pi / 4],
                        levels=niveles, symmetric=True, normed=True)
    props = {n: float(graycoprops(glcm, n).mean())
             for n in ("contrast", "homogeneity", "correlation", "energy", "dissimilarity")}
    pl = np.where(glcm > 0, glcm, 1.0)
    entropia = float(-(glcm * np.log2(pl)).sum(axis=(0, 1)).mean())
    return {"tex_contraste": round(props["contrast"], 3), "tex_homogeneidad": round(props["homogeneity"], 4),
            "tex_correlacion": round(props["correlation"], 4), "tex_energia": round(props["energy"], 4),
            "tex_disimilitud": round(props["dissimilarity"], 3), "tex_entropia": round(entropia, 3)}


def caracteristicas_region(lector, region, valido_fn):
    """Estadísticos RGB y textura de una región (x0,y0,x1,y1); `valido_fn(rgb, nodata)` da la máscara."""
    rgb, nodata = lector.leer(*region)
    valido, _ = valido_fn(rgb, nodata)
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return {**estadisticos_rgb(rgb, valido), **textura_glcm(gris)}
