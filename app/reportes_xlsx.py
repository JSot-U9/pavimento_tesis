"""
reportes_xlsx.py
================
Libro Excel (openpyxl): UNA TABLA POR HOJA, con título (y aviso PROVISIONAL en rojo), encabezado con filtro,
primera fila inmovilizada, anchos y formatos numéricos. Solo VALORES: no se escribe ninguna fórmula (no hay
referencias que se puedan romper) y todo texto que empiece por = + - @ se guarda como texto literal.
Lee solo `datos` (ver logica_reportes): sin BD.
"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.reportes_tablas import TITULOS, columnas, filas_tabla

AZUL = "2B6CB0"
ROJO = "C53030"
FORMATOS = {"int": "0", "f1": "0.0", "f2": "0.00", "f3": "0.000"}
INVALIDOS = set('[]:*?/\\')
HOJAS = (  # (nombre de hoja, tabla, nota)
    ("Detecciones", "detecciones", "Una fila por detección. «Incluida en el conteo = No» en los falsos positivos "
                                    "(registrados pero fuera de las Tablas 2-4)."),
    ("Resumen por tipo", "resumen_tipos", "N (conteo) excluye los falsos positivos; N registradas los incluye."),
    ("Tabla 2 Grietas", "tabla2", "Grietas longitudinales y transversales por ROI."),
    ("Tabla 3 Piel cocodrilo", "tabla3", "Zonas de piel de cocodrilo por ROI."),
    ("Tabla 4 Baches", "tabla4", "Baches por ROI."),
    ("Validación", "validacion", "Una fila por ROI y tipo; exactamente una de VP/FP/FN/VN vale 1. Solo ROI de prueba."),
    ("Métricas", "metricas", "Intervalos de confianza de Wilson al 95 %. n < 5: IC no fiable. Concordancia (%) = (VP+VN)/total×100."),
    ("Concordancia", "concordancia", "Kappa de Cohen; la severidad de Python es ORIENTATIVA."),
    ("Medidas", "medidas", "Error de Python frente a la Ficha 4 (sesgo = Python − campo)."),
    ("Pares de medidas", "pares_medidas", "Pares usados en el error de medidas."),
    ("Calidad de imagen", "calidad", "Una fila por ejecución."),
    ("Parámetros", "parametros", "Valores exactos del motor usados (reproducibles)."),
    ("Ficha 1 Tramo", "tramo", ""),
    ("Ficha 5 Vuelo", "vuelos", ""),
    ("Ficha 8 Condiciones", "condiciones", ""),
    ("Ficha 9 GCP", "gcps", ""),
    ("Fichas 2-4 Patologías", "patologias", "Severidad oficial (F3) y medidas de campo (F4) por patología."),
    ("Comparación tramos", "comparacion_tramos", "Comparación DESCRIPTIVA entre tramos, sin inferencia estadística."),
)


def _texto(v):
    """Texto a celda: nunca se interpreta como fórmula."""
    return str(v)


def _poner(ws, fila, col, valor, fmt):
    c = ws.cell(row=fila, column=col)
    if valor is None:
        return c
    if isinstance(valor, bool):
        c.value = "Sí" if valor else "No"
    elif isinstance(valor, (int, float)) and fmt != "txt":
        c.value = valor
        c.number_format = FORMATOS.get(fmt, "General")
    elif isinstance(valor, (int, float)):
        c.value = valor
    else:
        c.value = _texto(valor)
        c.data_type = "s"                                     # = + - @ al inicio: texto, no fórmula
    return c


def _hoja(wb, nombre, cols, filas, titulo, nota, provisional):
    ws = wb.create_sheet(nombre[:31])
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=12)
    if provisional:
        ws["A2"] = "PROVISIONAL: parámetros sin calibrar con datos reales; no son evidencia final."
        ws["A2"].font = Font(bold=True, color=ROJO)
    if nota:
        ws["A3"] = nota
        ws["A3"].font = Font(italic=True, color="5F6B7A")
    cab = 5
    borde = Border(bottom=Side(style="thin", color="D5DAE1"))
    for j, (_clave, enc, _f) in enumerate(cols, start=1):
        c = ws.cell(row=cab, column=j, value=enc)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, f in enumerate(filas, start=cab + 1):
        for j, (clave, _enc, fmt) in enumerate(cols, start=1):
            _poner(ws, i, j, f.get(clave), fmt).border = borde
    ultima = cab + max(len(filas), 1)
    ws.auto_filter.ref = f"A{cab}:{get_column_letter(len(cols))}{ultima}"
    ws.freeze_panes = ws.cell(row=cab + 1, column=1)
    for j, (clave, enc, fmt) in enumerate(cols, start=1):
        largo = max([len(enc)] + [len(str(f.get(clave, ""))) for f in filas[:200]])
        ws.column_dimensions[get_column_letter(j)].width = min(max(10, largo + 2), 60)
    ws.row_dimensions[cab].height = 30
    if not filas:
        ws.cell(row=cab + 1, column=1, value="Sin datos").font = Font(italic=True, color="5F6B7A")
    return ws


def _resumen(wb, d):
    ws = wb.active
    ws.title = "Resumen"
    m, t = d["meta"], d["tramo"]
    ws["A1"] = m["titulo"]
    ws["A1"].font = Font(bold=True, size=14)
    fila = 3
    if m["provisional"]:
        ws.cell(row=fila, column=1, value="PROVISIONAL: parámetros sin calibrar con datos reales; "
                                          "no son evidencia final.").font = Font(bold=True, color=ROJO)
        fila += 2
    for k, v in (("Tramo", m["tramo"]), ("Vía", t.get("via")), ("Ubicación", t.get("ubicacion")),
                 ("Método", m["metodo"]), ("Ejecuciones", ", ".join(str(i) for i in m["ejecuciones"])),
                 ("Validación", "incluida" if m["validado"] else "no incluida"),
                 ("Falsos positivos", "excluidos del conteo (registrados)" if m["excluye_fp"] else "incluidos en el conteo"),
                 ("Generado", m["generado"]), ("Autor", m["autor"]), ("Institución", m["institucion"])):
        if v not in (None, ""):
            ws.cell(row=fila, column=1, value=k).font = Font(bold=True)
            _poner(ws, fila, 2, v, "txt")
            fila += 1
    fila += 1
    ws.cell(row=fila, column=1, value="Conclusiones (solo datos calculados)").font = Font(bold=True, size=12)
    fila += 1
    for c in d["conclusiones"]:
        cel = _poner(ws, fila, 1, c, "txt")
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=6)
        ws.row_dimensions[fila].height = 15 * (1 + len(c) // 110)
        if c.startswith("PROVISIONAL"):
            cel.font = Font(bold=True, color=ROJO)
        fila += 1
    fila += 1
    if d["advertencias"]:
        ws.cell(row=fila, column=1, value="Advertencias").font = Font(bold=True, size=12)
        fila += 1
        for a in d["advertencias"]:
            cel = _poner(ws, fila, 1, a, "txt")
            cel.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=6)
            ws.row_dimensions[fila].height = 15 * (1 + len(a) // 110)
            fila += 1
    ws.column_dimensions["A"].width = 24
    for col in "BCDEF":
        ws.column_dimensions[col].width = 24


def escribir_xlsx(datos, ruta):
    wb = Workbook()
    _resumen(wb, datos)
    prov = datos["meta"]["provisional"]
    for nombre, tabla, nota in HOJAS:
        if tabla in ("validacion", "metricas", "concordancia", "medidas", "pares_medidas") and not datos["meta"]["validado"]:
            continue
        if tabla == "comparacion_tramos" and not datos.get("comparacion"):
            continue
        if set(nombre) & INVALIDOS:
            raise ValueError(f"nombre de hoja inválido: {nombre}")
        _hoja(wb, nombre, columnas(datos, tabla), filas_tabla(datos, tabla), TITULOS[tabla], nota, prov)
    wb.properties.title = f"Informe {datos['meta']['tramo']}"
    wb.save(ruta)
    return ruta
