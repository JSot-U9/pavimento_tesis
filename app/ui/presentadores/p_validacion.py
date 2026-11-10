"""
p_validacion.py
===============
Presentador de la pestaña Validación: opciones (umbral de solape, tolerancia, referencia), estado de los roles
de ROI y de sus solapes, ejecución de la validación, tabla de unidades (ROI × tipo) y totales por tipo, y
gestión de las geometrías de referencia opcionales. No usa Tk.
"""
from typing import Optional

from app import logica_roi, logica_validacion
from app.nucleo.estructuras import TIPOS
from app.ui.presentadores.base import Resultado, fnum, proteger
from app.ui.presentadores.formularios import datos_a_textos

NOMBRE_TIPO = {"longitudinal": "Longitudinal", "transversal": "Transversal", "piel_cocodrilo": "Piel de cocodrilo",
               "bache": "Bache"}
COLUMNAS_UNIDADES = (("roi", "ROI", 60), ("tipo", "Tipo", 120), ("ref", "Campo", 55), ("det", "Detec.", 50),
                     ("vp", "VP", 36), ("fp", "FP", 36), ("fn", "FN", 36), ("vn", "VN", 36),
                     ("solape", "Solape", 60), ("modo", "Referencia", 80), ("ejec", "Ejec.", 45))
COLUMNAS_TOTALES = (("tipo", "Tipo", 130), ("n", "Unidades", 70), ("vp", "VP", 45), ("fp", "FP", 45),
                    ("fn", "FN", 45), ("vn", "VN", 45))
COLUMNAS_GEOMETRIAS = (("roi", "ROI", 70), ("tipo", "Tipo (campo)", 120), ("n", "Geometrías", 80))


class PresentadorValidacion:
    def __init__(self, ctx):
        self.ctx = ctx
        self.resultado: Optional[dict] = None

    # ---------------------------------------------------------------- formulario
    def esquema(self):
        return logica_validacion.esquema_validacion()

    def textos_iniciales(self):
        r = proteger(logica_validacion.opciones_por_defecto)
        return datos_a_textos(self.esquema(), r.datos or {})

    # ---------------------------------------------------------------- roles y solapes
    def estado_roles(self, tramo_id):
        """{'texto', 'nivel' ('ok'|'aviso'|'error'), 'prueba', 'calibracion', 'solapes'} de los roles del tramo."""
        if tramo_id is None:
            return {"texto": "Elija un tramo.", "nivel": "aviso", "prueba": 0, "calibracion": 0, "solapes": []}
        r = proteger(logica_roi.listar_rois, tramo_id)
        rois = r.datos or []
        n = {k: sum(1 for x in rois if x["rol"] == k) for k in ("prueba", "calibracion", "sin_asignar")}
        sol = (proteger(logica_roi.rois_solapados, tramo_id, True).datos or [])
        txt = (f"ROI de prueba: {n['prueba']} · calibración: {n['calibracion']} · sin asignar: {n['sin_asignar']}. "
               "Solo las de prueba cuentan para la validación final.")
        nivel = "ok"
        if sol:
            nivel = "error"
            txt += ("\nBLOQUEO: hay ROI de calibración solapadas con ROI de prueba ("
                    + "; ".join(f"{s['a']}↔{s['b']}" for s in sol) + "). Corrija los rectángulos o los roles.")
        elif n["prueba"] == 0:
            nivel = "aviso"
            txt += "\nNo hay ROI de prueba: asigne roles en la pestaña Análisis → ROI."
        return {"texto": txt, "nivel": nivel, "prueba": n["prueba"], "calibracion": n["calibracion"], "solapes": sol}

    # ---------------------------------------------------------------- validar
    def ejecutar(self, tramo_id, textos, ejecucion_ids=None) -> Resultado:
        def _f():
            if tramo_id is None:
                from app.logica_comun import ErrorValidacion
                raise ErrorValidacion({"tramo": "elija un tramo"})
            opts = logica_validacion.leer_opciones(textos)
            return logica_validacion.evaluar(tramo_id, ejecucion_ids=ejecucion_ids, **opts)
        r = proteger(_f)
        if r.ok:
            self.resultado = r.datos
            self.ctx.emitir("validacion")
        return r

    def filas_unidades(self):
        if not self.resultado:
            return []
        out = []
        for i, f in enumerate(self.resultado["filas"]):
            out.append((i, (f["roi_codigo"], NOMBRE_TIPO[f["tipo"]], "Sí" if f["ref_presente"] else "No",
                            f["n_detecciones"], f["vp"], f["fp"], f["fn"], f["vn"], fnum(f["solape"], 2),
                            "geometría" if f["modo"] == "geometria" else "presencia", f"#{f['ejecucion_id']}")))
        return out

    def filas_totales(self):
        if not self.resultado:
            return []
        t = self.resultado["totales"]
        return [(k, (NOMBRE_TIPO[k], t[k]["n"], t[k]["vp"], t[k]["fp"], t[k]["fn"], t[k]["vn"])) for k in TIPOS]

    def texto_estado(self):
        r = self.resultado
        if not r:
            return "Sin validación. Elija las opciones y pulse Validar."
        s = (f"Validación guardada · {len(r['ejecuciones'])} ejecución(es) · {len({f['roi_id'] for f in r['filas']})} ROI de "
             f"{r['rol']} · umbral de solape {r['umbral_solape']:g} · tolerancia {r['tolerancia_m']:g} m")
        if r["provisional"]:
            s += "\nPROVISIONAL: parámetros sin calibrar con datos reales."
        return s

    # ---------------------------------------------------------------- geometrías de referencia
    def filas_geometrias(self, tramo_id):
        if tramo_id is None:
            return []
        out = []
        for r in (proteger(logica_roi.listar_rois, tramo_id).datos or []):
            g = proteger(logica_validacion.listar_geometrias_referencia, r["id"]).datos or []
            out.append((r["id"], (r["codigo"], NOMBRE_TIPO.get(r["tipo_campo"], r["tipo_campo"]), len(g))))
        return out

    @staticmethod
    def parsear_puntos(texto):
        """'x,y' por línea (también 'x y' o 'x;y') -> [(x, y)]. Lanza ErrorValidacion con la línea que falla."""
        from app.logica_comun import ErrorValidacion
        pts, malas = [], []
        for n, linea in enumerate((texto or "").splitlines(), 1):
            linea = linea.strip()
            if not linea:
                continue
            partes = linea.replace(";", " ").replace(",", " ").split()
            try:
                if len(partes) != 2:
                    raise ValueError
                pts.append((float(partes[0]), float(partes[1])))
            except ValueError:
                malas.append(str(n))
        if malas:
            raise ErrorValidacion({"puntos_px": "líneas con formato inválido (use «x, y»): " + ", ".join(malas)})
        return pts

    def agregar_geometria(self, roi_id, tipo, texto) -> Resultado:
        def _f():
            return logica_validacion.registrar_geometria_referencia(roi_id, tipo, self.parsear_puntos(texto), "manual")
        return proteger(_f)

    def listar_geometrias(self, roi_id):
        return [(g["id"], (g["tipo"], len(g["puntos_px"]), g.get("origen") or "")) for g in
                (proteger(logica_validacion.listar_geometrias_referencia, roi_id).datos or [])]

    def eliminar_geometria(self, geometria_id) -> Resultado:
        return proteger(logica_validacion.eliminar_geometria_referencia, geometria_id)
