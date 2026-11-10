"""
graficos.py
===========
Gráficos de la validación y la estadística como objetos `matplotlib.figure.Figure` (SIN pyplot ni backend
de pantalla). Los embebe la UI (`FigureCanvasTkAgg`) y los reutilizará el PDF de la Fase 6
(`fig.savefig(...)`). Cada función recibe los dicts que devuelven `logica_estadistica` / `logica_calibracion`.

Convenciones visuales: fondo blanco, un solo eje de lectura, rótulos directos (sin leyendas lejanas), colores
de tipo = los de las detecciones (`nucleo.estructuras.COLORES`), una sola tonalidad para métricas, y texto
"PROVISIONAL" en el pie de toda figura calculada con parámetros sin calibrar.
"""
from typing import Optional

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from app.nucleo.estructuras import COLORES, TIPOS

NOMBRE_TIPO = {"longitudinal": "Longitudinal", "transversal": "Transversal", "piel_cocodrilo": "Piel de cocodrilo",
               "bache": "Bache", "sano": "Sano"}
TINTA, SUAVE, REJILLA = "#1f2933", "#5f6b7a", "#e3e6ea"
AZUL, AZUL_CLARO, ROJO = "#2b6cb0", "#a9c6e8", "#c53030"
METRICAS = (("sensibilidad", "Sensibilidad"), ("especificidad", "Especificidad"), ("precision", "Precisión"),
            ("f1", "F1"))


def _hex(t):
    return "#%02x%02x%02x" % COLORES[t]


def _figura(ancho=6.4, alto=4.2, titulo="", provisional=False, subtitulo=""):
    fig = Figure(figsize=(ancho, alto), dpi=100, facecolor="white")
    if titulo:
        fig.suptitle(titulo, x=0.02, ha="left", fontsize=11, fontweight="bold", color=TINTA)
    if subtitulo:
        fig.text(0.02, 0.925, subtitulo, fontsize=8, color=SUAVE, ha="left")
    if provisional:
        fig.text(0.98, 0.012, "PROVISIONAL · parámetros sin calibrar con datos reales", fontsize=7.5, color=ROJO,
                 ha="right", va="bottom")
    return fig


def _ejes(fig, rect=(0.11, 0.17, 0.86, 0.68)):
    ax = fig.add_axes(rect)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#9aa5b1")
    ax.tick_params(colors=SUAVE, labelsize=8)
    ax.set_facecolor("white")
    return ax


def _vacia(fig, texto):
    fig.text(0.5, 0.5, texto, ha="center", va="center", fontsize=10, color=SUAVE)
    return fig


# ===================================================================================== validación
def fig_metricas_por_tipo(metricas: dict, titulo="Métricas por tipo (IC 95 % de Wilson)") -> Figure:
    """Barras agrupadas sensibilidad / especificidad / precisión / F1 por tipo, con IC. Valor None = sin barra ('n/d')."""
    fig = _figura(7.2, 4.2, titulo, metricas.get("provisional", False))
    ax = _ejes(fig, (0.09, 0.2, 0.89, 0.64))
    tipos = [t for t in TIPOS if t in metricas["por_tipo"]]
    if not tipos:
        return _vacia(fig, "Sin datos de validación")
    ancho = 0.2
    tonos = [AZUL, "#4a8bc9", AZUL_CLARO, "#7a8794"]
    for j, (clave, nombre) in enumerate(METRICAS):
        for i, t in enumerate(tipos):
            m = metricas["por_tipo"][t][clave]
            x = i + (j - 1.5) * ancho
            if m["valor"] is None:
                ax.text(x, 0.02, "n/d", ha="center", va="bottom", fontsize=7, color=SUAVE, rotation=90)
                continue
            ax.bar(x, m["valor"], ancho * 0.92, color=tonos[j])
            if m.get("ic95"):
                ax.vlines(x, m["ic95"][0], m["ic95"][1], color=TINTA, lw=1)
    ax.set_xticks(range(len(tipos)), [NOMBRE_TIPO[t] for t in tipos])
    ax.set_ylim(0, 1.08)
    ax.yaxis.grid(True, color=REJILLA)
    ax.set_axisbelow(True)
    # leyenda con proxies: no depende de que la primera barra de cada métrica exista (si es n/d no habría etiqueta)
    ax.legend(handles=[Patch(color=tonos[j], label=nombre) for j, (_, nombre) in enumerate(METRICAS)],
              loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=4, frameon=False, fontsize=8)
    return fig


def fig_matriz_confusion(mc: dict, titulo="Matriz de confusión", provisional=False, normalizar=False) -> Figure:
    """Matriz [referencia (filas) × predicción (columnas)] con el conteo en cada celda."""
    fig = _figura(5.6, 4.6, titulo, provisional)
    et, m = mc["etiquetas"], np.asarray(mc["matriz"], float)
    if m.size == 0 or m.sum() == 0:
        return _vacia(fig, "Sin casos")
    ax = fig.add_axes((0.24, 0.2, 0.62, 0.62))
    datos = m / np.maximum(m.sum(1, keepdims=True), 1) if normalizar else m
    ax.imshow(datos, cmap="Blues", vmin=0, vmax=max(datos.max(), 1e-9))
    for i in range(len(et)):
        for j in range(len(et)):
            v = int(m[i, j])
            ax.text(j, i, str(v), ha="center", va="center", fontsize=10,
                    color="white" if datos[i, j] > 0.55 * datos.max() else TINTA,
                    fontweight="bold" if i == j else "normal")
    nombres = [NOMBRE_TIPO.get(e, str(e)) for e in et]
    ax.set_xticks(range(len(et)), nombres, rotation=30, ha="right", fontsize=8, color=SUAVE)
    ax.set_yticks(range(len(et)), nombres, fontsize=8, color=SUAVE)
    ax.set_xlabel("Python (predicción)", fontsize=8.5, color=SUAVE)
    ax.set_ylabel("Campo (referencia)", fontsize=8.5, color=SUAVE)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    return fig


# ===================================================================================== medidas
def fig_bland_altman(ba: Optional[dict], titulo="Bland-Altman", unidad="", provisional=False) -> Figure:
    """Diferencia (Python − campo) frente a la media de ambos, con sesgo y límites de acuerdo 95 %."""
    fig = _figura(6.0, 4.2, titulo, provisional)
    if not ba:
        return _vacia(fig, "Se necesitan al menos 3 pares de medidas")
    ax = _ejes(fig, (0.12, 0.17, 0.84, 0.68))
    ax.scatter(ba["medias"], ba["diferencias"], s=26, color=AZUL, alpha=0.85, zorder=3)
    for y, txt, c, est in ((ba["sesgo"], f"sesgo {ba['sesgo']:.3g}", TINTA, "-"),
                           (ba["loa_sup"], f"+1.96 DE {ba['loa_sup']:.3g}", ROJO, "--"),
                           (ba["loa_inf"], f"−1.96 DE {ba['loa_inf']:.3g}", ROJO, "--")):
        ax.axhline(y, color=c, lw=1.1, ls=est)
        ax.text(1.0, y, txt, transform=ax.get_yaxis_transform(), ha="right", va="bottom", fontsize=8, color=c)
    ax.set_xlabel(f"Media de campo y Python {('(' + unidad + ')') if unidad else ''}", fontsize=8.5, color=SUAVE)
    ax.set_ylabel(f"Python − campo {('(' + unidad + ')') if unidad else ''}", fontsize=8.5, color=SUAVE)
    ax.yaxis.grid(True, color=REJILLA)
    ax.set_axisbelow(True)
    return fig


def fig_dispersion(pares: list, variable: str, unidad="", titulo=None, provisional=False) -> Figure:
    """Python vs campo (un punto por ROI y tipo) con la recta y = x. `pares` = lista de dicts de error_de_medidas."""
    fig = _figura(5.6, 4.4, titulo or f"{variable}: Python vs campo", provisional)
    sel = [p for p in pares if p["variable"] == variable]
    if not sel:
        return _vacia(fig, "Sin pares de medidas")
    ax = _ejes(fig, (0.13, 0.17, 0.82, 0.68))
    for t in TIPOS:
        s = [p for p in sel if p["tipo"] == t]
        if s:
            ax.scatter([p["campo"] for p in s], [p["python"] for p in s], s=30, color=_hex(t), label=NOMBRE_TIPO[t], zorder=3)
    lim = max(max(p["campo"], p["python"]) for p in sel) * 1.08 or 1.0
    ax.plot([0, lim], [0, lim], color="#9aa5b1", lw=1, ls="--", zorder=1)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel(f"Campo (Ficha 4) {('(' + unidad + ')') if unidad else ''}", fontsize=8.5, color=SUAVE)
    ax.set_ylabel(f"Python {('(' + unidad + ')') if unidad else ''}", fontsize=8.5, color=SUAVE)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    return fig


# ===================================================================================== conteos y calibración
def fig_conteos(totales: dict, titulo="Detecciones por tipo", provisional=False) -> Figure:
    """Número de detecciones por tipo (color del tipo), con el valor sobre cada barra."""
    fig = _figura(5.6, 3.8, titulo, provisional)
    ax = _ejes(fig, (0.1, 0.2, 0.86, 0.62))
    xs = list(range(len(TIPOS)))
    vals = [totales.get(t, {}).get("n", 0) for t in TIPOS]
    ax.bar(xs, vals, 0.62, color=[_hex(t) for t in TIPOS])
    for x, v in zip(xs, vals):
        ax.text(x, v, str(v), ha="center", va="bottom", fontsize=9, color=TINTA)
    ax.set_xticks(xs, [NOMBRE_TIPO[t] for t in TIPOS])
    ax.set_ylim(0, max(vals + [1]) * 1.15)
    ax.yaxis.grid(True, color=REJILLA)
    ax.set_axisbelow(True)
    return fig


def fig_calibracion(res: dict, titulo="Calibración: antes y después") -> Figure:
    """Sensibilidad, precisión y F1 con los parámetros anteriores y con los calibrados (ROI de calibración)."""
    fig = _figura(5.6, 3.8, titulo, True, f"objetivo: {res['objetivo']} · {res['n_rois']} ROI de calibración")
    ax = _ejes(fig, (0.1, 0.2, 0.86, 0.6))
    claves = (("sensibilidad", "Sensibilidad"), ("precision", "Precisión"), ("f1", "F1"), ("kappa", "Kappa"))
    ancho = 0.34
    for j, (k, color, nombre) in enumerate((("antes", AZUL_CLARO, "Antes"), ("despues", AZUL, "Después"))):
        for i, (c, _) in enumerate(claves):
            v = res[k][c]
            x = i + (j - 0.5) * ancho
            if v is None:
                ax.text(x, 0.02, "n/d", ha="center", fontsize=7, color=SUAVE, rotation=90)
                continue
            ax.bar(x, max(v, 0), ancho * 0.92, color=color)
            ax.text(x, max(v, 0), f"{v:.2f}", ha="center", va="bottom", fontsize=7.5, color=TINTA)
    ax.set_xticks(range(len(claves)), [n for _, n in claves])
    ax.set_ylim(0, 1.15)
    ax.yaxis.grid(True, color=REJILLA)
    ax.set_axisbelow(True)
    ax.legend(handles=[Patch(color=AZUL_CLARO, label="Antes"), Patch(color=AZUL, label="Después")], frameon=False,
              fontsize=8, loc="upper right", ncol=2)
    return fig
