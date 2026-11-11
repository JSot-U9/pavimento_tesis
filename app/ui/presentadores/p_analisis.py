"""
p_analisis.py
=============
Presentador de la pestaña Análisis: alcance (ROI / ventana / ortomosaico / ROI por rol), método, parámetros
editables (PROVISIONALES), ejecución en segundo plano, resultados y detalle de una detección.

Flujo de hilos (regla del proyecto):
    hilo principal:  preparar_analisis  ->  GestorTareas.iniciar(trabajos)
    hilo de trabajo: logica_deteccion.ejecutar_trabajo (solo núcleo; no toca BD ni Tk)
    hilo principal:  sondear() recibe progreso/resultado  ->  guardar_resultado / registrar_incidencia

No usa Tk: la vista llama a `sondear()` con `after` y pinta los eventos que devuelve.
"""
import dataclasses
from typing import Dict, List, Optional

from app import logica_configuracion, logica_deteccion, logica_roi
from app.logica_comun import ErrorValidacion, vacio
from app.nucleo import pipeline
from app.nucleo.estructuras import COLORES, TIPOS
from app.nucleo.parametros import Params
from app.tareas import GestorTareas
from app.ui.presentadores.base import Resultado, fnum, ftexto, proteger

AVISO_PROVISIONAL = ("PARÁMETROS PROVISIONALES: los umbrales se calibraron solo con imágenes sintéticas. Los "
                     "resultados no son evidencia hasta recalibrarlos con los ortomosaicos reales (Fase 5). "
                     "La severidad del programa es solo orientativa: la oficial es la de la ficha de campo.")

ALCANCES = (("roi", "ROI seleccionada"), ("ventana", "Ventana (rectángulo)"), ("tramo", "Ortomosaico completo"),
            ("rol", "Todas las ROI de un rol"))

NOMBRE_TIPO = {"longitudinal": "Grieta longitudinal", "transversal": "Grieta transversal",
               "piel_cocodrilo": "Piel de cocodrilo", "bache": "Bache"}

COLUMNAS_DET = (("id", "Id", 40), ("tipo", "Tipo", 145), ("progresiva", "Prog. (m)", 85), ("lado", "Lado", 70),
                ("longitud", "Long. (m)", 80), ("ancho", "Ancho", 80), ("area", "Área (m²)", 80),
                ("sev", "Sev. prelim.", 90), ("roi", "ROI", 45))

# Descripción corta (con unidad) de cada parámetro del motor; una prueba exige que no falte ninguno.
DESCRIPCION_PARAMS = {
    "tol_orient_deg": "Tolerancia de orientación longitudinal/transversal (°)",
    "eje_ventana_m": "Tramo del eje para su dirección local (m)",
    "nitidez_min": "Calidad: nitidez mínima (varianza del Laplaciano)",
    "brillo_min": "Calidad: brillo medio mínimo (0-255)",
    "brillo_max": "Calidad: brillo medio máximo (0-255)",
    "saturados_max": "Calidad: fracción máxima de píxeles saturados (0-1)",
    "exg_veg": "Máscara: ExG por encima del cual es vegetación",
    "iluminacion_sigma_m": "Preprocesado: escala del fondo de iluminación (m)",
    "grieta_kernel_m": "Grietas: tamaño del black-hat (m)",
    "grieta_k_mad": "Grietas: umbral = mediana + k·MAD",
    "grieta_contraste_min": "Grietas: umbral mínimo (niveles de gris)",
    "grieta_cierre_m": "Grietas: cierre morfológico (m)",
    "grieta_long_min_m": "Grietas: longitud mínima (m)",
    "grieta_en_cocodrilo": "Grietas: fracción dentro de cocodrilo para excluirlas (0-1)",
    "ancho_semi_perfil_m": "Ancho: largo del perfil de medición (m)",
    "ancho_paso_px": "Ancho: un perfil cada N píxeles del esqueleto",
    "ancho_contraste_min": "Ancho: profundidad mínima del perfil (niveles de gris)",
    "ancho_sigma_px": "Ancho: difuminado a corregir (px; 0 = no corregir)",
    "ancho_suavizado_px": "Ancho: suavizado previo (px)",
    "sev_grieta_baja_mm": "Severidad orientativa: grieta Baja hasta (mm)",
    "sev_grieta_media_mm": "Severidad orientativa: grieta Media hasta (mm)",
    "celda_min_m2": "Cocodrilo: área mínima de celda (m²)",
    "celda_max_m2": "Cocodrilo: área máxima de celda (m²)",
    "celda_union_m": "Cocodrilo: distancia para agrupar celdas (m)",
    "celdas_min": "Cocodrilo: mínimo de celdas por zona",
    "zona_min_m2": "Cocodrilo: área mínima de la zona (m²)",
    "bache_fondo_m": "Bache: escala del fondo local (m)",
    "bache_dL_min": "Bache: diferencia mínima de luminosidad",
    "bache_dC_min": "Bache: diferencia mínima de croma",
    "bache_ancho_min_m": "Bache: ancho mínimo (m)",
    "bache_area_min_m2": "Bache: área mínima (m²)",
    "bache_solidez_min": "Bache: solidez mínima (0-1)",
    "bache_relacion_min": "Bache: relación mínima eje menor/mayor",
    "marca_vial_L": "Bache: luminosidad por encima de la cual es marca vial",
    "sun_alfa": "Sun: T = alfa·kmin + beta (alfa; 0.2247 del código Matlab)",
    "sun_beta": "Sun: T = alfa·kmin + beta (beta, niveles de gris)",
    "sun_contraste_min": "Sun: tope del umbral = media − este contraste (niveles de gris; mejora sobre Sun)",
    "sun_vecinos_superficie": "Sun: manta con vecinos de la imagen (0, Matlab) o de las superficies (1, texto)",
    "sun_cierre_m": "Sun: radio del cierre morfológico (m)",
    "sun_ruido_dist_m": "Sun: distancia de los 8 puntos de la limpieza de ruido (m)",
    "sun_hueco_max_m": "Sun: hueco máximo que se puentea (m)",
    "sun_hueco_lateral_m": "Sun: desviación lateral admitida del puente (m)",
    "sun_componente_min_m": "Sun: tamaño mínimo de un componente del esqueleto (m)",
}
EDITABLES = tuple(f.name for f in dataclasses.fields(Params) if f.name not in ("version", "gsd_cm"))


def _tipo_param(nombre):
    t = next(f.type for f in dataclasses.fields(Params) if f.name == nombre)
    return int if t in (int, "int") else float


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


COLORES_HEX = {t: hex_color(c) for t, c in COLORES.items()}


def normalizar_region(region, ancho, alto, minimo=8):
    """Valida/recorta un rectángulo (x0, y0, x1, y1) al ortomosaico. Lanza ErrorValidacion."""
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in region)
    except (TypeError, ValueError):
        raise ErrorValidacion({"region": "las cuatro coordenadas deben ser números"}) from None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(ancho, x1), min(alto, y1)
    if x1 - x0 < minimo or y1 - y0 < minimo:
        raise ErrorValidacion({"region": f"la ventana debe medir al menos {minimo} px por lado dentro del "
                                         f"ortomosaico ({ancho}×{alto} px)"})
    return (x0, y0, x1, y1)


class PresentadorAnalisis:
    def __init__(self, ctx, gestor: Optional[GestorTareas] = None):
        self.ctx = ctx
        self.gestor = gestor or GestorTareas()
        self.metodo = "actual"
        self._params: Optional[Params] = None          # None = parámetros base
        self.ejecucion: Optional[dict] = None
        self.detecciones: List[dict] = []
        self.resumen: Dict[str, dict] = {}
        self.filtro_tipo: Optional[str] = None
        self.seleccion: Optional[int] = None
        self._trabajos: list = []
        self.progreso = (0.0, "")

    # ---------------------------------------------------------------- método y parámetros
    @staticmethod
    def metodos_disponibles():
        return sorted(pipeline.METODOS)

    def params_actuales(self) -> Params:
        return self._params if self._params is not None else logica_configuracion.params_base()

    def campos_parametros(self):
        """Filas para el diálogo de parámetros: nombre, texto del valor, descripción, si es provisional."""
        p = self.params_actuales()
        prov = set(Params.provisionales())
        return [{"nombre": n, "valor": f"{getattr(p, n):g}", "descripcion": DESCRIPCION_PARAMS.get(n, n),
                 "provisional": n in prov} for n in EDITABLES]

    def validar_parametros(self, textos: Dict[str, str]) -> Resultado:
        """Convierte TODOS los textos y valida; devuelve los errores de todos los campos juntos."""
        def _f():
            errores, cambios = {}, {}
            for n, t in textos.items():
                if n not in EDITABLES:
                    errores[n] = "parámetro no editable"
                    continue
                if vacio(t):
                    errores[n] = "es obligatorio"
                    continue
                try:
                    cambios[n] = _tipo_param(n)(str(t).strip().replace(",", "."))
                except ValueError:
                    errores[n] = f"'{t}' no es " + ("un número entero" if _tipo_param(n) is int else "un número")
            if errores:
                raise ErrorValidacion(errores)
            return self.params_actuales().con(**cambios)          # ValueError con todos los problemas coherentes
        r = proteger(_f)
        if r.ok:
            self._params = r.datos
        return r

    def restablecer_parametros(self):
        self._params = None

    def parametros_modificados(self) -> List[str]:
        if self._params is None:
            return []
        base = logica_configuracion.params_base()
        return [n for n in EDITABLES if getattr(base, n) != getattr(self._params, n)]

    def es_provisional(self) -> bool:
        return logica_configuracion.es_provisional(self.params_actuales(), self.metodo)

    def aviso_provisional(self) -> str:
        return AVISO_PROVISIONAL if self.es_provisional() else ""

    # ---------------------------------------------------------------- construir y lanzar
    @property
    def ocupado(self):
        return self.gestor.ocupado

    def construir_trabajos(self, tramo_id, alcance, roi_id=None, region=None, rol=None, tramo: dict = None):
        """Prepara los Trabajo (hilo principal: lee la BD). Devuelve Resultado(datos=[Trabajo])."""
        def _f():
            if tramo_id is None:
                raise ErrorValidacion({"tramo": "elija un tramo"})
            p = self.params_actuales()
            kw = dict(metodo=self.metodo, params=p)
            if alcance == "roi":
                if roi_id is None:
                    raise ErrorValidacion({"roi": "elija una ROI"})
                return [logica_deteccion.preparar_analisis(tramo_id, roi_id=roi_id, **kw)]
            if alcance == "ventana":
                if not tramo or not tramo.get("ancho_px"):
                    raise ErrorValidacion({"tramo": "el tramo no tiene ortomosaico"})
                reg = normalizar_region(region, tramo["ancho_px"], tramo["alto_px"])
                return [logica_deteccion.preparar_analisis(tramo_id, region=reg, **kw)]
            if alcance == "tramo":
                return [logica_deteccion.preparar_analisis(tramo_id, **kw)]
            if alcance == "rol":
                rois = logica_roi.listar_rois(tramo_id, rol=rol)
                if not rois:
                    raise ErrorValidacion({"rol": f"no hay ROI con rol '{rol}'"})
                return [logica_deteccion.preparar_analisis(tramo_id, roi_id=r["id"], **kw) for r in rois]
            raise ErrorValidacion({"alcance": f"alcance desconocido '{alcance}'"})
        return proteger(_f)

    def iniciar(self, tramo_id, alcance, **kw) -> Resultado:
        if self.gestor.ocupado:
            return Resultado(False, errores={"": "Ya hay un análisis en curso"}, mensaje="Ya hay un análisis en curso")
        r = self.construir_trabajos(tramo_id, alcance, **kw)
        if not r.ok:
            return r
        self._trabajos = list(r.datos)
        self.progreso = (0.0, "Iniciando…")
        return proteger(self._lanzar)

    def _lanzar(self):
        self.gestor.iniciar(self._trabajos)
        return len(self._trabajos)

    def cancelar(self):
        self.gestor.cancelar()

    # ---------------------------------------------------------------- sondeo (la vista lo llama con after)
    def sondear(self) -> List[tuple]:
        """Procesa los mensajes del hilo. TODA escritura en la BD ocurre aquí (hilo principal).
        Devuelve eventos para la vista: ('progreso', f, texto) ('ejecucion', dict) ('mensaje', nivel, texto)
        ('fin',)."""
        eventos = []
        for m in self.gestor.sondear():
            if m.tipo == "inicio":
                self.progreso = ((m.indice - 1) / m.total, f"Analizando {m.trabajo.etiqueta} ({m.indice}/{m.total})…")
                eventos.append(("progreso", *self.progreso))
            elif m.tipo == "progreso":
                f = ((m.indice - 1) + m.fraccion) / max(1, m.total)
                txt = (f"{m.trabajo.etiqueta} ({m.indice}/{m.total}): {m.texto}" if m.total > 1
                       else f"{m.trabajo.etiqueta}: {m.texto}")
                self.progreso = (f, txt)
                eventos.append(("progreso", f, txt))
            elif m.tipo == "resultado":
                r = proteger(logica_deteccion.guardar_resultado, m.trabajo, m.resultado)
                if r.ok:
                    self._fijar_ejecucion(r.datos)
                    eventos.append(("ejecucion", r.datos))
                    adv = list(m.resultado.advertencias) + list(m.resultado.analisis.advertencias)
                    if adv:
                        eventos.append(("mensaje", "aviso", "; ".join(dict.fromkeys(adv))))
                else:
                    proteger(logica_deteccion.registrar_incidencia, m.trabajo, "error", r.mensaje)
                    eventos.append(("mensaje", "error", f"No se pudo guardar el resultado: {r.mensaje}"))
            elif m.tipo == "cancelado":
                proteger(logica_deteccion.registrar_incidencia, m.trabajo, "cancelada", m.texto)
                eventos.append(("mensaje", "aviso", f"Análisis de {m.trabajo.etiqueta} cancelado (queda registrado)."))
                self.ctx.emitir("ejecuciones")
            elif m.tipo == "error":
                proteger(logica_deteccion.registrar_incidencia, m.trabajo, "error", m.texto)
                eventos.append(("mensaje", "error", f"El análisis de {m.trabajo.etiqueta} falló: {m.texto}"))
                self.ctx.emitir("ejecuciones")
            elif m.tipo == "fin":
                self._trabajos = []
                eventos.append(("fin",))
        return eventos

    def cerrar(self, timeout=8.0):
        """Al cerrar la ventana: cancela, espera al hilo y registra la incidencia."""
        if self.gestor.ocupado:
            self.gestor.cancelar()
            self.gestor.esperar(timeout)
            self.sondear()

    # ---------------------------------------------------------------- resultados
    def _fijar_ejecucion(self, e: dict):
        self.ejecucion = e
        self.seleccion = None
        self._cargar_resultados(e["id"])
        self.ctx.emitir("ejecuciones")

    def _cargar_resultados(self, ejecucion_id):
        self.detecciones = logica_deteccion.listar_detecciones(ejecucion_id)
        self.resumen = logica_deteccion.resumen_ejecucion(ejecucion_id)

    def historial(self, tramo_id) -> List[tuple]:
        """[(id, etiqueta)] de las ejecuciones del tramo (la más reciente primero)."""
        if tramo_id is None:
            return []
        r = proteger(logica_deteccion.listar_ejecuciones, tramo_id)
        out = []
        for e in (r.datos or []):
            donde = "tramo" if e["alcance"] == "tramo" else ("ventana" if e["alcance"] == "ventana" else
                                                              f"ROI {e['roi_id']}")
            estado = "" if e["estado"] == "completada" else f" [{e['estado']}]"
            prov = " · provisional" if e.get("provisional") else ""
            out.append((e["id"], f"#{e['id']} {ftexto(e.get('fecha'))[:16]} · {donde} · {e['metodo']}{estado}{prov}"))
        return out

    def cargar_ejecucion(self, ejecucion_id) -> Resultado:
        def _f():
            e = logica_deteccion.obtener_ejecucion(ejecucion_id)
            self.ejecucion = e
            self.seleccion = None
            if e["estado"] == "completada":
                self._cargar_resultados(ejecucion_id)
            else:
                self.detecciones, self.resumen = [], {}
            return e
        return proteger(_f)

    def limpiar(self):
        self.ejecucion, self.detecciones, self.resumen, self.seleccion = None, [], {}, None

    def detecciones_filtradas(self):
        if self.filtro_tipo:
            return [d for d in self.detecciones if d["tipo"] == self.filtro_tipo]
        return list(self.detecciones)

    @staticmethod
    def fila_deteccion(d: dict):
        if d.get("ancho_mm") is not None:
            ancho = f"{d['ancho_mm']:.1f} mm"
        elif d.get("ancho_m") is not None:
            ancho = f"{d['ancho_m']:.2f} m"
        else:
            ancho = "—"
        roi = d.get("roi_id")
        return (d["id"], NOMBRE_TIPO.get(d["tipo"], d["tipo"]), fnum(d.get("progresiva_m"), 1), ftexto(d.get("lado_via")),
                fnum(d.get("longitud_m")), ancho, fnum(d.get("area_m2"), 3), ftexto(d.get("severidad_prelim"), "—"),
                "" if roi is None else str(roi))

    def filas_resumen(self):
        out = []
        for t in TIPOS:
            if t in self.resumen:
                r = self.resumen[t]
                out.append((NOMBRE_TIPO[t], r["n"], fnum(r["longitud_m"]), fnum(r["area_m2"], 3)))
        return out

    def texto_ejecucion(self) -> str:
        e = self.ejecucion
        if e is None:
            return "Sin resultados. Elija un alcance y pulse Analizar."
        if e["estado"] != "completada":
            return f"Ejecución #{e['id']}: {e['estado']}. {ftexto(e.get('mensaje'))}"
        partes = [f"Ejecución #{e['id']} · método {e['metodo']} · {fnum(e['duracion_s'], 1)} s · {e['n_teselas']} teselas · "
                  f"calidad de imagen: {e['calidad']} (nitidez {fnum(e['nitidez'], 1)}, brillo {fnum(e['brillo_medio'], 0)}, "
                  f"cobertura {fnum(e['cobertura_pct'], 0)} %)"]
        if e.get("provisional"):
            partes.append("Parámetros PROVISIONALES.")
        if e.get("advertencias"):
            partes.append("Advertencias: " + e["advertencias"])
        return "\n".join(partes)

    def detalle_deteccion(self, det_id) -> str:
        d = next((x for x in self.detecciones if x["id"] == det_id), None)
        if d is None:
            return ""
        L = [f"{NOMBRE_TIPO.get(d['tipo'], d['tipo'])} · id {d['id']}",
             f"Progresiva: {fnum(d.get('progresiva_m'), 2)} m · lado: {ftexto(d.get('lado_via'), '—')}"]
        if d["tipo"] in ("longitudinal", "transversal"):
            L.append(f"Longitud: {fnum(d.get('longitud_m'), 2)} m")
            L.append("Ancho: " + (f"{d['ancho_mm']:.1f} mm ({d.get('metodo_ancho') or 'método n/d'})"
                                  if d.get("ancho_mm") is not None else "no resoluble"))
            L.append(f"Desviación respecto al eje: {fnum(d.get('desv_eje_deg'), 1)}° · contraste Weber: "
                     f"{fnum(d.get('contraste_weber'), 2)}")
            L.append(f"Ramificada: {ftexto(d.get('ramificada'), '—')}")
        elif d["tipo"] == "piel_cocodrilo":
            L.append(f"Celdas: {ftexto(d.get('n_celdas'), '—')} · celda media: {fnum(d.get('celda_media_m2'), 4)} m²")
            L.append(f"Densidad: {fnum(d.get('densidad_pct'), 1)} % · longitud de grietas: {fnum(d.get('longitud_m'))} m")
        elif d["tipo"] == "bache":
            L.append(f"Longitud: {fnum(d.get('longitud_m'), 2)} m · ancho: {fnum(d.get('ancho_m'), 2)} m · "
                     f"solidez: {fnum(d.get('solidez'), 2)}")
        L.append(f"Área: {fnum(d.get('area_m2'), 3)} m² ({ftexto(d.get('area_px'), '—')} px)")
        if d.get("pct_area_afectada") is not None:
            L.append(f"% del área de la ROI: {fnum(d['pct_area_afectada'], 2)} %")
        L.append(f"Severidad preliminar: {ftexto(d.get('severidad_prelim'), '—')} (ORIENTATIVA; la oficial es la de la ficha)")
        if d.get("advertencia"):
            L.append(f"⚠ {d['advertencia']}")
        return "\n".join(L)

    def para_visor(self):
        """Detecciones (filtradas) como lo necesita el visor."""
        return [{"id": d["id"], "tipo": d["tipo"], "geom_tipo": d.get("geom_tipo"), "geom": d.get("geom_px") or [],
                 "bbox": (d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])} for d in self.detecciones_filtradas()]
