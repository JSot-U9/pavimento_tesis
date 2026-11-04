"""
formularios.py
==============
Funciones puras para los formularios generados desde `esquema_*` (listas de dicts con nombre, etiqueta, tipo,
requerido, opciones, minimo, maximo, unidad). No usan Tk.
"""
from typing import Dict, Iterable, List, Tuple

from app.ui.presentadores.base import valor_a_texto


def etiquetas(esquema: List[dict]) -> Dict[str, str]:
    return {c["nombre"]: c["etiqueta"] for c in esquema}


def sin_campos(esquema: List[dict], nombres: Iterable[str]) -> List[dict]:
    """Esquema sin algunos campos (p. ej. el código del catálogo, que no se puede cambiar)."""
    quitar = set(nombres)
    return [c for c in esquema if c["nombre"] not in quitar]


def datos_a_textos(esquema: List[dict], datos: dict) -> Dict[str, str]:
    """Dict de una fila de la BD -> textos para los campos del formulario."""
    datos = datos or {}
    return {c["nombre"]: valor_a_texto(datos.get(c["nombre"]), c["tipo"]) for c in esquema}


def pista(campo: dict) -> str:
    """Texto de ayuda de un campo: unidad y rango válidos."""
    partes = []
    if campo.get("unidad"):
        partes.append(campo["unidad"])
    mn, mx = campo.get("minimo"), campo.get("maximo")
    if mn is not None and mx is not None:
        partes.append(f"{mn:g} – {mx:g}")
    elif mn is not None:
        partes.append(f"≥ {mn:g}")
    elif mx is not None:
        partes.append(f"≤ {mx:g}")
    if campo["tipo"] == "fecha":
        partes.append("AAAA-MM-DD")
    elif campo["tipo"] == "hora":
        partes.append("HH:MM")
    return " · ".join(partes)


def repartir_errores(esquema: List[dict], errores: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Separa los errores en (de campos de ESTE formulario, otros). Los otros se muestran en el área general."""
    nombres = {c["nombre"] for c in esquema}
    propios = {k: v for k, v in errores.items() if k in nombres}
    otros = {k: v for k, v in errores.items() if k not in nombres}
    return propios, otros


def lineas_error(esquema: List[dict], errores: Dict[str, str]) -> List[str]:
    """Una línea por error ('Etiqueta: mensaje'): TODOS los mensajes, sin quedarse con el primero."""
    et = etiquetas(esquema)
    return [f"{et.get(k, k)}: {v}" if (et.get(k, k)) else v for k, v in errores.items()]
