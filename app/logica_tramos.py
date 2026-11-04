"""
logica_tramos.py
================
Ficha 1 (tramo), ortomosaico asociado y eje de vía. Todas las funciones devuelven diccionarios.
"""
import math

from sqlalchemy import func, select

from app import basedatos
from app.logica_comun import (Campo, ErrorNoEncontrado, ErrorValidacion, esquema, obtener, validar)
from app.modelos import (ROI, EjeVia, EjecucionAnalisis, GCP, Inspeccion, Tramo, VueloUAV)
from app.nucleo import eje_via as _eje
from app.nucleo.geo import Transformacion
from app.nucleo.lectura import abrir

CAMPOS_TRAMO = (
    Campo("codigo", "Código del tramo", requerido=True),
    Campo("via", "Vía"),
    Campo("ruta", "Ruta"),
    Campo("ubicacion", "Ubicación"),
    Campo("progresiva_ini_m", "Progresiva inicial", "real", minimo=0, unidad="m"),
    Campo("progresiva_fin_m", "Progresiva final", "real", minimo=0, unidad="m"),
    Campo("longitud_m", "Longitud", "real", minimo=0.001, unidad="m"),
    Campo("ancho_calzada_m", "Ancho de calzada", "real", minimo=0.5, maximo=50, unidad="m"),
    Campo("ancho_berma_m", "Ancho de berma", "real", minimo=0, maximo=20, unidad="m"),
    Campo("n_carriles", "N.º de carriles", "entero", minimo=1, maximo=8),
    Campo("este_ini", "Este inicial", "real"), Campo("norte_ini", "Norte inicial", "real"),
    Campo("este_fin", "Este final", "real"), Campo("norte_fin", "Norte final", "real"),
    Campo("observaciones", "Observaciones"),
)


def esquema_tramo():
    return esquema(CAMPOS_TRAMO)


def _resolver(s, ref):
    """Tramo por id (int) o por código (str)."""
    t = s.get(Tramo, ref) if isinstance(ref, int) else s.scalar(select(Tramo).where(Tramo.codigo == str(ref)))
    if t is None:
        raise ErrorNoEncontrado(f"No existe el tramo '{ref}'")
    return t


def _coherencia(d, actual=None):
    """Reglas entre campos. Devuelve advertencias; lanza ErrorValidacion si hay contradicción dura."""
    g = lambda k: d[k] if k in d else (getattr(actual, k) if actual is not None else None)
    adv, ini, fin, lon = [], g("progresiva_ini_m"), g("progresiva_fin_m"), g("longitud_m")
    if ini is not None and fin is not None:
        if fin <= ini:
            raise ErrorValidacion({"progresiva_fin_m": "debe ser mayor que la progresiva inicial"})
        if lon is not None and abs((fin - ini) - lon) > 0.01 * lon:
            adv.append(f"la longitud ({lon:g} m) difiere de progresiva final - inicial ({fin - ini:g} m) en más de 1 %")
    return adv


def crear_tramo(datos):
    d = validar(datos, CAMPOS_TRAMO)
    adv = _coherencia(d)
    if d["longitud_m"] is None and d["progresiva_ini_m"] is not None and d["progresiva_fin_m"] is not None:
        d["longitud_m"] = d["progresiva_fin_m"] - d["progresiva_ini_m"]
    with basedatos.nueva_sesion() as s:
        if s.scalar(select(Tramo.id).where(Tramo.codigo == d["codigo"])):
            raise ErrorValidacion({"codigo": f"ya existe un tramo con el código {d['codigo']}"})
        t = Tramo(**d)
        s.add(t)
        s.flush()
        return {**t.a_dict(), "advertencias": adv}


def actualizar_tramo(tramo, cambios):
    d = validar(cambios, CAMPOS_TRAMO, parcial=True)
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        adv = _coherencia(d, t)
        if "codigo" in d and d["codigo"] != t.codigo and s.scalar(select(Tramo.id).where(Tramo.codigo == d["codigo"])):
            raise ErrorValidacion({"codigo": f"ya existe un tramo con el código {d['codigo']}"})
        for k, v in d.items():
            setattr(t, k, v)
        s.flush()
        return {**t.a_dict(), "advertencias": adv}


def obtener_tramo(tramo):
    with basedatos.nueva_sesion() as s:
        return _resolver(s, tramo).a_dict()


def listar_tramos():
    with basedatos.nueva_sesion() as s:
        return [t.a_dict() for t in s.scalars(select(Tramo).order_by(Tramo.codigo))]


def _resumen(s, t):
    n = lambda M: s.scalar(select(func.count()).select_from(M).where(M.tramo_id == t.id))
    return {"rois": n(ROI), "vuelos": n(VueloUAV), "gcps": n(GCP), "inspecciones": n(Inspeccion),
            "ejecuciones": n(EjecucionAnalisis), "ejes": n(EjeVia)}


def resumen_tramo(tramo):
    """Conteos de lo que depende del tramo (para confirmar un borrado)."""
    with basedatos.nueva_sesion() as s:
        return _resumen(s, _resolver(s, tramo))


def eliminar_tramo(tramo, confirmar=False):
    """Elimina el tramo y TODO lo que depende de él. Sin confirmar=True solo se permite si está vacío."""
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        dep = {k: v for k, v in _resumen(s, t).items() if v}
        if dep and not confirmar:
            raise ErrorValidacion(f"El tramo tiene datos asociados ({', '.join(f'{k}: {v}' for k, v in dep.items())}); "
                                  f"confirme el borrado para eliminarlos")
        s.delete(t)


# ------------------------------------------------------------------------------------ ortomosaico
def transformacion_de(t):
    """Transformacion del tramo (dict de fila o modelo) o None."""
    tr = t["transformacion"] if isinstance(t, dict) else t.transformacion
    return Transformacion(*tr) if tr else None


def asignar_ortomosaico(tramo, ruta, gsd_cm=None, transformacion=None, epsg=None):
    """Abre el ortomosaico (sin cargarlo entero) y guarda tamaño, resolución y georreferenciación.

    `gsd_cm` es obligatorio si el archivo no lo trae (PNG/JPG o CRS geográfico). `transformacion`
    (6 coeficientes GDAL) y `epsg` permiten georreferenciar un PNG/JPG a mano."""
    lector = abrir(ruta, gsd_cm=gsd_cm)
    try:
        gsd = lector.gsd_cm
        tr = list(lector.transformacion) if lector.transformacion is not None else None
        datos = dict(ancho=lector.ancho, alto=lector.alto, epsg=lector.epsg)
    finally:
        lector.cerrar()
    if not gsd:
        raise ErrorValidacion({"gsd_cm": "el archivo no indica la resolución: indíquela (cm/píxel)"})
    if not 0.05 <= gsd <= 100:
        raise ErrorValidacion({"gsd_cm": f"{gsd:g} cm/px fuera del rango razonable (0.05-100)"})
    if transformacion is not None:
        tr = list(Transformacion(*transformacion))
        Transformacion(*tr)._det()
    if epsg is not None:
        datos["epsg"] = int(epsg)
    adv = []
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        cambia = (t.ancho_px, t.alto_px) not in ((None, None), (datos["ancho"], datos["alto"]))
        if cambia and (s.scalar(select(func.count()).select_from(ROI).where(ROI.tramo_id == t.id)) or
                       s.scalar(select(func.count()).select_from(EjeVia).where(EjeVia.tramo_id == t.id))):
            adv.append("el tamaño del ortomosaico cambió: las ROI y el eje existentes están en píxeles del "
                       "ortomosaico anterior; revíselos")
        if tr is not None and datos["epsg"] is None:
            adv.append("hay georreferenciación pero no se conoce el EPSG: no se podrán importar capas en otro CRS")
        if tr is None:
            adv.append("el ortomosaico no está georreferenciado: solo se podrán importar ROI/eje en píxeles")
        t.ortomosaico_ruta, t.gsd_cm, t.ancho_px, t.alto_px = ruta, float(gsd), datos["ancho"], datos["alto"]
        t.transformacion, t.epsg = tr, datos["epsg"]
        s.flush()
        return {**t.a_dict(), "advertencias": adv}


# ------------------------------------------------------------------------------------ eje de vía
def _validar_vertices(v):
    try:
        pts = [(float(x), float(y)) for x, y in v]
    except (TypeError, ValueError):
        raise ErrorValidacion({"vertices": "debe ser una lista de pares (x, y) numéricos"}) from None
    if len(pts) < 2:
        raise ErrorValidacion({"vertices": "el eje necesita al menos 2 vértices"})
    if not all(math.isfinite(a) and math.isfinite(b) for a, b in pts):
        raise ErrorValidacion({"vertices": "hay coordenadas no finitas"})
    return pts


def definir_eje(tramo, vertices, sistema="px", progresiva_inicial_m=None, origen="manual"):
    """Guarda un eje nuevo (se conserva el historial). sistema = 'px' o 'geo' (coordenadas del mapa)."""
    pts = _validar_vertices(vertices)
    if sistema not in ("px", "geo"):
        raise ErrorValidacion({"sistema": "use 'px' o 'geo'"})
    adv = []
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        geo = None
        if sistema == "geo":
            if not t.transformacion:
                raise ErrorValidacion({"sistema": "el tramo no tiene ortomosaico georreferenciado: use sistema='px'"})
            geo = [list(p) for p in pts]
            cols, filas = Transformacion(*t.transformacion).geo_a_px([p[0] for p in pts], [p[1] for p in pts])
            pts = [(float(a), float(b)) for a, b in zip(cols, filas)]
        if t.ancho_px and any(not (0 <= x <= t.ancho_px and 0 <= y <= t.alto_px) for x, y in pts):
            adv.append("hay vértices fuera del ortomosaico")
        prog = progresiva_inicial_m if progresiva_inicial_m is not None else (t.progresiva_ini_m or 0.0)
        gsd = (t.gsd_cm or 0.5) / 100.0
        try:
            _eje.EjeVia(pts, gsd, prog)                              # valida (vértices repetidos, etc.)
        except ValueError as e:
            raise ErrorValidacion({"vertices": str(e)}) from e
        e = EjeVia(tramo_id=t.id, vertices_px=[list(p) for p in pts], vertices_geo=geo,
                   progresiva_inicial_m=float(prog), origen=origen)
        s.add(e)
        s.flush()
        return {**e.a_dict(), "advertencias": adv}


def obtener_eje(tramo):
    """Eje vigente (el último guardado) o None."""
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        e = s.scalar(select(EjeVia).where(EjeVia.tramo_id == t.id).order_by(EjeVia.id.desc()).limit(1))
        return e.a_dict() if e else None


def eje_nucleo(tramo, ventana_m=4.0):
    """Eje vigente como objeto del núcleo (EjeVia) o None. Para logica_deteccion."""
    with basedatos.nueva_sesion() as s:
        t = _resolver(s, tramo)
        e = s.scalar(select(EjeVia).where(EjeVia.tramo_id == t.id).order_by(EjeVia.id.desc()).limit(1))
        if e is None:
            return None
        return _eje.EjeVia(e.vertices_px, (t.gsd_cm or 0.5) / 100.0, e.progresiva_inicial_m, ventana_m)
