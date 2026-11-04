"""
geovector.py
============
Lectura de capas vectoriales de QGIS SIN dependencias externas (ni shapely, fiona ni GDAL):

  - GeoJSON (.geojson / .json)
  - GeoPackage (.gpkg): SQLite + geometría WKB con cabecera GeoPackage (OGC 12-128r18)

Cada entidad se devuelve como {"props": {...}, "geom": {"tipo": ..., "coords": ...} | None} con
coordenadas (x, y) (se descarta Z/M). Tipos: Point, LineString, Polygon y sus Multi*.
No lee Shapefile ni KML: exporte la capa desde QGIS a GeoPackage o GeoJSON.
"""
import json
import os
import re
import sqlite3
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from app.crs import ErrorCRS, convertir


class ErrorFormatoGeo(Exception):
    """Archivo vectorial ilegible, de formato no soportado o con geometrías inválidas."""


@dataclass
class Capa:
    nombre: str
    epsg: Optional[int]                      # None = el archivo no declara CRS
    features: List[dict] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------ WKB
_TIPOS_WKB = {1: "Point", 2: "LineString", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString",
              6: "MultiPolygon"}


class _Lector:
    def __init__(self, datos):
        self.d, self.i = datos, 0

    def tomar(self, fmt, n):
        v = struct.unpack_from(fmt, self.d, self.i)
        self.i += n
        return v


def _wkb(r: _Lector):
    orden = r.tomar("B", 1)[0]
    e = "<" if orden == 1 else ">"
    codigo = r.tomar(e + "I", 4)[0]
    z = bool(codigo & 0x80000000) or 1000 <= (codigo & 0xFFFF) < 2000 or 3000 <= (codigo & 0xFFFF) < 4000
    m = bool(codigo & 0x40000000) or 2000 <= (codigo & 0xFFFF) < 4000
    if codigo & 0x20000000:
        r.tomar(e + "I", 4)                                     # SRID incrustado (EWKB): se ignora
    base = (codigo & 0xFFFF) % 1000
    if base not in _TIPOS_WKB:
        raise ErrorFormatoGeo(f"Tipo de geometría WKB no soportado: {codigo}")
    nd = 2 + z + m

    def punto():
        v = r.tomar(e + "d" * nd, 8 * nd)
        return (v[0], v[1])

    def puntos():
        n = r.tomar(e + "I", 4)[0]
        return [punto() for _ in range(n)]

    tipo = _TIPOS_WKB[base]
    if tipo == "Point":
        return {"tipo": tipo, "coords": punto()}
    if tipo == "LineString":
        return {"tipo": tipo, "coords": puntos()}
    if tipo == "Polygon":
        return {"tipo": tipo, "coords": [puntos() for _ in range(r.tomar(e + "I", 4)[0])]}
    partes = [_wkb(r)["coords"] for _ in range(r.tomar(e + "I", 4)[0])]
    return {"tipo": tipo, "coords": partes}


def decodificar_wkb(datos):
    try:
        return _wkb(_Lector(bytes(datos)))
    except struct.error as e:
        raise ErrorFormatoGeo(f"Geometría WKB truncada o dañada: {e}") from e


def decodificar_geometria_gpkg(blob):
    """Cabecera GeoPackage: 'GP', versión, banderas, srs_id, [envolvente] + WKB."""
    blob = bytes(blob)
    if len(blob) < 8 or blob[:2] != b"GP":
        raise ErrorFormatoGeo("Geometría GeoPackage inválida (falta la marca 'GP')")
    banderas = blob[3]
    if banderas & 0b00010000:                                   # geometría vacía
        return None
    envolvente = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((banderas >> 1) & 0b111)
    if envolvente is None:
        raise ErrorFormatoGeo("Indicador de envolvente GeoPackage inválido")
    return decodificar_wkb(blob[8 + envolvente:])


# ------------------------------------------------------------------------------------ GeoJSON
def _epsg_de_texto(texto):
    if not texto:
        return None
    t = str(texto)
    if "CRS84" in t.upper():
        return 4326
    m = re.search(r"EPSG:{1,2}(\d+)", t, re.I) or re.search(r"/EPSG/\d+/(\d+)", t)
    return int(m.group(1)) if m else None


def _geom_geojson(g):
    if g is None:
        return None
    tipo = g.get("type")
    if tipo not in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
        raise ErrorFormatoGeo(f"Tipo de geometría GeoJSON no soportado: {tipo}")

    def rec(c):
        if c and isinstance(c[0], (int, float)):
            return (float(c[0]), float(c[1]))
        return [rec(x) for x in c]

    return {"tipo": tipo, "coords": rec(g["coordinates"])}


def leer_geojson(ruta):
    try:
        with open(ruta, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
    except (OSError, ValueError) as e:
        raise ErrorFormatoGeo(f"No se pudo leer el GeoJSON {ruta}: {e}") from e
    tipo = datos.get("type")
    if tipo == "FeatureCollection":
        entidades = datos.get("features", [])
    elif tipo == "Feature":
        entidades = [datos]
    elif tipo in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
        entidades = [{"properties": {}, "geometry": datos}]
    else:
        raise ErrorFormatoGeo("El archivo no es un GeoJSON válido (FeatureCollection, Feature o geometría)")
    crs = datos.get("crs")
    epsg = _epsg_de_texto(((crs or {}).get("properties") or {}).get("name")) if crs else 4326   # RFC 7946
    capa = Capa(os.path.splitext(os.path.basename(ruta))[0], epsg)
    if crs and epsg is None:
        capa.advertencias.append("el GeoJSON declara un CRS que no se pudo interpretar")
    for k, ent in enumerate(entidades):
        try:
            geom = _geom_geojson(ent.get("geometry"))
        except (KeyError, IndexError, TypeError) as e:
            raise ErrorFormatoGeo(f"Entidad {k + 1}: geometría GeoJSON mal formada ({e})") from e
        capa.features.append({"props": dict(ent.get("properties") or {}), "geom": geom})
    return capa


# ------------------------------------------------------------------------------------ GeoPackage
def _abrir_gpkg(ruta):
    if not os.path.isfile(ruta):
        raise ErrorFormatoGeo(f"No existe el archivo: {ruta}")
    try:
        con = sqlite3.connect(f"file:{os.path.abspath(ruta).replace(os.sep, '/')}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM gpkg_contents LIMIT 1")
        return con
    except sqlite3.Error as e:
        raise ErrorFormatoGeo(f"{ruta} no es un GeoPackage válido: {e}") from e


def listar_capas_gpkg(ruta):
    con = _abrir_gpkg(ruta)
    try:
        return [r["table_name"] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name")]
    finally:
        con.close()


def leer_gpkg(ruta, capa=None):
    con = _abrir_gpkg(ruta)
    try:
        nombres = [r["table_name"] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name")]
        if not nombres:
            raise ErrorFormatoGeo("El GeoPackage no contiene capas vectoriales")
        if capa is None:
            if len(nombres) > 1:
                raise ErrorFormatoGeo(f"El GeoPackage tiene varias capas ({', '.join(nombres)}): indique cuál usar")
            capa = nombres[0]
        elif capa not in nombres:
            raise ErrorFormatoGeo(f"La capa '{capa}' no existe en el GeoPackage. Capas: {', '.join(nombres)}")
        gc = con.execute("SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?",
                         (capa,)).fetchone()
        if gc is None:
            raise ErrorFormatoGeo(f"La capa '{capa}' no declara columna de geometría")
        col_geom, srs = gc["column_name"], gc["srs_id"]
        sr = con.execute("SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id=?",
                         (srs,)).fetchone()
        epsg = int(sr["organization_coordsys_id"]) if sr and str(sr["organization"]).upper() == "EPSG" else None
        if srs == 4326:
            epsg = 4326
        out = Capa(capa, epsg)
        if epsg is None:
            out.advertencias.append(f"el GeoPackage usa srs_id={srs}, que no es EPSG")
        for fila in con.execute(f'SELECT * FROM "{capa}"'):
            props = {k: fila[k] for k in fila.keys() if k != col_geom}
            blob = fila[col_geom]
            out.features.append({"props": props, "geom": decodificar_geometria_gpkg(blob) if blob else None})
        return out
    except sqlite3.Error as e:
        raise ErrorFormatoGeo(f"Error leyendo el GeoPackage: {e}") from e
    finally:
        con.close()


def leer_capa(ruta, capa=None):
    ext = os.path.splitext(ruta)[1].lower()
    if ext in (".geojson", ".json"):
        return leer_geojson(ruta)
    if ext == ".gpkg":
        return leer_gpkg(ruta, capa)
    raise ErrorFormatoGeo(f"Formato '{ext}' no soportado. Use .geojson o .gpkg (exporte desde QGIS).")


# ------------------------------------------------------------------------------------ utilidades
def _mapear(coords, f):
    if isinstance(coords, tuple):
        return f(coords)
    return [_mapear(c, f) for c in coords]


def transformar_geom(geom, epsg_origen, epsg_destino):
    """Reproyecta una geometría (solo 4326 <-> UTM WGS84; ver crs.py)."""
    if geom is None or epsg_origen == epsg_destino:
        return geom

    def un_punto(p):
        x, y = convertir(p[0], p[1], epsg_origen, epsg_destino)
        return (float(x), float(y))

    return {"tipo": geom["tipo"], "coords": _mapear(geom["coords"], un_punto)}


def anillos(geom):
    """Lista de anillos exteriores de un Polygon/MultiPolygon."""
    if geom is None:
        return []
    if geom["tipo"] == "Polygon":
        return [geom["coords"][0]]
    if geom["tipo"] == "MultiPolygon":
        return [p[0] for p in geom["coords"]]
    return []


def lineas(geom):
    """Lista de polilíneas de un LineString/MultiLineString."""
    if geom is None:
        return []
    if geom["tipo"] == "LineString":
        return [geom["coords"]]
    if geom["tipo"] == "MultiLineString":
        return list(geom["coords"])
    return []


def puntos(geom):
    if geom is None:
        return []
    if geom["tipo"] == "Point":
        return [geom["coords"]]
    if geom["tipo"] == "MultiPoint":
        return list(geom["coords"])
    return []


def area_anillo(anillo):
    """Área por la fórmula del zapatero (valor absoluto)."""
    a = 0.0
    for (x0, y0), (x1, y1) in zip(anillo, anillo[1:] + anillo[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def unir_lineas(partes, tol=1e-6):
    """Concatena partes consecutivas (fin de una = inicio de la siguiente). Error si no empalman."""
    if len(partes) == 1:
        return list(partes[0])
    out = list(partes[0])
    for k, p in enumerate(partes[1:], start=2):
        if abs(out[-1][0] - p[0][0]) > tol or abs(out[-1][1] - p[0][1]) > tol:
            raise ErrorFormatoGeo(f"La línea tiene varias partes que no empalman (parte {k}). "
                                  f"Únalas en QGIS (Vector > Herramientas de geoprocesamiento > Disolver) "
                                  f"o deje solo el eje de vía en la capa.")
        out.extend(p[1:])
    return out


__all__ = ["Capa", "ErrorFormatoGeo", "ErrorCRS", "leer_capa", "leer_geojson", "leer_gpkg", "listar_capas_gpkg",
           "decodificar_wkb", "decodificar_geometria_gpkg", "transformar_geom", "anillos", "lineas", "puntos",
           "area_anillo", "unir_lineas"]
