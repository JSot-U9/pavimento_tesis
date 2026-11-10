"""
logica_reportes.py
==================
Reportes del tramo (Fase 6): PDF, XLSX y CSV a partir de UN SOLO diccionario de datos.

    recopilar(tramo, ...)   lee la BD y calcula todo (tablas 2-4, validación, estadística, fichas, conclusiones)
                            -> `datos` (dict de valores simples; es lo ÚNICO que ven los generadores)
    generar_pdf / generar_xlsx / generar_csv_*   escriben el archivo desde `datos` (NO tocan la BD: pueden correr
                            en un hilo de trabajo; ver `ejecutar_reportes`)
    generar(tramo, carpeta, formatos, ...)       recopila + genera todo lo pedido (uso síncrono / pruebas)

Reglas de contenido
  * Las CONCLUSIONES salen solo de cifras calculadas (plantillas con números; nunca juicios sin dato).
  * Todo lo calculado con parámetros provisionales lleva el aviso PROVISIONAL en PDF, XLSX y en `datos`.
  * Decisión del tesista (8-nov): las detecciones de unidades (ROI, tipo) validadas como FALSO POSITIVO NO entran al
    conteo de las Tablas 2-4 (`excluir_fp=True` por defecto) pero SIGUEN registradas: aparecen en la hoja/CSV de
    detecciones con `estado_validacion = FP` e `incluida_en_conteo = No`, y en la validación.
  * Estadística visible: proporciones con IC de Wilson, kappa y error de medidas descriptivo; McNemar, Bland-Altman,
    correlaciones y pruebas pareadas solo con `estadistica_avanzada` activada en la configuración.
  * Selección de ejecuciones: las indicadas; si no, la última ejecución VALIDADA de cada ROI del `rol`; si no hay
    validación, la última ejecución completada de cada ROI (informe sin validación: sin sección de estadística).
"""
import csv
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from app import (logica_configuracion as cfg, logica_deteccion as ld, logica_estadistica as le, logica_fichas as lf,
                 logica_roi, logica_tramos as lt, logica_validacion as lv)
from app.logica_comun import ErrorNoEncontrado, ErrorValidacion
from app.nucleo.estructuras import TIPOS

log = logging.getLogger("pavimento.reportes")

FORMATOS = ("pdf", "xlsx", "csv")
NOMBRE_TIPO = {"longitudinal": "Grieta longitudinal", "transversal": "Grieta transversal",
               "piel_cocodrilo": "Piel de cocodrilo", "bache": "Bache", "sano": "Sano"}
AVISO_PROVISIONAL = "PROVISIONAL: parámetros sin calibrar con datos reales; no son evidencia final."


class ErrorReporte(ValueError):
    """No se pudo generar el reporte (selección vacía, archivo no escribible, falta una librería...)."""


# ===================================================================================== utilidades
def _num(v, nd=2, unidad=""):
    if v is None:
        return "n/d"
    return f"{v:.{nd}f}{(' ' + unidad) if unidad else ''}"


def _ic(m, nd=2):
    ic = m.get("ic95")
    return f" (IC 95 % {ic[0]:.{nd}f}–{ic[1]:.{nd}f})" if ic else ""


def nombre_archivo_seguro(texto):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(texto)).strip("_") or "tramo"


def _intentar(secciones_omitidas, nombre, fn, *args, **kwargs):
    """Ejecuta una sección; si falla por datos faltantes la omite y anota el motivo (el resto del reporte sigue)."""
    try:
        return fn(*args, **kwargs)
    except (ErrorValidacion, ErrorNoEncontrado) as e:
        secciones_omitidas[nombre] = _texto_error(e)
    except Exception as e:                                     # noqa: BLE001 - un fallo no debe perder el reporte
        log.exception("Sección '%s' del reporte falló", nombre)
        secciones_omitidas[nombre] = f"error inesperado ({type(e).__name__}): {e}"
    return None


def _texto_error(e):
    errores = getattr(e, "errores", None)
    if isinstance(errores, dict) and errores:
        return "; ".join(str(v) for v in errores.values())
    return str(e)


# ===================================================================================== selección de ejecuciones
def seleccionar_ejecuciones(tramo, ejecucion_ids=None, metodo="actual", rol="prueba"):
    """{'ids', 'origen': 'indicadas'|'validadas'|'ultimas', 'advertencias'}. Ver la regla en el docstring del módulo."""
    adv = []
    if ejecucion_ids:
        ids = [ejecucion_ids] if isinstance(ejecucion_ids, int) else list(ejecucion_ids)
        t_id = lt.obtener_tramo(tramo)["id"]
        for i in ids:
            if ld.obtener_ejecucion(i)["tramo_id"] != t_id:
                raise ErrorValidacion({"ejecucion": f"la ejecución {i} no pertenece al tramo {tramo}"})
        return {"ids": sorted(ids), "origen": "indicadas", "advertencias": adv}
    ids = lv.ejecuciones_validadas(tramo, metodo, rol)
    if ids:
        return {"ids": ids, "origen": "validadas", "advertencias": adv}
    ultimas = {}
    for e in ld.listar_ejecuciones(tramo, estado="completada"):          # más reciente primero
        if e["metodo"] != metodo:
            continue
        clave = ("roi", e["roi_id"]) if e["alcance"] == "roi" else (e["alcance"], e["x0"], e["y0"], e["x1"], e["y1"])
        ultimas.setdefault(clave, e["id"])
    if not ultimas:
        raise ErrorValidacion({"ejecucion": f"el tramo {tramo} no tiene ejecuciones completadas del método '{metodo}': "
                                            f"analice primero (pestaña Análisis)"})
    adv.append(f"No hay validación guardada para el tramo {tramo}: se usan las últimas ejecuciones completadas y el "
               f"informe NO incluye validación ni estadística.")
    return {"ids": sorted(ultimas.values()), "origen": "ultimas", "advertencias": adv}


# ===================================================================================== recopilación
def _fila_ejecucion(e, rois_por_id):
    r = rois_por_id.get(e["roi_id"])
    return {"id": e["id"], "fecha": e["fecha"].strftime("%Y-%m-%d %H:%M") if e["fecha"] else None,
            "alcance": e["alcance"], "roi": r["codigo"] if r else None, "metodo": e["metodo"],
            "region": [e["x0"], e["y0"], e["x1"], e["y1"]], "params_huella": e["params_huella"],
            "provisional": bool(e["provisional"]), "duracion_s": e["duracion_s"], "n_teselas": e["n_teselas"],
            "calidad": e["calidad"], "nitidez": e["nitidez"], "brillo_medio": e["brillo_medio"],
            "fraccion_saturada": e["fraccion_saturada"], "resolucion_cm_px": e["resolucion_cm_px"],
            "cobertura_pct": e["cobertura_pct"], "calzada_util_pct": e["calzada_util_pct"],
            "preprocesamiento": e["preprocesamiento"], "advertencias": e["advertencias"]}


def _parametros(ejecs_db):
    """Grupos de parámetros distintos usados (por huella) con sus valores exactos."""
    grupos = {}
    for e in ejecs_db:
        g = grupos.setdefault(e["params_huella"], {"huella": e["params_huella"], "provisional": bool(e["provisional"]),
                                                   "ejecuciones": [], "valores": dict(e["params_json"]),
                                                   "version": e["params_version"]})
        g["ejecuciones"].append(e["id"])
    return list(grupos.values())


def _estado_por_unidad(filas_validacion):
    """{(ejecucion_id, roi_id, tipo): 'VP'|'FP'|'FN'|'VN'} de la validación guardada."""
    out = {}
    for f in filas_validacion:
        out[(f["ejecucion_id"], f["roi_id"], f["tipo"])] = next(
            c.upper() for c in ("vp", "fp", "fn", "vn") if f[c])
    return out


def _detecciones(ids, rois_por_id, estados, excluir_fp):
    filas = []
    for e in ids:
        ej = ld.obtener_ejecucion(e)
        for d in ld.listar_detecciones(e):
            r = rois_por_id.get(d["roi_id"])
            est = estados.get((e, d["roi_id"], d["tipo"]), "sin validar") if r else "sin ROI"
            filas.append({
                "id": d["id"], "ejecucion_id": e, "roi": r["codigo"] if r else None, "rol": r["rol"] if r else None,
                "tipo": d["tipo"], "estado_validacion": est, "incluida_en_conteo": not (excluir_fp and est == "FP"),
                "progresiva_m": d["progresiva_m"], "lado_via": d["lado_via"], "este": d["este"], "norte": d["norte"],
                "longitud_m": d["longitud_m"], "ancho_mm": d["ancho_mm"], "ancho_m": d["ancho_m"],
                "area_m2": d["area_m2"], "pct_area_afectada": d["pct_area_afectada"], "densidad_pct": d["densidad_pct"],
                "n_celdas": d["n_celdas"], "celda_media_m2": d["celda_media_m2"],
                "severidad_prelim": d["severidad_prelim"], "desv_eje_deg": d["desv_eje_deg"],
                "contraste_weber": d["contraste_weber"], "ramificada": d["ramificada"],
                "metodo_ancho": d["metodo_ancho"], "provisional": bool(ej["provisional"]),
                "advertencia": d["advertencia"]})
    return filas


def _fichas(tramo_codigo, rois_por_id):
    pats = []
    insp = {i["id"]: i for i in lf.listar("inspeccion", tramo_codigo)}
    for p in lf.listar_patologias(tramo=tramo_codigo):
        g, s, i = p["geometria"] or {}, p["severidad"] or {}, insp.get(p["inspeccion_id"], {})
        r = rois_por_id.get(p["roi_id"])
        pats.append({"id": p["id"], "inspeccion_id": p["inspeccion_id"], "observador": i.get("observador"),
                     "fecha": i.get("fecha"), "responsable": i.get("responsable"), "roi": r["codigo"] if r else None,
                     "codigo": p["codigo"], "presencia": p["presencia"], "progresiva_m": p["progresiva_m"],
                     "lado": p["lado"], "este": p["este"], "norte": p["norte"], "severidad": s.get("nivel"),
                     "criterio": s.get("criterio"), "area_m2": g.get("area_m2"), "longitud_m": g.get("longitud_m"),
                     "ancho_prom_mm": g.get("ancho_prom_mm"), "ancho_max_mm": g.get("ancho_max_mm"),
                     "profundidad_cm": g.get("profundidad_cm"), "perimetro_m": g.get("perimetro_m"),
                     "pct_area": g.get("pct_area"), "separacion_m": g.get("separacion_m"),
                     "orientacion_deg": g.get("orientacion_deg"), "observaciones": p["observaciones"]})
    return {"inspecciones": list(insp.values()), "patologias": pats}


def _resumen_gcp(gcps):
    precs = [g["precision_m"] for g in gcps if g["precision_m"] is not None]
    return {"n": len(gcps), "usados": sum(1 for g in gcps if g["usado_ortomosaico"]),
            "precision_media_m": (sum(precs) / len(precs)) if precs else None}


def _longitud_eje(vertices):
    return sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in zip(vertices, vertices[1:]))


def recopilar(tramo, ejecucion_ids=None, metodo="actual", rol="prueba", excluir_fp=True, con_comparacion=True,
              titulo=None, autor=None, institucion=None):
    """Lee la BD y devuelve `datos` (ver el módulo). Lanza ErrorValidacion si el tramo no tiene ejecuciones."""
    omit: Dict[str, str] = {}
    t = lt.obtener_tramo(tramo)
    codigo = t["codigo"]
    sel = seleccionar_ejecuciones(codigo, ejecucion_ids, metodo, rol)
    ids = sel["ids"]
    validado = sel["origen"] in ("validadas", "indicadas") and any(lv.listar_validacion(ejecucion_id=i) for i in ids)
    avanzada = bool(cfg.obtener("estadistica_avanzada"))
    rois = logica_roi.listar_rois(codigo)
    rois_por_id = {r["id"]: r for r in rois}
    ejecs_db = [ld.obtener_ejecucion(i) for i in ids]
    filas_val = [f for i in ids for f in lv.listar_validacion(ejecucion_id=i)]
    estados = _estado_por_unidad(filas_val)
    provisional = any(e["provisional"] for e in ejecs_db)

    eje = lt.obtener_eje(codigo)
    transf = lt.transformacion_de(t)
    datos = {
        "meta": {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "tramo": codigo, "metodo": metodo,
                 "rol": rol, "origen_ejecuciones": sel["origen"], "ejecuciones": ids, "validado": validado,
                 "provisional": provisional, "avanzada": avanzada, "excluye_fp": bool(excluir_fp),
                 "umbral_concordancia": float(cfg.obtener("umbral_concordancia")),
                 "titulo": titulo or "Detección de deterioros en pavimento flexible con ortomosaicos RGB",
                 "autor": autor or "", "institucion": institucion or ""},
        "tramo": t,
        "ortomosaico": {"ruta": t["ortomosaico_ruta"], "gsd_cm": t["gsd_cm"], "ancho_px": t["ancho_px"],
                        "alto_px": t["alto_px"], "epsg": t["epsg"], "georreferenciado": transf is not None},
        "eje": ({"n_vertices": len(eje["vertices_px"]), "origen": eje["origen"],
                 "progresiva_inicial_m": eje["progresiva_inicial_m"],
                 "longitud_m": _longitud_eje(eje["vertices_px"]) * (t["gsd_cm"] or 0) / 100.0 if t["gsd_cm"] else None}
                if eje else None),
        "vuelos": lf.listar("vuelo", codigo), "condiciones": lf.listar("condicion", codigo),
        "gcps": lf.listar("gcp", codigo),
        "ejecuciones": [_fila_ejecucion(e, rois_por_id) for e in ejecs_db],
        "parametros": _parametros(ejecs_db),
        "rois": [{k: r[k] for k in ("codigo", "tipo_campo", "severidad_campo", "rol", "progresiva_ini_m",
                                    "progresiva_fin_m")} for r in rois],
        "fichas": _fichas(codigo, rois_por_id),
        "validacion": {"filas": filas_val, "metricas": None, "concordancia_tipo": None, "concordancia_severidad": None,
                       "medidas": None},
        "tablas": None, "comparacion": None, "advertencias": list(sel["advertencias"]),
    }
    datos["gcp_resumen"] = _resumen_gcp(datos["gcps"])
    datos["detecciones"] = _detecciones(ids, rois_por_id, estados, excluir_fp)

    rol_tablas = rol if validado else None
    datos["tablas"] = _intentar(omit, "tablas_2_4", le.tablas_conteo, ids, codigo, rol_tablas, excluir_fp=excluir_fp)
    if validado:
        v = datos["validacion"]
        v["metricas"] = _intentar(omit, "metricas", le.metricas_validacion, ids, None, rol, 0.95,
                                  2000 if avanzada else 200, metodo)
        v["concordancia_tipo"] = _intentar(omit, "concordancia_tipo", le.concordancia_tipo, ids, codigo, rol)
        v["concordancia_severidad"] = _intentar(omit, "concordancia_severidad", le.concordancia_severidad, ids, codigo,
                                                rol)
        v["medidas"] = _intentar(omit, "error_de_medidas", le.error_de_medidas, ids, codigo, rol)
        if con_comparacion:
            comp = _intentar(omit, "comparacion_tramos", le.comparacion_tramos, None, metodo, rol)
            if comp and len(comp["tramos"]) >= 2:
                datos["comparacion"] = comp
    else:
        omit["validacion"] = "no hay validación guardada para esta selección"

    datos["secciones_omitidas"] = omit
    for sec in (datos["tablas"], datos["validacion"]["metricas"], datos["validacion"]["concordancia_tipo"],
                datos["validacion"]["medidas"]):
        for a in (sec or {}).get("advertencias", []):
            if a not in datos["advertencias"] and not a.startswith("PROVISIONAL"):
                datos["advertencias"].append(a)
    if provisional:
        datos["advertencias"].insert(0, AVISO_PROVISIONAL)
    datos["advertencias"] += _advertencias_datos(datos)
    datos["conclusiones"] = conclusiones(datos)
    return datos


def _advertencias_datos(d):
    adv = []
    if not d["ortomosaico"]["georreferenciado"]:
        adv.append("El ortomosaico no está georreferenciado: no hay coordenadas del mapa (este/norte) en el informe.")
    if not d["fichas"]["patologias"]:
        adv.append("No hay fichas de patologías (F2-F4): no hay severidad oficial ni medidas de campo.")
    if not d["vuelos"]:
        adv.append("No hay Ficha 5 (vuelo UAV) registrada para este tramo.")
    for n, motivo in d["secciones_omitidas"].items():
        if n != "validacion":
            adv.append(f"Sección omitida «{n}»: {motivo}")
    return adv


# ===================================================================================== conclusiones (solo cifras)
def conclusiones(d):
    """Frases construidas SOLO con cifras calculadas. Sin validación no se emite ninguna conclusión de desempeño."""
    out = []
    m = d["meta"]
    if m["provisional"]:
        out.append("PROVISIONAL: todas las cifras de este informe se calcularon con parámetros sin calibrar con datos "
                   "reales; deben leerse como prueba del procedimiento, no como evidencia final.")
    n_ej = len(m["ejecuciones"])
    out.append(f"Tramo {m['tramo']}: se informan {n_ej} ejecución(es) de análisis (método «{m['metodo']}»).")
    tb = d["tablas"]
    if tb:
        partes = []
        for t in TIPOS:
            x = tb["totales"][t]
            if x["n"]:
                p = f"{x['n']} {NOMBRE_TIPO[t].lower()}"
                if t == "bache":
                    p += f" ({_num(x['area_m2'], 2)} m²)"
                elif t == "piel_cocodrilo":
                    p += f" ({_num(x['area_m2'], 2)} m²)"
                else:
                    p += f" ({_num(x['longitud_m'], 2)} m)"
                partes.append(p)
        out.append("Detecciones contabilizadas: " + ("; ".join(partes) if partes else "ninguna") +
                   f" en {_num(tb['area_analizada_m2'], 1)} m² analizados.")
        if tb.get("fp_excluidos"):
            out.append(f"No entran al conteo {tb['fp_excluidos']} detecciones de unidades validadas como falso positivo "
                       f"(quedan registradas en la validación).")
    if not m["validado"]:
        out.append("No hay validación guardada: este informe no emite conclusiones sobre el desempeño del método.")
        return out
    me = d["validacion"]["metricas"]
    if me:
        g = me["global"]
        out.append(f"Validación sobre {me['n_rois']} ROI de «{m['rol']}» ({g['unidades']} unidades ROI×tipo): "
                   f"sensibilidad {_num(g['sensibilidad']['valor'])}{_ic(g['sensibilidad'])}, "
                   f"especificidad {_num(g['especificidad']['valor'])}{_ic(g['especificidad'])}, "
                   f"precisión {_num(g['precision']['valor'])}{_ic(g['precision'])}, "
                   f"concordancia {_num(None if g['exactitud']['valor'] is None else 100 * g['exactitud']['valor'], 1)} %.")
        k = g["kappa"]
        if k["kappa"] is not None:
            cumple = "alcanza" if k["concordante"] else "no alcanza"
            out.append(f"Kappa de presencia = {k['kappa']:.2f} ({k['interpretacion']}): {cumple} el mínimo de "
                       f"{m['umbral_concordancia']:.2f}.")
        else:
            out.append("Kappa de presencia no calculable (sin variabilidad en las clasificaciones).")
        sin = [NOMBRE_TIPO[t].lower() for t in TIPOS if me["por_tipo"][t]["sensibilidad"]["valor"] is None]
        if sin:
            out.append("Sensibilidad sin datos (no hay ROI de prueba con el tipo en campo): " + ", ".join(sin) + ".")
        if any("no es fiable" in a for a in me["advertencias"]):
            out.append("Hay métricas con n < 5: sus intervalos de confianza no son fiables.")
    ct = d["validacion"]["concordancia_tipo"]
    if ct and ct["kappa"]["kappa"] is not None:
        k = ct["kappa"]
        out.append(f"Concordancia del tipo por ROI (campo vs Python, multiclase): kappa = {k['kappa']:.2f} "
                   f"({k['interpretacion']}), n = {k['n']}.")
    ms = d["validacion"]["medidas"]
    if ms:
        for v, nombre, u in (("longitud_m", "longitud", "m"), ("ancho_mm", "ancho", "mm"), ("area_m2", "área", "m²")):
            e = ms["global"].get(v)
            if e and e["n"]:
                out.append(f"Error de {nombre} frente a la Ficha 4 (n = {e['n']}): sesgo {_num(e['sesgo'], 3, u)}, "
                           f"MAE {_num(e['mae'], 3, u)}, RMSE {_num(e['rmse'], 3, u)}.")
    return out


# ===================================================================================== CSV
def _celda_csv(v, decimal):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, float):
        s = f"{round(v, 6):.6f}".rstrip("0").rstrip(".")
        s = s if s not in ("", "-0") else "0"
        return s.replace(".", decimal) if decimal != "." else s
    if isinstance(v, (list, dict)):
        return str(v)
    return str(v)


def escribir_csv(columnas, filas, ruta, separador=",", decimal="."):
    """CSV UTF-8 con BOM (Excel lo abre con tildes). `separador` ',' o ';' · `decimal` '.' o ','."""
    if separador not in (",", ";"):
        raise ErrorReporte("el separador del CSV debe ser ',' o ';'")
    if decimal not in (".", ","):
        raise ErrorReporte("el separador decimal debe ser '.' o ','")
    if decimal == separador:
        raise ErrorReporte("el separador de campos y el decimal no pueden ser el mismo carácter")
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=separador, quoting=csv.QUOTE_MINIMAL)
        w.writerow([c[1] for c in columnas])
        for fila in filas:
            w.writerow([_celda_csv(fila.get(c[0]), decimal) for c in columnas])
    return ruta


def generar_csv_detecciones(datos, ruta, separador=",", decimal="."):
    from app.reportes_tablas import COLUMNAS
    return escribir_csv(COLUMNAS["detecciones"], datos["detecciones"], ruta, separador, decimal)


def generar_csv_validacion(datos, ruta, separador=",", decimal="."):
    from app.reportes_tablas import COLUMNAS, filas_validacion
    return escribir_csv(COLUMNAS["validacion"], filas_validacion(datos), ruta, separador, decimal)


# ===================================================================================== PDF / XLSX
def generar_pdf(datos, ruta):
    try:
        from app import reportes_pdf
    except ImportError as e:
        raise ErrorReporte("Falta la librería «reportlab» (pip install reportlab) para generar el PDF.") from e
    return reportes_pdf.escribir_pdf(datos, ruta)


def generar_xlsx(datos, ruta):
    try:
        from app import reportes_xlsx
    except ImportError as e:
        raise ErrorReporte("Falta la librería «openpyxl» (pip install openpyxl) para generar el Excel.") from e
    return reportes_xlsx.escribir_xlsx(datos, ruta)


def archivos_destino(datos, carpeta, formatos):
    base = f"informe_{nombre_archivo_seguro(datos['meta']['tramo'])}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    out = {}
    if "pdf" in formatos:
        out["pdf"] = os.path.join(carpeta, base + ".pdf")
    if "xlsx" in formatos:
        out["xlsx"] = os.path.join(carpeta, base + ".xlsx")
    if "csv" in formatos:
        out["csv_detecciones"] = os.path.join(carpeta, base + "_detecciones.csv")
        out["csv_validacion"] = os.path.join(carpeta, base + "_validacion.csv")
    return out


def escribir_reportes(datos, carpeta, formatos=("pdf", "xlsx", "csv"), separador_csv=",", decimal_csv=".",
                      cancelar=None, progreso=None):
    """Escribe los archivos pedidos desde `datos` (sin BD; apto para hilo de trabajo).
    `progreso(fracción, texto)`. Devuelve {'archivos': {clave: ruta}, 'omitidos': {clave: motivo}, 'advertencias': [...]}."""
    malos = [f for f in formatos if f not in FORMATOS]
    if malos:
        raise ErrorReporte(f"formato(s) desconocido(s): {', '.join(malos)}. Disponibles: {', '.join(FORMATOS)}")
    if not formatos:
        raise ErrorReporte("elija al menos un formato (PDF, XLSX o CSV)")
    try:
        os.makedirs(carpeta, exist_ok=True)
    except OSError as e:
        raise ErrorReporte(f"No se puede usar la carpeta de destino «{carpeta}»: {e}") from e
    destinos = archivos_destino(datos, carpeta, formatos)
    archivos, omitidos = {}, {}
    pasos = [(k, r) for k, r in destinos.items()]
    for i, (clave, ruta) in enumerate(pasos):
        if cancelar is not None and cancelar.is_set():
            omitidos[clave] = "cancelado"
            continue
        if progreso:
            progreso(i / len(pasos), f"Generando {os.path.basename(ruta)}")
        try:
            if clave == "pdf":
                generar_pdf(datos, ruta)
            elif clave == "xlsx":
                generar_xlsx(datos, ruta)
            elif clave == "csv_detecciones":
                generar_csv_detecciones(datos, ruta, separador_csv, decimal_csv)
            else:
                generar_csv_validacion(datos, ruta, separador_csv, decimal_csv)
            archivos[clave] = ruta
        except ErrorReporte as e:
            omitidos[clave] = str(e)
        except PermissionError:
            omitidos[clave] = f"No se pudo escribir «{ruta}»: el archivo está abierto en otro programa o no hay permiso."
        except OSError as e:
            omitidos[clave] = f"No se pudo escribir «{ruta}»: {e}"
    if progreso:
        progreso(1.0, "Listo")
    adv = list(datos["advertencias"][:1]) if datos["meta"]["provisional"] else []
    return {"archivos": archivos, "omitidos": omitidos, "advertencias": adv,
            "provisional": datos["meta"]["provisional"]}


def generar(tramo, carpeta, formatos=("pdf", "xlsx", "csv"), ejecucion_ids=None, metodo="actual", rol="prueba",
            excluir_fp=True, separador_csv=",", decimal_csv=".", **opciones):
    """Recopila y escribe (síncrono). `opciones`: titulo, autor, institucion, con_comparacion."""
    datos = recopilar(tramo, ejecucion_ids, metodo, rol, excluir_fp, **opciones)
    res = escribir_reportes(datos, carpeta, formatos, separador_csv, decimal_csv)
    res["datos"] = datos
    return res
