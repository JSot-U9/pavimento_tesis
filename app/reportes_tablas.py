"""
reportes_tablas.py
==================
Fuente ÚNICA de las tablas de los reportes: columnas (clave, encabezado, formato) y filas como dicts, construidas
solo desde `datos` (ver logica_reportes). PDF, XLSX y CSV leen de aquí, así que las cifras no pueden diferir entre
formatos. Sin BD, sin Tk: apto para hilos de trabajo.

Formatos de columna: 'txt' · 'int' · 'f1' · 'f2' · 'f3' · 'sino' (bool).
"""
from app.nucleo.estructuras import TIPOS

NOMBRE_TIPO = {"longitudinal": "Longitudinal", "transversal": "Transversal", "piel_cocodrilo": "Piel de cocodrilo",
               "bache": "Bache", "sano": "Sano"}
VARIABLES = (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²"))

COLUMNAS = {
    "resumen_tipos": [("tipo", "Tipo", "txt"), ("n", "N (conteo)", "int"), ("n_registradas", "N registradas", "int"),
                      ("fp_excluidas", "Excluidas por FP", "int"), ("longitud_m", "Longitud (m)", "f2"),
                      ("area_m2", "Área (m²)", "f2"), ("pct_area_afectada", "% área afectada", "f2"),
                      ("rois_con_tipo", "ROI con el tipo", "int")],
    "tabla2": [("roi", "ROI", "txt"), ("rol", "Rol", "txt"), ("tipo", "Tipo", "txt"), ("n", "N", "int"),
               ("longitud_m", "Longitud (m)", "f2"), ("ancho_medio_mm", "Ancho medio (mm)", "f2"),
               ("ancho_max_mm", "Ancho máx. (mm)", "f2"), ("area_m2", "Área (m²)", "f3"),
               ("pct_area_afectada", "% área afectada", "f2")],
    "tabla3": [("roi", "ROI", "txt"), ("rol", "Rol", "txt"), ("n", "Zonas", "int"),
               ("longitud_m", "Long. grietas (m)", "f2"), ("area_m2", "Área (m²)", "f3"),
               ("pct_area_afectada", "% área afectada", "f2"), ("densidad_media_pct", "Densidad (%)", "f1")],
    "tabla4": [("roi", "ROI", "txt"), ("rol", "Rol", "txt"), ("n", "Baches", "int"), ("longitud_m", "Longitud (m)", "f2"),
               ("ancho_medio_m", "Ancho (m)", "f2"), ("area_m2", "Área (m²)", "f3"),
               ("pct_area_afectada", "% área afectada", "f2")],
    "detecciones": [("id", "ID", "int"), ("ejecucion_id", "Ejecución", "int"), ("roi", "ROI", "txt"), ("rol", "Rol", "txt"),
                    ("tipo", "Tipo", "txt"), ("estado_validacion", "Estado de validación", "txt"),
                    ("incluida_en_conteo", "Incluida en el conteo", "sino"), ("progresiva_m", "Progresiva (m)", "f2"),
                    ("lado_via", "Lado", "txt"), ("este", "Este", "f2"), ("norte", "Norte", "f2"),
                    ("longitud_m", "Longitud (m)", "f3"), ("ancho_mm", "Ancho (mm)", "f2"), ("ancho_m", "Ancho bache (m)", "f3"),
                    ("area_m2", "Área (m²)", "f3"), ("pct_area_afectada", "% área afectada", "f2"),
                    ("densidad_pct", "Densidad (%)", "f1"), ("n_celdas", "N.º de celdas", "int"),
                    ("celda_media_m2", "Celda media (m²)", "f3"), ("severidad_prelim", "Severidad (ORIENTATIVA)", "txt"),
                    ("desv_eje_deg", "Desv. del eje (°)", "f1"), ("contraste_weber", "Contraste Weber", "f2"),
                    ("ramificada", "Ramificada", "sino"), ("metodo_ancho", "Método de ancho", "txt"),
                    ("provisional", "PROVISIONAL", "sino"), ("advertencia", "Advertencia", "txt")],
    "validacion": [("roi", "ROI", "txt"), ("rol", "Rol", "txt"), ("tipo_campo", "Tipo de campo", "txt"),
                   ("tipo", "Tipo evaluado", "txt"), ("resultado", "Resultado", "txt"), ("vp", "VP", "int"),
                   ("fp", "FP", "int"), ("fn", "FN", "int"), ("vn", "VN", "int"), ("solape", "Solape (Dice)", "f2"),
                   ("umbral_solape", "Umbral de solape", "f2"), ("ejecucion_id", "Ejecución", "int"),
                   ("provisional", "PROVISIONAL", "sino")],
    "metricas": [("tipo", "Tipo", "txt"), ("vp", "VP", "int"), ("fp", "FP", "int"), ("fn", "FN", "int"), ("vn", "VN", "int"),
                 ("sens", "Sensibilidad", "f3"), ("sens_lo", "Sens. IC95 inf.", "f3"), ("sens_hi", "Sens. IC95 sup.", "f3"),
                 ("esp", "Especificidad", "f3"), ("esp_lo", "Esp. IC95 inf.", "f3"), ("esp_hi", "Esp. IC95 sup.", "f3"),
                 ("prec", "Precisión", "f3"), ("prec_lo", "Prec. IC95 inf.", "f3"), ("prec_hi", "Prec. IC95 sup.", "f3"),
                 ("f1", "F1", "f3"), ("concordancia_pct", "Concordancia (%)", "f1"), ("kappa", "Kappa", "f3"),
                 ("kappa_interp", "Interpretación", "txt"), ("kappa_ok", "¿Kappa ≥ umbral?", "sino"),
                 ("unidades", "Unidades", "int")],
    "concordancia": [("comparacion", "Comparación", "txt"), ("n", "n", "int"), ("kappa", "Kappa", "f3"),
                     ("lo", "IC95 inf.", "f3"), ("hi", "IC95 sup.", "f3"), ("interp", "Interpretación", "txt"),
                     ("ok", "¿≥ umbral?", "sino")],
    "medidas": [("variable", "Variable", "txt"), ("tipo", "Tipo", "txt"), ("n", "n", "int"), ("sesgo", "Sesgo", "f3"),
                ("mae", "MAE", "f3"), ("rmse", "RMSE", "f3")],
    "medidas_avanzadas": [("pearson", "Pearson r", "f3"), ("pearson_p", "p (Pearson)", "f3"),
                          ("spearman", "Spearman ρ", "f3"), ("spearman_p", "p (Spearman)", "f3"),
                          ("prueba", "Prueba pareada", "txt"), ("prueba_p", "p (pareada)", "f3")],
    "pares_medidas": [("roi", "ROI", "txt"), ("tipo", "Tipo", "txt"), ("variable", "Variable", "txt"),
                      ("campo", "Campo (Ficha 4)", "f3"), ("python", "Python", "f3"), ("error", "Error (Python − campo)", "f3")],
    "calidad": [("id", "Ejecución", "int"), ("roi", "ROI", "txt"), ("alcance", "Alcance", "txt"), ("calidad", "Calidad", "txt"),
                ("nitidez", "Nitidez", "f1"), ("brillo_medio", "Brillo medio", "f1"),
                ("fraccion_saturada", "Fracción saturada", "f3"), ("resolucion_cm_px", "Resolución (cm/px)", "f2"),
                ("cobertura_pct", "Cobertura (%)", "f1"), ("calzada_util_pct", "Calzada útil (%)", "f1"),
                ("params_huella", "Parámetros", "txt"), ("provisional", "PROVISIONAL", "sino"),
                ("advertencias", "Advertencias", "txt")],
    "parametros": [("grupo", "Conjunto (huella)", "txt"), ("provisional", "PROVISIONAL", "sino"),
                   ("parametro", "Parámetro", "txt"), ("valor", "Valor", "txt")],
    "tramo": [("campo", "Campo", "txt"), ("valor", "Valor", "txt")],
    "vuelos": [("codigo", "Código", "txt"), ("fecha", "Fecha", "txt"), ("hora_inicio", "Inicio", "txt"),
               ("hora_fin", "Fin", "txt"), ("dron", "Dron", "txt"), ("camara", "Cámara", "txt"),
               ("altura_m", "Altura (m)", "f1"), ("gsd_cm", "GSD (cm/px)", "f2"),
               ("traslape_frontal_pct", "Traslape frontal (%)", "f1"), ("traslape_lateral_pct", "Traslape lateral (%)", "f1"),
               ("velocidad_ms", "Velocidad (m/s)", "f1"), ("n_fotos", "Fotos", "int"), ("n_gcp", "GCP", "int"),
               ("operador", "Operador", "txt"), ("observaciones", "Observaciones", "txt")],
    "condiciones": [("fecha", "Fecha", "txt"), ("hora", "Hora", "txt"), ("temperatura_c", "Temp. (°C)", "f1"),
                    ("humedad_pct", "Humedad (%)", "f1"), ("cielo", "Cielo", "txt"), ("viento_ms", "Viento (m/s)", "f1"),
                    ("lluvia", "Lluvia", "txt"), ("humedad_pavimento", "Pavimento", "txt"), ("sombras", "Sombras", "txt"),
                    ("observaciones", "Observaciones", "txt")],
    "gcps": [("codigo", "Código", "txt"), ("ubicacion", "Ubicación", "txt"), ("este", "Este", "f3"), ("norte", "Norte", "f3"),
             ("altitud", "Altitud", "f2"), ("tipo", "Tipo", "txt"), ("metodo", "Método", "txt"),
             ("precision_m", "Precisión (m)", "f3"), ("usado_ortomosaico", "Usado en el ortomosaico", "sino")],
    "patologias": [("roi", "ROI", "txt"), ("observador", "Obs.", "int"), ("fecha", "Fecha", "txt"), ("codigo", "Código", "txt"),
                   ("presencia", "Presencia", "sino"), ("progresiva_m", "Progresiva (m)", "f2"), ("lado", "Lado", "txt"),
                   ("severidad", "Severidad (F3)", "txt"), ("criterio", "Criterio", "txt"),
                   ("longitud_m", "Longitud (m)", "f2"), ("ancho_prom_mm", "Ancho prom. (mm)", "f2"),
                   ("ancho_max_mm", "Ancho máx. (mm)", "f2"), ("area_m2", "Área (m²)", "f2"),
                   ("profundidad_cm", "Prof. (cm)", "f1"), ("perimetro_m", "Perímetro (m)", "f2"),
                   ("pct_area", "% área", "f1"), ("separacion_m", "Separación (m)", "f2"),
                   ("orientacion_deg", "Orientación (°)", "f1"), ("observaciones", "Observaciones", "txt")],
    "comparacion_tramos": [("tramo", "Tramo", "txt"), ("tipo", "Tipo", "txt"), ("n_rois", "ROI", "int"),
                           ("n_rois_con_tipo", "ROI con el tipo", "int"), ("pct_rois_con_tipo", "% ROI con el tipo", "f1"),
                           ("n_detecciones", "Detecciones", "int"), ("long_media", "Longitud media (m)", "f2"),
                           ("ancho_media", "Ancho medio (mm)", "f1"), ("area_total_m2", "Área total (m²)", "f2"),
                           ("pct_area_afectada", "% área afectada", "f2")],
    # F7: comparación de métodos ('actual' vs 'sun')
    "metodos_metricas": [("metodo", "Método", "txt"), ("tipo", "Tipo", "txt"), ("vp", "VP", "int"), ("fp", "FP", "int"),
                         ("fn", "FN", "int"), ("vn", "VN", "int"), ("sens", "Sensibilidad", "f2"),
                         ("esp", "Especificidad", "f2"), ("prec", "Precisión", "f2"), ("f1", "F1", "f2"),
                         ("concordancia_pct", "Concordancia (%)", "f1"), ("kappa", "Kappa", "f2")],
    "metodos_mcnemar": [("tipo", "Tipo", "txt"), ("n", "Unidades", "int"), ("ambos_aciertan", "Ambos aciertan", "int"),
                        ("solo_a", "Solo A acierta", "int"), ("solo_b", "Solo B acierta", "int"),
                        ("ambos_fallan", "Ambos fallan", "int"), ("prueba", "Prueba", "txt"), ("p", "p", "f3")],
    "metodos_medidas": [("variable", "Variable", "txt"), ("tipo", "Tipo", "txt"), ("n", "Pares", "int"),
                        ("sesgo", "Sesgo (B − A)", "f3"), ("mae", "MAE", "f3"), ("rmse", "RMSE", "f3"),
                        ("loa_inf", "Límite inf.", "f3"), ("loa_sup", "Límite sup.", "f3")],
    "metodos_rendimiento": [("metodo", "Método", "txt"), ("n_ejecuciones", "Ejecuciones", "int"),
                            ("segundos", "Tiempo (s)", "f2"), ("mpx", "Megapíxeles", "f2"),
                            ("s_por_mpx", "s / Mpx", "f2"), ("ram_adicional_max_mb", "RAM adicional máx. (MB)", "f1"),
                            ("ram_pico_max_mb", "RAM pico máx. (MB)", "f1")],
}

TITULOS = {"resumen_tipos": "Resumen por tipo de deterioro",
           "tabla2": "Tabla 2. Grietas lineales (longitudinales y transversales) por ROI",
           "tabla3": "Tabla 3. Piel de cocodrilo por ROI", "tabla4": "Tabla 4. Baches por ROI",
           "detecciones": "Detecciones", "validacion": "Validación por ROI y tipo (VP/FP/FN/VN)",
           "metricas": "Métricas por tipo (IC 95 % de Wilson)", "concordancia": "Concordancia (kappa de Cohen)",
           "medidas": "Error de medidas frente a la Ficha 4", "pares_medidas": "Pares de medidas (campo vs Python)",
           "calidad": "Calidad de imagen por ejecución", "parametros": "Parámetros del motor usados",
           "tramo": "Ficha 1 · Datos del tramo", "vuelos": "Ficha 5 · Vuelo UAV", "condiciones": "Ficha 8 · Condiciones ambientales",
           "gcps": "Ficha 9 · Puntos de control (GCP)", "patologias": "Fichas 2-4 · Patologías, severidad y medidas de campo",
           "comparacion_tramos": "Comparación descriptiva entre tramos",
           "metodos_metricas": "Comparación de métodos · métricas (mismas ROI de prueba)",
           "metodos_mcnemar": "Comparación de métodos · McNemar sobre la presencia (acierto = VP o VN)",
           "metodos_medidas": "Comparación de métodos · diferencias de medidas (B − A)",
           "metodos_rendimiento": "Comparación de métodos · tiempo de cómputo y RAM"}

CAMPOS_TRAMO = (("codigo", "Código"), ("via", "Vía"), ("ruta", "Ruta"), ("ubicacion", "Ubicación"),
                ("progresiva_ini_m", "Progresiva inicial (m)"), ("progresiva_fin_m", "Progresiva final (m)"),
                ("longitud_m", "Longitud (m)"), ("ancho_calzada_m", "Ancho de calzada (m)"),
                ("ancho_berma_m", "Ancho de berma (m)"), ("n_carriles", "N.º de carriles"),
                ("este_ini", "Este inicial"), ("norte_ini", "Norte inicial"), ("este_fin", "Este final"),
                ("norte_fin", "Norte final"), ("observaciones", "Observaciones"))


def _p(m):
    """(valor, inf, sup) de una proporción {'valor','ic95'}."""
    ic = m.get("ic95") or (None, None)
    return m["valor"], ic[0], ic[1]


def filas_tabla(datos, nombre):
    """Filas (dicts) de la tabla `nombre`. Lista vacía si la sección no existe (omitida o sin datos)."""
    v = datos["validacion"]
    if nombre == "resumen_tipos":
        return filas_resumen_tipos(datos)
    if nombre in ("tabla2", "tabla3", "tabla4"):
        return [{**f, "tipo": NOMBRE_TIPO.get(f["tipo"], f["tipo"])}
                for f in datos["tablas"]["tablas"][nombre]] if datos["tablas"] else []
    if nombre == "detecciones":
        return datos["detecciones"]
    if nombre == "validacion":
        return filas_validacion(datos)
    if nombre == "metricas":
        return filas_metricas(datos)
    if nombre == "concordancia":
        return filas_concordancia(datos)
    if nombre in ("medidas", "pares_medidas"):
        return filas_medidas(datos, nombre)
    if nombre == "calidad":
        return datos["ejecuciones"]
    if nombre == "parametros":
        return [{"grupo": g["huella"], "provisional": g["provisional"], "parametro": k, "valor": str(val)}
                for g in datos["parametros"] for k, val in g["valores"].items()]
    if nombre == "tramo":
        return [{"campo": etq, "valor": "" if datos["tramo"].get(k) is None else str(datos["tramo"][k])}
                for k, etq in CAMPOS_TRAMO]
    if nombre in ("vuelos", "condiciones", "gcps"):
        return [{k: (str(x) if hasattr(x, "isoformat") else x) for k, x in f.items()} for f in datos[nombre]]
    if nombre == "patologias":
        return [{k: (str(x) if hasattr(x, "isoformat") else x) for k, x in f.items()} for f in datos["fichas"]["patologias"]]
    if nombre == "comparacion_tramos":
        return filas_comparacion(datos)
    if nombre.startswith("metodos_"):
        return filas_metodos(datos, nombre)
    raise KeyError(nombre)


def filas_resumen_tipos(datos):
    tb = datos["tablas"]
    if not tb:
        return []
    out = []
    for t in TIPOS:
        x = tb["totales"][t]
        det = [d for d in datos["detecciones"] if d["tipo"] == t]
        out.append({"tipo": NOMBRE_TIPO[t], "n": x["n"], "n_registradas": len(det),
                    "fp_excluidas": sum(1 for d in det if not d["incluida_en_conteo"]), "longitud_m": x["longitud_m"],
                    "area_m2": x["area_m2"], "pct_area_afectada": x["pct_area_afectada"],
                    "rois_con_tipo": x["rois_con_tipo"]})
    return out


def filas_validacion(datos):
    out = []
    for f in datos["validacion"]["filas"]:
        res = next(c.upper() for c in ("vp", "fp", "fn", "vn") if f[c])
        out.append({"roi": f["roi_codigo"], "rol": f["rol"], "tipo_campo": f["tipo_campo"], "tipo": f["tipo"],
                    "resultado": res, "vp": f["vp"], "fp": f["fp"], "fn": f["fn"], "vn": f["vn"], "solape": f["solape"],
                    "umbral_solape": f["umbral_solape"], "ejecucion_id": f["ejecucion_id"],
                    "provisional": f["provisional"]})
    return out


def filas_metricas(datos):
    m = datos["validacion"]["metricas"]
    if not m:
        return []
    out = []
    for t in list(TIPOS) + ["global"]:
        x = m["global"] if t == "global" else m["por_tipo"][t]
        s, sl, sh = _p(x["sensibilidad"])
        e, el, eh = _p(x["especificidad"])
        p, pl, ph = _p(x["precision"])
        k = x["kappa"]
        ex = x["exactitud"]["valor"]
        out.append({"tipo": "Todos los tipos" if t == "global" else NOMBRE_TIPO[t], "vp": x["vp"], "fp": x["fp"],
                    "fn": x["fn"], "vn": x["vn"], "sens": s, "sens_lo": sl, "sens_hi": sh, "esp": e, "esp_lo": el,
                    "esp_hi": eh, "prec": p, "prec_lo": pl, "prec_hi": ph, "f1": x["f1"]["valor"],
                    "concordancia_pct": None if ex is None else 100 * ex, "kappa": k["kappa"],
                    "kappa_interp": k["interpretacion"], "kappa_ok": k["concordante"],
                    "unidades": x.get("unidades")})
    return out


def filas_concordancia(datos):
    out = []
    v = datos["validacion"]

    def fila(texto, k):
        ic = k.get("ic95") or (None, None)
        out.append({"comparacion": texto, "n": k["n"], "kappa": k["kappa"], "lo": ic[0], "hi": ic[1],
                    "interp": k["interpretacion"], "ok": k["concordante"]})
    if v["metricas"]:
        fila("Presencia por ROI y tipo: campo vs Python", v["metricas"]["global"]["kappa"])
    if v["concordancia_tipo"]:
        fila("Tipo por ROI: campo vs Python (multiclase)", v["concordancia_tipo"]["kappa"])
    sv = v["concordancia_severidad"] or {}
    if sv.get("observadores"):
        fila("Severidad: observador 1 vs 2 (kappa ponderado)", sv["observadores"])
    if sv.get("python"):
        fila("Severidad: campo vs Python (ORIENTATIVA)", sv["python"])
    return out


def _pv(x, clave):
    return None if not x else x.get(clave)


def filas_medidas(datos, nombre="medidas"):
    ms = datos["validacion"]["medidas"]
    if not ms:
        return []
    if nombre == "pares_medidas":
        return [{"roi": p["roi"], "tipo": NOMBRE_TIPO[p["tipo"]], "variable": p["variable"], "campo": p["campo"],
                 "python": p["python"], "error": p["python"] - p["campo"]} for p in ms["pares"]]
    out = []

    def fila(var, tipo, e):
        pr, sp = e.get("pearson") or {}, e.get("spearman") or {}
        pa = e.get("prueba") or {}
        out.append({"variable": var, "tipo": tipo, "n": e["n"], "sesgo": e["sesgo"], "mae": e["mae"], "rmse": e["rmse"],
                    "pearson": pr.get("r") if isinstance(pr, dict) else None, "pearson_p": pr.get("p") if isinstance(pr, dict) else None,
                    "spearman": sp.get("r", sp.get("rho")) if isinstance(sp, dict) else None,
                    "spearman_p": sp.get("p") if isinstance(sp, dict) else None,
                    "prueba": pa.get("nombre", pa.get("prueba")) if isinstance(pa, dict) else None,
                    "prueba_p": pa.get("p") if isinstance(pa, dict) else None})
    for v, nombre_v, u in VARIABLES:
        e = ms["global"].get(v)
        if e and e["n"]:
            fila(f"{nombre_v} ({u})", "Todos", e)
        for t in TIPOS:
            e = ms["por_tipo"].get(t, {}).get(v)
            if e and e["n"]:
                fila(f"{nombre_v} ({u})", NOMBRE_TIPO[t], e)
    return out


def filas_comparacion(datos):
    comp = datos.get("comparacion")
    if not comp:
        return []
    return [{"tramo": f["tramo"], "tipo": NOMBRE_TIPO[f["tipo"]], "n_rois": f["n_rois"],
             "n_rois_con_tipo": f["n_rois_con_tipo"], "pct_rois_con_tipo": f["pct_rois_con_tipo"],
             "n_detecciones": f["n_detecciones"], "long_media": f["longitud_m"]["media"],
             "ancho_media": f["ancho_mm"]["media"], "area_total_m2": f["area_total_m2"],
             "pct_area_afectada": f["pct_area_afectada"]} for f in comp["filas"]]


def filas_metodos(datos, nombre):
    """Filas de las tablas de la comparación de métodos (vacías si no hay comparación en `datos`)."""
    c = datos.get("comparacion_metodos")
    if not c:
        return []
    a, b = c["metodos"]
    out = []
    if nombre == "metodos_metricas":
        for m in (a, b):
            for t in list(c["tipos"]) + ["global"]:
                x = c["metricas"][m]["global"] if t == "global" else c["metricas"][m]["por_tipo"][t]
                ex = x["exactitud"]["valor"]
                out.append({"metodo": m, "tipo": "Todos los comparables" if t == "global" else NOMBRE_TIPO[t],
                            "vp": x["vp"], "fp": x["fp"], "fn": x["fn"], "vn": x["vn"],
                            "sens": x["sensibilidad"]["valor"], "esp": x["especificidad"]["valor"],
                            "prec": x["precision"]["valor"], "f1": x["f1"]["valor"],
                            "concordancia_pct": None if ex is None else 100 * ex, "kappa": x["kappa"]["kappa"]})
    elif nombre == "metodos_mcnemar":
        for t in ["global"] + list(c["tipos"]):
            x = c["mcnemar"]["global"] if t == "global" else c["mcnemar"]["por_tipo"][t]
            out.append({"tipo": "Todos los comparables" if t == "global" else NOMBRE_TIPO[t], "n": x["n"],
                        "ambos_aciertan": x["ambos_aciertan"], "solo_a": x["solo_a"], "solo_b": x["solo_b"],
                        "ambos_fallan": x["ambos_fallan"], "prueba": x["metodo"] or "sin discordantes", "p": x["p"]})
    elif nombre == "metodos_medidas":
        for v, nom, u in (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²")):
            filas = [("Todos", c["medidas"]["global"][v])] + [
                (NOMBRE_TIPO[t], c["medidas"]["por_tipo"][t][v]) for t in c["tipos"] if v in c["medidas"]["por_tipo"].get(t, {})]
            for etq, e in filas:
                if e["n"]:
                    ba = e.get("bland_altman") or {}
                    out.append({"variable": f"{nom} ({u})", "tipo": etq, "n": e["n"], "sesgo": e["sesgo"], "mae": e["mae"],
                                "rmse": e["rmse"], "loa_inf": ba.get("loa_inf"), "loa_sup": ba.get("loa_sup")})
    elif nombre == "metodos_rendimiento":
        for m in (a, b):
            out.append({"metodo": m, **{k: c["rendimiento"][m][k] for k in
                                        ("n_ejecuciones", "segundos", "mpx", "s_por_mpx", "ram_adicional_max_mb",
                                         "ram_pico_max_mb")}})
    return out


def columnas(datos, nombre):
    """Columnas de la tabla; `medidas` añade las avanzadas solo si está activada la estadística avanzada."""
    cols = list(COLUMNAS[nombre])
    if nombre == "medidas" and datos["meta"]["avanzada"]:
        cols += COLUMNAS["medidas_avanzadas"]
    return cols


def formatear(v, fmt):
    """Texto para PDF/pantalla: n/d para None; decimales según el formato."""
    if v is None or v == "":
        return "n/d" if fmt not in ("txt",) else ""
    if fmt == "sino":
        return "Sí" if v else "No"
    if fmt == "int":
        return str(int(v))
    if fmt in ("f1", "f2", "f3"):
        return f"{float(v):.{int(fmt[1])}f}"
    return str(v)
