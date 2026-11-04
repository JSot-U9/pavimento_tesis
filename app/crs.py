"""
crs.py
======
Conversión de coordenadas entre WGS84 (EPSG:4326) y WGS84/UTM (EPSG:326zz norte, 327zz sur), en Python
puro (serie de Krüger de 4.º orden, error < 1 mm dentro de la zona). Cubre el caso habitual de la tesis:
QGIS exporta GeoJSON en 4326 y el ortomosaico está en UTM (Cusco: 32719 = WGS84 / UTM 19S).

No sustituye a pyproj: otros sistemas (PSAD56, SIRGAS, Transversal de Mercator local, etc.) no se
convierten aquí; en ese caso se pide reproyectar la capa en QGIS al CRS del ortomosaico.
"""
import math

import numpy as np

_A = 6378137.0
_F = 1 / 298.257223563
_N = _F / (2 - _F)
_K0 = 0.9996
_E0 = 500000.0
_RADIO = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64 + _N ** 6 / 256)
_n = _N
_ALFA = (_n / 2 - 2 * _n ** 2 / 3 + 5 * _n ** 3 / 16 + 41 * _n ** 4 / 180,
         13 * _n ** 2 / 48 - 3 * _n ** 3 / 5 + 557 * _n ** 4 / 1440,
         61 * _n ** 3 / 240 - 103 * _n ** 4 / 140,
         49561 * _n ** 4 / 161280)
_BETA = (_n / 2 - 2 * _n ** 2 / 3 + 37 * _n ** 3 / 96 - _n ** 4 / 360,
         _n ** 2 / 48 + _n ** 3 / 15 - 437 * _n ** 4 / 1440,
         17 * _n ** 3 / 480 - 37 * _n ** 4 / 840,
         4397 * _n ** 4 / 161280)
_DELTA = (2 * _n - 2 * _n ** 2 / 3 - 2 * _n ** 3 + 116 * _n ** 4 / 45,
          7 * _n ** 2 / 3 - 8 * _n ** 3 / 5 - 227 * _n ** 4 / 45,
          56 * _n ** 3 / 15 - 136 * _n ** 4 / 35,
          4279 * _n ** 4 / 630)


class ErrorCRS(Exception):
    """No se puede convertir entre los sistemas de coordenadas indicados."""


def zona_utm(epsg):
    """(zona, es_sur) si `epsg` es WGS84/UTM; si no, None."""
    if epsg is None:
        return None
    if 32601 <= epsg <= 32660:
        return epsg - 32600, False
    if 32701 <= epsg <= 32760:
        return epsg - 32700, True
    return None


def es_geografico_wgs84(epsg):
    return epsg == 4326


def _utm_directo(lon, lat, zona, sur):
    lon, lat = np.radians(np.asarray(lon, float)), np.radians(np.asarray(lat, float))
    dl = lon - math.radians(zona * 6 - 183)
    dl = (dl + np.pi) % (2 * np.pi) - np.pi
    c = 2 * math.sqrt(_N) / (1 + _N)
    s = np.sin(lat)
    t = np.sinh(np.arctanh(s) - c * np.arctanh(c * s))
    xi_p = np.arctan2(t, np.cos(dl))
    eta_p = np.arctanh(np.sin(dl) / np.sqrt(1 + t * t))
    xi, eta = xi_p.copy(), eta_p.copy()
    for j, a in enumerate(_ALFA, start=1):
        xi += a * np.sin(2 * j * xi_p) * np.cosh(2 * j * eta_p)
        eta += a * np.cos(2 * j * xi_p) * np.sinh(2 * j * eta_p)
    este = _E0 + _K0 * _RADIO * eta
    norte = _K0 * _RADIO * xi + (10_000_000.0 if sur else 0.0)
    return este, norte


def _utm_inverso(este, norte, zona, sur):
    este, norte = np.asarray(este, float), np.asarray(norte, float)
    xi = (norte - (10_000_000.0 if sur else 0.0)) / (_K0 * _RADIO)
    eta = (este - _E0) / (_K0 * _RADIO)
    xi_p, eta_p = xi.copy(), eta.copy()
    for j, b in enumerate(_BETA, start=1):
        xi_p -= b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta_p -= b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xi_p) / np.cosh(eta_p))
    lat = chi.copy()
    for j, d in enumerate(_DELTA, start=1):
        lat += d * np.sin(2 * j * chi)
    lon = math.radians(zona * 6 - 183) + np.arctan2(np.sinh(eta_p), np.cos(xi_p))
    return np.degrees(lon), np.degrees(lat)


def convertir(x, y, epsg_origen, epsg_destino):
    """Convierte arreglos/escalares (x, y) entre EPSG. x = este o longitud; y = norte o latitud."""
    if epsg_origen == epsg_destino:
        return np.asarray(x, float), np.asarray(y, float)
    z_o, z_d = zona_utm(epsg_origen), zona_utm(epsg_destino)
    if es_geografico_wgs84(epsg_origen) and z_d:
        return _utm_directo(x, y, *z_d)
    if z_o and es_geografico_wgs84(epsg_destino):
        return _utm_inverso(x, y, *z_o)
    if z_o and z_d:
        lon, lat = _utm_inverso(x, y, *z_o)
        return _utm_directo(lon, lat, *z_d)
    raise ErrorCRS(
        f"No se puede convertir de EPSG:{epsg_origen} a EPSG:{epsg_destino} dentro del programa "
        f"(solo WGS84 EPSG:4326 y WGS84/UTM EPSG:326xx/327xx). Reproyecte la capa en QGIS al CRS del "
        f"ortomosaico (Vector > Herramientas de gestión de datos > Reproyectar capa).")
