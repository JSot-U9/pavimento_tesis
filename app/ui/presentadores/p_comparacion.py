"""
p_comparacion.py
================
Presentador de la pestaña «Métodos» (F7): compara 'actual' y 'sun' sobre las MISMAS ROI de prueba con los MISMOS Params.
No usa Tk. Reparto de hilos (regla del proyecto: la BD solo se escribe en el hilo principal):

    hilo principal : preparar los Trabajo (lee la BD) -> guardar cada resultado -> validar -> comparar
    hilo de cálculo: solo el núcleo (`logica_deteccion.ejecutar_trabajo`, que no toca BD ni Tk)
"""
from typing import List, Optional

from app import logica_comparacion as lc, logica_configuracion as cfg, logica_deteccion as ld, logica_roi
from app import logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.nucleo import pipeline
from app.tareas import GestorTareas
from app.ui.presentadores.base import Resultado, fnum, proteger

COLUMNAS_METRICAS = (("metodo", "Método", 70), ("tipo", "Tipo", 150), ("vp", "VP", 40), ("fp", "FP", 40), ("fn", "FN", 40),
                     ("vn", "VN", 40), ("sens", "Sensib.", 62), ("esp", "Espec.", 62), ("prec", "Precis.", 62),
                     ("f1", "F1", 55), ("conc", "Concord. %", 80), ("kappa", "Kappa", 55))
COLUMNAS_RENDIMIENTO = (("metodo", "Método", 80), ("n", "Ejecuciones", 80), ("seg", "Tiempo (s)", 80),
                        ("spm", "s / Mpx", 70), ("ram", "RAM adic. máx. (MB)", 130))


class PresentadorComparacion:
    def __init__(self, ctx, gestor: Optional[GestorTareas] = None):
        self.ctx = ctx
        self.gestor = gestor or GestorTareas()
        self.metodo_a, self.metodo_b = "actual", "sun"
        self.comparacion: Optional[dict] = None
        self.progreso = (0.0, "")
        self._trabajos: list = []
        self._ids = {}
        self._fallo = False
        self._tramo = None

    @property
    def ocupado(self):
        return self.gestor.ocupado

    @staticmethod
    def metodos_disponibles():
        return sorted(pipeline.METODOS)

    def fijar_metodos(self, a, b):
        if a == b:
            return Resultado(False, errores={"metodo": "elija dos métodos distintos"}, mensaje="Elija dos métodos distintos")
        self.metodo_a, self.metodo_b = a, b
        self.comparacion = None
        return Resultado()

    # ---------------------------------------------------------------- comparar lo ya validado
    def comparar(self, tramo_id) -> Resultado:
        def _f():
            if tramo_id is None:
                raise ErrorValidacion({"tramo": "elija un tramo"})
            c = lc.comparar_metodos(tramo_id, self.metodo_a, self.metodo_b)
            self.comparacion = c
            return c
        r = proteger(_f)
        if r.ok and r.datos["provisional"]:
            r.advertencias = [lc.AVISO_PROVISIONAL]
        return r

    # ---------------------------------------------------------------- analizar y validar con ambos
    def iniciar(self, tramo_id) -> Resultado:
        if self.gestor.ocupado:
            return Resultado(False, errores={"": "Ya hay un cálculo en curso"}, mensaje="Ya hay un cálculo en curso")

        def _f():
            if tramo_id is None:
                raise ErrorValidacion({"tramo": "elija un tramo"})
            rois = logica_roi.listar_rois(tramo_id, rol="prueba")
            if not rois:
                raise ErrorValidacion({"rois": "el tramo no tiene ROI de rol «prueba» (asigne los roles primero)"})
            base = cfg.params_base()                       # los MISMOS Params para ambos métodos
            trabajos = [ld.preparar_analisis(tramo_id, roi_id=r["id"], metodo=m, params=base, caracteristicas=False)
                        for m in (self.metodo_a, self.metodo_b) for r in rois]
            self._trabajos, self._ids, self._fallo, self._tramo = trabajos, {self.metodo_a: [], self.metodo_b: []}, False, tramo_id
            self.gestor.iniciar(trabajos)
            return len(trabajos)
        r = proteger(_f)
        if r.ok:
            self.progreso = (0.0, "Iniciando…")
        return r

    def cancelar(self):
        self.gestor.cancelar()

    def cerrar(self, timeout=8.0):
        if self.gestor.ocupado:
            self.gestor.cancelar()
            self.gestor.esperar(timeout)
            self.sondear()

    def sondear(self) -> List[tuple]:
        """Eventos: ('progreso', f, texto) ('mensaje', nivel, texto) ('comparacion', dict) ('fin',).
        TODA escritura en la BD (guardar, validar) ocurre aquí, en el hilo principal."""
        ev = []
        for m in self.gestor.sondear():
            if m.tipo in ("inicio", "progreso"):
                base = (m.indice - 1) / max(1, m.total)
                f = base + (m.fraccion / max(1, m.total) if m.tipo == "progreso" else 0.0)
                txt = f"{m.trabajo.metodo} · ROI {m.trabajo.etiqueta} ({m.indice}/{m.total})" + (f": {m.texto}" if m.texto else "")
                self.progreso = (f, txt)
                ev.append(("progreso", f, txt))
            elif m.tipo == "resultado":
                r = proteger(ld.guardar_resultado, m.trabajo, m.resultado)
                if r.ok:
                    self._ids.setdefault(m.trabajo.metodo, []).append(r.datos["id"])
                else:
                    self._fallo = True
                    proteger(ld.registrar_incidencia, m.trabajo, "error", r.mensaje)
                    ev.append(("mensaje", "error", f"No se pudo guardar el resultado de {m.trabajo.etiqueta}: {r.mensaje}"))
            elif m.tipo == "cancelado":
                self._fallo = True
                proteger(ld.registrar_incidencia, m.trabajo, "cancelada", m.texto)
                ev.append(("mensaje", "aviso", "Comparación cancelada (lo ya analizado queda guardado)."))
            elif m.tipo == "error":
                self._fallo = True
                proteger(ld.registrar_incidencia, m.trabajo, "error", m.texto)
                ev.append(("mensaje", "error", f"El análisis de {m.trabajo.etiqueta} ({m.trabajo.metodo}) falló: {m.texto}"))
            elif m.tipo == "fin":
                ev += self._terminar()
                ev.append(("fin",))
        return ev

    def _terminar(self):
        if self._fallo or not all(self._ids.get(m) for m in (self.metodo_a, self.metodo_b)):
            return []
        for met in (self.metodo_a, self.metodo_b):
            r = proteger(lv.evaluar, self._tramo, ejecucion_ids=self._ids[met], rol="prueba", metodo=met)
            if not r.ok:
                return [("mensaje", "error", f"No se pudo validar el método {met}: {r.texto_errores()}")]
        self.ctx.emitir("ejecuciones")
        self.ctx.emitir("validacion")
        r = self.comparar(self._tramo)
        if not r.ok:
            return [("mensaje", "error", r.texto_errores())]
        return [("comparacion", r.datos)]

    # ---------------------------------------------------------------- tablas para la vista
    @staticmethod
    def filas_metricas(c) -> List[tuple]:
        out = []
        for m in c["metodos"]:
            for t in list(c["tipos"]) + ["global"]:
                x = c["metricas"][m]["global"] if t == "global" else c["metricas"][m]["por_tipo"][t]
                ex = x["exactitud"]["valor"]
                out.append((f"{m}|{t}", (m, "todos los comparables" if t == "global" else t, x["vp"], x["fp"], x["fn"], x["vn"],
                                         fnum(x["sensibilidad"]["valor"], 2, "n/d"), fnum(x["especificidad"]["valor"], 2, "n/d"),
                                         fnum(x["precision"]["valor"], 2, "n/d"), fnum(x["f1"]["valor"], 2, "n/d"),
                                         fnum(None if ex is None else 100 * ex, 1, "n/d"), fnum(x["kappa"]["kappa"], 2, "n/d"))))
        return out

    @staticmethod
    def filas_rendimiento(c) -> List[tuple]:
        out = []
        for m in c["metodos"]:
            r = c["rendimiento"][m]
            out.append((m, (m, r["n_ejecuciones"], fnum(r["segundos"], 2, "n/d"), fnum(r["s_por_mpx"], 2, "n/d"),
                            fnum(r["ram_adicional_max_mb"], 0, "n/d"))))
        return out

    @staticmethod
    def texto_conclusiones(c) -> str:
        return "\n".join("• " + t for t in c["conclusiones"])

    @staticmethod
    def texto_advertencias(c) -> str:
        return "\n".join("• " + t for t in c["advertencias"] if not t.startswith("PROVISIONAL"))
