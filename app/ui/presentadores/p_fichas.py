"""
p_fichas.py
===========
Presentador de la pestaña Fichas: vuelos, condiciones ambientales, GCP, catálogo, inspecciones y patologías
(con geometría y severidad). Los formularios se generan desde `esquema_ficha` / `esquema_patologia`.
"""
from app import logica_comun, logica_fichas, logica_importacion, logica_roi
from app.logica_comun import ErrorValidacion
from app.ui.presentadores.base import Resultado, fnum, ftexto, proteger
from app.ui.presentadores.informe import InformeImportacion

TITULOS = {"vuelo": "Vuelos UAV", "condicion": "Condiciones ambientales", "gcp": "Puntos de control (GCP)",
           "catalogo": "Catálogo de patologías", "inspeccion": "Inspecciones"}
FICHAS = tuple(TITULOS)

# columnas visibles por ficha: (campo, encabezado, ancho)
COLUMNAS = {
    "vuelo": (("codigo", "Código", 90), ("fecha", "Fecha", 90), ("dron", "Dron", 110), ("altura_m", "Altura (m)", 80),
              ("gsd_cm", "GSD (cm/px)", 90)),
    "condicion": (("id", "Id", 40), ("vuelo", "Vuelo", 80), ("fecha", "Fecha", 90), ("hora", "Hora", 60),
                  ("temperatura_c", "T (°C)", 60), ("humedad_pct", "HR (%)", 60), ("cielo", "Cielo", 90)),
    "gcp": (("codigo", "Código", 80), ("este", "Este", 100), ("norte", "Norte", 100), ("altitud", "Altitud", 70),
            ("precision_m", "Prec. (m)", 70), ("usado_ortomosaico", "Usado", 60)),
    "catalogo": (("codigo", "Código", 70), ("nombre", "Nombre", 200), ("grupo", "Grupo", 130),
                 ("tipo_motor", "Tipo motor", 100), ("activo", "Activo", 55)),
    "inspeccion": (("id", "Id", 40), ("fecha", "Fecha", 90), ("responsable", "Responsable", 130),
                   ("observador", "Obs.", 45)),
}
COLUMNAS_PATOLOGIA = (("id", "Id", 40), ("codigo", "Código", 70), ("progresiva_m", "Prog. (m)", 75),
                      ("lado", "Lado", 70), ("presencia", "Presencia", 80), ("severidad", "Severidad", 85),
                      ("medida", "Medida", 190))


class PresentadorFichas:
    def __init__(self, ctx):
        self.ctx = ctx
        self._vuelos = {}

    # ---------------------------------------------------------------- fichas genéricas
    def esquema(self, ficha):
        return logica_fichas.esquema_ficha(ficha)

    def necesita_tramo(self, ficha):
        return ficha in logica_fichas.CON_TRAMO

    def listar(self, ficha, tramo_id=None) -> Resultado:
        if self.necesita_tramo(ficha) and tramo_id is None:
            return Resultado(True, datos=[])
        r = proteger(logica_fichas.listar, ficha, tramo_id if self.necesita_tramo(ficha) else None)
        if r.ok and ficha == "condicion":
            self._vuelos = {v["id"]: v["codigo"] for v in (self.listar("vuelo", tramo_id).datos or [])}
        return r

    def fila(self, ficha, d: dict):
        out = []
        for campo, _, _ in COLUMNAS[ficha]:
            if campo == "vuelo":
                out.append(self._vuelos.get(d.get("vuelo_id"), ""))
            elif isinstance(d.get(campo), float):
                out.append(f"{d[campo]:g}")
            else:
                out.append(ftexto(d.get(campo)))
        return tuple(out)

    def crear(self, ficha, datos, tramo_id=None) -> Resultado:
        r = proteger(logica_fichas.crear, ficha, datos, tramo_id if self.necesita_tramo(ficha) else None)
        if r.ok:
            self.ctx.emitir("fichas", ficha)
        return r

    def actualizar(self, ficha, id_, datos) -> Resultado:
        if ficha == "catalogo":                                  # el código no se puede cambiar
            datos = {k: v for k, v in datos.items() if k != "codigo"}
        r = proteger(logica_fichas.actualizar, ficha, id_, datos)
        if r.ok:
            self.ctx.emitir("fichas", ficha)
        return r

    def eliminar(self, ficha, id_) -> Resultado:
        r = proteger(logica_fichas.eliminar, ficha, id_)
        if r.ok:
            self.ctx.emitir("fichas", ficha)
        return r

    def selectores(self, ficha, tramo_id=None):
        """Campos que se eligen de una lista en vez de escribir un id: {campo: [(valor, etiqueta)]}."""
        sel = {}
        if ficha in ("condicion", "gcp") and tramo_id is not None:
            r = proteger(logica_fichas.listar, "vuelo", tramo_id)
            sel["vuelo_id"] = [(v["id"], v["codigo"]) for v in (r.datos or [])] if r.ok else []
        return sel

    def importar(self, ficha, ruta, tramo_id=None, si_existe="error", estricto=True, simular=False) -> Resultado:
        def _f():
            rep = logica_importacion.importar_fichas(ficha, ruta, tramo=tramo_id if self.necesita_tramo(ficha) else None,
                                                     si_existe=si_existe, estricto=estricto, simular=simular)
            return InformeImportacion.desde_dict(f"Importar {TITULOS[ficha].lower()}", rep, estricto)
        r = proteger(_f)
        if r.ok and not simular and r.datos.aplicado:
            self.ctx.emitir("fichas", ficha)
        return r

    # ---------------------------------------------------------------- patologías
    def esquema_patologia(self):
        return logica_fichas.esquema_patologia()

    def selectores_patologia(self, tramo_id):
        sel = {"codigo": [], "roi_id": []}
        cat = proteger(logica_fichas.listar, "catalogo")
        if cat.ok:
            sel["codigo"] = [(c["codigo"], f"{c['codigo']} — {c['nombre']}") for c in cat.datos if c.get("activo")]
        if tramo_id is not None:
            rois = proteger(logica_roi.listar_rois, tramo_id)
            if rois.ok:
                sel["roi_id"] = [(r["id"], r["codigo"]) for r in rois.datos]
        return sel

    def listar_patologias(self, inspeccion_id) -> Resultado:
        if inspeccion_id is None:
            return Resultado(True, datos=[])
        return proteger(logica_fichas.listar_patologias, inspeccion_id=inspeccion_id)

    @staticmethod
    def fila_patologia(p: dict):
        g, s = p.get("geometria") or {}, p.get("severidad") or {}
        medidas = []
        if g.get("area_m2") is not None:
            medidas.append(f"A={fnum(g['area_m2'])} m²")
        if g.get("longitud_m") is not None:
            medidas.append(f"L={fnum(g['longitud_m'])} m")
        if g.get("ancho_prom_mm") is not None:
            medidas.append(f"w={fnum(g['ancho_prom_mm'], 1)} mm")
        if g.get("profundidad_cm") is not None:
            medidas.append(f"h={fnum(g['profundidad_cm'], 1)} cm")
        return (p["id"], p["codigo"], fnum(p.get("progresiva_m"), 1, ""), ftexto(p.get("lado")),
                "Sí" if p.get("presencia") else "No", ftexto(s.get("nivel"), "—"), " · ".join(medidas))

    def _validar_grupos(self, datos, geometria, severidad, parcial=False):
        """Valida a la vez patología, geometría y severidad para mostrar TODOS los errores de formato juntos
        (logica_fichas los valida por etapas y solo informaría los del primer grupo con error)."""
        errores = {}
        for valores, campos in ((datos, logica_fichas.CAMPOS_PATOLOGIA), (_no_vacio(geometria),
                                 logica_fichas.CAMPOS_GEOMETRIA), (_no_vacio(severidad), logica_fichas.CAMPOS_SEVERIDAD)):
            if valores is None and campos is not logica_fichas.CAMPOS_PATOLOGIA:
                continue
            try:
                logica_comun.validar(valores or {}, campos, parcial=parcial)
            except ErrorValidacion as e:
                errores.update(e.errores)
        if errores:
            raise ErrorValidacion(errores)

    def registrar_patologia(self, inspeccion_id, datos, geometria, severidad) -> Resultado:
        def _f():
            self._validar_grupos(datos, geometria, severidad)
            return logica_fichas.registrar_patologia(inspeccion_id, datos, _no_vacio(geometria), _no_vacio(severidad))
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("fichas", "patologia")
        return r

    def actualizar_patologia(self, patologia_id, datos, geometria, severidad) -> Resultado:
        """Combina con lo existente. Si la severidad/geometría se dejó en blanco, se quita (cuando existía)."""
        def _f():
            self._validar_grupos(datos, geometria, severidad, parcial=True)
            actual = logica_fichas.listar_patologias()                # pequeña: una tesis, pocas filas
            p = next((x for x in actual if x["id"] == patologia_id), None)
            res = logica_fichas.actualizar_patologia(patologia_id, datos, _no_vacio(geometria), _no_vacio(severidad))
            if p is not None:
                if p.get("severidad") and not _no_vacio(severidad):
                    logica_fichas.eliminar_severidad(patologia_id)
                if p.get("geometria") and not _no_vacio(geometria):
                    logica_fichas.eliminar_geometria(patologia_id)
            return res
        r = proteger(_f)
        if r.ok:
            self.ctx.emitir("fichas", "patologia")
        return r

    def eliminar_patologia(self, patologia_id) -> Resultado:
        r = proteger(logica_fichas.eliminar_patologia, patologia_id)
        if r.ok:
            self.ctx.emitir("fichas", "patologia")
        return r

    def importar_patologias(self, inspeccion_id, ruta, estricto=True, simular=False) -> Resultado:
        def _f():
            rep = logica_importacion.importar_patologias(inspeccion_id, ruta, estricto=estricto, simular=simular)
            return InformeImportacion.desde_dict("Importar patologías", rep, estricto)
        r = proteger(_f)
        if r.ok and not simular and r.datos.aplicado:
            self.ctx.emitir("fichas", "patologia")
        return r


def _no_vacio(d):
    """dict con solo los valores escritos; None si no hay ninguno (no crear geometría/severidad vacías)."""
    if not d:
        return None
    out = {k: v for k, v in d.items() if v is not None and str(v).strip() != ""}
    return out or None
