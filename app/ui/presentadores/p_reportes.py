"""
p_reportes.py
=============
Presentador de la pestaña Reportes: (1) reportes PDF/XLSX/CSV del tramo, (2) exportación a QGIS (GPKG/GeoJSON) y
(3) respaldo y restauración de la base de datos. No usa Tk.

Hilos: `recopilar` lee la BD, así que corre en el hilo principal (aquí); solo la ESCRITURA de los archivos (PDF con
gráficos, Excel) va al hilo de `tareas.gestor_de_calculos()`, que recibe `datos` ya calculados (sin BD ni Tk).
"""
import os
from typing import List, Optional

from app import logica_configuracion as cfg, logica_exportacion as lx, logica_reportes as lrep, logica_respaldo as lresp
from app.logica_comun import ErrorValidacion
from app.tareas import Calculo, GestorTareas, gestor_de_calculos
from app.ui.presentadores.base import Resultado, proteger

FORMATOS = (("pdf", "Informe PDF"), ("xlsx", "Libro Excel (una hoja por tabla)"),
            ("csv", "CSV (detecciones y validación)"))
CAPAS = (("detecciones", "Detecciones"), ("roi", "ROI"), ("eje_via", "Eje de vía"))
COLUMNAS_RESPALDOS = (("nombre", "Respaldo", 330), ("fecha", "Fecha", 140), ("tamano", "Tamaño", 80))
NOMBRE_CLAVE = {"pdf": "Informe PDF", "xlsx": "Libro Excel", "csv_detecciones": "CSV de detecciones",
                "csv_validacion": "CSV de validación"}


def _kb(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


class PresentadorReportes:
    def __init__(self, ctx, gestor: Optional[GestorTareas] = None):
        self.ctx = ctx
        self.gestor = gestor or gestor_de_calculos()
        self.datos: Optional[dict] = None
        self.resultado: Optional[dict] = None
        self.progreso = (0.0, "")

    @property
    def ocupado(self):
        return self.gestor.ocupado

    # ================================================================= reportes
    @staticmethod
    def opciones_por_defecto():
        return {"formatos": [f for f, _ in FORMATOS], "excluir_fp": True, "excel_es": False, "titulo": "", "autor": "",
                "institucion": "", "carpeta": ""}

    @staticmethod
    def _validar_opciones(o):
        o = dict(o)
        formatos = [f for f in o.get("formatos", []) if f in lrep.FORMATOS]
        if not formatos:
            raise ErrorValidacion({"formatos": "elija al menos un formato (PDF, Excel o CSV)"})
        o["formatos"] = formatos
        return o

    def _recopilar(self, tramo_id, o):
        if tramo_id is None:
            raise ErrorValidacion({"tramo": "elija un tramo"})
        return lrep.recopilar(tramo_id, excluir_fp=bool(o.get("excluir_fp", True)), titulo=(o.get("titulo") or "").strip() or None,
                              autor=(o.get("autor") or "").strip() or None,
                              institucion=(o.get("institucion") or "").strip() or None)

    def vista_previa(self, tramo_id, o) -> Resultado:
        """Recopila los datos y devuelve el texto de lo que contendrá el reporte (sin escribir archivos)."""
        def _f():
            oo = self._validar_opciones(o)
            d = self._recopilar(tramo_id, oo)
            self.datos = d
            return {"datos": d, "texto": self.texto_previa(d, oo)}
        r = proteger(_f)
        if r.ok:
            r.advertencias = list(r.datos["datos"]["advertencias"][:1]) if r.datos["datos"]["meta"]["provisional"] else []
        return r

    @staticmethod
    def texto_previa(d, o=None) -> str:
        m = d["meta"]
        lineas = [f"Tramo {m['tramo']} · método «{m['metodo']}» · {len(m['ejecuciones'])} ejecución(es): "
                  f"{', '.join(str(i) for i in m['ejecuciones'])}",
                  {"validadas": "Ejecuciones: la última validada de cada ROI de prueba.",
                   "indicadas": "Ejecuciones elegidas.",
                   "ultimas": "Sin validación: se usan las últimas ejecuciones completadas."}[m["origen_ejecuciones"]],
                  f"Detecciones registradas: {len(d['detecciones'])}"
                  + (f" · fuera del conteo por ser falsos positivos: {sum(1 for x in d['detecciones'] if not x['incluida_en_conteo'])}"
                     if m["excluye_fp"] else ""),
                  "Validación y estadística: " + ("incluidas" if m["validado"] else "NO incluidas (no hay validación guardada)"),
                  "Fichas: " + f"{len(d['vuelos'])} vuelo(s), {len(d['condiciones'])} condición(es), {len(d['gcps'])} GCP, "
                  f"{len(d['fichas']['patologias'])} patología(s)"]
        if d["comparacion"]:
            lineas.append("Incluye la comparación descriptiva entre tramos: " + ", ".join(d["comparacion"]["tramos"]))
        return "\n".join(lineas)

    def iniciar(self, tramo_id, o, carpeta) -> Resultado:
        """Recopila (hilo principal) y lanza la escritura de archivos en el hilo de trabajo."""
        if self.gestor.ocupado:
            return Resultado(False, errores={"": "Ya hay un cálculo en curso"}, mensaje="Ya hay un cálculo en curso")

        def _f():
            oo = self._validar_opciones(o)
            if not (carpeta or "").strip():
                raise ErrorValidacion({"carpeta": "elija la carpeta donde guardar los archivos"})
            d = self._recopilar(tramo_id, oo)                       # siempre datos frescos al generar
            self.datos = d
            sep, dec = (";", ",") if oo.get("excel_es") else (",", ".")
            self.gestor.iniciar([Calculo("Reportes", lambda cancelar, progreso, d=d, c=carpeta.strip(), f=tuple(oo["formatos"]):
                                         lrep.escribir_reportes(d, c, f, sep, dec, cancelar, progreso))])
            return d
        r = proteger(_f)
        if r.ok:
            self.resultado = None
            self.progreso = (0.0, "Generando…")
            r.advertencias = list(r.datos["advertencias"][:1]) if r.datos["meta"]["provisional"] else []
        return r

    def cancelar(self):
        self.gestor.cancelar()

    def cerrar(self, timeout=8.0):
        if self.gestor.ocupado:
            self.gestor.cancelar()
            self.gestor.esperar(timeout)
            self.sondear()

    def sondear(self) -> List[tuple]:
        """Eventos: ('progreso', f, texto) ('resultado', dict) ('mensaje', nivel, texto) ('fin',)."""
        ev = []
        for m in self.gestor.sondear():
            if m.tipo == "progreso":
                self.progreso = (m.fraccion, m.texto)
                ev.append(("progreso", m.fraccion, m.texto))
            elif m.tipo == "resultado":
                self.resultado = m.resultado
                ev.append(("resultado", m.resultado))
            elif m.tipo == "cancelado":
                ev.append(("mensaje", "aviso", "Generación cancelada."))
            elif m.tipo == "error":
                ev.append(("mensaje", "error", self._error_amigable(m.texto)))
            elif m.tipo == "fin":
                ev.append(("fin",))
        return ev

    @staticmethod
    def _error_amigable(texto):
        t = texto.lower()
        if "permission" in t:
            return ("No se pudo escribir un archivo: está abierto en otro programa (Excel, visor de PDF) o la carpeta "
                    "no permite escribir.")
        if "reportlab" in t or "openpyxl" in t:
            return "Falta una librería: ejecute «pip install -r requirements.txt»."
        return f"La generación falló: {texto}"

    @staticmethod
    def filas_archivos(res):
        """[(iid, (tipo, archivo, tamaño))] de lo generado; los omitidos van con su motivo."""
        filas = []
        for k, ruta in (res or {}).get("archivos", {}).items():
            filas.append((ruta, (NOMBRE_CLAVE.get(k, k), os.path.basename(ruta), _kb(os.path.getsize(ruta)))))
        for k, motivo in (res or {}).get("omitidos", {}).items():
            filas.append((f"omitido:{k}", (NOMBRE_CLAVE.get(k, k), "NO generado", motivo)))
        return filas

    # ================================================================= exportación a QGIS
    def estado_georreferencia(self, tramo_id) -> str:
        from app import logica_tramos
        if tramo_id is None:
            return "Elija un tramo."
        t = logica_tramos.obtener_tramo(tramo_id)
        if t["transformacion"] and t["epsg"]:
            return f"Ortomosaico georreferenciado (EPSG:{t['epsg']}): las capas se exportan en ese sistema."
        if t["transformacion"]:
            return "Ortomosaico georreferenciado SIN EPSG: asigne el EPSG para poder exportar."
        return ("El ortomosaico no está georreferenciado: solo se puede exportar en coordenadas de imagen (sin CRS), "
                "que QGIS no superpone con otras capas.")

    def exportar(self, tramo_id, destino, formato="gpkg", capas=("detecciones", "roi", "eje_via"), wgs84=False,
                 pixeles=False, solo_conteo=False, sobrescribir=False) -> Resultado:
        def _f():
            if tramo_id is None:
                raise ErrorValidacion({"tramo": "elija un tramo"})
            if not (destino or "").strip():
                raise ErrorValidacion({"destino": "elija el archivo o la carpeta de destino"})
            if not capas:
                raise ErrorValidacion({"capas": "elija al menos una capa"})
            return lx.exportar(tramo_id, destino.strip(), formato, capas=tuple(capas), epsg_salida=4326 if wgs84 else None,
                               permitir_pixeles=pixeles, solo_conteo=solo_conteo, sobrescribir=sobrescribir)
        return proteger(_f)

    @staticmethod
    def texto_exportacion(res) -> str:
        capas = ", ".join(f"{n} ({k})" for n, k in res["capas"].items())
        crs = f"CRS EPSG:{res['epsg']}" if res["epsg"] else "sin CRS (coordenadas de imagen)"
        return f"Exportado y verificado releyendo el archivo · {crs} · capas: {capas}"

    # ================================================================= respaldo
    @property
    def respaldo_automatico(self) -> bool:
        return bool(cfg.obtener("respaldo_automatico"))

    def fijar_respaldo_automatico(self, v: bool):
        cfg.establecer("respaldo_automatico", bool(v))

    def filas_respaldos(self):
        r = proteger(lresp.listar_respaldos)
        return [(x["ruta"], (x["nombre"], x["fecha"], _kb(x["tamano"]))) for x in (r.datos or [])]

    def crear_respaldo(self, destino=None) -> Resultado:
        return proteger(lresp.crear_respaldo, destino or None)

    def verificar(self, ruta) -> Resultado:
        r = proteger(lresp.verificar_respaldo, ruta)
        if r.ok and not r.datos["ok"]:
            return Resultado(False, errores={"": "; ".join(r.datos["problemas"])}, mensaje="; ".join(r.datos["problemas"]),
                             datos=r.datos)
        return r

    def restaurar(self, ruta) -> Resultado:
        """Restaura (la vista pidió confirmación ANTES). Tras reabrir la BD se avisa a todas las pestañas."""
        if self.gestor.ocupado:
            return Resultado(False, errores={"": "Hay un cálculo en curso: espere o cancélelo antes de restaurar."},
                             mensaje="Hay un cálculo en curso")
        r = proteger(lresp.restaurar_respaldo, ruta)
        if r.ok:
            self.ctx.fijar_tramo(None)
            self.ctx.emitir("bd")
        return r
