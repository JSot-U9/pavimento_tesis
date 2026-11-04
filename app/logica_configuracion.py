"""
logica_configuracion.py
=======================
Configuración persistente (tabla Configuracion) y parámetros base del motor.

`params_base()` devuelve los Params con los que se analiza por defecto. Mientras la huella de esos
parámetros no coincida con `params_calibrados_huella` (que escribirá la calibración de la F5 con
datos reales), todo análisis se marca como PROVISIONAL.
"""
from sqlalchemy import select

from app import basedatos
from app.logica_comun import ErrorValidacion
from app.modelos import Configuracion
from app.nucleo.parametros import Params

DEFAULTS = {
    "tesela_px": 1600,                    # lado de la tesela de análisis (px)
    "margen_m": 1.0,                      # margen de contexto de cada tesela (m)
    "umbral_concordancia": 0.60,          # kappa mínimo aceptable (valor por defecto: CONFIRMAR con el asesor)
    "params_base": None,                  # dict de Params o None = valores de fábrica
    "params_calibrados_huella": None,     # huella de los Params calibrados con ROI reales
}


def _validar(clave, valor):
    if clave not in DEFAULTS:
        raise ErrorValidacion({clave: f"clave desconocida. Disponibles: {', '.join(DEFAULTS)}"})
    try:
        if clave == "tesela_px":
            valor = int(valor)
            if valor < 512:
                raise ValueError("debe ser al menos 512")
        elif clave == "margen_m":
            valor = float(valor)
            if valor <= 0:
                raise ValueError("debe ser mayor que 0")
        elif clave == "umbral_concordancia":
            valor = float(valor)
            if not 0 < valor <= 1:
                raise ValueError("debe estar entre 0 y 1")
        elif clave == "params_base" and valor is not None:
            valor = Params.desde_dict(dict(valor)).a_dict()
    except (TypeError, ValueError) as e:
        raise ErrorValidacion({clave: str(e)}) from e
    return valor


def obtener(clave):
    if clave not in DEFAULTS:
        raise ErrorValidacion({clave: "clave desconocida"})
    with basedatos.nueva_sesion() as s:
        fila = s.get(Configuracion, clave)
        return DEFAULTS[clave] if fila is None else fila.valor


def establecer(clave, valor):
    valor = _validar(clave, valor)
    with basedatos.nueva_sesion() as s:
        fila = s.get(Configuracion, clave)
        if fila is None:
            s.add(Configuracion(clave=clave, valor=valor))
        else:
            fila.valor = valor
    return valor


def todas():
    with basedatos.nueva_sesion() as s:
        guardado = {f.clave: f.valor for f in s.scalars(select(Configuracion))}
    return {k: guardado.get(k, v) for k, v in DEFAULTS.items()}


def params_base():
    d = obtener("params_base")
    return Params.desde_dict(d) if d else Params()


def _huella(p):
    """Huella sin gsd_cm: la resolución es dato de cada tramo, no un umbral calibrado."""
    return p.con(gsd_cm=Params().gsd_cm).huella()


def guardar_params_base(params, calibrado=False):
    """Guarda los Params base. calibrado=True SOLO tras calibrar con ROI reales (F5)."""
    params.validar()
    establecer("params_base", params.a_dict())
    establecer("params_calibrados_huella", _huella(params) if calibrado else None)


def es_provisional(params):
    """True salvo que `params` sean exactamente los marcados como calibrados con datos reales."""
    return obtener("params_calibrados_huella") != _huella(params)
