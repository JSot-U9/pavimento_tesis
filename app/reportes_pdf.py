"""
reportes_pdf.py
===============
PDF del tramo con reportlab (platypus). Solo lee `datos` (ver logica_reportes): sin BD, apto para hilo de trabajo.

Contenido: portada · 1 datos del tramo (Ficha 1) · 2 vuelo, condiciones y GCP · 3 calidad de imagen · 4 parámetros
usados · 5 resultados de detección (tablas 2-4) · 6 validación y estadística (con las Figure de `graficos`) ·
7 conclusiones (solo cifras calculadas) · 8 advertencias y supuestos. Aviso PROVISIONAL en cabecera y portada si
corresponde. Fuente Helvetica (WinAnsi): los símbolos fuera de ese juego se sustituyen (`_t`).
"""
import io
import logging

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app import graficos
from app.nucleo.estructuras import TIPOS
from app.reportes_tablas import COLUMNAS, TITULOS, columnas, filas_tabla, formatear

log = logging.getLogger("pavimento.reportes")

AZUL = colors.HexColor("#2b6cb0")
ROJO = colors.HexColor("#c53030")
GRIS = colors.HexColor("#5f6b7a")
ZEBRA = colors.HexColor("#f3f5f8")
_SUST = {"≥": ">=", "≤": "<=", "ρ": "rho", "Σ": "suma", "χ": "chi", "−": "-", "→": "->", "✓": "si", "≠": "!=",
         "’": "'", "“": '"', "”": '"', " ": " ", " ": " "}


def _t(texto):
    """Texto seguro para Helvetica/WinAnsi (cp1252) y para el marcado de Paragraph."""
    s = "" if texto is None else str(texto)
    for k, v in _SUST.items():
        s = s.replace(k, v)
    s = s.encode("cp1252", "replace").decode("cp1252")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _estilos():
    b = getSampleStyleSheet()
    return {
        "t": ParagraphStyle("t", parent=b["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_LEFT,
                            textColor=colors.HexColor("#1f2933")),
        "sub": ParagraphStyle("sub", parent=b["Normal"], fontSize=13, leading=17, textColor=GRIS),
        "h1": ParagraphStyle("h1", parent=b["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=18,
                             textColor=AZUL, spaceBefore=10, spaceAfter=6, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=b["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                             textColor=colors.HexColor("#1f2933"), spaceBefore=8, spaceAfter=4, keepWithNext=1),
        "p": ParagraphStyle("p", parent=b["Normal"], fontSize=9.5, leading=13),
        "peq": ParagraphStyle("peq", parent=b["Normal"], fontSize=8, leading=10.5, textColor=GRIS),
        "celda": ParagraphStyle("celda", parent=b["Normal"], fontSize=7.5, leading=9),
        "celdah": ParagraphStyle("celdah", parent=b["Normal"], fontSize=7.5, leading=9, fontName="Helvetica-Bold",
                                 textColor=colors.white),
        "prov": ParagraphStyle("prov", parent=b["Normal"], fontSize=9.5, leading=13, textColor=ROJO,
                               fontName="Helvetica-Bold"),
    }


class _LienzoNumerado(rl_canvas.Canvas):
    """«Página x de y» y cabecera con el tramo y el aviso PROVISIONAL."""
    tramo, provisional = "", False

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._paginas)
        for est in self._paginas:
            self.__dict__.update(est)
            self._decorar(n)
            super().showPage()
        super().save()

    def _decorar(self, n):
        w, h = A4
        if self._pageNumber > 1:
            self.setFont("Helvetica", 8)
            self.setFillColor(GRIS)
            self.drawString(18 * mm, h - 11 * mm, _t(f"Tramo {self.tramo} · Informe de detección de deterioros"))
            if self.provisional:
                self.setFillColor(ROJO)
                self.setFont("Helvetica-Bold", 8)
                self.drawRightString(w - 18 * mm, h - 11 * mm, "PROVISIONAL")
            self.setStrokeColor(colors.HexColor("#d5dae1"))
            self.line(18 * mm, h - 13 * mm, w - 18 * mm, h - 13 * mm)
        self.setFont("Helvetica", 8)
        self.setFillColor(GRIS)
        self.drawRightString(w - 18 * mm, 10 * mm, f"Página {self._pageNumber} de {n}")


def _tabla(datos, nombre, st, anchos=None, claves=None, maxfilas=None, totales=None):
    cols = [c for c in columnas(datos, nombre) if claves is None or c[0] in claves]
    filas = filas_tabla(datos, nombre)
    if maxfilas and len(filas) > maxfilas:
        extra = len(filas) - maxfilas
        filas = filas[:maxfilas]
    else:
        extra = 0
    cab = [Paragraph(_t(c[1]), st["celdah"]) for c in cols]
    cuerpo = [[Paragraph(_t(formatear(f.get(c[0]), c[2])), st["celda"]) for c in cols] for f in filas]
    if totales:
        cuerpo.append([Paragraph(f"<b>{_t(totales.get(c[0], ''))}</b>", st["celda"]) for c in cols])
    ancho_total = A4[0] - 36 * mm
    if anchos is None:
        anchos = [ancho_total / len(cols)] * len(cols)
    else:
        k = ancho_total / sum(anchos)
        anchos = [a * k for a in anchos]
    t = Table([cab] + cuerpo, colWidths=anchos, repeatRows=1)
    est = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dae1")),
           ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    for i in range(2, len(cuerpo) + 1, 2):
        est.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(est))
    out = [KeepTogether([t]) if len(cuerpo) <= 18 else t]
    if extra:
        out.append(Paragraph(_t(f"… y {extra} filas más (ver el Excel)."), st["peq"]))
    return out, len(filas)


def _fig(fig, ancho_mm=170):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="white")
    buf.seek(0)
    w, h = fig.get_size_inches()
    ancho = ancho_mm * mm
    return Image(buf, width=ancho, height=ancho * h / w)


def _kv(pares, st, w1=55 * mm):
    filas = [[Paragraph(f"<b>{_t(k)}</b>", st["celda"]), Paragraph(_t(v), st["celda"])] for k, v in pares
             if v not in (None, "")]
    t = Table(filas, colWidths=[w1, A4[0] - 36 * mm - w1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dae1")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    return t


def _sin_datos(texto, st):
    return Paragraph(_t(texto), st["peq"])


def _fmt(v, nd=2, u=""):
    return "n/d" if v is None else f"{v:.{nd}f}{(' ' + u) if u else ''}"


# ===================================================================================== secciones
def _portada(d, st):
    m, t = d["meta"], d["tramo"]
    el = [Spacer(1, 38 * mm), Paragraph(_t(m["titulo"]), st["t"]), Spacer(1, 6 * mm),
          Paragraph(_t(f"Informe del tramo {m['tramo']}" + (f" · {t['via']}" if t.get("via") else "")), st["sub"])]
    if m["institucion"]:
        el += [Spacer(1, 4 * mm), Paragraph(_t(m["institucion"]), st["sub"])]
    if m["autor"]:
        el.append(Paragraph(_t(f"Autor: {m['autor']}"), st["sub"]))
    el += [Spacer(1, 12 * mm), _kv([("Tramo", m["tramo"]), ("Ubicación", t.get("ubicacion")),
                                    ("Longitud del tramo", None if t.get("longitud_m") is None else f"{t['longitud_m']:.0f} m"),
                                    ("Método de análisis", m["metodo"]),
                                    ("Ejecuciones incluidas", ", ".join(str(i) for i in m["ejecuciones"])),
                                    ("Validación", "incluida (ROI de " + m["rol"] + ")" if m["validado"] else "no incluida"),
                                    ("Generado", m["generado"])], st)]
    if m["provisional"]:
        el += [Spacer(1, 10 * mm), Paragraph("PROVISIONAL: este informe se calculó con parámetros sin calibrar con datos "
                                             "reales. Sus cifras son una prueba del procedimiento, no evidencia final.",
                                             st["prov"])]
    el.append(PageBreak())
    return el


def _s1(d, st):
    t, o, e = d["tramo"], d["ortomosaico"], d["eje"]
    pares = [("Código", t["codigo"]), ("Vía", t.get("via")), ("Ruta", t.get("ruta")), ("Ubicación", t.get("ubicacion")),
             ("Progresivas (m)", None if t.get("progresiva_ini_m") is None else
              f"{t['progresiva_ini_m']:.0f} – {_fmt(t.get('progresiva_fin_m'), 0)}"),
             ("Longitud (m)", _fmt(t.get("longitud_m"), 1)), ("Ancho de calzada (m)", _fmt(t.get("ancho_calzada_m"), 2)),
             ("Ancho de berma (m)", _fmt(t.get("ancho_berma_m"), 2)), ("N.º de carriles", t.get("n_carriles")),
             ("Observaciones", t.get("observaciones"))]
    pares = [(k, v) for k, v in pares if v not in (None, "n/d")]
    ort = [("Archivo", o["ruta"]), ("Resolución (cm/px)", _fmt(o["gsd_cm"], 2)),
           ("Tamaño (px)", f"{o['ancho_px']} × {o['alto_px']}" if o["ancho_px"] else None),
           ("EPSG", o["epsg"]), ("Georreferenciado", "Sí" if o["georreferenciado"] else "No")]
    if e:
        ort.append(("Eje de vía", f"{e['n_vertices']} vértices" + (f", {e['longitud_m']:.1f} m" if e["longitud_m"] else "")))
    return [Paragraph("1. Datos del tramo (Ficha 1)", st["h1"]), _kv(pares, st), Paragraph("Ortomosaico y eje", st["h2"]),
            _kv(ort, st)]


def _s2(d, st):
    el = [Paragraph("2. Vuelo, condiciones ambientales y control terrestre (Fichas 5, 8 y 9)", st["h1"])]
    for nombre, cl, aviso in (("vuelos", ("codigo", "fecha", "dron", "camara", "altura_m", "gsd_cm", "traslape_frontal_pct",
                                          "traslape_lateral_pct", "n_fotos", "n_gcp"), "No hay Ficha 5 registrada."),
                              ("condiciones", ("fecha", "hora", "temperatura_c", "humedad_pct", "cielo", "viento_ms",
                                               "lluvia", "humedad_pavimento", "sombras"), "No hay Ficha 8 registrada."),
                              ("gcps", ("codigo", "este", "norte", "altitud", "tipo", "precision_m", "usado_ortomosaico"),
                               "No hay Ficha 9 (GCP) registrada.")):
        el.append(Paragraph(_t(TITULOS[nombre]), st["h2"]))
        if filas_tabla(d, nombre):
            el += _tabla(d, nombre, st, claves=cl)[0]
        else:
            el.append(_sin_datos(aviso, st))
    g = d["gcp_resumen"]
    if g["n"]:
        el.append(Spacer(1, 2 * mm))
        el.append(Paragraph(_t(f"GCP: {g['n']} registrados, {g['usados']} usados en el ortomosaico; precisión media "
                               f"declarada {_fmt(g['precision_media_m'], 3, 'm')}."), st["peq"]))
    return el


def _s3(d, st):
    el = [Paragraph("3. Calidad de imagen", st["h1"])]
    if not d["ejecuciones"]:
        return el + [_sin_datos("Sin ejecuciones.", st)]
    cl = ("id", "roi", "calidad", "nitidez", "brillo_medio", "fraccion_saturada", "resolucion_cm_px", "cobertura_pct",
          "calzada_util_pct")
    t, n = _tabla(d, "calidad", st, claves=cl, maxfilas=40)
    el += t
    malas = [e for e in d["ejecuciones"] if e["calidad"] and "no" in str(e["calidad"]).lower()]
    if malas:
        el.append(Paragraph(_t(f"{len(malas)} ejecución(es) con calidad de imagen no adecuada: sus resultados deben "
                               f"tomarse con cautela."), st["peq"]))
    return el


def _s4(d, st):
    el = [Paragraph("4. Parámetros utilizados", st["h1"])]
    if d["meta"]["provisional"]:
        el.append(Paragraph("PROVISIONAL: umbrales calibrados solo con imágenes sintéticas; recalibrar con ortomosaicos "
                            "reales antes de usar los resultados como evidencia.", st["prov"]))
    for g in d["parametros"]:
        el.append(Paragraph(_t(f"Conjunto {g['huella']} (versión {g['version']}) · ejecuciones "
                               f"{', '.join(str(i) for i in g['ejecuciones'])}" + (" · PROVISIONAL" if g["provisional"] else
                                                                                   " · calibrado")), st["h2"]))
        items = [f"{k} = {v}" for k, v in g["valores"].items() if k != "version"]
        k3 = 3
        filas = [items[i:i + k3] for i in range(0, len(items), k3)]
        filas = [r + [""] * (k3 - len(r)) for r in filas]
        t = Table([[Paragraph(_t(x), st["celda"]) for x in r] for r in filas],
                  colWidths=[(A4[0] - 36 * mm) / k3] * k3)
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.2, colors.HexColor("#e3e6ea"))]))
        el.append(t)
    return el


def _s5(d, st):
    el = [Paragraph("5. Resultados de la detección (tablas 2 a 4 del capítulo 3.2)", st["h1"])]
    tb = d["tablas"]
    if not tb:
        return el + [_sin_datos("Sección omitida: " + d["secciones_omitidas"].get("tablas_2_4", "sin datos"), st)]
    if d["meta"]["excluye_fp"]:
        el.append(Paragraph(_t("Las detecciones de unidades validadas como falso positivo no entran al conteo; quedan "
                               "registradas en la validación y en el Excel/CSV de detecciones."), st["peq"]))
    el.append(Paragraph(_t(TITULOS["resumen_tipos"]), st["h2"]))
    el += _tabla(d, "resumen_tipos", st)[0]
    tot = {t: tb["totales"][t] for t in TIPOS}
    el += [Spacer(1, 3 * mm), _fig(graficos.fig_conteos(tot, "Detecciones contabilizadas por tipo", d["meta"]["provisional"]), 110)]
    for nombre in ("tabla2", "tabla3", "tabla4"):
        filas = tb["tablas"][nombre]
        bloque = [Paragraph(_t(TITULOS[nombre]), st["h2"])]
        if not filas:
            bloque.append(_sin_datos("Sin detecciones de este tipo.", st))
            el += bloque
            continue
        tot_f = _totales(nombre, tb)
        t, _n = _tabla(d, nombre, st, totales=tot_f, maxfilas=60)
        el += bloque + t
    return el


def _totales(nombre, tb):
    ts = {"tabla2": ("longitudinal", "transversal"), "tabla3": ("piel_cocodrilo",), "tabla4": ("bache",)}[nombre]
    x = [tb["totales"][t] for t in ts]
    return {"roi": "TOTAL", "n": sum(i["n"] for i in x), "longitud_m": f"{sum(i['longitud_m'] for i in x):.2f}",
            "area_m2": f"{sum(i['area_m2'] for i in x):.3f}"}


def _s6(d, st):
    el = [Paragraph("6. Validación y estadística", st["h1"])]
    if not d["meta"]["validado"]:
        return el + [_sin_datos("No hay validación guardada para esta selección; esta sección no se genera.", st)]
    v, prov = d["validacion"], d["meta"]["provisional"]
    if prov:
        el.append(Paragraph("PROVISIONAL: resultados con parámetros sin calibrar con datos reales.", st["prov"]))
    me = v["metricas"]
    if me:
        el.append(Paragraph(_t(TITULOS["metricas"]), st["h2"]))
        cl = ("tipo", "vp", "fp", "fn", "vn", "sens", "esp", "prec", "f1", "concordancia_pct", "kappa", "kappa_ok")
        el += _tabla(d, "metricas", st, claves=cl, anchos=[20, 7, 7, 7, 7, 19, 20, 16, 9, 18, 11, 15])[0]
        el.append(Paragraph(_t("Los intervalos de confianza (Wilson al 95 %) están en el Excel (hoja «Métricas»). "
                               "n < 5: el IC no es fiable."), st["peq"]))
        el += [Spacer(1, 2 * mm), _fig(graficos.fig_metricas_por_tipo(me), 165)]
    ct = v["concordancia_tipo"]
    if ct:
        el += [Paragraph("Concordancia del tipo por ROI", st["h2"]),
               _fig(graficos.fig_matriz_confusion(ct["matriz"], "Tipo: campo vs Python", ct["provisional"]), 105)]
    if filas_tabla(d, "concordancia"):
        el += [Paragraph(_t(TITULOS["concordancia"]), st["h2"]), *_tabla(d, "concordancia", st,
                                                                         claves=("comparacion", "n", "kappa", "interp", "ok"),
                                                                         anchos=[70, 8, 12, 20, 14])[0]]
    ms = v["medidas"]
    if ms and filas_tabla(d, "medidas"):
        el += [Paragraph(_t(TITULOS["medidas"]), st["h2"]),
               *_tabla(d, "medidas", st, claves=("variable", "tipo", "n", "sesgo", "mae", "rmse"))[0]]
        for var, _n, u in (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²")):
            if any(p["variable"] == var for p in ms["pares"]):
                el.append(_fig(graficos.fig_dispersion(ms["pares"], var, u, provisional=prov), 105))
                break
        if d["meta"]["avanzada"]:
            for var, _n, u in (("longitud_m", "Longitud", "m"), ("ancho_mm", "Ancho", "mm"), ("area_m2", "Área", "m²")):
                ba = ms["global"].get(var, {}).get("bland_altman")
                if ba:
                    el.append(_fig(graficos.fig_bland_altman(ba, f"Bland-Altman · {_n}", u, prov), 105))
    elif d["secciones_omitidas"].get("error_de_medidas"):
        el.append(_sin_datos("Error de medidas omitido: " + d["secciones_omitidas"]["error_de_medidas"], st))
    if d["comparacion"] and filas_tabla(d, "comparacion_tramos"):
        el += [Paragraph(_t(TITULOS["comparacion_tramos"] + " (descriptiva, sin inferencia)"), st["h2"]),
               *_tabla(d, "comparacion_tramos", st)[0]]
    return el


def _s7(d, st):
    el = [Paragraph("7. Conclusiones (solo con datos calculados)", st["h1"])]
    for c in d["conclusiones"]:
        el.append(Paragraph("• " + _t(c), st["prov"] if c.startswith("PROVISIONAL") else st["p"]))
        el.append(Spacer(1, 1.5 * mm))
    return el


def _s8(d, st):
    el = [Paragraph("8. Advertencias y supuestos", st["h1"])]
    for a in d["advertencias"]:
        el.append(Paragraph("• " + _t(a), st["p"]))
    sup = ["Unidad de validación = (ROI, tipo): una sola celda VP/FP/FN/VN por unidad; solo cuentan las ROI de prueba.",
           "La referencia de campo es el tipo de la ROI y las fichas de patologías (presencia); la severidad oficial es la "
           "de la ficha de campo, no la orientativa del programa.",
           "Concordancia (%) = (VP + VN) / total × 100.",
           "El tipo dominante de Python por ROI es el de más detecciones; la severidad de una ROI es la peor registrada."]
    el.append(Paragraph("Supuestos de cálculo", st["h2"]))
    el += [Paragraph("• " + _t(x), st["peq"]) for x in sup]
    return el


def escribir_pdf(datos, ruta):
    st = _estilos()
    _LienzoNumerado.tramo, _LienzoNumerado.provisional = datos["meta"]["tramo"], datos["meta"]["provisional"]
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm,
                            bottomMargin=18 * mm, title=_t(f"Informe {datos['meta']['tramo']}"),
                            author=_t(datos["meta"]["autor"] or "pavimento_tesis"),
                            subject="Detección de deterioros en pavimento flexible")
    historia = _portada(datos, st)
    for sec in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8):
        historia += sec(datos, st)
    doc.build(historia, canvasmaker=_LienzoNumerado)
    return ruta
