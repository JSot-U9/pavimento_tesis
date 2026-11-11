"""
logica_deteccion.py
===================
Puente entre la BD y el núcleo de visión, en tres pasos que respetan la regla de hilos (el hilo de
trabajo SOLO calcula; la BD la escribe el hilo principal):

    1. preparar_analisis(...)  -> Trabajo      (hilo principal: lee BD, no abre el ortomosaico)
    2. ejecutar_trabajo(...)   -> ResultadoTrabajo   (puede correr en un hilo: núcleo, sin BD ni Tk)
    3. guardar_resultado(...)  -> dict         (hilo principal: escribe EjecucionAnalisis y detecciones)

`analizar()` y `analizar_rois()` encadenan los tres pasos de forma síncrona (CLI, pruebas, scripts).
Cada ejecución guarda los Params exactos (JSON) para poder reproducirla, y se marca `provisional`
mientras los umbrales no estén calibrados con datos reales (ver logica_configuracion).
"""
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app import basedatos, logica_configuracion, logica_tramos
from app.logica_comun import ErrorNoEncontrado, ErrorValidacion, obtener
from app.modelos import (ROI, CaracteristicaROI, Deteccion, EjecucionAnalisis, RendimientoEjecucion)
from app.nucleo import pipeline
from app.nucleo.calidad import mascara_valida
from app.nucleo.caracteristicas import caracteristicas_region
from app.nucleo.eje_via import EjeVia as EjeNucleo
from app.nucleo.estructuras import AnalisisCancelado, ResultadoAnalisis
from app.nucleo.geo import Transformacion
from app.nucleo.lectura import abrir
from app.nucleo.parametros import Params
from app.rendimiento import MedidorPico

MAX_PX_CARACTERISTICAS = 40_000_000          # por encima, no se calculan estadísticos RGB/GLCM de la ROI


@dataclass
class Trabajo:
    """Todo lo necesario para analizar, en datos simples (sin sesiones ni modelos)."""
    tramo_id: int
    ruta: str
    region: Tuple[int, int, int, int]
    alcance: str                                  # 'tramo' | 'roi' | 'ventana'
    params: Params
    metodo: str = "actual"
    roi_id: Optional[int] = None
    roi_codigo: Optional[str] = None
    eje: Optional[dict] = None                    # EjeVia.a_dict() o None
    transformacion: Optional[list] = None
    tesela_px: int = 1600
    margen_m: float = 1.0
    provisional: bool = True
    caracteristicas: bool = True

    @property
    def etiqueta(self):
        return self.roi_codigo or ("tramo completo" if self.alcance == "tramo" else "ventana")


@dataclass
class ResultadoTrabajo:
    analisis: ResultadoAnalisis
    duracion_s: float
    caracteristicas: Optional[dict] = None
    advertencias: List[str] = field(default_factory=list)
    ram: Optional[tuple] = None            # (base_mb, pico_mb, adicional_mb) medidos durante el análisis (F7)


# ------------------------------------------------------------------------------------ 1. preparar
def preparar_analisis(tramo, roi_id=None, region=None, metodo="actual", params=None, caracteristicas=True):
    """Arma el Trabajo. Sin `roi_id` ni `region` se analiza el ortomosaico completo."""
    if metodo not in pipeline.METODOS:
        raise ErrorValidacion({"metodo": f"método '{metodo}' no disponible. Disponibles: "
                                         f"{', '.join(sorted(pipeline.METODOS))}"})
    if roi_id is not None and region is not None:
        raise ErrorValidacion("Indique roi_id o region, no ambos")
    with basedatos.nueva_sesion() as s:
        t = logica_tramos._resolver(s, tramo)
        if not t.ortomosaico_ruta or not t.gsd_cm:
            raise ErrorValidacion("El tramo no tiene ortomosaico asignado (logica_tramos.asignar_ortomosaico)")
        if not os.path.isfile(t.ortomosaico_ruta):
            raise ErrorValidacion(f"No se encuentra el ortomosaico: {t.ortomosaico_ruta}")
        tid, ruta, gsd, tr = t.id, t.ortomosaico_ruta, t.gsd_cm, t.transformacion
        ancho, alto = t.ancho_px, t.alto_px
        rcod = None
        if roi_id is not None:
            r = obtener(s, ROI, roi_id, "ROI")
            if r.tramo_id != tid:
                raise ErrorValidacion({"roi_id": "la ROI es de otro tramo"})
            reg, alcance, rcod = r.region, "roi", r.codigo
        elif region is not None:
            reg, alcance = tuple(int(round(v)) for v in region), "ventana"
        else:
            reg, alcance = (0, 0, ancho, alto), "tramo"
    base = params if params is not None else logica_configuracion.params_base()
    p = base.migrar().con(gsd_cm=gsd)
    e = logica_tramos.obtener_eje(tid)
    eje = None if e is None else {"vertices_px": e["vertices_px"], "gsd_m": p.gsd_m,
                                  "progresiva_inicial_m": e["progresiva_inicial_m"], "ventana_m": p.eje_ventana_m}
    return Trabajo(tramo_id=tid, ruta=ruta, region=reg, alcance=alcance, params=p, metodo=metodo, roi_id=roi_id,
                   roi_codigo=rcod, eje=eje, transformacion=tr, tesela_px=int(logica_configuracion.obtener("tesela_px")),
                   margen_m=float(logica_configuracion.obtener("margen_m")),
                   provisional=logica_configuracion.es_provisional(p, metodo),
                   caracteristicas=caracteristicas and alcance == "roi")


# ------------------------------------------------------------------------------------ 2. ejecutar
def ejecutar_trabajo(trabajo, cancelar=None, progreso=None):
    """Corre el núcleo. NO toca la BD: se puede llamar desde un hilo. Lanza AnalisisCancelado si se cancela."""
    t0 = time.perf_counter()
    medidor = MedidorPico().__enter__()
    lector = abrir(trabajo.ruta, gsd_cm=trabajo.params.gsd_cm)
    try:
        eje = EjeNucleo.desde_dict(trabajo.eje) if trabajo.eje else None
        res = pipeline.analizar_region(lector, trabajo.region, trabajo.params, eje=eje, margen_m=trabajo.margen_m,
                                       tesela_px=trabajo.tesela_px, metodo=trabajo.metodo, cancelar=cancelar,
                                       progreso=progreso)
        carac, adv = None, []
        if trabajo.caracteristicas:
            x0, y0, x1, y1 = res.region
            if (x1 - x0) * (y1 - y0) > MAX_PX_CARACTERISTICAS:
                adv.append("ROI demasiado grande: no se calcularon estadísticos RGB ni textura")
            else:
                if cancelar is not None and cancelar.is_set():
                    raise AnalisisCancelado("Análisis cancelado por el usuario")
                carac = caracteristicas_region(lector, res.region,
                                               lambda rgb, nd: mascara_valida(rgb, trabajo.params, nd))
        medidor.__exit__(None, None, None)
        return ResultadoTrabajo(res, time.perf_counter() - t0, carac, adv,
                                (medidor.base_mb, medidor.pico_mb, medidor.adicional_mb))
    finally:
        medidor.__exit__(None, None, None)
        lector.cerrar()


# ------------------------------------------------------------------------------------ 3. guardar
def _py(v):
    """Valores de numpy -> Python (JSON y SQLite no aceptan numpy)."""
    if hasattr(v, "item") and not isinstance(v, (list, tuple, dict)):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, dict):
        return {k: _py(x) for k, x in v.items()}
    return v


def _roi_contenedora(rois, cx, cy):
    """La ROI más pequeña que contiene (cx, cy); desempata por id. rois = [(id, x0, y0, x1, y1, área_px)]."""
    mejores = [r for r in rois if r[1] <= cx < r[3] and r[2] <= cy < r[4]]
    return min(mejores, key=lambda r: (r[5], r[0]))[0] if mejores else None


def guardar_resultado(trabajo, resultado):
    """Escribe la ejecución, sus detecciones y las características de la ROI. Hilo principal."""
    a = resultado.analisis
    q = a.calidad
    tr = Transformacion(*trabajo.transformacion) if trabajo.transformacion else None
    adv = list(a.advertencias) + list(resultado.advertencias) + list(q.advertencias)
    with basedatos.nueva_sesion() as s:
        if trabajo.roi_id is not None and s.get(ROI, trabajo.roi_id) is None:
            raise ErrorNoEncontrado("La ROI analizada ya no existe")
        rois, area_roi = [], None
        if trabajo.roi_id is not None:
            r = s.get(ROI, trabajo.roi_id)
            area_roi = (r.x1 - r.x0) * (r.y1 - r.y0) * trabajo.params.gsd_m ** 2
        else:
            rois = [(r.id, r.x0, r.y0, r.x1, r.y1, (r.x1 - r.x0) * (r.y1 - r.y0))
                    for r in s.scalars(select(ROI).where(ROI.tramo_id == trabajo.tramo_id))]
        x0, y0, x1, y1 = a.region
        e = EjecucionAnalisis(
            tramo_id=trabajo.tramo_id, roi_id=trabajo.roi_id, alcance=trabajo.alcance, metodo=a.metodo,
            x0=x0, y0=y0, x1=x1, y1=y1, params_json=trabajo.params.a_dict(), params_version=trabajo.params.version,
            params_huella=a.params_huella, provisional=trabajo.provisional, preprocesamiento="Sí",
            duracion_s=round(resultado.duracion_s, 2), n_teselas=a.n_teselas, estado="completada",
            calidad=q.calidad, nitidez=_py(q.nitidez), brillo_medio=_py(q.brillo_medio),
            fraccion_saturada=_py(q.fraccion_saturada), resolucion_cm_px=_py(q.resolucion_cm_px),
            cobertura_pct=_py(q.cobertura_pct), calzada_util_pct=_py(q.calzada_util_pct),
            advertencias="; ".join(adv) or None)
        s.add(e)
        s.flush()
        filas = []
        for d in a.detecciones:
            roi_id = trabajo.roi_id if trabajo.roi_id is not None else _roi_contenedora(rois, d.cx, d.cy)
            este = norte = None
            if tr is not None:
                este, norte = (float(v) for v in tr.px_a_geo(d.cx, d.cy))
            pct = None
            if area_roi:
                pct = round(100.0 * d.area_m2 / area_roi, 3)
            elif roi_id is not None:
                rr = next(r for r in rois if r[0] == roi_id)
                pct = round(100.0 * d.area_m2 / (rr[5] * trabajo.params.gsd_m ** 2), 3)
            filas.append(Deteccion(
                ejecucion_id=e.id, roi_id=roi_id, tipo=d.tipo, geom_tipo=d.geom_tipo or None,
                geom_px=_py([list(p) for p in d.geom]), x=int(d.x), y=int(d.y), w=int(d.w), h=int(d.h),
                cx=float(d.cx), cy=float(d.cy), este=este, norte=norte, progresiva_m=_py(d.progresiva_m),
                lado_via=d.lado_via, longitud_m=_py(d.longitud_m), ancho_mm=_py(d.ancho_mm), ancho_m=_py(d.ancho_m),
                area_m2=_py(d.area_m2), area_px=_py(d.area_px), pct_area_afectada=pct,
                angulo_img_deg=_py(d.angulo_img_deg), angulo_eje_deg=_py(d.angulo_eje_deg),
                desv_eje_deg=_py(d.desv_eje_deg), contraste_weber=_py(d.contraste_weber),
                ramificada=None if d.ramificada is None else bool(d.ramificada), n_celdas=_py(d.n_celdas),
                celda_media_m2=_py(d.celda_media_m2), densidad_pct=_py(d.densidad_pct), solidez=_py(d.solidez),
                severidad_prelim=d.severidad_prelim, metodo_ancho=d.metodo_ancho or None,
                advertencia=d.advertencia or None, metodo=d.metodo))
        s.add_all(filas)
        if resultado.ram is not None and resultado.ram[1] is not None:
            s.add(RendimientoEjecucion(ejecucion_id=e.id, ram_base_mb=_py(resultado.ram[0]),
                                       ram_pico_mb=_py(resultado.ram[1]), ram_adicional_mb=_py(resultado.ram[2])))
        if resultado.caracteristicas is not None:
            s.add(CaracteristicaROI(ejecucion_id=e.id, roi_id=trabajo.roi_id, valores=_py(resultado.caracteristicas)))
        s.flush()
        return {**e.a_dict(), "n_detecciones": len(filas)}


def registrar_incidencia(trabajo, estado, mensaje):
    """Deja constancia de un análisis cancelado o fallido (sin detecciones)."""
    if estado not in ("cancelada", "error"):
        raise ErrorValidacion({"estado": "use 'cancelada' o 'error'"})
    x0, y0, x1, y1 = trabajo.region
    with basedatos.nueva_sesion() as s:
        e = EjecucionAnalisis(tramo_id=trabajo.tramo_id, roi_id=trabajo.roi_id, alcance=trabajo.alcance,
                              metodo=trabajo.metodo, x0=x0, y0=y0, x1=x1, y1=y1, params_json=trabajo.params.a_dict(),
                              params_version=trabajo.params.version, params_huella=trabajo.params.huella(),
                              provisional=trabajo.provisional, estado=estado, mensaje=str(mensaje))
        s.add(e)
        s.flush()
        return e.a_dict()


# ------------------------------------------------------------------------------------ síncrono
def analizar(tramo, roi_id=None, region=None, metodo="actual", params=None, cancelar=None, progreso=None):
    """Prepara, ejecuta y guarda. Si se cancela o falla, registra la incidencia y relanza la excepción."""
    trabajo = preparar_analisis(tramo, roi_id, region, metodo, params)
    try:
        res = ejecutar_trabajo(trabajo, cancelar, progreso)
    except AnalisisCancelado as e:
        registrar_incidencia(trabajo, "cancelada", e)
        raise
    except Exception as e:
        registrar_incidencia(trabajo, "error", f"{type(e).__name__}: {e}")
        raise
    return guardar_resultado(trabajo, res)


def analizar_rois(tramo, rol=None, tipo=None, metodo="actual", params=None, cancelar=None, progreso=None):
    """Una ejecución por ROI (opcionalmente solo las de un rol/tipo). Devuelve la lista de ejecuciones."""
    from app import logica_roi
    rois = logica_roi.listar_rois(tramo, rol=rol, tipo=tipo)
    if not rois:
        raise ErrorValidacion("No hay ROI que cumplan el filtro")
    out = []
    for k, r in enumerate(rois):
        sub = None if progreso is None else (lambda f, txt, k=k, c=r["codigo"]:
                                             progreso((k + f) / len(rois), f"ROI {c} ({k + 1}/{len(rois)}): {txt}"))
        out.append(analizar(tramo, roi_id=r["id"], metodo=metodo, params=params, cancelar=cancelar, progreso=sub))
    return out


# ------------------------------------------------------------------------------------ consultas
def listar_ejecuciones(tramo, roi_id=None, estado=None):
    with basedatos.nueva_sesion() as s:
        q = (select(EjecucionAnalisis).where(EjecucionAnalisis.tramo_id == logica_tramos._resolver(s, tramo).id)
             .order_by(EjecucionAnalisis.id.desc()))
        if roi_id is not None:
            q = q.where(EjecucionAnalisis.roi_id == roi_id)
        if estado:
            q = q.where(EjecucionAnalisis.estado == estado)
        return [e.a_dict() for e in s.scalars(q)]


def obtener_ejecucion(ejecucion_id):
    with basedatos.nueva_sesion() as s:
        return obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución").a_dict()


def rendimiento_de(ejecucion_ids):
    """{ejecucion_id: {'duracion_s', 'mpx', 'ram_base_mb', 'ram_pico_mb', 'ram_adicional_mb', 'metodo'}} (F7).
    La RAM es None en ejecuciones anteriores a la F7 o en sistemas donde no se pudo medir."""
    ids = [int(i) for i in ejecucion_ids]
    out = {}
    with basedatos.nueva_sesion() as s:
        for e in s.scalars(select(EjecucionAnalisis).where(EjecucionAnalisis.id.in_(ids))):
            r = s.get(RendimientoEjecucion, e.id)
            out[e.id] = {"metodo": e.metodo, "duracion_s": e.duracion_s, "mpx": (e.x1 - e.x0) * (e.y1 - e.y0) / 1e6,
                         "ram_base_mb": r.ram_base_mb if r else None, "ram_pico_mb": r.ram_pico_mb if r else None,
                         "ram_adicional_mb": r.ram_adicional_mb if r else None}
    return out


def parametros_de_ejecucion(ejecucion_id):
    """Params exactos de una ejecución (para reproducirla)."""
    return Params.desde_dict(obtener_ejecucion(ejecucion_id)["params_json"])


def listar_detecciones(ejecucion_id, tipo=None, roi_id=None):
    with basedatos.nueva_sesion() as s:
        obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución")
        q = select(Deteccion).where(Deteccion.ejecucion_id == ejecucion_id).order_by(Deteccion.progresiva_m, Deteccion.id)
        if tipo:
            q = q.where(Deteccion.tipo == tipo)
        if roi_id is not None:
            q = q.where(Deteccion.roi_id == roi_id)
        return [d.a_dict() for d in s.scalars(q)]


def caracteristicas_de(ejecucion_id):
    with basedatos.nueva_sesion() as s:
        return [{"roi_id": c.roi_id, **c.valores}
                for c in s.scalars(select(CaracteristicaROI).where(CaracteristicaROI.ejecucion_id == ejecucion_id))]


def resumen_ejecucion(ejecucion_id):
    """Conteo, longitud total y área total por tipo de deterioro."""
    with basedatos.nueva_sesion() as s:
        obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución")
        filas = s.execute(select(Deteccion.tipo, func.count(), func.coalesce(func.sum(Deteccion.longitud_m), 0.0),
                                 func.coalesce(func.sum(Deteccion.area_m2), 0.0))
                          .where(Deteccion.ejecucion_id == ejecucion_id).group_by(Deteccion.tipo))
        return {t: {"n": n, "longitud_m": round(l, 3), "area_m2": round(a, 4)} for t, n, l, a in filas}


def eliminar_ejecucion(ejecucion_id):
    with basedatos.nueva_sesion() as s:
        s.delete(obtener(s, EjecucionAnalisis, ejecucion_id, "ejecución"))
