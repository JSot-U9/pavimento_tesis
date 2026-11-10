"""
logica_exportacion.py
=====================
Exporta a QGIS las capas de un tramo: `detecciones`, `roi` y `eje_via`, en el CRS del ortomosaico y con los
atributos del capítulo 3.2 (tipo, longitud, ancho, área, % de área afectada, progresiva, severidad ORIENTATIVA,
estado de validación...).

    exportar_gpkg(tramo, ruta, ...)      GeoPackage escrito con sqlite3 + WKB (sin GDAL, sin fiona, sin shapely)
    exportar_geojson(tramo, carpeta, ...) un .geojson por capa (con miembro `crs`, que QGIS/GDAL leen)
    exportar(tramo, ruta_o_carpeta, formato)

El GPKG sigue OGC 12-128r18 (application_id 'GPKG', user_version 10300, tablas gpkg_spatial_ref_sys /
gpkg_contents / gpkg_geometry_columns, cabecera de geometría con envolvente XY). Tras escribirlo se RELEE con
`geovector.leer_gpkg` (el lector inverso del programa) y se comprueba nº de entidades, CRS y envolvente: el
resultado trae `verificado=True` solo si coincide.

Convenciones
  * Píxel -> mapa con la transformación afín del tramo. Los vértices de las detecciones son ÍNDICES de píxel y se
    llevan al centro del píxel (+0.5); los rectángulos de ROI y los vértices del eje son coordenadas continuas (sin
    desplazamiento).
  * Sin georreferenciación el export se rechaza, salvo `permitir_pixeles=True`: entonces las coordenadas son las del
    ortomosaico con y invertida (x, -y), con CRS cartesiano indefinido (srs_id -1) y se avisa.
  * `epsg_salida` permite 4326 u otro WGS84/UTM (solo los que convierte `crs.py`); por defecto el EPSG del ortomosaico.
  * Los falsos positivos NO se eliminan del export (están registrados): `estado_validacion = FP` e
    `incluida_en_conteo = 0`; con `solo_conteo=True` se omiten.
"""
import json
import logging
import os
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app import logica_deteccion as ld, logica_reportes as lrep, logica_roi, logica_tramos as lt, logica_validacion as lv
from app import geovector
from app.crs import ErrorCRS, convertir, zona_utm
from app.logica_comun import ErrorValidacion

log = logging.getLogger("pavimento.exportacion")

CAPAS = ("detecciones", "roi", "eje_via")
GPKG_APP_ID = 0x47504B47                     # 'GPKG'
GPKG_VERSION = 10300                         # 1.3.0


class ErrorExportacion(ValueError):
    """No se puede exportar (sin georreferenciación, archivo existente, CRS no soportado...)."""


# ===================================================================================== esquema de atributos
# (columna, tipo GPKG, clave en la fila)
ATRIBUTOS = {
    "detecciones": [("id_deteccion", "INTEGER"), ("ejecucion_id", "INTEGER"), ("roi", "TEXT"), ("tipo", "TEXT"),
                    ("estado_validacion", "TEXT"), ("incluida_en_conteo", "BOOLEAN"), ("progresiva_m", "REAL"),
                    ("lado_via", "TEXT"), ("longitud_m", "REAL"), ("ancho_mm", "REAL"), ("ancho_m", "REAL"),
                    ("area_m2", "REAL"), ("pct_area_afectada", "REAL"), ("densidad_pct", "REAL"),
                    ("n_celdas", "INTEGER"), ("celda_media_m2", "REAL"), ("severidad_prelim", "TEXT"),
                    ("desv_eje_deg", "REAL"), ("contraste_weber", "REAL"), ("ramificada", "BOOLEAN"),
                    ("metodo_ancho", "TEXT"), ("metodo", "TEXT"), ("provisional", "BOOLEAN"), ("advertencia", "TEXT")],
    "roi": [("codigo", "TEXT"), ("tipo_campo", "TEXT"), ("severidad_campo", "TEXT"), ("rol", "TEXT"),
            ("patologia_codigo", "TEXT"), ("progresiva_ini_m", "REAL"), ("progresiva_fin_m", "REAL"),
            ("area_m2", "REAL"), ("origen", "TEXT"), ("n_detecciones", "INTEGER"), ("n_fp", "INTEGER")],
    "eje_via": [("tramo", "TEXT"), ("progresiva_inicial_m", "REAL"), ("longitud_m", "REAL"), ("origen", "TEXT"),
                ("n_vertices", "INTEGER")],
}
TIPO_GEOM = {"detecciones": "GEOMETRY", "roi": "POLYGON", "eje_via": "LINESTRING"}


# ===================================================================================== CRS
def _wkt_utm(epsg):
    zona, sur = zona_utm(epsg)
    nombre = f"WGS 84 / UTM zone {zona}{'S' if sur else 'N'}"
    return (f'PROJCS["{nombre}",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
            f'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
            f'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]],'
            f'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
            f'PARAMETER["central_meridian",{zona * 6 - 183}],PARAMETER["scale_factor",0.9996],'
            f'PARAMETER["false_easting",500000],PARAMETER["false_northing",{10000000 if sur else 0}],'
            f'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH],'
            f'AUTHORITY["EPSG","{epsg}"]]'), nombre


_WKT_4326 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
             'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
             'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],'
             'AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]')


def _filas_srs(srs_id):
    """Filas de gpkg_spatial_ref_sys: las tres obligatorias (-1, 0, 4326) y la del CRS de salida."""
    filas = [("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined Cartesian coordinate reference system"),
             ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
             ("WGS 84 geodetic", 4326, "EPSG", 4326, _WKT_4326, "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid")]
    if srs_id not in (-1, 0, 4326):
        if zona_utm(srs_id):
            wkt, nombre = _wkt_utm(srs_id)
        else:
            wkt, nombre = "undefined", f"EPSG:{srs_id}"
        filas.append((nombre, srs_id, "EPSG", srs_id, wkt, None))
    return filas


def _funcion_coordenadas(t, epsg_salida, permitir_pixeles, adv):
    """(px_x, px_y, desplazamiento) -> (X, Y) en el CRS de salida; devuelve (función, srs_id, es_geografico)."""
    tr = lt.transformacion_de(t)
    epsg = t["epsg"]
    if tr is None:
        if not permitir_pixeles:
            raise ErrorExportacion(
                f"El tramo {t['codigo']} no está georreferenciado: no hay coordenadas del mapa para exportar. "
                f"Asigne un ortomosaico georreferenciado o use la opción «coordenadas de imagen (píxeles)».")
        adv.append("Exportado en coordenadas de IMAGEN (píxeles, y invertida): sin CRS. No se superpone a otras capas.")
        return (lambda x, y, off=0.0: (float(x) + off, -(float(y) + off))), -1, False
    if epsg is None:
        if epsg_salida is None:
            raise ErrorExportacion(
                "El ortomosaico está georreferenciado pero no se conoce su EPSG: indíquelo al asignar el ortomosaico "
                "para que QGIS lo ubique.")
        epsg = epsg_salida
        adv.append(f"El EPSG del ortomosaico no estaba registrado: se asumió EPSG:{epsg_salida}.")
    destino = epsg_salida or epsg
    if destino != epsg:
        try:
            convertir(0.0, 0.0, epsg, destino)
        except ErrorCRS as e:
            raise ErrorExportacion(str(e)) from e

    def f(x, y, off=0.0):
        X, Y = tr.px_a_geo(float(x) + off, float(y) + off)
        if destino != epsg:
            X, Y = convertir(X, Y, epsg, destino)
        return float(X), float(Y)
    return f, destino, destino == 4326


# ===================================================================================== WKB / GeoPackage
def _ring(pts):
    pts = list(pts)
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def wkb(geom) -> bytes:
    """WKB little-endian de {'tipo': Point|LineString|Polygon, 'coords': ...} (inverso de geovector.decodificar_wkb)."""
    tipo, c = geom["tipo"], geom["coords"]
    if tipo == "Point":
        return struct.pack("<BIdd", 1, 1, c[0], c[1])
    if tipo == "LineString":
        return struct.pack("<BII", 1, 2, len(c)) + b"".join(struct.pack("<dd", x, y) for x, y in c)
    if tipo == "Polygon":
        out = struct.pack("<BII", 1, 3, len(c))
        for anillo in c:
            out += struct.pack("<I", len(anillo)) + b"".join(struct.pack("<dd", x, y) for x, y in anillo)
        return out
    raise ErrorExportacion(f"Tipo de geometría no soportado para exportar: {tipo}")


def _puntos_geom(geom):
    if geom["tipo"] == "Point":
        return [geom["coords"]]
    if geom["tipo"] == "LineString":
        return geom["coords"]
    return [p for a in geom["coords"] for p in a]


def blob_gpkg(geom, srs_id) -> bytes:
    """Cabecera GeoPackage (marca 'GP', versión 0, banderas LE + envolvente XY, srs_id) + WKB."""
    xs = [p[0] for p in _puntos_geom(geom)]
    ys = [p[1] for p in _puntos_geom(geom)]
    return (b"GP" + bytes([0, 0b00000011]) + struct.pack("<i", srs_id)
            + struct.pack("<dddd", min(xs), max(xs), min(ys), max(ys)) + wkb(geom))


def _crear_gpkg(ruta, capas, srs_id):
    """Escribe el GPKG. `capas` = {nombre: {'tipo_geom', 'atributos': [(col, tipo)], 'filas': [(geom, {col: valor})]}}."""
    con = sqlite3.connect(ruta)
    try:
        con.execute(f"PRAGMA application_id={GPKG_APP_ID}")
        con.execute(f"PRAGMA user_version={GPKG_VERSION}")
        con.executescript("""
            CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
            CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
                description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
                CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
            CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
                geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
                CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
                CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
                CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
        """)
        con.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", _filas_srs(srs_id))
        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for nombre, c in capas.items():
            cols = ", ".join(f'"{n}" {t}' for n, t in c["atributos"])
            con.execute(f'CREATE TABLE "{nombre}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom {c["tipo_geom"]}'
                        f'{", " + cols if cols else ""})')
            marcas = ",".join("?" * (1 + len(c["atributos"])))
            nombres = ", ".join(['geom'] + [f'"{n}"' for n, _ in c["atributos"]])
            xs, ys = [], []
            for geom, attrs in c["filas"]:
                pts = _puntos_geom(geom)
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                con.execute(f'INSERT INTO "{nombre}" ({nombres}) VALUES ({marcas})',
                            [blob_gpkg(geom, srs_id)] + [_valor_sql(attrs.get(n), t) for n, t in c["atributos"]])
            env = (min(xs), min(ys), max(xs), max(ys)) if xs else (None,) * 4
            con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change, "
                        "min_x, min_y, max_x, max_y, srs_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (nombre, "features", nombre, c.get("descripcion", ""), ahora, *env, srs_id))
            con.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,0,0)", (nombre, "geom", c["tipo_geom"], srs_id))
        con.commit()
    finally:
        con.close()


def _valor_sql(v, tipo):
    if v is None:
        return None
    if tipo == "BOOLEAN":
        return 1 if v else 0
    if tipo == "INTEGER":
        return int(v)
    if tipo == "REAL":
        return float(v)
    return str(v)


# ===================================================================================== construcción de capas
def _geom_deteccion(d, fxy):
    pts = d.get("geom_px") or []
    if len(pts) >= 3 and (d.get("geom_tipo") or "").startswith("poligono"):
        return {"tipo": "Polygon", "coords": [_ring([fxy(x, y, 0.5) for x, y in pts])]}, False
    distintos = {(int(x), int(y)) for x, y in pts}
    if len(distintos) >= 2:
        return {"tipo": "LineString", "coords": [fxy(x, y, 0.5) for x, y in pts]}, False
    if len(distintos) == 1:
        x, y = pts[0]
        return {"tipo": "Point", "coords": fxy(x, y, 0.5)}, False
    x, y, w, h = d["x"], d["y"], d["w"], d["h"]                                  # sin geometría: caja envolvente
    return {"tipo": "Polygon", "coords": [_ring([fxy(x, y), fxy(x + w, y), fxy(x + w, y + h), fxy(x, y + h)])]}, True


def _capa_detecciones(ids, rois_por_id, estados, fxy, solo_conteo, adv):
    filas, sin_geom, prov = [], 0, {}
    for e in ids:
        prov[e] = bool(ld.obtener_ejecucion(e)["provisional"])
        for d in ld.listar_detecciones(e):
            r = rois_por_id.get(d["roi_id"])
            est = estados.get((e, d["roi_id"], d["tipo"]), "sin validar") if r else "sin ROI"
            incluida = est != "FP"
            if solo_conteo and not incluida:
                continue
            g, caja = _geom_deteccion(d, fxy)
            sin_geom += caja
            a = {"id_deteccion": d["id"], "ejecucion_id": e, "roi": r["codigo"] if r else None, "tipo": d["tipo"],
                 "estado_validacion": est, "incluida_en_conteo": incluida, "provisional": prov[e]}
            for k in ("progresiva_m", "lado_via", "longitud_m", "ancho_mm", "ancho_m", "area_m2", "pct_area_afectada",
                      "densidad_pct", "n_celdas", "celda_media_m2", "severidad_prelim", "desv_eje_deg",
                      "contraste_weber", "ramificada", "metodo_ancho", "metodo", "advertencia"):
                a[k] = d.get(k)
            filas.append((g, a))
    if sin_geom:
        adv.append(f"{sin_geom} detecciones sin geometría se exportaron como su caja envolvente.")
    return filas


def _capa_roi(t, rois, dets_por_roi, fxy):
    filas = []
    gsd = (t["gsd_cm"] or 0) / 100.0
    for r in rois:
        pol = r.get("poligono_px")
        if pol and len(pol) >= 3:
            anillo = [fxy(x, y) for x, y in pol]
        else:
            anillo = [fxy(r["x0"], r["y0"]), fxy(r["x1"], r["y0"]), fxy(r["x1"], r["y1"]), fxy(r["x0"], r["y1"])]
        d = dets_por_roi.get(r["id"], [])
        filas.append(({"tipo": "Polygon", "coords": [_ring(anillo)]},
                      {"codigo": r["codigo"], "tipo_campo": r["tipo_campo"], "severidad_campo": r["severidad_campo"],
                       "rol": r["rol"], "patologia_codigo": r["patologia_codigo"],
                       "progresiva_ini_m": r["progresiva_ini_m"], "progresiva_fin_m": r["progresiva_fin_m"],
                       "area_m2": (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) * gsd ** 2 if gsd else None,
                       "origen": r["origen"], "n_detecciones": len(d), "n_fp": sum(1 for x in d if x["estado"] == "FP")}))
    return filas


def _capa_eje(t, fxy):
    eje = lt.obtener_eje(t["codigo"])
    if eje is None:
        return []
    v = eje["vertices_px"]
    if len(v) < 2:
        return []
    gsd = (t["gsd_cm"] or 0) / 100.0
    long_m = sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in zip(v, v[1:])) * gsd if gsd else None
    return [({"tipo": "LineString", "coords": [fxy(x, y) for x, y in v]},
             {"tramo": t["codigo"], "progresiva_inicial_m": eje["progresiva_inicial_m"], "longitud_m": long_m,
              "origen": eje["origen"], "n_vertices": len(v)})]


def preparar_capas(tramo, ejecucion_ids=None, metodo="actual", rol="prueba", capas=CAPAS, solo_conteo=False,
                   epsg_salida=None, permitir_pixeles=False):
    """Lee la BD y devuelve {'capas': {nombre: {...filas...}}, 'srs_id', 'geografico', 'advertencias', 'tramo', 'ids'}."""
    malas = [c for c in capas if c not in CAPAS]
    if malas or not capas:
        raise ErrorExportacion(f"capas no válidas: {', '.join(malas) or '(ninguna)'}. Disponibles: {', '.join(CAPAS)}")
    t = lt.obtener_tramo(tramo)
    adv: List[str] = []
    fxy, srs_id, geografico = _funcion_coordenadas(t, epsg_salida, permitir_pixeles, adv)
    rois = logica_roi.listar_rois(t["codigo"])
    rois_por_id = {r["id"]: r for r in rois}
    ids, estados = [], {}
    if "detecciones" in capas or "roi" in capas:
        try:
            sel = lrep.seleccionar_ejecuciones(t["codigo"], ejecucion_ids, metodo, rol)
        except ErrorValidacion:
            if "detecciones" in capas and capas != ("eje_via",):
                raise
            sel = {"ids": [], "advertencias": []}
        ids = sel["ids"]
        adv += sel["advertencias"]
        estados = lrep._estado_por_unidad([f for i in ids for f in lv.listar_validacion(ejecucion_id=i)])
    out = {}
    dets_roi: Dict[int, list] = {}
    if "detecciones" in capas:
        filas = _capa_detecciones(ids, rois_por_id, estados, fxy, solo_conteo, adv)
        out["detecciones"] = filas
    for e in ids:
        for d in ld.listar_detecciones(e):
            dets_roi.setdefault(d["roi_id"], []).append({"estado": estados.get((e, d["roi_id"], d["tipo"]))})
    if "roi" in capas:
        out["roi"] = _capa_roi(t, rois, dets_roi, fxy)
    if "eje_via" in capas:
        out["eje_via"] = _capa_eje(t, fxy)
    for nombre in list(out):
        if not out[nombre]:
            adv.append(f"La capa «{nombre}» no tiene entidades y no se exporta.")
            del out[nombre]
    if not out:
        raise ErrorExportacion("No hay nada que exportar: el tramo no tiene detecciones, ROI ni eje de vía.")
    if any(ld.obtener_ejecucion(i)["provisional"] for i in ids):
        adv.insert(0, lrep.AVISO_PROVISIONAL)
    return {"capas": out, "srs_id": srs_id, "geografico": geografico, "advertencias": adv, "tramo": t["codigo"],
            "ids": ids}


# ===================================================================================== GPKG / GeoJSON
def exportar_gpkg(tramo, ruta, sobrescribir=False, **opciones):
    """Escribe el GeoPackage y lo verifica releyéndolo. `opciones`: las de `preparar_capas`."""
    prep = preparar_capas(tramo, **opciones)
    if os.path.exists(ruta) and not sobrescribir:
        raise ErrorExportacion(f"Ya existe «{ruta}». Elija otro nombre o confirme el reemplazo.")
    carpeta = os.path.dirname(os.path.abspath(ruta))
    try:
        os.makedirs(carpeta, exist_ok=True)
    except OSError as e:
        raise ErrorExportacion(f"No se puede usar la carpeta de destino «{carpeta}»: {e}") from e
    capas = {n: {"tipo_geom": TIPO_GEOM[n], "atributos": ATRIBUTOS[n], "filas": f,
                 "descripcion": f"Tramo {prep['tramo']} · {n}"} for n, f in prep["capas"].items()}
    tmp = ruta + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    try:
        _crear_gpkg(tmp, capas, prep["srs_id"])
        problemas = verificar_gpkg(tmp, prep)
        if problemas:
            raise ErrorExportacion("El GeoPackage escrito no coincide con lo esperado al releerlo: " + "; ".join(problemas))
        os.replace(tmp, ruta)
    except PermissionError as e:
        raise ErrorExportacion(f"No se pudo escribir «{ruta}»: el archivo está abierto en otro programa (¿QGIS?) o "
                               f"no hay permiso.") from e
    except OSError as e:
        raise ErrorExportacion(f"No se pudo escribir «{ruta}»: {e}") from e
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return {"archivos": {"gpkg": ruta}, "capas": {n: len(f) for n, f in prep["capas"].items()},
            "epsg": prep["srs_id"] if prep["srs_id"] > 0 else None, "advertencias": prep["advertencias"],
            "verificado": True, "provisional": any("PROVISIONAL" in a for a in prep["advertencias"])}


def verificar_gpkg(ruta, prep) -> List[str]:
    """Relee el GPKG con `geovector.leer_gpkg` y compara con lo preparado. Devuelve la lista de discrepancias."""
    problemas = []
    try:
        con = sqlite3.connect(ruta)
        try:
            if con.execute("PRAGMA application_id").fetchone()[0] != GPKG_APP_ID:
                problemas.append("application_id incorrecto")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problemas.append("integrity_check falló")
        finally:
            con.close()
        esperado_epsg = prep["srs_id"] if prep["srs_id"] > 0 else None
        for nombre, filas in prep["capas"].items():
            capa = geovector.leer_gpkg(ruta, nombre)
            if len(capa.features) != len(filas):
                problemas.append(f"{nombre}: {len(capa.features)} entidades releídas, {len(filas)} escritas")
                continue
            if capa.epsg != esperado_epsg and not (esperado_epsg is None and capa.epsg is None):
                problemas.append(f"{nombre}: EPSG {capa.epsg} releído, {esperado_epsg} escrito")
            for (g, _a), f in zip(filas, capa.features):
                if f["geom"] is None or f["geom"]["tipo"] != g["tipo"]:
                    problemas.append(f"{nombre}: tipo de geometría distinto al releer")
                    break
                a = _puntos_geom(g)
                b = _puntos_geom(f["geom"])
                if len(a) != len(b) or any(abs(p[0] - q[0]) > 1e-9 or abs(p[1] - q[1]) > 1e-9 for p, q in zip(a, b)):
                    problemas.append(f"{nombre}: coordenadas distintas al releer")
                    break
    except (geovector.ErrorFormatoGeo, sqlite3.Error) as e:
        problemas.append(f"no se pudo releer: {e}")
    return problemas


def _redondeo(c, nd):
    if isinstance(c, tuple):
        return [round(c[0], nd), round(c[1], nd)]
    return [_redondeo(x, nd) for x in c]


def exportar_geojson(tramo, carpeta, sobrescribir=False, **opciones):
    """Un .geojson por capa. CRS = el de salida (miembro `crs` 'urn:ogc:def:crs:EPSG::N', salvo 4326)."""
    prep = preparar_capas(tramo, **opciones)
    try:
        os.makedirs(carpeta, exist_ok=True)
    except OSError as e:
        raise ErrorExportacion(f"No se puede usar la carpeta de destino «{carpeta}»: {e}") from e
    base = lrep.nombre_archivo_seguro(prep["tramo"])
    archivos, nd = {}, 9 if prep["geografico"] else 4
    for nombre, filas in prep["capas"].items():
        ruta = os.path.join(carpeta, f"{base}_{nombre}.geojson")
        if os.path.exists(ruta) and not sobrescribir:
            raise ErrorExportacion(f"Ya existe «{ruta}». Elija otra carpeta o confirme el reemplazo.")
        fc = {"type": "FeatureCollection", "name": f"{base}_{nombre}", "features": [
            {"type": "Feature", "properties": {n: _json_val(a.get(n), t) for n, t in ATRIBUTOS[nombre]},
             "geometry": {"type": g["tipo"], "coordinates": _redondeo(g["coords"], nd)}} for g, a in filas]}
        if prep["srs_id"] > 0 and prep["srs_id"] != 4326:
            fc = {"type": "FeatureCollection", "name": fc["name"],
                  "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{prep['srs_id']}"}},
                  "features": fc["features"]}
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(fc, f, ensure_ascii=False)
        except PermissionError as e:
            raise ErrorExportacion(f"No se pudo escribir «{ruta}»: archivo abierto en otro programa o sin permiso.") from e
        except OSError as e:
            raise ErrorExportacion(f"No se pudo escribir «{ruta}»: {e}") from e
        capa = geovector.leer_geojson(ruta)                                   # verificación por relectura
        if len(capa.features) != len(filas):
            raise ErrorExportacion(f"{ruta}: {len(capa.features)} entidades releídas, {len(filas)} escritas")
        archivos[nombre] = ruta
    return {"archivos": archivos, "capas": {n: len(f) for n, f in prep["capas"].items()},
            "epsg": prep["srs_id"] if prep["srs_id"] > 0 else None, "advertencias": prep["advertencias"],
            "verificado": True, "provisional": any("PROVISIONAL" in a for a in prep["advertencias"])}


def _json_val(v, tipo):
    if v is None:
        return None
    if tipo == "BOOLEAN":
        return bool(v)
    if tipo == "INTEGER":
        return int(v)
    if tipo == "REAL":
        return float(v)
    return str(v)


def exportar(tramo, destino, formato="gpkg", **opciones):
    """`formato`: 'gpkg' (destino = archivo .gpkg) o 'geojson' (destino = carpeta)."""
    if formato == "gpkg":
        return exportar_gpkg(tramo, destino, **opciones)
    if formato == "geojson":
        return exportar_geojson(tramo, destino, **opciones)
    raise ErrorExportacion(f"formato desconocido «{formato}». Use 'gpkg' o 'geojson'.")
