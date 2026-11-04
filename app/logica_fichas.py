"""
logica_fichas.py
================
Fichas de campo con CRUD genérico dirigido por esquema (la UI construye los formularios con
`esquema_ficha` sin conocer los modelos):

    'vuelo' (F5) · 'condicion' (F8) · 'gcp' (F9) · 'catalogo' (códigos de patología de la F2) · 'inspeccion' (F2)

y el registro compuesto de patologías (F2) con su geometría (F4) y severidad (F3).
La severidad OFICIAL es la de la ficha (tabla Severidad), no la `severidad_prelim` del motor.
"""
from sqlalchemy import select

from app import basedatos
from app.logica_comun import Campo, ErrorNoEncontrado, ErrorValidacion, esquema, obtener, validar
from app.logica_tramos import _resolver
from app.modelos import (LADOS, NIVELES_SEVERIDAD, ROI, CatalogoPatologia, CondicionAmbiental, GCP, Geometria,
                         Inspeccion, Patologia, Severidad, VueloUAV)
from app.nucleo.estructuras import TIPOS

_F = "real"
CAMPOS = {
    "vuelo": (
        Campo("codigo", "Código del vuelo", requerido=True), Campo("fecha", "Fecha", "fecha"),
        Campo("hora_inicio", "Hora de inicio", "hora"), Campo("hora_fin", "Hora de fin", "hora"),
        Campo("dron", "Dron"), Campo("camara", "Cámara"),
        Campo("altura_m", "Altura de vuelo", _F, minimo=1, maximo=500, unidad="m"),
        Campo("gsd_cm", "GSD", _F, minimo=0.05, maximo=50, unidad="cm/px"),
        Campo("traslape_frontal_pct", "Traslape frontal", _F, minimo=0, maximo=100, unidad="%"),
        Campo("traslape_lateral_pct", "Traslape lateral", _F, minimo=0, maximo=100, unidad="%"),
        Campo("velocidad_ms", "Velocidad", _F, minimo=0, maximo=40, unidad="m/s"),
        Campo("n_fotos", "N.º de fotos", "entero", minimo=0), Campo("n_gcp", "N.º de GCP", "entero", minimo=0),
        Campo("operador", "Operador"), Campo("observaciones", "Observaciones"),
    ),
    "condicion": (
        Campo("vuelo_id", "Vuelo", "entero", minimo=1), Campo("fecha", "Fecha", "fecha"),
        Campo("hora", "Hora", "hora"),
        Campo("temperatura_c", "Temperatura", _F, minimo=-40, maximo=60, unidad="°C"),
        Campo("humedad_pct", "Humedad relativa", _F, minimo=0, maximo=100, unidad="%"),
        Campo("cielo", "Cielo"), Campo("viento_ms", "Viento", _F, minimo=0, maximo=80, unidad="m/s"),
        Campo("lluvia", "Lluvia"), Campo("humedad_pavimento", "Humedad del pavimento"),
        Campo("sombras", "Sombras"), Campo("observaciones", "Observaciones"),
    ),
    "gcp": (
        Campo("codigo", "Código", requerido=True), Campo("vuelo_id", "Vuelo", "entero", minimo=1),
        Campo("ubicacion", "Ubicación"), Campo("este", "Este", _F, unidad="m"), Campo("norte", "Norte", _F, unidad="m"),
        Campo("altitud", "Altitud", _F, minimo=-500, maximo=9000, unidad="m"), Campo("tipo", "Tipo"),
        Campo("metodo", "Método"), Campo("precision_m", "Precisión", _F, minimo=0, unidad="m"),
        Campo("usado_ortomosaico", "Usado en el ortomosaico", "bool"), Campo("observaciones", "Observaciones"),
    ),
    "catalogo": (
        Campo("codigo", "Código", requerido=True), Campo("nombre", "Nombre", requerido=True), Campo("grupo", "Grupo"),
        Campo("tipo_motor", "Equivale al tipo del motor", "opcion", opciones=TIPOS), Campo("activo", "Activo", "bool"),
    ),
    "inspeccion": (
        Campo("fecha", "Fecha", "fecha"), Campo("responsable", "Responsable"),
        Campo("observador", "Observador (1 o 2)", "entero", minimo=1, maximo=2), Campo("observaciones", "Observaciones"),
    ),
}
MODELOS = {"vuelo": VueloUAV, "condicion": CondicionAmbiental, "gcp": GCP, "catalogo": CatalogoPatologia,
           "inspeccion": Inspeccion}
CON_TRAMO = ("vuelo", "condicion", "gcp", "inspeccion")
UNICO_POR_TRAMO = {"vuelo": "codigo", "gcp": "codigo"}          # (tramo, codigo) único

CAMPOS_PATOLOGIA = (
    Campo("codigo", "Código de patología", requerido=True), Campo("roi_id", "ROI vinculada", "entero", minimo=1),
    Campo("progresiva_m", "Progresiva", _F, minimo=0, unidad="m"),
    Campo("lado", "Lado", "opcion", opciones=LADOS),
    Campo("este", "Este", _F), Campo("norte", "Norte", _F), Campo("altitud", "Altitud", _F),
    Campo("presencia", "Presencia", "bool"), Campo("foto", "Foto"), Campo("observaciones", "Observaciones"),
)
CAMPOS_GEOMETRIA = (                                            # Ficha 4; anchos SIEMPRE en mm
    Campo("area_m2", "Área", _F, minimo=0, unidad="m²"), Campo("longitud_m", "Longitud", _F, minimo=0, unidad="m"),
    Campo("ancho_prom_mm", "Ancho promedio", _F, minimo=0, unidad="mm"),
    Campo("ancho_max_mm", "Ancho máximo", _F, minimo=0, unidad="mm"),
    Campo("profundidad_cm", "Profundidad", _F, minimo=0, unidad="cm"),
    Campo("perimetro_m", "Perímetro", _F, minimo=0, unidad="m"),
    Campo("pct_area", "% de área afectada", _F, minimo=0, maximo=100, unidad="%"),
    Campo("separacion_m", "Separación", _F, minimo=0, unidad="m"),
    Campo("orientacion_deg", "Orientación", _F, minimo=0, maximo=180, unidad="°"),
)
CAMPOS_SEVERIDAD = (
    Campo("nivel", "Nivel de severidad", "opcion", requerido=True, opciones=NIVELES_SEVERIDAD),
    Campo("criterio", "Criterio"),
)


def _ficha(nombre):
    if nombre not in MODELOS:
        raise ErrorValidacion({"ficha": f"ficha desconocida '{nombre}'. Disponibles: {', '.join(MODELOS)}"})
    return MODELOS[nombre], CAMPOS[nombre]


def esquema_ficha(nombre):
    _ficha(nombre)
    return esquema(CAMPOS[nombre])


def esquema_patologia():
    return {"patologia": esquema(CAMPOS_PATOLOGIA), "geometria": esquema(CAMPOS_GEOMETRIA),
            "severidad": esquema(CAMPOS_SEVERIDAD)}


# ------------------------------------------------------------------------------------ CRUD genérico
def _comprobar_vuelo(s, d, tramo_id):
    if d.get("vuelo_id") is not None:
        v = s.get(VueloUAV, d["vuelo_id"])
        if v is None or v.tramo_id != tramo_id:
            raise ErrorValidacion({"vuelo_id": "no existe un vuelo con ese id en este tramo"})


def _crear(s, ficha, datos, tramo_id=None):
    """Crea la fila dentro de la sesión `s` (la usan los importadores). Devuelve el modelo."""
    Modelo, campos = _ficha(ficha)
    d = validar(datos, campos)
    if ficha == "catalogo":
        d["codigo"] = d["codigo"].upper()
        d["activo"] = True if d["activo"] is None else d["activo"]
        if s.scalar(select(CatalogoPatologia.id).where(CatalogoPatologia.codigo == d["codigo"])):
            raise ErrorValidacion({"codigo": f"ya existe el código {d['codigo']} en el catálogo"})
    if ficha == "inspeccion":
        d["observador"] = d["observador"] or 1
    if ficha in CON_TRAMO:
        if tramo_id is None:
            raise ErrorValidacion({"tramo": "indique el tramo"})
        d["tramo_id"] = tramo_id
        _comprobar_vuelo(s, d, tramo_id)
        campo_u = UNICO_POR_TRAMO.get(ficha)
        if campo_u and s.scalar(select(Modelo.id).where(Modelo.tramo_id == tramo_id,
                                                        getattr(Modelo, campo_u) == d[campo_u])):
            raise ErrorValidacion({campo_u: f"ya existe '{d[campo_u]}' en este tramo"})
    o = Modelo(**d)
    s.add(o)
    s.flush()
    return o


def crear(ficha, datos, tramo=None):
    with basedatos.nueva_sesion() as s:
        tid = _resolver(s, tramo).id if tramo is not None else None
        return _crear(s, ficha, datos, tid).a_dict()


def actualizar(ficha, id_, cambios):
    Modelo, campos = _ficha(ficha)
    d = validar(cambios, campos, parcial=True)
    with basedatos.nueva_sesion() as s:
        o = obtener(s, Modelo, id_, f"{ficha}")
        if ficha == "catalogo" and "codigo" in d:
            raise ErrorValidacion({"codigo": "el código del catálogo no se puede cambiar (lo usan las patologías)"})
        if "vuelo_id" in d:
            _comprobar_vuelo(s, d, o.tramo_id)
        campo_u = UNICO_POR_TRAMO.get(ficha)
        if campo_u and campo_u in d and d[campo_u] != getattr(o, campo_u) and s.scalar(
                select(Modelo.id).where(Modelo.tramo_id == o.tramo_id, getattr(Modelo, campo_u) == d[campo_u])):
            raise ErrorValidacion({campo_u: f"ya existe '{d[campo_u]}' en este tramo"})
        for k, v in d.items():
            setattr(o, k, v)
        s.flush()
        return o.a_dict()


def obtener_ficha(ficha, id_):
    Modelo, _ = _ficha(ficha)
    with basedatos.nueva_sesion() as s:
        return obtener(s, Modelo, id_, ficha).a_dict()


def listar(ficha, tramo=None):
    Modelo, _ = _ficha(ficha)
    with basedatos.nueva_sesion() as s:
        q = select(Modelo).order_by(Modelo.id)
        if tramo is not None and ficha in CON_TRAMO:
            q = q.where(Modelo.tramo_id == _resolver(s, tramo).id)
        return [o.a_dict() for o in s.scalars(q)]


def eliminar(ficha, id_):
    Modelo, _ = _ficha(ficha)
    with basedatos.nueva_sesion() as s:
        o = obtener(s, Modelo, id_, ficha)
        if ficha == "catalogo" and s.scalar(select(Patologia.id).where(Patologia.codigo == o.codigo).limit(1)):
            raise ErrorValidacion("El código se usa en patologías registradas: desactívelo en vez de eliminarlo")
        s.delete(o)


# ------------------------------------------------------------------------------------ patologías
def _a_dict_patologia(p):
    return {**p.a_dict(), "geometria": p.geometria.a_dict() if p.geometria else None,
            "severidad": p.severidad.a_dict() if p.severidad else None}


def _crear_patologia(s, insp, datos, geometria, severidad):
    d = validar(datos, CAMPOS_PATOLOGIA)
    cat = s.scalar(select(CatalogoPatologia).where(CatalogoPatologia.codigo == d["codigo"].upper()))
    if cat is None:
        raise ErrorValidacion({"codigo": f"el código '{d['codigo']}' no está en el catálogo (Ficha 2)"})
    if not cat.activo:
        raise ErrorValidacion({"codigo": f"el código {cat.codigo} está desactivado"})
    d["codigo"] = cat.codigo
    d["presencia"] = True if d["presencia"] is None else d["presencia"]
    if d["roi_id"] is not None:
        r = s.get(ROI, d["roi_id"])
        if r is None or r.tramo_id != insp.tramo_id:
            raise ErrorValidacion({"roi_id": "la ROI no existe o es de otro tramo"})
    if not d["presencia"] and (geometria or severidad):
        raise ErrorValidacion("Una patología con presencia = No no puede tener geometría ni severidad")
    p = Patologia(inspeccion_id=insp.id, **d)
    if geometria:
        g = validar(geometria, CAMPOS_GEOMETRIA)
        if g["ancho_prom_mm"] is not None and g["ancho_max_mm"] is not None and g["ancho_max_mm"] < g["ancho_prom_mm"]:
            raise ErrorValidacion({"ancho_max_mm": "el ancho máximo no puede ser menor que el promedio"})
        p.geometria = Geometria(**g)
    if severidad:
        sv = validar(severidad, CAMPOS_SEVERIDAD)
        p.severidad = Severidad(observador=insp.observador, **sv)
    s.add(p)
    s.flush()
    return p


def registrar_patologia(inspeccion_id, datos, geometria=None, severidad=None):
    """Crea la patología (Ficha 2) con su geometría (F4) y severidad (F3) en una sola transacción."""
    with basedatos.nueva_sesion() as s:
        insp = obtener(s, Inspeccion, inspeccion_id, "inspección")
        return _a_dict_patologia(_crear_patologia(s, insp, datos, geometria, severidad))


def actualizar_patologia(patologia_id, datos=None, geometria=None, severidad=None):
    """Actualiza campos de la patología; `geometria`/`severidad` (dict) se combinan con lo existente.
    Para quitar la severidad o la geometría use eliminar_severidad / eliminar_geometria."""
    with basedatos.nueva_sesion() as s:
        p = obtener(s, Patologia, patologia_id, "patología")
        if datos:
            d = validar(datos, CAMPOS_PATOLOGIA, parcial=True)
            if "codigo" in d:
                cat = s.scalar(select(CatalogoPatologia).where(CatalogoPatologia.codigo == d["codigo"].upper()))
                if cat is None:
                    raise ErrorValidacion({"codigo": f"el código '{d['codigo']}' no está en el catálogo"})
                d["codigo"] = cat.codigo
            if d.get("roi_id") is not None:
                r = s.get(ROI, d["roi_id"])
                if r is None or r.tramo_id != p.inspeccion.tramo_id:
                    raise ErrorValidacion({"roi_id": "la ROI no existe o es de otro tramo"})
            for k, v in d.items():
                setattr(p, k, v)
        if geometria:
            g = validar(geometria, CAMPOS_GEOMETRIA, parcial=True)
            if p.geometria is None:
                p.geometria = Geometria(**g)
            else:
                for k, v in g.items():
                    setattr(p.geometria, k, v)
        if severidad:
            sv = validar(severidad, CAMPOS_SEVERIDAD, parcial=p.severidad is not None)
            if p.severidad is None:
                p.severidad = Severidad(observador=p.inspeccion.observador, **sv)
            else:
                for k, v in sv.items():
                    setattr(p.severidad, k, v)
        if not p.presencia and (p.geometria or p.severidad):
            raise ErrorValidacion("Una patología con presencia = No no puede tener geometría ni severidad")
        s.flush()
        return _a_dict_patologia(p)


def eliminar_severidad(patologia_id):
    with basedatos.nueva_sesion() as s:
        p = obtener(s, Patologia, patologia_id, "patología")
        p.severidad = None


def eliminar_geometria(patologia_id):
    with basedatos.nueva_sesion() as s:
        p = obtener(s, Patologia, patologia_id, "patología")
        p.geometria = None


def eliminar_patologia(patologia_id):
    with basedatos.nueva_sesion() as s:
        s.delete(obtener(s, Patologia, patologia_id, "patología"))


def listar_patologias(inspeccion_id=None, roi_id=None, tramo=None):
    with basedatos.nueva_sesion() as s:
        q = select(Patologia).order_by(Patologia.id)
        if inspeccion_id is not None:
            q = q.where(Patologia.inspeccion_id == inspeccion_id)
        if roi_id is not None:
            q = q.where(Patologia.roi_id == roi_id)
        if tramo is not None:
            q = q.join(Inspeccion).where(Inspeccion.tramo_id == _resolver(s, tramo).id)
        return [_a_dict_patologia(p) for p in s.scalars(q)]


def severidades_roi(roi_id):
    """Severidad OFICIAL registrada en las fichas para una ROI, por observador:
    [{observador, codigo, patologia_id, nivel}]. Es la referencia de campo para la validación (F5)."""
    with basedatos.nueva_sesion() as s:
        q = (select(Patologia, Inspeccion.observador).join(Inspeccion).where(Patologia.roi_id == roi_id)
             .order_by(Inspeccion.observador, Patologia.id))
        return [{"observador": obs, "codigo": p.codigo, "patologia_id": p.id, "nivel": p.severidad.nivel}
                for p, obs in s.execute(q) if p.severidad is not None]
