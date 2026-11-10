"""
p_calibracion.py
================
Presentador de la calibración. La búsqueda es LARGA (corre el motor muchas veces), así que va en el hilo de
`tareas.gestor_de_calculos()`; todo lo que lee de la BD se prepara aquí, en el hilo principal
(`logica_calibracion.preparar_calibracion`). Guardar los parámetros calibrados exige confirmación explícita.
"""
from typing import List, Optional

from app import logica_calibracion
from app.logica_comun import ErrorValidacion
from app.tareas import Calculo, GestorTareas, gestor_de_calculos
from app.ui.presentadores.base import Resultado, fnum, proteger

COLUMNAS_PARAMS = (("sel", "Usar", 40), ("nombre", "Parámetro", 160), ("valor", "Valor actual", 90),
                   ("rango", "Límites", 110))
COLUMNAS_CAMBIOS = (("nombre", "Parámetro", 170), ("antes", "Antes", 90), ("despues", "Después", 90))


class PresentadorCalibracion:
    def __init__(self, ctx, gestor: Optional[GestorTareas] = None):
        self.ctx = ctx
        self.gestor = gestor or gestor_de_calculos()
        self.resultado: Optional[dict] = None
        self.progreso = (0.0, "")
        self.seleccion: List[str] = []

    @property
    def ocupado(self):
        return self.gestor.ocupado

    # ---------------------------------------------------------------- parámetros
    def filas_parametros(self):
        r = proteger(logica_calibracion.parametros_calibrables)
        return [(p["nombre"], ("☑" if p["por_defecto"] else "☐", p["nombre"], f"{p['valor']:g}",
                               f"{p['minimo']:g} – {p['maximo']:g}")) for p in (r.datos or [])]

    def seleccion_inicial(self):
        return list(logica_calibracion.PARAMETROS_POR_DEFECTO)

    # ---------------------------------------------------------------- lanzar / cancelar
    def iniciar(self, tramo_id, parametros, objetivo, max_pasadas, max_evaluaciones, solapes="bloquear") -> Resultado:
        if self.gestor.ocupado:
            return Resultado(False, errores={"": "Ya hay un cálculo en curso"}, mensaje="Ya hay un cálculo en curso")

        def _f():
            if tramo_id is None:
                raise ErrorValidacion({"tramo": "elija un tramo"})
            try:
                mp, me = int(str(max_pasadas).strip()), int(str(max_evaluaciones).strip())
            except ValueError:
                raise ErrorValidacion({"max_evaluaciones": "pasadas y evaluaciones deben ser números enteros"}) from None
            plan = logica_calibracion.preparar_calibracion(                      # hilo principal: lee la BD
                tramo_id, parametros=parametros or None, objetivo=objetivo, max_pasadas=mp, max_evaluaciones=me,
                solapes=solapes)
            self.gestor.iniciar([Calculo("Calibración", lambda cancelar, progreso, p=plan:
                                         logica_calibracion.ejecutar_calibracion(p, cancelar, progreso))])
            return plan
        r = proteger(_f)
        if r.ok:
            self.resultado = None
            self.progreso = (0.0, "Calibrando…")
        return r

    def cancelar(self):
        self.gestor.cancelar()

    def cerrar(self, timeout=8.0):
        if self.gestor.ocupado:
            self.gestor.cancelar()
            self.gestor.esperar(timeout)
            self.sondear()

    def sondear(self) -> List[tuple]:
        """Eventos para la vista: ('progreso', f, texto) ('resultado', dict) ('mensaje', nivel, texto) ('fin',)."""
        ev = []
        for m in self.gestor.sondear():
            if m.tipo == "progreso":
                self.progreso = (m.fraccion, m.texto)
                ev.append(("progreso", m.fraccion, m.texto))
            elif m.tipo == "resultado":
                self.resultado = m.resultado
                ev.append(("resultado", m.resultado))
            elif m.tipo == "cancelado":
                ev.append(("mensaje", "aviso", "Calibración cancelada: no se cambió ningún parámetro."))
            elif m.tipo == "error":
                ev.append(("mensaje", "error", f"La calibración falló: {m.texto}"))
            elif m.tipo == "fin":
                ev.append(("fin",))
        return ev

    # ---------------------------------------------------------------- resultado y confirmación
    def filas_cambios(self):
        r = self.resultado
        if not r:
            return []
        return [(n, (n, f"{c['antes']:g}", f"{c['despues']:g}")) for n, c in r["cambios"].items()]

    def texto_antes_despues(self):
        r = self.resultado
        if not r:
            return "Sin calibración."
        a, d = r["antes"], r["despues"]

        def lin(x):
            vp, fp, fn, vn = x["conteos"]
            return (f"VP {vp} · FP {fp} · FN {fn} · VN {vn} · sensibilidad {fnum(x['sensibilidad'])} · "
                    f"precisión {fnum(x['precision'])} · F1 {fnum(x['f1'])} · kappa {fnum(x['kappa'])}")
        return (f"Objetivo: {r['objetivo']} · {r['n_rois']} ROI de calibración ({', '.join(r['rois'])}) · "
                f"{r['evaluaciones']} evaluaciones\nAntes:   {lin(a)}\nDespués: {lin(d)}\n"
                + ("Parámetros sin cambios." if not r["cambios"] else f"{len(r['cambios'])} parámetro(s) cambian."))

    def puede_confirmar(self):
        return bool(self.resultado) and not self.resultado.get("guardado") and not self.gestor.ocupado

    def confirmar(self) -> Resultado:
        """Guarda los Params calibrados como base (calibrado=True). La vista pide confirmación ANTES de llamar."""
        if not self.puede_confirmar():
            return Resultado(False, errores={"": "No hay una calibración pendiente de confirmar"},
                             mensaje="No hay una calibración pendiente de confirmar")
        r = proteger(logica_calibracion.aplicar_calibracion, self.resultado, confirmar=True)
        if r.ok:
            self.resultado["guardado"] = True
            self.ctx.emitir("params")
        return r
