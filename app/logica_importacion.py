"""
logica_importacion.py
=====================
Importadores desde CSV, GeoJSON y GeoPackage (lo que exporta QGIS) hacia la BD:

    importar_rois(tramo, ruta, ...)          ROI: CSV (px o coordenadas) o capa de polígonos
    importar_eje(tramo, ruta, ...)           eje de vía: CSV de vértices o capa de líneas
    importar_fichas(ficha, ruta, ...)        'vuelo' | 'condicion' | 'gcp' | 'catalogo' | 'inspeccion'
    importar_patologias(inspeccion_id, ruta) Fichas 2-4 en un CSV (patología + geometría + severidad)

Garantías
  - `simular=True` ejecuta TODO el proceso (incluidas las reglas de unicidad) y deshace los cambios:
    es una vista previa fiel.
  - `estricto=True` (por defecto): si alguna fila falla no se importa NADA. Con estricto=False se importan
    las filas válidas y se informan las fallidas.
  - Cada resultado es {creados, actualizados, omitidos, errores:[{fila, mensaje}], advertencias, simulado,
    aplicado}. `aplicado` es False si se simuló o si se abortó por errores.
  - CRS: las capas se convierten al EPSG del ortomosaico (4326 <-> UTM WGS84, ver crs.py). Una capa sin CRS
    se asume en el CRS del ortomosaico (se advierte). `sistema='px'` indica que las coordenadas ya son
    píxeles del ortomosaico (x a la derecha, y hacia abajo).
"""
import math
import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import basedatos, geovector
from app.crs import ErrorCRS, convertir
from app.logica_comun import ErrorValidacion, leer_csv, normalizar, vacio
from app.logica_fichas import (CAMPOS, CAMPOS_GEOMETRIA, CAMPOS_PATOLOGIA, CAMPOS_SEVERIDAD, CON_TRAMO, MODELOS,
                               UNICO_POR_TRAMO, _crear, _crear_patologia)
from app.logica_roi import _actualizar_roi, _crear_roi
from app.logica_tramos import _resolver, definir_eje
from app.modelos import ROI, Inspeccion, Tramo, VueloUAV
from app.nucleo.geo import Transformacion

_ERRORES_FILA = (ErrorValidacion, geovector.ErrorFormatoGeo, ErrorCRS, IntegrityError)

ALIAS_ROI = {
    "codigo": ("codigo", "codigo_roi", "roi", "id_roi", "nombre", "name", "id"),
    "tipo_campo": ("tipo_campo", "tipo", "tipo_de_campo", "deterioro"),
    "severidad_campo": ("severidad_campo", "severidad", "nivel_severidad"),
    "patologia_codigo": ("patologia_codigo", "patologia", "cod_patologia", "codigo_patologia"),
    "rol": ("rol",), "observaciones": ("observaciones", "obs", "comentarios"),
    "progresiva_ini_m": ("progresiva_ini_m", "progresiva_inicial", "prog_ini", "progresiva_ini"),
    "progresiva_fin_m": ("progresiva_fin_m", "progresiva_final", "prog_fin", "progresiva_fin"),
}
TIPO_ALIAS = {
    "longitudinal": "longitudinal", "grieta_longitudinal": "longitudinal", "glo": "longitudinal",
    "transversal": "transversal", "grieta_transversal": "transversal", "gtr": "transversal",
    "piel_cocodrilo": "piel_cocodrilo", "cocodrilo": "piel_cocodrilo", "piel_de_cocodrilo": "piel_cocodrilo",
    "grieta_piel_de_cocodrilo": "piel_cocodrilo", "gpc": "piel_cocodrilo",
    "bache": "bache", "baches": "bache", "hueco": "bache", "huecos": "bache", "hue": "bache",
    "sano": "sano", "sin_falla": "sano", "sin_deterioro": "sano", "ninguno": "sano",
}
_CSV_PX = (("x", "y", "ancho", "alto"), ("x0", "y0", "x1", "y1"))
_CSV_GEO = (("xmin", "ymin", "xmax", "ymax"), ("x_min", "y_min", "x_max", "y_max"),
            ("este_min", "norte_min", "este_max", "norte_max"))


class _Abortar(Exception):
    pass


def _informe():
    return {"creados": 0, "actualizados": 0, "omitidos": 0, "errores": [], "advertencias": [],
            "simulado": False, "aplicado": False}


def _ejecutar(trabajo, simular, estricto, rep):
    """Corre `trabajo(s)` en una transacción; la deshace si se simula o si hay errores en modo estricto."""
    rep["simulado"] = bool(simular)
    try:
        with basedatos.nueva_sesion() as s:
            trabajo(s)
            if simular:
                raise _Abortar
            if rep["errores"] and estricto:
                raise _Abortar
            rep["aplicado"] = True
    except _Abortar:
        rep["aplicado"] = False
    return rep


def _por_fila(s, items, fn, rep):
    for it in items:
        try:
            with s.begin_nested():
                rep[fn(it)] += 1
        except _ERRORES_FILA as e:
            msg = str(e.orig) if isinstance(e, IntegrityError) else str(e)
            rep["errores"].append({"fila": it["n"], "mensaje": msg})


def _pick(props, alias):
    """Primer valor no vacío entre los alias (props con claves ya normalizadas)."""
    for a in alias:
        if a in props and not vacio(props[a]):
            return props[a]
    return None


# ------------------------------------------------------------------------------------ lectura de origen
def _items(ruta, capa):
    """-> (items, formato, capa_o_None). item = {'n', 'props'(normalizadas), 'geom'}."""
    ext = os.path.splitext(ruta)[1].lower()
    if ext in (".csv", ".txt"):
        filas = leer_csv(ruta)
        return [{"n": f.pop("_fila"), "props": f, "geom": None} for f in filas], "csv", None
    c = geovector.leer_capa(ruta, capa)
    items = [{"n": k, "props": {normalizar(a): b for a, b in f["props"].items()}, "geom": f["geom"]}
             for k, f in enumerate(c.features, start=1)]
    return items, ("geojson" if ext in (".geojson", ".json") else "gpkg"), c


def _epsg_capa(t, capa, epsg_archivo, rep):
    """EPSG de las coordenadas del archivo (None = se asume el del ortomosaico / desconocido)."""
    if not t.transformacion:
        raise ErrorValidacion("El tramo no tiene ortomosaico georreferenciado: importe en píxeles (sistema='px') "
                              "o asigne un GeoTIFF con georreferenciación")
    origen = epsg_archivo or (capa.epsg if capa is not None else None)
    if origen is None:
        if t.epsg is not None:
            rep["advertencias"].append(f"el archivo no declara CRS: se asume el del ortomosaico (EPSG:{t.epsg})")
        return t.epsg
    if t.epsg is None:
        rep["advertencias"].append("el EPSG del ortomosaico es desconocido: se asume que el archivo está en su CRS")
    return origen


def _geo_a_px(t, epsg_origen, pts):
    """Puntos (x, y) en el CRS de origen -> (px, geo_en_crs_del_tramo)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if epsg_origen is not None and t.epsg is not None and epsg_origen != t.epsg:
        xs, ys = convertir(xs, ys, epsg_origen, t.epsg)
    cols, filas = Transformacion(*t.transformacion).geo_a_px(xs, ys)
    return ([(float(a), float(b)) for a, b in zip(cols, filas)], [(float(a), float(b)) for a, b in zip(xs, ys)])


# ------------------------------------------------------------------------------------ ROI
def _bbox_px(pts):
    return (math.floor(min(p[0] for p in pts)), math.floor(min(p[1] for p in pts)),
            math.ceil(max(p[0] for p in pts)), math.ceil(max(p[1] for p in pts)))


def _roi_desde_item(t, it, formato, epsg_fn, sistema, rep, rol):
    p = it["props"]
    d = {k: _pick(p, a) for k, a in ALIAS_ROI.items()}
    d = {k: v for k, v in d.items() if v is not None}
    if "tipo_campo" in d:
        d["tipo_campo"] = TIPO_ALIAS.get(normalizar(d["tipo_campo"]), d["tipo_campo"])
    if rol and "rol" not in d:
        d["rol"] = rol
    d["origen"] = formato
    extra = {}
    if formato == "csv":
        sis = sistema
        if sis == "auto":
            sis = "px" if any(all(c in p for c in cols) for cols in _CSV_PX) else "geo"
        if sis == "px":
            cols = next((c for c in _CSV_PX if all(k in p and not vacio(p[k]) for k in c)), None)
            if cols is None:
                raise ErrorValidacion("faltan columnas de la región: x, y, ancho, alto (o x0, y0, x1, y1)")
            try:
                a, b, c_, e = (float(str(p[k]).replace(",", ".")) for k in cols)
            except ValueError:
                raise ErrorValidacion("las coordenadas de la región no son numéricas") from None
            x0, y0, x1, y1 = (a, b, a + c_, b + e) if cols == _CSV_PX[0] else (a, b, c_, e)
            d.update(x0=math.floor(x0), y0=math.floor(y0), x1=math.ceil(x1), y1=math.ceil(y1))
        else:
            cols = next((c for c in _CSV_GEO if all(k in p and not vacio(p[k]) for k in c)), None)
            if cols is None:
                raise ErrorValidacion("faltan columnas de coordenadas: xmin, ymin, xmax, ymax "
                                      "(o este_min, norte_min, este_max, norte_max)")
            try:
                xa, ya, xb, yb = (float(str(p[k]).replace(",", ".")) for k in cols)
            except ValueError:
                raise ErrorValidacion("las coordenadas de la región no son numéricas") from None
            px, geo = _geo_a_px(t, epsg_fn(), [(xa, ya), (xb, yb), (xa, yb), (xb, ya)])
            d.update(zip(("x0", "y0", "x1", "y1"), _bbox_px(px)))
    else:
        g = it["geom"]
        anillos = geovector.anillos(g)
        if len(anillos) != 1:
            raise ErrorValidacion("la entidad debe ser un polígono simple (sin geometría o multipolígono)")
        ring = anillos[0]
        if sistema == "px":
            px, geo = [(float(x), float(y)) for x, y in ring], None
        else:
            px, geo = _geo_a_px(t, epsg_fn(), ring)
        d.update(zip(("x0", "y0", "x1", "y1"), _bbox_px(px)))
        a_bbox = (d["x1"] - d["x0"]) * (d["y1"] - d["y0"])
        if a_bbox > 0 and geovector.area_anillo(px) / a_bbox < 0.9:
            rep["advertencias"].append(f"fila {it['n']}: el polígono ocupa menos del 90 % de su rectángulo "
                                       f"envolvente (¿ROI rotada?); se analizará el rectángulo")
            extra["poligono_px"] = [[round(x, 2), round(y, 2)] for x, y in px]
            if geo:
                extra["poligono_geo"] = [[x, y] for x, y in geo]
    return d, extra


def importar_rois(tramo, ruta, capa=None, sistema="auto", epsg_archivo=None, si_existe="error",
                  estricto=True, simular=False, rol="sin_asignar"):
    """ROI desde CSV o capa de polígonos.

    CSV en píxeles (formato del motor anterior): codigo_roi, tipo_campo, severidad_campo, x, y, ancho, alto
    CSV en coordenadas: codigo, tipo, xmin, ymin, xmax, ymax (o este_min, norte_min, este_max, norte_max)
    GeoJSON / GPKG: un polígono por ROI; propiedades = codigo, tipo_campo, severidad_campo, ...
    si_existe: 'error' | 'omitir' | 'actualizar' (cuando el código de ROI ya existe en el tramo)."""
    if si_existe not in ("error", "omitir", "actualizar"):
        raise ErrorValidacion({"si_existe": "use 'error', 'omitir' o 'actualizar'"})
    if sistema not in ("auto", "px", "geo"):
        raise ErrorValidacion({"sistema": "use 'auto', 'px' o 'geo'"})
    items, formato, c = _items(ruta, capa)
    rep = _informe()
    rep["advertencias"] += list(c.advertencias) if c else []

    def trabajo(s):
        t = _resolver(s, tramo)
        cache = []

        def epsg_fn():                                    # se calcula una vez y solo si hace falta
            if not cache:
                cache.append(_epsg_capa(t, c, epsg_archivo, rep))
            return cache[0]

        if formato != "csv" and sistema != "px":
            epsg_fn()                                     # error global si el tramo no está georreferenciado

        def fila(it):
            d, extra = _roi_desde_item(t, it, formato, epsg_fn, sistema, rep, rol)
            ex = s.scalar(select(ROI).where(ROI.tramo_id == t.id, ROI.codigo == str(d.get("codigo", "")).strip()))
            if ex is not None and si_existe == "omitir":
                return "omitidos"
            if ex is not None and si_existe == "actualizar":
                d.pop("codigo", None)
                _actualizar_roi(s, ex, {**d, **extra})
                return "actualizados"
            _, adv = _crear_roi(s, t, {**d, **extra})
            rep["advertencias"] += [f"fila {it['n']}: {a}" for a in adv]
            return "creados"

        if not items:
            raise ErrorValidacion("El archivo no contiene filas/entidades")
        _por_fila(s, items, fila, rep)

    try:
        return _ejecutar(trabajo, simular, estricto, rep)
    except _ERRORES_FILA as e:                                  # error global (CRS, tramo sin georreferencia...)
        rep["errores"].append({"fila": 0, "mensaje": str(e)})
        rep["aplicado"] = False
        return rep


# ------------------------------------------------------------------------------------ eje de vía
def importar_eje(tramo, ruta, capa=None, sistema="auto", epsg_archivo=None, progresiva_inicial_m=None):
    """Eje de vía desde una capa de una línea o un CSV de vértices ordenados (x, y en píxeles; o este, norte)."""
    ext = os.path.splitext(ruta)[1].lower()
    adv = []
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        tid, tdict = t.id, {"transformacion": t.transformacion, "epsg": t.epsg}
    if ext in (".csv", ".txt"):
        filas = leer_csv(ruta)
        cols_px = ("x", "y") if filas and "x" in filas[0] else None
        cols_geo = next((c for c in (("este", "norte"), ("x_geo", "y_geo"), ("lon", "lat"))
                         if filas and all(k in filas[0] for k in c)), None)
        sis = sistema if sistema != "auto" else ("px" if cols_px else "geo")
        cols = cols_px if sis == "px" else cols_geo
        if cols is None:
            raise ErrorValidacion("El CSV del eje necesita columnas x, y (píxeles) o este, norte (mapa)")
        try:
            pts = [(float(f[cols[0]].replace(",", ".")), float(f[cols[1]].replace(",", "."))) for f in filas]
        except (ValueError, KeyError):
            raise ErrorValidacion("El CSV del eje tiene coordenadas vacías o no numéricas") from None
        origen, epsg_o = "csv", epsg_archivo
        if cols == ("lon", "lat"):
            epsg_o = 4326
    else:
        c = geovector.leer_capa(ruta, capa)
        adv += c.advertencias
        lineas = [ln for f in c.features for ln in geovector.lineas(f["geom"])]
        n_feat = sum(1 for f in c.features if geovector.lineas(f["geom"]))
        if n_feat != 1:
            raise ErrorValidacion(f"La capa debe tener exactamente 1 línea (tiene {n_feat}): deje solo el eje de vía")
        pts = geovector.unir_lineas(lineas)
        sis = "px" if sistema == "px" else "geo"
        origen, epsg_o = ext.lstrip("."), epsg_archivo or c.epsg
        origen = "geojson" if origen == "json" else origen
    if sis == "geo":
        if not tdict["transformacion"]:
            raise ErrorValidacion("El tramo no tiene ortomosaico georreferenciado: importe el eje en píxeles")
        destino = tdict["epsg"]
        if epsg_o is None:
            epsg_o = destino
            adv.append("el archivo no declara CRS: se asume el del ortomosaico")
        if destino is not None and epsg_o != destino:
            xs, ys = convertir([p[0] for p in pts], [p[1] for p in pts], epsg_o, destino)
            pts = list(zip(map(float, xs), map(float, ys)))
    r = definir_eje(tid, pts, sistema=sis, progresiva_inicial_m=progresiva_inicial_m, origen=origen)
    r["advertencias"] = adv + r["advertencias"]
    return r


# ------------------------------------------------------------------------------------ fichas por CSV / GCP geo
def _mapa_columnas(campos):
    m = {}
    for c in campos:
        m[normalizar(c.etiqueta)] = c.nombre
        m[c.nombre] = c.nombre
    return m


def importar_fichas(ficha, ruta, tramo=None, capa=None, epsg_archivo=None, si_existe="error",
                    estricto=True, simular=False):
    """Importa filas de 'vuelo' | 'condicion' | 'gcp' | 'catalogo' | 'inspeccion'.

    Las columnas se reconocen por el nombre del campo o por su etiqueta (ver `esquema_ficha`). Si no se
    indica `tramo`, el CSV debe traer la columna `tramo` (código). `vuelo` (código) enlaza condiciones y
    GCP con su vuelo. GCP también se importa desde capas de puntos (este/norte salen de la geometría)."""
    if ficha not in MODELOS:
        raise ErrorValidacion({"ficha": f"ficha desconocida '{ficha}'. Disponibles: {', '.join(MODELOS)}"})
    if si_existe not in ("error", "omitir", "actualizar"):
        raise ErrorValidacion({"si_existe": "use 'error', 'omitir' o 'actualizar'"})
    if os.path.splitext(ruta)[1].lower() not in (".csv", ".txt") and ficha != "gcp":
        raise ErrorValidacion(f"La ficha '{ficha}' solo se importa desde CSV")
    items, formato, c = _items(ruta, capa)
    campos = CAMPOS[ficha]
    mapa = _mapa_columnas(campos)
    rep = _informe()
    rep["advertencias"] += list(c.advertencias) if c else []
    ignoradas = sorted({k for it in items for k in it["props"] if k not in mapa and k not in ("tramo", "vuelo")})
    if ignoradas:
        rep["advertencias"].append(f"columnas ignoradas: {', '.join(ignoradas)}")
    clave = {"catalogo": "codigo", **UNICO_POR_TRAMO}.get(ficha)
    Modelo = MODELOS[ficha]

    def trabajo(s):
        t_fijo = _resolver(s, tramo) if tramo is not None else None
        epsg_o = None
        if formato != "csv":
            if t_fijo is None:
                raise ErrorValidacion("Para importar GCP desde una capa indique el tramo")
            epsg_o = _epsg_capa(t_fijo, c, epsg_archivo, rep)

        def fila(it):
            p = it["props"]
            d = {mapa[k]: v for k, v in p.items() if k in mapa}
            t = t_fijo
            if ficha in CON_TRAMO and t is None:
                if vacio(p.get("tramo")):
                    raise ErrorValidacion("indique el tramo (parámetro o columna 'tramo')")
                t = _resolver(s, str(p["tramo"]).strip())
            if formato != "csv":
                pts = geovector.puntos(it["geom"])
                if len(pts) != 1:
                    raise ErrorValidacion("la entidad debe ser un punto")
                xs, ys = ([pts[0][0]], [pts[0][1]])
                if epsg_o is not None and t.epsg is not None and epsg_o != t.epsg:
                    xs, ys = convertir(xs, ys, epsg_o, t.epsg)
                d["este"], d["norte"] = float(xs[0]), float(ys[0])
            if not vacio(p.get("vuelo")) and ficha in ("condicion", "gcp"):
                v = s.scalar(select(VueloUAV).where(VueloUAV.tramo_id == t.id, VueloUAV.codigo == str(p["vuelo"]).strip()))
                if v is None:
                    raise ErrorValidacion(f"no existe el vuelo '{p['vuelo']}' en el tramo {t.codigo}")
                d["vuelo_id"] = v.id
            ex = None
            if clave and not vacio(d.get(clave)):
                valor = str(d[clave]).strip().upper() if ficha == "catalogo" else str(d[clave]).strip()
                q = select(Modelo).where(getattr(Modelo, clave) == valor)
                if ficha in CON_TRAMO:
                    q = q.where(Modelo.tramo_id == t.id)
                ex = s.scalar(q)
            if ex is not None and si_existe == "omitir":
                return "omitidos"
            if ex is not None and si_existe == "actualizar":
                from app.logica_comun import validar
                cambios = validar({k: v for k, v in d.items() if k != clave}, campos, parcial=True)
                for k, v in cambios.items():
                    if v is not None:
                        setattr(ex, k, v)
                s.flush()
                return "actualizados"
            _crear(s, ficha, d, t.id if t is not None else None)
            return "creados"

        if not items:
            raise ErrorValidacion("El archivo no contiene filas/entidades")
        _por_fila(s, items, fila, rep)

    try:
        return _ejecutar(trabajo, simular, estricto, rep)
    except _ERRORES_FILA as e:
        rep["errores"].append({"fila": 0, "mensaje": str(e)})
        rep["aplicado"] = False
        return rep


# ------------------------------------------------------------------------------------ patologías (F2-F4)
def importar_patologias(inspeccion_id, ruta, estricto=True, simular=False):
    """CSV con una fila por patología: campos de la Ficha 2 (codigo, progresiva_m, lado, este, norte, altitud,
    presencia, foto, observaciones), `roi` (código de ROI del tramo), medidas de la Ficha 4 (area_m2, longitud_m,
    ancho_prom_mm, ancho_max_mm, profundidad_cm, perimetro_m, pct_area, separacion_m, orientacion_deg) y
    severidad de la Ficha 3 (`severidad`, `criterio`)."""
    items, formato, _ = _items(ruta, None)
    if formato != "csv":
        raise ErrorValidacion("Las patologías se importan desde CSV")
    rep = _informe()
    nom_pat = {c.nombre for c in CAMPOS_PATOLOGIA if c.nombre != "roi_id"}
    nom_geo = {c.nombre for c in CAMPOS_GEOMETRIA}
    conocidas = nom_pat | nom_geo | {"roi", "severidad", "nivel", "criterio"}
    ignoradas = sorted({k for it in items for k in it["props"] if k not in conocidas})
    if ignoradas:
        rep["advertencias"].append(f"columnas ignoradas: {', '.join(ignoradas)}")

    def trabajo(s):
        insp = s.get(Inspeccion, inspeccion_id)
        if insp is None:
            raise ErrorValidacion({"inspeccion_id": f"no existe la inspección {inspeccion_id}"})

        def fila(it):
            p = it["props"]
            d = {k: v for k, v in p.items() if k in nom_pat}
            if not vacio(p.get("roi")):
                r = s.scalar(select(ROI).where(ROI.tramo_id == insp.tramo_id, ROI.codigo == str(p["roi"]).strip()))
                if r is None:
                    raise ErrorValidacion(f"no existe la ROI '{p['roi']}' en el tramo de la inspección")
                d["roi_id"] = r.id
            g = {k: v for k, v in p.items() if k in nom_geo and not vacio(v)}
            nivel = p.get("severidad") if not vacio(p.get("severidad")) else p.get("nivel")
            sv = {"nivel": nivel, "criterio": p.get("criterio")} if not vacio(nivel) else None
            _crear_patologia(s, insp, d, g or None, sv)
            return "creados"

        if not items:
            raise ErrorValidacion("El archivo no contiene filas")
        _por_fila(s, items, fila, rep)

    try:
        return _ejecutar(trabajo, simular, estricto, rep)
    except _ERRORES_FILA as e:
        rep["errores"].append({"fila": 0, "mensaje": str(e)})
        rep["aplicado"] = False
        return rep
