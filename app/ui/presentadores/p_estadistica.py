"""
p_estadistica.py
================
Presentador de la pestaña Estadística: elige el conjunto de ejecuciones validadas (método + parámetros), calcula
todas las secciones con `logica_estadistica` (cada una protegida: si una falla las demás se muestran) y entrega
filas de tabla, textos y objetos `Figure` (de `app.graficos`, reutilizables por el PDF de F6). No usa Tk.
"""
from typing import Dict, Optional

from app import graficos, logica_configuracion as cfg, logica_estadistica as le, logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.nucleo.estructuras import TIPOS
from app.ui.presentadores.base import Resultado, fnum, proteger

NOMBRE_TIPO = graficos.NOMBRE_TIPO
VARIABLES = (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²"))

COLUMNAS_METRICAS = (("tipo", "Tipo", 110), ("vp", "VP", 36), ("fp", "FP", 36), ("fn", "FN", 36), ("vn", "VN", 36),
                     ("sens", "Sensibilidad [IC 95 %]", 150), ("esp", "Especificidad [IC 95 %]", 150),
                     ("prec", "Precisión [IC 95 %]", 150), ("exac", "Exactitud [IC 95 %]", 150),
                     ("f1", "F1", 130), ("conc_pct", "Concordancia (%)", 110), ("kappa", "Kappa", 60),
                     ("conc", "¿≥ umbral?", 70))
COLUMNAS_CONCORDANCIA = (("comp", "Comparación", 230), ("n", "n", 40), ("kappa", "Kappa [IC 95 %]", 150),
                         ("interp", "Interpretación", 100), ("conc", "¿≥ umbral?", 80))
COLUMNAS_MEDIDAS = (("var", "Variable", 90), ("n", "n", 36), ("sesgo", "Sesgo", 70), ("mae", "MAE", 70),
                    ("rmse", "RMSE", 70), ("pearson", "Pearson r (p)", 110), ("spearman", "Spearman ρ (p)", 110),
                    ("shapiro", "Shapiro (p)", 90), ("prueba", "Prueba pareada (p)", 230))
COLUMNAS_TABLAS = {
    "tabla2": (("roi", "ROI", 60), ("tipo", "Tipo", 100), ("n", "N", 36), ("long", "Longitud (m)", 90),
               ("ancho", "Ancho medio (mm)", 110), ("anchomax", "Ancho máx. (mm)", 110), ("area", "Área (m²)", 80),
               ("pct", "% área afectada", 100)),
    "tabla3": (("roi", "ROI", 60), ("n", "Zonas", 50), ("long", "Long. grietas (m)", 110), ("area", "Área (m²)", 80),
               ("pct", "% área afectada", 100), ("dens", "Densidad (%)", 90)),
    "tabla4": (("roi", "ROI", 60), ("n", "Baches", 55), ("long", "Longitud (m)", 90), ("ancho", "Ancho (m)", 80),
               ("area", "Área (m²)", 80), ("pct", "% área afectada", 100)),
}
COLUMNAS_TRAMOS = (("tramo", "Tramo", 70), ("tipo", "Tipo", 110), ("rois", "ROI con el tipo", 100), ("n", "Detec.", 50),
                   ("long", "Longitud m (media; mín–máx; DE)", 210), ("ancho", "Ancho mm (media; mín–máx; DE)", 210),
                   ("area", "Área m² (total)", 90), ("pct", "% área afectada", 100))
COLUMNAS_TOTALES = (("tipo", "Tipo", 130), ("n", "N", 50), ("long", "Longitud (m)", 90), ("area", "Área (m²)", 90),
                    ("pct", "% área afectada", 110), ("rois", "ROI con el tipo", 100))


def _prop(m):
    if m["valor"] is None:
        return "n/d"
    ic = m.get("ic95")
    return f"{m['valor']:.2f}" + (f" [{ic[0]:.2f}–{ic[1]:.2f}]" if ic else "")


def _k(k):
    if k["kappa"] is None:
        return "n/d"
    return f"{k['kappa']:.2f}" + (f" [{k['ic95'][0]:.2f}–{k['ic95'][1]:.2f}]" if k.get("ic95") else "")


def _si_no(v):
    return "—" if v is None else ("Sí" if v else "No")


def _pv(p):
    return "n/d" if p is None else (f"{p:.3f}" if p >= 0.001 else "<0.001")


class PresentadorEstadistica:
    def __init__(self, ctx):
        self.ctx = ctx
        self.grupos = []
        self.grupo: Optional[dict] = None
        self.res: Dict[str, Resultado] = {}
        self.tramo_id = None

    # ---------------------------------------------------------------- estadística avanzada (oculta por defecto)
    # Por decisión del tesista, por ahora solo se muestran las proporciones con IC de Wilson, el kappa y lo descriptivo.
    # McNemar, Bland-Altman, correlaciones, pruebas pareadas y el IC bootstrap del F1 se calculan igual (logica_estadistica)
    # pero la interfaz los oculta salvo que se active «estadistica_avanzada».
    COLUMNAS_AVANZADAS_MEDIDAS = ("pearson", "spearman", "shapiro", "prueba")
    FIGURAS_AVANZADAS = ("ba_longitud_m", "ba_ancho_mm", "ba_area_m2")

    @property
    def avanzada(self) -> bool:
        return bool(cfg.obtener("estadistica_avanzada"))

    def fijar_avanzada(self, valor: bool):
        cfg.establecer("estadistica_avanzada", bool(valor))

    def columnas_medidas(self):
        return [c[0] for c in COLUMNAS_MEDIDAS if self.avanzada or c[0] not in self.COLUMNAS_AVANZADAS_MEDIDAS]

    def figuras_visibles(self):
        return [f for f in self.FIGURAS if self.avanzada or f[0] not in self.FIGURAS_AVANZADAS]

    # ---------------------------------------------------------------- conjuntos validados
    def listar_grupos(self, tramo_id):
        """[(clave, etiqueta)] de los conjuntos de ejecuciones validadas del tramo (más reciente primero)."""
        self.grupos = (proteger(lv.grupos_validados, tramo_id).datos or []) if tramo_id is not None else []
        return [(g["clave"], self.etiqueta_grupo(g)) for g in self.grupos]

    @staticmethod
    def etiqueta_grupo(g):
        return (f"{g['metodo']} · parámetros {g['params_huella']} · {g['n_rois']} ROI de prueba"
                + (" · PROVISIONAL" if g["provisional"] else " · calibrado"))

    def elegir_grupo(self, clave):
        self.grupo = next((g for g in self.grupos if g["clave"] == clave), None)

    # ---------------------------------------------------------------- cálculo
    def calcular(self, tramo_id) -> Resultado:
        """Calcula todas las secciones. Cada una se guarda en `self.res[nombre]` como Resultado."""
        self.tramo_id, self.res = tramo_id, {}
        if tramo_id is None:
            return Resultado(False, errores={"tramo": "elija un tramo"}, mensaje="Elija un tramo")
        if self.grupo is None:
            return Resultado(False, errores={"": "No hay validación guardada: valide primero (pestaña Validación)"},
                             mensaje="No hay validación guardada: valide primero (pestaña Validación)")
        ids = self.grupo["ejecuciones"]
        self.res = {"metricas": proteger(le.metricas_validacion, ids),
                    "tipo": proteger(le.concordancia_tipo, ids, tramo_id),
                    "severidad": proteger(le.concordancia_severidad, ids, tramo_id),
                    "medidas": proteger(le.error_de_medidas, ids, tramo_id),
                    "tablas": proteger(le.tablas_conteo, ids, tramo_id, "prueba")}
        return Resultado(True, datos=self.res, advertencias=self.advertencias())

    def advertencias(self):
        vistas = []
        for k, r in self.res.items():
            if r.ok and isinstance(r.datos, dict):
                for a in r.datos.get("advertencias", []):
                    if a not in vistas:
                        vistas.append(a)
        prov = [a for a in vistas if a.startswith("PROVISIONAL")]
        resto = [a for a in vistas if not a.startswith("PROVISIONAL")]
        return prov[:1] + resto                                  # un solo aviso de PROVISIONAL, primero

    @staticmethod
    def resumen_advertencias(adv, maximo=3):
        """Texto corto para el banner: las primeras líneas (PROVISIONAL siempre) y cuántas más hay."""
        if len(adv) <= maximo:
            return "\n".join(adv)
        return "\n".join(adv[:maximo - 1]) + f"\n… y {len(adv) - maximo + 1} advertencias más (botón «Ver advertencias»)."

    def errores_parciales(self):
        """Secciones que fallaron, con su mensaje (p. ej. 'no hay ficha 4 para esas ROI')."""
        return {k: r.texto_errores() for k, r in self.res.items() if not r.ok}

    def provisional(self):
        return any(r.ok and r.datos.get("provisional") for r in self.res.values())

    def _d(self, nombre):
        r = self.res.get(nombre)
        return r.datos if r is not None and r.ok else None

    # ---------------------------------------------------------------- tablas
    def filas_metricas(self):
        m = self._d("metricas")
        if not m:
            return []
        out = []
        for t in list(TIPOS) + ["global"]:
            x = m["global"] if t == "global" else m["por_tipo"][t]
            k = x["kappa"]
            out.append((t, ("Todos los tipos" if t == "global" else NOMBRE_TIPO[t], x["vp"], x["fp"], x["fn"], x["vn"],
                            _prop(x["sensibilidad"]), _prop(x["especificidad"]), _prop(x["precision"]),
                            _prop(x["exactitud"]),
                            "n/d" if x["f1"]["valor"] is None else f"{x['f1']['valor']:.2f}" + (
                                f" [{x['f1']['ic95'][0]:.2f}–{x['f1']['ic95'][1]:.2f}]"
                                if (x["f1"]["ic95"] and self.avanzada) else ""),
                            "n/d" if x["exactitud"]["valor"] is None else f"{100 * x['exactitud']['valor']:.1f}",
                            fnum(k["kappa"]), _si_no(k["concordante"]))))
        return out

    def filas_concordancia(self):
        out = []
        m, t, s = self._d("metricas"), self._d("tipo"), self._d("severidad")
        if m:
            k = m["global"]["kappa"]
            out.append(("presencia", ("Presencia por ROI y tipo: campo vs Python", k["n"], _k(k),
                                      k["interpretacion"] or "—", _si_no(k["concordante"]))))
        if t:
            k = t["kappa"]
            out.append(("tipo", ("Tipo por ROI: campo vs Python (multiclase)", k["n"], _k(k),
                                 k["interpretacion"] or "—", _si_no(k["concordante"]))))
        if s:
            for clave, texto in (("observadores", "Severidad: observador 1 vs 2 (kappa ponderado)"),
                                 ("python", "Severidad: campo vs Python (ORIENTATIVA)")):
                k = s.get(clave)
                if k:
                    out.append((clave, (texto, k["n"], _k(k), k["interpretacion"] or "—", _si_no(k["concordante"]))))
        return out

    def filas_medidas(self):
        d = self._d("medidas")
        if not d:
            return []
        out = []
        for v, nombre, unidad in VARIABLES:
            e = d["global"][v]
            if e["n"] == 0:
                continue
            p, sp, nm, pr = e["pearson"], e["spearman"], e["normalidad"], e["prueba"]
            out.append((v, (f"{nombre} ({unidad})", e["n"], fnum(e["sesgo"], 3), fnum(e["mae"], 3), fnum(e["rmse"], 3),
                            "n/d" if p is None else f"{p['r']:.2f} ({_pv(p['p'])})",
                            "n/d" if sp is None else f"{sp['rho']:.2f} ({_pv(sp['p'])})",
                            "n/d" if nm is None else _pv(nm["p"]),
                            "n/d" if pr is None else f"{pr['nombre']} ({_pv(pr['p'])})")))
        return out

    def filas_tabla(self, nombre):
        t = self._d("tablas")
        if not t:
            return []
        out = []
        for i, f in enumerate(t["tablas"][nombre]):
            if nombre == "tabla2":
                v = (f["roi"], NOMBRE_TIPO[f["tipo"]], f["n"], fnum(f["longitud_m"]), fnum(f["ancho_medio_mm"], 1),
                     fnum(f["ancho_max_mm"], 1), fnum(f["area_m2"], 3), fnum(f["pct_area_afectada"], 2))
            elif nombre == "tabla3":
                v = (f["roi"], f["n"], fnum(f["longitud_m"]), fnum(f["area_m2"], 3), fnum(f["pct_area_afectada"], 2),
                     fnum(f["densidad_media_pct"], 1))
            else:
                v = (f["roi"], f["n"], fnum(f["longitud_m"]), fnum(f["ancho_medio_m"]), fnum(f["area_m2"], 3),
                     fnum(f["pct_area_afectada"], 2))
            out.append((i, v))
        return out

    def filas_totales(self):
        t = self._d("tablas")
        if not t:
            return []
        return [(k, (NOMBRE_TIPO[k], v["n"], fnum(v["longitud_m"]), fnum(v["area_m2"], 3),
                     fnum(v["pct_area_afectada"], 2), v["rois_con_tipo"])) for k, v in t["totales"].items()]

    # ---------------------------------------------------------------- figuras (Figure de matplotlib)
    FIGURAS = (("metricas", "Métricas por tipo"), ("conteos", "Detecciones por tipo"),
               ("conf_tipo", "Matriz de confusión · tipo"), ("conf_sev_obs", "Severidad · observador 1 vs 2"),
               ("conf_sev_py", "Severidad · campo vs Python"), ("ba_longitud_m", "Bland-Altman · longitud"),
               ("ba_ancho_mm", "Bland-Altman · ancho"), ("ba_area_m2", "Bland-Altman · área"),
               ("disp_longitud_m", "Dispersión · longitud"), ("disp_ancho_mm", "Dispersión · ancho"),
               ("disp_area_m2", "Dispersión · área"))

    def figura(self, clave):
        """Figure para `clave` (ver FIGURAS) o None si faltan datos. No usa pyplot: apta para savefig en el PDF."""
        prov = self.provisional()
        if clave == "metricas":
            m = self._d("metricas")
            return graficos.fig_metricas_por_tipo(m) if m else None
        if clave == "conteos":
            t = self._d("tablas")
            return graficos.fig_conteos(t["totales"], provisional=prov) if t else None
        if clave == "conf_tipo":
            t = self._d("tipo")
            return graficos.fig_matriz_confusion(t["matriz"], "Tipo: campo vs Python", prov) if t else None
        if clave in ("conf_sev_obs", "conf_sev_py"):
            s = self._d("severidad")
            k = None if not s else s.get("observadores" if clave == "conf_sev_obs" else "python")
            if not k:
                return None
            tit = ("Severidad: observador 1 vs 2" if clave == "conf_sev_obs" else
                   "Severidad: campo vs Python (orientativa)")
            return graficos.fig_matriz_confusion(k["matriz"], tit, prov)
        if clave.startswith(("ba_", "disp_")):
            pref, var = clave.split("_", 1)
            d = self._d("medidas")
            if not d:
                return None
            nombre, unidad = next((n, u) for v, n, u in VARIABLES if v == var)
            if pref == "ba":
                return graficos.fig_bland_altman(d["global"][var]["bland_altman"], f"Bland-Altman · {nombre}", unidad, prov)
            return graficos.fig_dispersion(d["pares"], var, unidad, f"{nombre}: Python vs campo", prov)
        return None

    # ---------------------------------------------------------------- comparación descriptiva entre tramos
    def comparar_tramos(self, metodo="actual") -> Resultado:
        r = proteger(le.comparacion_tramos, None, metodo)
        self.tramos = r.datos if r.ok else None
        return r

    @staticmethod
    def _fdesc(x):
        if not x or not x["n"]:
            return "—"
        sd = "n/d" if x["sd"] is None else f"{x['sd']:.2f}"
        return f"{x['media']:.2f}; {x['min']:.2f}–{x['max']:.2f}; {sd}"

    def filas_tramos(self):
        t = getattr(self, "tramos", None)
        if not t:
            return []
        return [(i, (f["tramo"], NOMBRE_TIPO[f["tipo"]], f"{f['n_rois_con_tipo']}/{f['n_rois']}", f["n_detecciones"],
                     self._fdesc(f["longitud_m"]), self._fdesc(f["ancho_mm"]), fnum(f["area_total_m2"], 3),
                     fnum(f["pct_area_afectada"], 2))) for i, f in enumerate(t["filas"])]

    # ---------------------------------------------------------------- comparación de dos conjuntos
    def comparar(self, clave_a, clave_b, tipo=None) -> Resultado:
        def _f():
            a = next((g for g in self.grupos if g["clave"] == clave_a), None)
            b = next((g for g in self.grupos if g["clave"] == clave_b), None)
            if a is None or b is None:
                raise ErrorValidacion({"": "elija dos conjuntos de ejecuciones validadas"})
            if clave_a == clave_b:
                raise ErrorValidacion({"": "elija dos conjuntos distintos"})
            return le.comparar_ejecuciones(a["ejecuciones"], b["ejecuciones"], tipo=tipo)
        return proteger(_f)

    @staticmethod
    def texto_comparacion(c):
        m = c["mcnemar"]
        p = "no calculable (no hay pares discordantes)" if m["p"] is None else f"p = {_pv(m['p'])} ({m['metodo']})"
        s = (f"{c['n_unidades']} unidades (ROI × tipo) en común · ambos aciertan {c['ambos_aciertan']} · solo A {c['solo_a_acierta']}"
             f" · solo B {c['solo_b_acierta']} · ambos fallan {c['ambos_fallan']}\n"
             f"Exactitud A {fnum(c['exactitud_a'])} · B {fnum(c['exactitud_b'])} · McNemar: {p}")
        if c.get("advertencias"):
            s += "\n" + "\n".join(c["advertencias"])
        return s
