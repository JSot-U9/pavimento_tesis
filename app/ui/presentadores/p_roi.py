"""
p_roi.py
========
Presentador del panel de ROI: lista, formulario, roles calibración/prueba (`asignar_roles`) e importación
con vista previa (`simular=True`).
"""
from app import logica_importacion, logica_roi
from app.ui.presentadores.base import Resultado, fnum, ftexto, proteger
from app.ui.presentadores.informe import InformeImportacion

COLUMNAS = (("codigo", "ROI", 60), ("tipo_campo", "Tipo", 95), ("rol", "Rol", 85), ("severidad_campo", "Sev.", 55),
            ("progresiva", "Progresiva (m)", 100))
ETIQUETA_ROL = {"calibracion": "calibración", "prueba": "prueba", "sin_asignar": "sin asignar"}


class PresentadorROI:
    def __init__(self, ctx):
        self.ctx = ctx

    def esquema(self):
        return logica_roi.esquema_roi()

    def roles(self):
        campo = next(c for c in self.esquema() if c["nombre"] == "rol")
        return list(campo["opciones"])

    # ---------------------------------------------------------------- lista
    def listar(self, tramo_id, rol=None) -> Resultado:
        if tramo_id is None:
            return Resultado(True, datos=[])
        return proteger(logica_roi.listar_rois, tramo_id, rol=rol or None)

    @staticmethod
    def fila(r: dict):
        prog = ""
        if r.get("progresiva_ini_m") is not None and r.get("progresiva_fin_m") is not None:
            prog = f"{fnum(r['progresiva_ini_m'], 1)} – {fnum(r['progresiva_fin_m'], 1)}"
        return (r["codigo"], ftexto(r.get("tipo_campo")), ETIQUETA_ROL.get(r.get("rol"), ftexto(r.get("rol"))),
                ftexto(r.get("severidad_campo"), "—"), prog)

    @staticmethod
    def region(r: dict):
        return (r["x0"], r["y0"], r["x1"], r["y1"])

    def etiqueta(self, r: dict, gsd_cm=None) -> str:
        s = f"{r['codigo']} · {r.get('tipo_campo')} · {r['x1'] - r['x0']}×{r['y1'] - r['y0']} px"
        if gsd_cm:
            s += f" ({fnum(logica_roi.area_m2(r, gsd_cm), 2)} m²)"
        return s

    # ---------------------------------------------------------------- CRUD
    def crear(self, tramo_id, datos) -> Resultado:
        r = proteger(logica_roi.crear_roi, tramo_id, datos)
        if not r.ok and "" not in r.errores and not (datos.get("tipo_campo") or datos.get("patologia_codigo")) \
                and "tipo_campo" not in r.errores:
            # logica_roi comprueba el tipo en una etapa posterior a los formatos: se informa junto con los demás
            r.errores["tipo_campo"] = "es obligatorio (o indique un código de patología con equivalencia en el motor)"
        if r.ok:
            self.ctx.emitir("rois", tramo_id)
        return r

    def actualizar(self, roi_id, datos) -> Resultado:
        r = proteger(logica_roi.actualizar_roi, roi_id, datos)
        if r.ok:
            self.ctx.emitir("rois", self.ctx.tramo_id)
        return r

    def eliminar(self, roi_id) -> Resultado:
        r = proteger(logica_roi.eliminar_roi, roi_id)
        if r.ok:
            self.ctx.emitir("rois", self.ctx.tramo_id)
        return r

    def region_a_datos(self, region):
        """Rectángulo dibujado en el visor -> campos x0..y1 del formulario."""
        x0, y0, x1, y1 = (int(round(v)) for v in region)
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}

    # ---------------------------------------------------------------- roles
    def asignar_roles(self, tramo_id, proporcion_texto="0.5", semilla_texto="42", reasignar=False) -> Resultado:
        from app.logica_comun import ErrorValidacion

        def _f():
            errores = {}
            try:
                prop = float(str(proporcion_texto).strip().replace(",", "."))
            except ValueError:
                errores["proporcion_calibracion"] = f"'{proporcion_texto}' no es un número"
            try:
                sem = int(str(semilla_texto).strip())
            except ValueError:
                errores["semilla"] = f"'{semilla_texto}' no es un número entero"
            if errores:
                raise ErrorValidacion(errores)
            return logica_roi.asignar_roles(tramo_id, proporcion_calibracion=prop, semilla=sem, reasignar=reasignar)
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("rois", tramo_id)
        return r

    @staticmethod
    def texto_roles(res: dict) -> str:
        lineas = [f"Semilla: {res['semilla']}"]
        for tipo, c in sorted(res["por_tipo"].items()):
            lineas.append(f"  {tipo}: {c['calibracion']} calibración / {c['prueba']} prueba")
        if not res["por_tipo"]:
            lineas.append("  (no había ROI por asignar)")
        for a in res["advertencias"]:
            lineas.append(f"⚠ {a}")
        return "\n".join(lineas)

    def solapes(self, tramo_id) -> Resultado:
        return proteger(logica_roi.rois_solapados, tramo_id)

    @staticmethod
    def texto_solapes(pares) -> str:
        if not pares:
            return "No hay ROI solapadas."
        return "\n".join(f"{p['a']} ({p['roles'][0]}) ↔ {p['b']} ({p['roles'][1]}): {p['fraccion_menor']:.0%} de la menor"
                         for p in pares)

    # ---------------------------------------------------------------- importación
    def importar(self, tramo_id, ruta, opciones: dict, simular: bool) -> Resultado:
        """opciones: sistema ('auto'|'px'|'geo'), si_existe, estricto (bool), capa (texto o ''), epsg (texto o '')."""
        def _f():
            capa = (opciones.get("capa") or "").strip() or None
            epsg_txt = str(opciones.get("epsg") or "").strip()
            epsg = int(epsg_txt) if epsg_txt else None
            estricto = bool(opciones.get("estricto", True))
            rep = logica_importacion.importar_rois(
                tramo_id, ruta, capa=capa, sistema=opciones.get("sistema", "auto"), epsg_archivo=epsg,
                si_existe=opciones.get("si_existe", "error"), estricto=estricto, simular=simular)
            return InformeImportacion.desde_dict("Importar ROI", rep, estricto)
        r = proteger(_f)
        if r.ok and not simular and r.datos.aplicado:
            self.ctx.emitir("rois", tramo_id)
        return r


OPCIONES_IMPORTACION_ROI = (
    ("sistema", "Coordenadas", "opcion", ("auto", "px", "geo"), "auto"),
    ("si_existe", "Si el código ya existe", "opcion", ("error", "omitir", "actualizar"), "error"),
    ("estricto", "Estricto (no importar nada si una fila falla)", "bool", (), True),
    ("capa", "Capa (solo GeoPackage con varias)", "texto", (), ""),
    ("epsg", "EPSG del archivo (si no lo declara)", "texto", (), ""),
)
