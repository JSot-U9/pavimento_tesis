"""Escritor mínimo de GeoPackage y GeoJSON para las pruebas (sin shapely/fiona/GDAL)."""
import json
import sqlite3
import struct


def _wkb_poligono(anillo):
    cuerpo = struct.pack("<BIII", 1, 3, 1, len(anillo)) + b"".join(struct.pack("<dd", x, y) for x, y in anillo)
    return cuerpo


def _wkb_punto(x, y):
    return struct.pack("<BIdd", 1, 1, x, y)


def _wkb_linea(pts):
    return struct.pack("<BII", 1, 2, len(pts)) + b"".join(struct.pack("<dd", x, y) for x, y in pts)


def escribir_gpkg(ruta, capa, epsg, filas):
    """filas = [(props_dict, ('poligono'|'punto'|'linea', coords))]. Props con tipos simples (texto/real)."""
    con = sqlite3.connect(ruta)
    con.executescript(f"""
    PRAGMA application_id=1196444487; PRAGMA user_version=10300;
    CREATE TABLE gpkg_spatial_ref_sys(srs_name TEXT, srs_id INTEGER PRIMARY KEY, organization TEXT,
        organization_coordsys_id INTEGER, definition TEXT, description TEXT);
    CREATE TABLE gpkg_contents(table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT, description TEXT,
        last_change TEXT, min_x REAL, min_y REAL, max_x REAL, max_y REAL, srs_id INTEGER);
    CREATE TABLE gpkg_geometry_columns(table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER,
        z INTEGER, m INTEGER);
    INSERT INTO gpkg_spatial_ref_sys VALUES('EPSG:{epsg}', {epsg}, 'EPSG', {epsg}, 'x', '');
    INSERT INTO gpkg_contents(table_name, data_type, identifier, srs_id) VALUES('{capa}', 'features', '{capa}', {epsg});
    INSERT INTO gpkg_geometry_columns VALUES('{capa}', 'geom', 'GEOMETRY', {epsg}, 0, 0);
    """)
    cols = sorted({k for p, _ in filas for k in p})
    con.execute(f'CREATE TABLE "{capa}"(fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB' +
                "".join(f', "{c}" TEXT' for c in cols) + ")")
    for props, (kind, coords) in filas:
        wkb = {"poligono": lambda c: _wkb_poligono(c), "punto": lambda c: _wkb_punto(*c),
               "linea": _wkb_linea}[kind](coords)
        cab = b"GP" + bytes([0, 0b00000001]) + struct.pack("<i", epsg)       # sin envolvente, little endian
        con.execute(f'INSERT INTO "{capa}"(geom{"".join(f", {chr(34)}{c}{chr(34)}" for c in cols)}) VALUES (?'
                    + ",?" * len(cols) + ")", [cab + wkb] + [None if props.get(c) is None else str(props[c]) for c in cols])
    con.commit()
    con.close()


def escribir_geojson(ruta, features, epsg=None):
    """features = [(props, geometría GeoJSON)]. Sin `epsg` no se escribe 'crs' (RFC 7946 = WGS84)."""
    d = {"type": "FeatureCollection",
         "features": [{"type": "Feature", "properties": p, "geometry": g} for p, g in features]}
    if epsg:
        d["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{epsg}"}}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(d, f)
