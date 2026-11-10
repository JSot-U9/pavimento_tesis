"""
logica_calibracion.py
=====================
Calibración de los umbrales PROVISIONALES (`Params.provisionales()`) con las ROI de rol 'calibracion'.

Método: BÚSQUEDA POR COORDENADAS sobre una rejilla ACOTADA (no una rejilla completa, que sería combinatoria):
para cada parámetro elegido se prueban valores `valor_actual × factor` (factores de `FACTORES`, recortados a
los límites de `LIMITES`) manteniendo los demás fijos; se adopta el mejor si MEJORA estrictamente el objetivo
(empates: se conserva el valor actual → el cambio mínimo); se repite hasta `max_pasadas` o hasta que una pasada
no mejore, con un tope `max_evaluaciones` de corridas del motor. Cada candidato se evalúa corriendo el núcleo
sobre TODAS las ROI de calibración (no se guarda nada en la BD) y comparando con la referencia de campo con las
mismas reglas que la validación (`logica_validacion.evaluar_roi`).

Objetivo configurable (`Configuracion['objetivo_calibracion']`): 'f1' (micro, sobre todas las unidades ROI×tipo)
o 'kappa' (presencia campo vs Python). F1/kappa no definidos puntúan −1 (peor que cualquier valor real).

Garantías
---------
* NUNCA se procesa una ROI de prueba. Si una ROI de calibración se solapa con una de prueba, se BLOQUEA
  (o advierte con `solapes='advertir'`), igual que en la validación.
* `calibrar` NO guarda nada: devuelve antes/después. Solo `aplicar_calibracion(resultado, confirmar=True)` llama a
  `guardar_params_base(params, calibrado=True)`. Cada ejecución posterior sigue guardando sus Params exactos.
* Los límites y factores son SUPUESTOS de ingeniería (no vienen del plan de tesis): ajústelos si el asesor indica otros.
* Con pocas ROI de calibración (< 5) el resultado se advierte como sobreajustado/no fiable.
"""

from dataclasses import dataclass, field, replace

from app import logica_configuracion as cfg, logica_roi
from app.logica_comun import ErrorValidacion
from app.logica_estadistica import f1_de, kappa_de_conteos, metricas_binarias
from app.logica_validacion import _comprobar_solapes, cargar_referencia, evaluar_roi
from app.nucleo.estructuras import AnalisisCancelado, TIPOS
from app.nucleo.parametros import Params

FACTORES = (0.5, 0.7, 0.85, 1.0, 1.2, 1.5, 2.0)

# (mínimo, máximo) absolutos de cada parámetro calibrable (SUPUESTO de ingeniería, en las unidades de Params)
LIMITES = {
    "grieta_k_mad": (2.0, 10.0), "grieta_contraste_min": (3.0, 30.0), "grieta_long_min_m": (0.05, 0.6),
    "grieta_cierre_m": (0.01, 0.10), "grieta_kernel_m": (0.03, 0.15), "grieta_en_cocodrilo": (0.2, 0.9),
    "celda_min_m2": (0.0001, 0.002), "celda_max_m2": (0.03, 0.2), "celda_union_m": (0.03, 0.2),
    "celdas_min": (2, 12), "zona_min_m2": (0.02, 0.5),
    "bache_dL_min": (8.0, 40.0), "bache_dC_min": (6.0, 35.0), "bache_ancho_min_m": (0.06, 0.4),
    "bache_area_min_m2": (0.01, 0.2), "bache_solidez_min": (0.4, 0.9), "bache_relacion_min": (0.1, 0.6),
    "bache_fondo_m": (0.3, 1.5), "exg_veg": (10.0, 50.0), "iluminacion_sigma_m": (0.2, 1.5),
    "nitidez_min": (1.0, 30.0), "brillo_min": (10.0, 80.0), "brillo_max": (180.0, 250.0),
    "saturados_max": (0.01, 0.2), "marca_vial_L": (150.0, 240.0),
    "ancho_semi_perfil_m": (0.04, 0.2), "ancho_paso_px": (1, 8), "ancho_contraste_min": (3.0, 30.0),
    "ancho_sigma_px": (0.0, 2.0), "ancho_suavizado_px": (0.0, 2.0),
}
# Los que realmente deciden presencia/ausencia de cada tipo (los de medición de ancho se afinan con la Ficha 4, no aquí).
PARAMETROS_POR_DEFECTO = ("grieta_k_mad", "grieta_contraste_min", "grieta_long_min_m", "grieta_cierre_m",
                          "celdas_min", "zona_min_m2", "bache_dL_min", "bache_dC_min", "bache_area_min_m2",
                          "bache_solidez_min")


def parametros_calibrables():
    """[{nombre, valor, minimo, maximo}] de los Params provisionales con límites definidos (valores de los Params base)."""
    base = cfg.params_base().a_dict()
    return [{"nombre": n, "valor": base[n], "minimo": LIMITES[n][0], "maximo": LIMITES[n][1],
             "por_defecto": n in PARAMETROS_POR_DEFECTO}
            for n in Params.provisionales() if n in LIMITES]


def candidatos(nombre, actual, factores=FACTORES):
    """Valores a probar para un parámetro: actual × factor, dentro de LIMITES, sin repetir (el actual primero)."""
    lo, hi = LIMITES[nombre]
    es_int = isinstance(actual, int) and not isinstance(actual, bool)
    vistos, out = set(), []
    for f in (1.0,) + tuple(factores):
        v = min(max(actual * f, lo), hi)
        v = int(round(v)) if es_int else float(f"{v:.6g}")
        if v not in vistos:
            vistos.add(v)
            out.append(v)
    return out


def puntaje(conteos, objetivo):
    """Puntaje del objetivo a partir de (vp, fp, fn, vn) agrupados. No definido → −1."""
    vp, fp, fn, vn = (int(v) for v in conteos)
    v = f1_de(vp, fp, fn) if objetivo == "f1" else kappa_de_conteos(vp, fp, fn, vn)["kappa"]
    return -1.0 if v is None else float(v)


# ===================================================================================== búsqueda (pura)
def busqueda_coordenada(evaluar, base, parametros, objetivo="f1", max_pasadas=2, max_evaluaciones=200,
                        cancelar=None, progreso=None, factores=FACTORES):
    """Búsqueda por coordenadas. `evaluar(params) -> (vp, fp, fn, vn)`. Devuelve dict con params, puntajes e historial."""
    cache, historial = {}, []

    def punt(p):
        k = p.huella()
        if k not in cache:
            if cancelar is not None and cancelar.is_set():
                raise AnalisisCancelado("Calibración cancelada")
            cache[k] = tuple(evaluar(p))
            if progreso:
                progreso(min(0.99, len(cache) / max_evaluaciones), f"Evaluación {len(cache)} de ≤ {max_evaluaciones}")
        return puntaje(cache[k], objetivo), cache[k]

    mejor, (s_mejor, c_mejor) = base, punt(base)
    s_inicial, c_inicial = s_mejor, c_mejor
    agotado = False
    for pasada in range(1, max_pasadas + 1):
        mejoro = False
        for nombre in parametros:
            actual = getattr(mejor, nombre)
            for v in candidatos(nombre, actual, factores):
                if v == actual:
                    continue
                if len(cache) >= max_evaluaciones:
                    agotado = True
                    break
                try:
                    cand = mejor.con(**{nombre: v})
                except ValueError:
                    continue                                    # combinación incoherente: se descarta
                s, c = punt(cand)
                historial.append({"pasada": pasada, "parametro": nombre, "valor": v, "puntaje": s})
                if s > s_mejor + 1e-9:
                    mejor, s_mejor, c_mejor, mejoro = cand, s, c, True
            if agotado:
                break
        if agotado or not mejoro:
            break
    return {"params": mejor, "puntaje_antes": s_inicial, "puntaje_despues": s_mejor, "conteos_antes": c_inicial,
            "conteos_despues": c_mejor, "evaluaciones": len(cache), "agotado": agotado, "historial": historial}


# ===================================================================================== evaluación con el motor
@dataclass
class PlanCalibracion:
    """Todo lo que la búsqueda necesita, preparado en el HILO PRINCIPAL (lee la BD). `ejecutar_calibracion` solo
    usa el núcleo y cálculos puros, así que puede correr en el hilo de trabajo (regla del proyecto)."""
    tramo: object
    objetivo: str
    parametros: list
    max_pasadas: int
    max_evaluaciones: int
    factores: tuple
    base: Params
    rois: list
    trabajos: list
    refs: dict
    umbral: float
    tol_m: float
    advertencias: list = field(default_factory=list)


def _dets_dict(analisis):
    return [{"tipo": d.tipo, "geom_px": [list(p) for p in d.geom], "geom_tipo": d.geom_tipo} for d in analisis.detecciones]


def _evaluador(plan, cancelar):
    from app import logica_deteccion as ld                      # solo ejecutar_trabajo (núcleo): no toca la BD

    def evaluar(params):
        tot = [0, 0, 0, 0]
        for r, trabajo in zip(plan.rois, plan.trabajos):
            t = replace(trabajo, params=params.con(gsd_cm=trabajo.params.gsd_cm))       # gsd del tramo, umbrales del candidato
            res = ld.ejecutar_trabajo(t, cancelar)
            tol_px = plan.tol_m / t.params.gsd_m
            for f in evaluar_roi(r, plan.refs[r["id"]]["tipos"], _dets_dict(res.analisis),
                                 plan.refs[r["id"]]["geometrias"], plan.umbral, tol_px):
                tot[0] += f["vp"]; tot[1] += f["fp"]; tot[2] += f["fn"]; tot[3] += f["vn"]
        return tuple(tot)
    return evaluar


def preparar_calibracion(tramo, parametros=None, objetivo=None, max_pasadas=2, max_evaluaciones=200,
                         umbral_solape=None, tolerancia_m=None, solapes="bloquear", factores=FACTORES,
                         params_base=None):
    """Valida entradas y arma el `PlanCalibracion` (HILO PRINCIPAL: lee la BD). Solo ROI de calibración."""
    from app import logica_deteccion as ld
    objetivo = (objetivo or cfg.obtener("objetivo_calibracion")).lower()
    if objetivo not in ("f1", "kappa"):
        raise ErrorValidacion({"objetivo": "use 'f1' o 'kappa'"})
    parametros = list(parametros or PARAMETROS_POR_DEFECTO)
    malos = [p for p in parametros if p not in Params.provisionales() or p not in LIMITES]
    if malos:
        raise ErrorValidacion({"parametros": f"no calibrables (no son provisionales o no tienen límites): {', '.join(malos)}"})
    if max_pasadas < 1 or max_evaluaciones < 1:
        raise ErrorValidacion({"max_evaluaciones": "max_pasadas y max_evaluaciones deben ser al menos 1"})
    adv = []
    _comprobar_solapes(tramo, solapes, adv)
    rois = logica_roi.listar_rois(tramo, rol="calibracion")
    if not rois:
        raise ErrorValidacion({"rois": "el tramo no tiene ROI de rol 'calibracion' (use asignar_roles)"})
    assert all(r["rol"] == "calibracion" for r in rois)             # salvaguarda: nunca ROI de prueba
    if len(rois) < 5:
        adv.append(f"solo {len(rois)} ROI de calibración: el ajuste puede sobreajustarse y no es fiable")
    base = params_base or cfg.params_base()
    trabajos = [ld.preparar_analisis(tramo, roi_id=r["id"], params=base, caracteristicas=False) for r in rois]
    return PlanCalibracion(
        tramo=tramo, objetivo=objetivo, parametros=parametros, max_pasadas=max_pasadas,
        max_evaluaciones=max_evaluaciones, factores=tuple(factores), base=base, rois=rois, trabajos=trabajos,
        refs=cargar_referencia([r["id"] for r in rois]),
        umbral=float(cfg.obtener("umbral_solape") if umbral_solape is None else umbral_solape),
        tol_m=float(cfg.obtener("tolerancia_ref_m") if tolerancia_m is None else tolerancia_m), advertencias=adv)


def ejecutar_calibracion(plan, cancelar=None, progreso=None):
    """Corre la búsqueda (SIN BD: apta para el hilo de trabajo). `cancelar` = threading.Event (lanza
    AnalisisCancelado); `progreso(fracción, texto)`. NO guarda nada."""
    adv = list(plan.advertencias)
    base = plan.base
    r = busqueda_coordenada(_evaluador(plan, cancelar), base, plan.parametros, plan.objetivo, plan.max_pasadas,
                            plan.max_evaluaciones, cancelar, progreso, plan.factores)
    despues = r["params"]
    cambios = {n: {"antes": getattr(base, n), "despues": getattr(despues, n)} for n in plan.parametros
               if getattr(base, n) != getattr(despues, n)}
    if r["agotado"]:
        adv.append(f"se alcanzó el tope de {plan.max_evaluaciones} evaluaciones: el resultado puede no ser el óptimo")
    if not cambios:
        adv.append("la búsqueda no encontró mejora: los parámetros actuales ya son los mejores de la rejilla")
    adv.append("Los parámetros calibrados solo reflejan las ROI de calibración; valide con las ROI de PRUEBA "
               "(no se tocaron) antes de usarlos como evidencia.")
    return {"tramo": plan.tramo, "objetivo": plan.objetivo, "n_rois": len(plan.rois),
            "rois": [r_["codigo"] for r_ in plan.rois], "parametros": plan.parametros,
            "params_antes": base.a_dict(), "params_despues": despues.a_dict(), "cambios": cambios,
            "antes": _resumen(r["conteos_antes"], r["puntaje_antes"]),
            "despues": _resumen(r["conteos_despues"], r["puntaje_despues"]), "evaluaciones": r["evaluaciones"],
            "historial": r["historial"], "provisional": True, "guardado": False, "advertencias": adv}


def calibrar(tramo, cancelar=None, progreso=None, **kw):
    """Preparar + ejecutar de forma síncrona (pruebas, scripts). NO guarda nada. La UI usa las dos fases por
    separado para correr la segunda en segundo plano. Argumentos de `preparar_calibracion`."""
    return ejecutar_calibracion(preparar_calibracion(tramo, **kw), cancelar, progreso)


def _resumen(c, puntaje_):
    m = metricas_binarias(*c)
    return {"conteos": list(c), "puntaje": puntaje_, "sensibilidad": m["sensibilidad"]["valor"],
            "precision": m["precision"]["valor"], "f1": m["f1"]["valor"],
            "kappa": kappa_de_conteos(*c)["kappa"], "exactitud": m["exactitud"]["valor"]}


def aplicar_calibracion(resultado, confirmar=False):
    """Guarda los Params calibrados como base (`calibrado=True`) SOLO si `confirmar` es True. Un análisis posterior
    con exactamente estos Params deja de marcarse PROVISIONAL."""
    if not confirmar:
        raise ErrorValidacion({"confirmar": "la calibración solo se guarda si el usuario la confirma"})
    if not isinstance(resultado, dict) or "params_despues" not in resultado or resultado.get("n_rois", 0) < 1:
        raise ErrorValidacion({"resultado": "resultado de calibración inválido"})
    p = Params.desde_dict(resultado["params_despues"])
    cfg.guardar_params_base(p, calibrado=True)
    return {"guardado": True, "huella": p.huella(), "provisional": cfg.es_provisional(p)}
