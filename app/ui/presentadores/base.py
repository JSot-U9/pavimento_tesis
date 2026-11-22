"""
base.py (presentadores)
=======================
Piezas comunes de los presentadores: la lógica de la interfaz que NO necesita pantalla y por tanto se prueba
con pytest. Los presentadores solo llaman a `logica_*` (que devuelven dicts) y al núcleo para constantes;
nunca importan `modelos`, `basedatos.nueva_sesion` ni SQLAlchemy.

    Resultado    {ok, datos, errores{campo: mensaje}, mensaje, advertencias}: lo que las vistas muestran.
    proteger()   ejecuta una función de logica_* y convierte sus excepciones en un Resultado.
    Contexto     estado compartido entre pestañas (tramo activo) con eventos de cambio.
    formato_*    texto para tablas y paneles.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Callable, Dict, List

from app.logica_comun import ErrorNoEncontrado, ErrorValidacion
from app.nucleo.estructuras import ErrorLectura

log = logging.getLogger("pavimento.ui")


@dataclass
class Resultado:
    ok: bool = True
    datos: Any = None
    errores: Dict[str, str] = field(default_factory=dict)       # por campo ('' = error general)
    mensaje: str = ""
    advertencias: List[str] = field(default_factory=list)

    def texto_errores(self, etiquetas: Dict[str, str] = None) -> str:
        """TODOS los mensajes, uno por línea, con la etiqueta del campo si se conoce."""
        etiquetas = etiquetas or {}
        lineas = []
        for campo, msg in self.errores.items():
            nombre = etiquetas.get(campo, campo)
            lineas.append(f"{nombre}: {msg}" if nombre else msg)
        if not lineas and self.mensaje:
            lineas.append(self.mensaje)
        return "\n".join(lineas)


def proteger(fn: Callable, *args, **kwargs) -> Resultado:
    """Llama a `fn` y devuelve Resultado. Los ErrorValidacion conservan TODOS sus mensajes por campo."""
    try:
        datos = fn(*args, **kwargs)
    except ErrorValidacion as e:
        return Resultado(False, errores=dict(e.errores), mensaje=str(e))
    except ErrorNoEncontrado as e:
        return Resultado(False, errores={"": str(e)}, mensaje=str(e))
    except ErrorLectura as e:
        return Resultado(False, errores={"": str(e)}, mensaje=str(e))
    except ValueError as e:                                      # p. ej. Params.validar
        return Resultado(False, errores={"": str(e)}, mensaje=str(e))
    except OSError as e:
        return Resultado(False, errores={"": f"Error de archivo: {e}"}, mensaje=str(e))
    except Exception as e:                                       # noqa: BLE001 - la UI no debe caerse
        log.exception("Error inesperado en %s", getattr(fn, "__name__", fn))
        msg = f"Error inesperado ({type(e).__name__}): {e}"
        return Resultado(False, errores={"": msg}, mensaje=msg)
    adv = list(datos.get("advertencias", [])) if isinstance(datos, dict) and isinstance(
        datos.get("advertencias"), (list, tuple)) else []
    return Resultado(True, datos=datos, advertencias=adv)


class Contexto:
    """Estado compartido entre pestañas. Eventos: 'tramo_activo', 'tramos', 'rois', 'eje', 'ortomosaico',
    'ejecuciones', 'fichas', 'bd'. Los suscriptores se llaman en el hilo principal."""

    def __init__(self):
        self.tramo_id = None
        self.modo_tutorial = False              # True mientras se trabaja en la BD de práctica del tutorial
        self._obs: Dict[str, List[Callable]] = defaultdict(list)

    def suscribir(self, evento: str, fn: Callable):
        self._obs[evento].append(fn)

    def emitir(self, evento: str, *args):
        for fn in list(self._obs[evento]):
            fn(*args)

    def fijar_tramo(self, tramo_id):
        if tramo_id != self.tramo_id:
            self.tramo_id = tramo_id
            self.emitir("tramo_activo", tramo_id)


# ------------------------------------------------------------------------------------ formato
def fnum(v, decimales=2, vacio="—"):
    if v is None or v == "":
        return vacio
    try:
        return f"{float(v):.{decimales}f}"
    except (TypeError, ValueError):
        return str(v)


def ftexto(v, vacio=""):
    if v is None:
        return vacio
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, (datetime, date, time)):
        return v.isoformat(timespec="minutes") if isinstance(v, (datetime, time)) else v.isoformat()
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def valor_a_texto(v, tipo="texto"):
    """Valor Python (de un dict de logica_*) -> texto editable en un formulario."""
    if v is None:
        return ""
    if tipo == "bool":
        return "Sí" if v else "No"
    if tipo == "hora" and isinstance(v, time):
        return v.strftime("%H:%M")
    return ftexto(v)
