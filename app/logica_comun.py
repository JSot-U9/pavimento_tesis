"""
logica_comun.py
===============
Piezas compartidas por las funciones logica_*: validación de campos con mensajes claros, lectura de
CSV tolerante (Excel en español: ';' y coma decimal) y normalización de nombres.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Tuple


class ErrorValidacion(Exception):
    """Datos inválidos. `errores` = {campo: mensaje}."""

    def __init__(self, errores):
        self.errores = dict(errores) if isinstance(errores, dict) else {"": str(errores)}
        super().__init__("; ".join(f"{k}: {v}" if k else v for k, v in self.errores.items()))


class ErrorNoEncontrado(Exception):
    """No existe el registro pedido."""


@dataclass(frozen=True)
class Campo:
    nombre: str
    etiqueta: str
    tipo: str = "texto"            # texto | entero | real | fecha | hora | bool | opcion
    requerido: bool = False
    opciones: Tuple[str, ...] = ()
    minimo: float = None
    maximo: float = None
    unidad: str = ""

    def a_dict(self):
        return {"nombre": self.nombre, "etiqueta": self.etiqueta, "tipo": self.tipo, "requerido": self.requerido,
                "opciones": list(self.opciones), "minimo": self.minimo, "maximo": self.maximo, "unidad": self.unidad}


def sin_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn")


def normalizar(t):
    """'Código ROI ' -> 'codigo_roi' (para comparar encabezados y valores)."""
    return re.sub(r"[^a-z0-9]+", "_", sin_acentos(t).strip().lower()).strip("_")


def vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _real(v):
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        x = float(str(v).strip().replace(" ", "").replace(",", "."))
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError
    return x


def _fecha(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    raise ValueError


def _hora(v):
    if isinstance(v, datetime):
        return v.time().replace(microsecond=0)
    if isinstance(v, time):
        return v.replace(microsecond=0)
    t = str(v).strip()
    for f in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(t, f).time()
        except ValueError:
            pass
    raise ValueError


_SI = {"si", "s", "true", "1", "x", "yes", "y", "verdadero"}
_NO = {"no", "n", "false", "0", "falso"}


def validar(datos, campos, parcial=False):
    """Convierte y valida `datos` contra la lista de `Campo`. Devuelve un dict limpio (None = vacío).
    parcial=True: solo valida las claves presentes (actualización). Lanza ErrorValidacion con TODOS los errores."""
    por_nombre = {c.nombre: c for c in campos}
    errores, out = {}, {}
    for k in datos:
        if k not in por_nombre:
            errores[k] = "campo desconocido"
    for c in campos:
        if parcial and c.nombre not in datos:
            continue
        v = datos.get(c.nombre)
        if vacio(v):
            if c.requerido:
                errores[c.nombre] = "es obligatorio"
            out[c.nombre] = None
            continue
        try:
            if c.tipo == "texto":
                v = str(v).strip()
            elif c.tipo == "entero":
                x = _real(v)
                if x != int(x):
                    raise ValueError
                v = int(x)
            elif c.tipo == "real":
                v = _real(v)
            elif c.tipo == "fecha":
                v = _fecha(v)
            elif c.tipo == "hora":
                v = _hora(v)
            elif c.tipo == "bool":
                if isinstance(v, bool):
                    pass
                else:
                    n = normalizar(v)
                    if n in _SI:
                        v = True
                    elif n in _NO:
                        v = False
                    else:
                        raise ValueError
            elif c.tipo == "opcion":
                mapa = {normalizar(o): o for o in c.opciones}
                n = normalizar(v)
                if n not in mapa:
                    errores[c.nombre] = f"'{v}' no es válido; use: {', '.join(c.opciones)}"
                    continue
                v = mapa[n]
        except (ValueError, TypeError):
            esperado = {"entero": "un número entero", "real": "un número", "fecha": "una fecha (AAAA-MM-DD o DD/MM/AAAA)",
                        "hora": "una hora (HH:MM)", "bool": "Sí/No"}.get(c.tipo, "un valor válido")
            errores[c.nombre] = f"'{v}' no es {esperado}"
            continue
        if c.tipo in ("entero", "real"):
            if c.minimo is not None and v < c.minimo:
                errores[c.nombre] = f"debe ser ≥ {c.minimo}"
            elif c.maximo is not None and v > c.maximo:
                errores[c.nombre] = f"debe ser ≤ {c.maximo}"
        out[c.nombre] = v
    if errores:
        raise ErrorValidacion(errores)
    return out


def esquema(campos):
    """Descripción de los campos (para que la UI construya formularios sin conocer los modelos)."""
    return [c.a_dict() for c in campos]


# ------------------------------------------------------------------------------------ CSV
def _decodificar(datos: bytes):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            pass
    return datos.decode("latin-1")


def leer_csv(ruta):
    """Lee un CSV (UTF-8 o Windows-1252; separador ',', ';' o tabulador) -> lista de dicts con
    encabezados normalizados. Cada fila lleva '_fila' (n.º de línea en el archivo, base 1)."""
    try:
        with open(ruta, "rb") as f:
            texto = _decodificar(f.read())
    except OSError as e:
        raise ErrorValidacion(f"No se pudo leer {ruta}: {e}") from e
    primera = next((ln for ln in texto.splitlines() if ln.strip()), "")
    sep = max((",", ";", "\t"), key=primera.count)
    rd = csv.reader(io.StringIO(texto), delimiter=sep)
    filas = list(rd)
    while filas and not any(c.strip() for c in filas[0]):
        filas.pop(0)
    if not filas:
        raise ErrorValidacion("El CSV está vacío")
    cab = [normalizar(c) for c in filas[0]]
    if len(set(cab)) != len(cab):
        dup = sorted({c for c in cab if cab.count(c) > 1})
        raise ErrorValidacion(f"Encabezados repetidos en el CSV: {', '.join(dup)}")
    out = []
    for n, fila in enumerate(filas[1:], start=2):
        if not any(c.strip() for c in fila):
            continue
        d = {cab[i]: (fila[i].strip() if i < len(fila) else "") for i in range(len(cab))}
        d["_fila"] = n
        out.append(d)
    return out


def fila_a_dict(obj):
    return obj.a_dict()


def obtener(s, modelo, id_, nombre="registro"):
    o = s.get(modelo, id_)
    if o is None:
        raise ErrorNoEncontrado(f"No existe {nombre} con id {id_}")
    return o
