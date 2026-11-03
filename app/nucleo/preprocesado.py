"""
preprocesado.py
===============
Utilidades de imagen y normalización de la iluminación (Sun, 2009, cap. 3):
    I_norm = I - gauss(I) + media(I)
"""
import cv2
import numpy as np


def impar(n, minimo, maximo):
    """Entero impar acotado entre minimo y maximo (tamaños de kernel morfológico)."""
    n = max(minimo, min(maximo, int(round(n))))
    return n if n % 2 == 1 else n + 1


def blur_grande(img, sigma):
    """Gaussiana de sigma grande (reduce primero la imagen para que sea rápida)."""
    h, w = img.shape[:2]
    s = max(1, min(int(sigma // 6), min(h, w) // 8))
    if s > 1:
        pequena = cv2.resize(img, None, fx=1.0 / s, fy=1.0 / s, interpolation=cv2.INTER_AREA)
        pequena = cv2.GaussianBlur(pequena, (0, 0), max(sigma / s, 0.5))
        return cv2.resize(pequena, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(img, (0, 0), max(sigma, 0.5))


def mad_robusto(x):
    """Desviación absoluta mediana escalada (equivale a sigma si los datos son normales)."""
    x = np.asarray(x, dtype=np.float32).ravel()
    if x.size == 0:
        return 0.0
    return float(np.median(np.abs(x - np.median(x))) * 1.4826)


def preprocesar(gris, valido, p):
    """Normaliza la iluminación del tono de gris (uint8) usando solo la calzada válida."""
    g = gris.astype(np.float32)
    media = float(g[valido].mean()) if valido.any() else float(g.mean())
    g = np.where(valido, g, media)                    # evita bordes falsos fuera de la calzada
    sigma = max(5.0, p.iluminacion_sigma_m / p.gsd_m)
    sigma = min(sigma, max(3.0, min(g.shape) / 3.0))
    fondo = blur_grande(g, sigma)
    return np.clip(g - fondo + media, 0, 255).astype(np.uint8)
