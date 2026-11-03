"""
estructuras.py
==============
Estructuras de datos que devuelve el núcleo (en vez de escribir CSV). No dependen de la BD ni de
la interfaz: la capa logica_* las convierte en filas de BD y las vistas las muestran.

Correspondencia con la operacionalización de variables (cap. 3.2: Tabla 2 = grietas longitudinales y
transversales, Tabla 3 = piel de cocodrilo, Tabla 4 = baches):

  Indicador de la tesis                          Columna / origen
  ---------------------------------------------  ------------------------------------------------
  Calidad de imagen (adecuada / no adecuada)     Calidad.calidad (+ advertencias)
  Resolución espacial (cm/píxel)                 Calidad.resolucion_cm_px
  Cobertura del tramo (%)                        Calidad.cobertura_pct (calzada_util_pct: sin vegetación)
  Análisis de canales R, G y B (valores RGB)     caracteristicas.estadisticos_rgb()
  Preprocesamiento (Sí / No)                     se registra en EjecucionAnalisis (F3): siempre 'Sí'
  Segmentación de grietas (píxeles / área)       Deteccion.area_px
  Área segmentada de la grieta / piel / bache    Deteccion.area_m2
  Contraste respecto al pavimento (valores RGB)  Deteccion.contraste_weber (sobre la luminancia)
  Características de textura                     caracteristicas.textura_glcm()
  N.º de grietas / baches detectados             conteo de Deteccion por tipo (logica_estadistica, F5)
  Falsos positivos / negativos, concordancia     logica_validacion (F5)
  Clasificación / tipo según orientación         Deteccion.tipo, desv_eje_deg (orientación local del eje)
  Presencia (Sí / No)                            existencia de Deteccion del tipo en la región
  Longitud de la grieta / del bache (m)          Deteccion.longitud_m
  Ancho de la grieta (mm)                        Deteccion.ancho_mm        [solo grietas lineales]
  Ancho del bache (m)                            Deteccion.ancho_m         [solo baches]
  Longitud representativa de grietas (m)         Deteccion.longitud_m      [piel de cocodrilo]*
  Densidad o concentración del patrón (%)        Deteccion.densidad_pct    [piel de cocodrilo]
  Área afectada (m²)                             Deteccion.area_m2
  Porcentaje de área afectada (%)                area_m2 / área de la ROI o del tramo (logica_*, F5)
  Nivel de severidad (Baja / Media / Alta)       SOLO la ficha de campo; severidad_prelim es orientativa

  * Supuesto: 'longitud representativa' = longitud total de grietas dentro de la zona.
"""
from dataclasses import asdict, dataclass, field, replace
from typing import List, Optional, Tuple

TIPOS = ("longitudinal", "transversal", "piel_cocodrilo", "bache")
TIPOS_GRIETA = ("longitudinal", "transversal")

# Colores RGB para superposiciones y reportes
COLORES = {
    "longitudinal": (0, 120, 255),
    "transversal": (255, 40, 40),
    "piel_cocodrilo": (255, 165, 0),
    "bache": (255, 0, 255),
}


@dataclass
class Deteccion:
    tipo: str
    x: int                                   # caja envolvente en píxeles del ortomosaico
    y: int
    w: int
    h: int
    cx: float                                # centroide (px del ortomosaico)
    cy: float
    longitud_m: float = 0.0
    ancho_mm: Optional[float] = None         # solo grietas lineales
    ancho_m: Optional[float] = None          # solo baches
    area_m2: float = 0.0
    area_px: Optional[int] = None            # área segmentada en píxeles
    angulo_img_deg: Optional[float] = None   # orientación de la grieta en la imagen
    angulo_eje_deg: Optional[float] = None   # orientación LOCAL del eje de vía en ese punto
    desv_eje_deg: Optional[float] = None     # 0 = paralela al eje, 90 = perpendicular
    contraste_weber: Optional[float] = None
    ramificada: Optional[bool] = None
    n_celdas: Optional[int] = None           # piel de cocodrilo
    celda_media_m2: Optional[float] = None
    densidad_pct: Optional[float] = None     # % de la zona ocupado por grietas
    solidez: Optional[float] = None          # baches
    severidad_prelim: Optional[str] = None   # ORIENTATIVA; la oficial es la de la ficha de campo
    metodo_ancho: str = ""
    advertencia: str = ""
    metodo: str = "actual"                   # algoritmo que la produjo
    geom_tipo: str = ""                      # 'polilinea_aprox' | 'poligono'
    geom: List[Tuple[int, int]] = field(default_factory=list)   # puntos en px del ortomosaico
    progresiva_m: Optional[float] = None     # se completa con el eje de vía
    lado_via: Optional[str] = None
    # bordes de tesela por los que fue cortada: ('v'|'h', coordenada, +1 si queda antes de la línea
    # / -1 si queda después). Uso interno de fusion.py; vacío una vez fusionadas las piezas.
    bordes_corte: List[Tuple[str, int, int]] = field(default_factory=list, repr=False)

    def desplazada(self, dx, dy):
        """Copia con todas las coordenadas sumadas (dx, dy): de ventana local a ortomosaico."""
        return replace(self, x=self.x + dx, y=self.y + dy, cx=self.cx + dx, cy=self.cy + dy,
                       geom=[(px + dx, py + dy) for px, py in self.geom])

    def a_dict(self):
        return asdict(self)


@dataclass
class Calidad:
    calidad: str                             # 'Adecuada' | 'No adecuada'
    nitidez: float
    brillo_medio: float
    fraccion_saturada: float
    resolucion_cm_px: float
    cobertura_pct: float                     # % de píxeles con datos (sin NoData)
    calzada_util_pct: float                  # % de píxeles analizables (sin NoData ni vegetación)
    advertencias: List[str] = field(default_factory=list)

    @property
    def adecuada(self):
        return self.calidad == "Adecuada"

    def a_dict(self):
        d = asdict(self)
        d["advertencias"] = "; ".join(self.advertencias)
        return d


@dataclass
class ResultadoAnalisis:
    detecciones: List[Deteccion]
    calidad: Calidad
    region: Tuple[int, int, int, int]        # (x0, y0, x1, y1) analizada
    n_teselas: int
    params_huella: str
    metodo: str
    advertencias: List[str] = field(default_factory=list)


class AnalisisCancelado(Exception):
    """Se lanza cuando el usuario cancela el análisis (el resultado parcial se descarta)."""


class ErrorLectura(Exception):
    """No se pudo leer el ortomosaico (archivo inexistente, formato no soportado o demasiado grande)."""
