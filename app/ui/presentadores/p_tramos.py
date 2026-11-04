"""
p_tramos.py
===========
Presentador de la pestaña Tramos: CRUD de la Ficha 1, ortomosaico asignado y eje de vía.
Solo llama a `logica_tramos` / `logica_importacion` (dicts); no usa Tk.
"""
from app import logica_importacion, logica_tramos
from app.logica_comun import ErrorValidacion, vacio
from app.ui.presentadores.base import Resultado, fnum, ftexto, proteger

COLUMNAS = (("codigo", "Código", 90), ("via", "Vía", 150), ("ubicacion", "Ubicación", 150),
            ("longitud_m", "Long. (m)", 70), ("orto", "Ortomosaico", 85))


NOMBRE_DEPENDENCIA = {"rois": "ROI", "vuelos": "vuelos", "gcps": "GCP", "inspecciones": "inspecciones",
                      "ejecuciones": "ejecuciones de análisis", "ejes": "ejes de vía"}


def leer_real_opcional(texto, campo):
    """'0,5' -> 0.5; '' -> None; otro -> ErrorValidacion con el nombre del campo."""
    if vacio(texto):
        return None
    try:
        return float(str(texto).strip().replace(",", "."))
    except ValueError:
        raise ErrorValidacion({campo: f"'{texto}' no es un número"}) from None


def leer_entero_opcional(texto, campo):
    if vacio(texto):
        return None
    try:
        x = float(str(texto).strip().replace(",", "."))
        if x != int(x):
            raise ValueError
        return int(x)
    except ValueError:
        raise ErrorValidacion({campo: f"'{texto}' no es un número entero"}) from None


class PresentadorTramos:
    def __init__(self, ctx):
        self.ctx = ctx

    def esquema(self):
        return logica_tramos.esquema_tramo()

    # ---------------------------------------------------------------- lista
    def listar(self) -> Resultado:
        return proteger(logica_tramos.listar_tramos)

    @staticmethod
    def fila(t: dict):
        return (t["codigo"], ftexto(t.get("via")), ftexto(t.get("ubicacion")), fnum(t.get("longitud_m"), 1),
                "Sí" if t.get("ortomosaico_ruta") else "No")

    def obtener(self, tramo_id) -> Resultado:
        return proteger(logica_tramos.obtener_tramo, tramo_id)

    # ---------------------------------------------------------------- CRUD
    def guardar(self, datos: dict, tramo_id=None) -> Resultado:
        r = proteger(logica_tramos.actualizar_tramo, tramo_id, datos) if tramo_id is not None \
            else proteger(logica_tramos.crear_tramo, datos)
        if r.ok:
            self.ctx.emitir("tramos")
        return r

    def aviso_borrado(self, tramo_id) -> str:
        """Texto para confirmar el borrado: lo que se perdería junto con el tramo."""
        r = proteger(logica_tramos.resumen_tramo, tramo_id)
        if not r.ok:
            return r.mensaje
        dep = {k: v for k, v in r.datos.items() if v}
        if not dep:
            return "El tramo no tiene datos asociados."
        return "Se eliminarán también: " + ", ".join(f"{NOMBRE_DEPENDENCIA.get(k, k)}: {v}"
                                                      for k, v in dep.items()) + "."

    def eliminar(self, tramo_id, confirmado=False) -> Resultado:
        r = proteger(logica_tramos.eliminar_tramo, tramo_id, confirmar=confirmado)
        if r.ok:
            if self.ctx.tramo_id == tramo_id:
                self.ctx.fijar_tramo(None)
            self.ctx.emitir("tramos")
        return r

    # ---------------------------------------------------------------- ortomosaico
    def asignar_ortomosaico(self, tramo_id, ruta, gsd_texto="", epsg_texto="") -> Resultado:
        def _f():
            if vacio(ruta):
                raise ErrorValidacion({"ruta": "indique el archivo del ortomosaico"})
            gsd = leer_real_opcional(gsd_texto, "gsd_cm")
            epsg = leer_entero_opcional(epsg_texto, "epsg")
            return logica_tramos.asignar_ortomosaico(tramo_id, ruta, gsd_cm=gsd, epsg=epsg)
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("tramos")
            self.ctx.emitir("ortomosaico", tramo_id)
        return r

    @staticmethod
    def info_ortomosaico(t: dict) -> str:
        if not t.get("ortomosaico_ruta"):
            return "Sin ortomosaico asignado."
        geo = "georreferenciado" + (f" (EPSG:{t['epsg']})" if t.get("epsg") else "") if t.get("transformacion") \
            else "sin georreferenciación (solo ROI/eje en píxeles)"
        return (f"{t['ortomosaico_ruta']}\n{t['ancho_px']} × {t['alto_px']} px · {fnum(t['gsd_cm'], 3)} cm/px · "
                f"{geo}")

    # ---------------------------------------------------------------- eje de vía
    def info_eje(self, tramo_id) -> str:
        r = proteger(logica_tramos.obtener_eje, tramo_id)
        if not r.ok:
            return r.mensaje
        e = r.datos
        if e is None:
            return "Sin eje de vía: el análisis asumirá un eje horizontal y lo advertirá."
        return (f"{len(e['vertices_px'])} vértices · origen: {e['origen']} · progresiva inicial "
                f"{fnum(e['progresiva_inicial_m'], 2)} m")

    def importar_eje(self, tramo_id, ruta, sistema="auto", progresiva_texto="") -> Resultado:
        def _f():
            if vacio(ruta):
                raise ErrorValidacion({"ruta": "indique el archivo del eje"})
            prog = leer_real_opcional(progresiva_texto, "progresiva_inicial_m")
            return logica_importacion.importar_eje(tramo_id, ruta, sistema=sistema, progresiva_inicial_m=prog)
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("eje", tramo_id)
        return r

    def guardar_eje_px(self, tramo_id, vertices, progresiva_texto="") -> Resultado:
        """Eje dibujado en el visor (vértices en píxeles)."""
        def _f():
            prog = leer_real_opcional(progresiva_texto, "progresiva_inicial_m")
            return logica_tramos.definir_eje(tramo_id, vertices, sistema="px", progresiva_inicial_m=prog,
                                             origen="manual")
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("eje", tramo_id)
        return r

    def eje(self, tramo_id):
        r = proteger(logica_tramos.obtener_eje, tramo_id)
        return r.datos if r.ok else None
