"""
parametros.py
=============
Parámetros del motor de detección, en un dataclass VERSIONADO.

- `version` identifica el esquema de parámetros; se guarda en cada EjecucionAnalisis para poder
  reproducir un análisis con exactamente los valores usados.
- Los umbrales listados en PROVISIONALES se calibraron SOLO con imágenes sintéticas. Deben
  recalibrarse con ortomosaicos reales de los tres tramos (prueba piloto) antes de usar sus
  resultados como evidencia en la tesis.
- La severidad del programa es solo orientativa: la oficial es la de la ficha de campo.

Versiones del esquema (VERSION_PARAMS):
  1  Fases 2-6: método 'actual'.
  2  Fase 7: añade los parámetros `sun_*` del método 'sun' (Sun, 2009). Las ejecuciones guardadas con la
     versión 1 NO se reescriben: se leen con `Params.desde_dict` (conservan version = 1, sin campos `sun_*`,
     y su huella sigue siendo la que se guardó). `Params.migrar()` las convierte a la versión actual con los
     valores de fábrica de los campos nuevos (así lo hace `logica_configuracion.params_base`).
"""
import hashlib
import json
from dataclasses import asdict, dataclass, fields, replace

VERSION_PARAMS = 2
VERSIONES_SOPORTADAS = (1, 2)


@dataclass
class Params:
    version: int = VERSION_PARAMS

    # --- geometría de la imagen -------------------------------------------------------------
    gsd_cm: float = 0.5                  # resolución espacial (cm/píxel)
    tol_orient_deg: float = 45.0         # |ángulo - eje| <= tol -> longitudinal; si no, transversal
    eje_ventana_m: float = 4.0           # tramo del eje (m) con el que se promedia su dirección local

    # --- calidad de imagen (Ficha 5: calidad adecuada / no adecuada) -------------------------
    nitidez_min: float = 5.0             # varianza del Laplaciano (mediana de teselas)
    brillo_min: float = 40.0
    brillo_max: float = 215.0
    saturados_max: float = 0.05          # fracción máxima de píxeles saturados

    # --- máscara de calzada -----------------------------------------------------------------
    exg_veg: float = 25.0                # ExG (2G-R-B) por encima del cual es vegetación

    # --- preprocesamiento -------------------------------------------------------------------
    iluminacion_sigma_m: float = 0.5     # escala del fondo de iluminación a restar

    # --- grietas ----------------------------------------------------------------------------
    grieta_kernel_m: float = 0.06        # tamaño del black-hat (> ancho máximo de grieta)
    grieta_k_mad: float = 4.5            # umbral = mediana + k * MAD del black-hat
    grieta_contraste_min: float = 8.0    # umbral mínimo (niveles de gris)
    grieta_cierre_m: float = 0.03        # cierre morfológico: une puntos de ruptura menores a esto
    grieta_long_min_m: float = 0.15      # longitud mínima de una grieta
    grieta_en_cocodrilo: float = 0.5     # fracción dentro de zona de cocodrilo para excluirla

    # --- ancho de grieta (perfil de gris a media altura) -------------------------------------
    ancho_semi_perfil_m: float = 0.08    # ancho máximo medible (el perfil abarca este largo)
    ancho_paso_px: int = 3               # se mide un perfil cada `paso` píxeles del esqueleto
    ancho_contraste_min: float = 8.0     # profundidad mínima del perfil (niveles de gris)
    ancho_sigma_px: float = 0.9          # difuminado total (óptica+suavizado) a deconvolucionar; 0 = sin corregir
    ancho_suavizado_px: float = 0.6      # suavizado gaussiano aplicado antes de medir perfiles

    # --- severidad orientativa de grietas lineales (criterio de la Ficha 3, ancho en mm) -----
    sev_grieta_baja_mm: float = 1.0      # <= baja
    sev_grieta_media_mm: float = 3.0     # <= media; mayor = alta

    # --- piel de cocodrilo (celdas < 0.3 m de lado, FHWA/ASTM D6433) -------------------------
    celda_min_m2: float = 0.0004
    celda_max_m2: float = 0.09
    celda_union_m: float = 0.08          # distancia máxima para agrupar celdas en una zona
    celdas_min: int = 4                  # mínimo de celdas por zona
    zona_min_m2: float = 0.05

    # --- baches -----------------------------------------------------------------------------
    bache_fondo_m: float = 0.75          # escala del fondo local de referencia
    bache_dL_min: float = 18.0           # diferencia mínima de luminosidad (escala 0-255)
    bache_dC_min: float = 14.0           # diferencia mínima de croma
    bache_ancho_min_m: float = 0.12      # ancho mínimo (la apertura elimina grietas)
    bache_area_min_m2: float = 0.03
    bache_solidez_min: float = 0.6
    bache_relacion_min: float = 0.25     # eje menor / eje mayor
    marca_vial_L: float = 190.0          # L > este valor y croma bajo: marca vial, se excluye

    # --- método 'sun' (versión 2 del esquema; Sun, 2009) ---------------------------------------
    # Todos PROVISIONALES. Las constantes en metros equivalen a las de píxeles de Sun suponiendo ~0.8 cm/px
    # (SUPUESTO: la tesis no declara la resolución de sus imágenes de cámara vehicular).
    sun_alfa: float = 0.2247             # T = fix(alfa * kmin + beta)   (constante del Matlab de Sun)
    sun_beta: float = 40.0               # (el texto de la tesis dice 0.22 y 45; se usa el CÓDIGO, a petición)
    sun_contraste_min: float = 25.0      # MEJORA: T nunca supera media - este valor (0 = sin tope: T puede cubrir toda la imagen)
    sun_vecinos_superficie: int = 0      # 0 = vecinos de la imagen original (como el Matlab); 1 = superficies u,b (ec. 4-5)
    sun_cierre_m: float = 0.04           # radio del disco del cierre morfológico (Sun: 5 px)
    sun_ruido_dist_m: float = 0.016      # distancia de los 8 puntos de la limpieza de ruido (Sun: 2 px)
    sun_hueco_max_m: float = 0.05        # distancia máxima que se puentea entre un extremo y otra grieta (Sun: ~6 px)
    sun_hueco_lateral_m: float = 0.032   # desviación lateral admitida del puente (Sun: 4 filas)
    sun_componente_min_m: float = 0.24   # tamaño mínimo de un componente del esqueleto (Sun: 30 px)

    # ---------------------------------------------------------------------------------------
    def a_dict(self):
        """Valores del esquema de ESTA versión (un objeto de versión 1 no incluye los campos `sun_*`)."""
        d = asdict(self)
        if self.version < 2:
            for n in CAMPOS_V2:
                d.pop(n, None)
        return d

    def a_json(self):
        return json.dumps(self.a_dict(), sort_keys=True, ensure_ascii=False)

    def huella(self):
        """Huella corta de los valores (para detectar si dos análisis usaron los mismos parámetros)."""
        return hashlib.sha1(self.a_json().encode("utf-8")).hexdigest()[:10]

    def huella_nucleo(self):
        """Huella de los campos de la versión 1 (los del método 'actual'): no cambia al añadir parámetros de 'sun',
        así que una calibración del método 'actual' sigue valiendo tras migrar el esquema."""
        d = {k: v for k, v in asdict(self).items() if k not in CAMPOS_V2 and k != "version"}
        d["version"] = 1
        return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]

    def migrar(self):
        """Copia en la versión actual del esquema (campos nuevos con sus valores de fábrica). Idempotente."""
        return self if self.version == VERSION_PARAMS else replace(self, version=VERSION_PARAMS)

    def con(self, **cambios):
        """Copia con algunos valores cambiados (valida que existan y que el resultado sea coherente)."""
        _comprobar_nombres(cambios)
        nuevo = replace(self, **cambios)
        nuevo.validar()
        return nuevo

    @classmethod
    def desde_dict(cls, datos):
        _comprobar_nombres(datos)
        p = cls(**datos)
        p.validar()
        return p

    @classmethod
    def desde_json(cls, texto):
        return cls.desde_dict(json.loads(texto))

    def validar(self):
        """Lanza ValueError con un mensaje claro si algún valor es incoherente."""
        errores = []

        def positivo(nombre):
            if getattr(self, nombre) <= 0:
                errores.append(f"{nombre} debe ser mayor que 0 (vale {getattr(self, nombre)})")

        for n in ("gsd_cm", "eje_ventana_m", "iluminacion_sigma_m", "grieta_kernel_m", "grieta_cierre_m",
                  "grieta_long_min_m", "ancho_semi_perfil_m", "celda_min_m2", "celda_max_m2",
                  "bache_fondo_m", "bache_ancho_min_m", "bache_area_min_m2"):
            positivo(n)
        for n in ("sun_cierre_m", "sun_ruido_dist_m", "sun_hueco_max_m", "sun_hueco_lateral_m", "sun_componente_min_m"):
            positivo(n)
        if self.version not in VERSIONES_SOPORTADAS:
            errores.append(f"versión de parámetros {self.version} no soportada (actual: {VERSION_PARAMS})")
        if self.sun_vecinos_superficie not in (0, 1):
            errores.append("sun_vecinos_superficie debe ser 0 (imagen original) o 1 (superficies u, b)")
        if self.sun_contraste_min < 0:
            errores.append("sun_contraste_min no puede ser negativo")
        if self.sun_alfa <= 0:
            errores.append("sun_alfa debe ser mayor que 0")
        if not 0 <= self.sun_beta <= 255:
            errores.append("sun_beta debe estar entre 0 y 255 (niveles de gris)")
        if not 0 < self.tol_orient_deg < 90:
            errores.append("tol_orient_deg debe estar entre 0 y 90 grados")
        if self.brillo_min >= self.brillo_max:
            errores.append("brillo_min debe ser menor que brillo_max")
        if not 0 <= self.saturados_max <= 1:
            errores.append("saturados_max debe estar entre 0 y 1")
        if self.celda_min_m2 >= self.celda_max_m2:
            errores.append("celda_min_m2 debe ser menor que celda_max_m2")
        if self.sev_grieta_baja_mm >= self.sev_grieta_media_mm:
            errores.append("sev_grieta_baja_mm debe ser menor que sev_grieta_media_mm")
        if self.ancho_sigma_px < 0 or self.ancho_suavizado_px < 0:
            errores.append("ancho_sigma_px y ancho_suavizado_px no pueden ser negativos")
        if self.ancho_paso_px < 1:
            errores.append("ancho_paso_px debe ser al menos 1")
        if errores:
            raise ValueError("Parámetros inválidos: " + "; ".join(errores))

    @property
    def gsd_m(self):
        return self.gsd_cm / 100.0

    @staticmethod
    def provisionales():
        """Nombres de los parámetros calibrados solo con datos sintéticos."""
        return PROVISIONALES


# Campos añadidos por la versión 2 del esquema.
CAMPOS_V2 = tuple(f.name for f in fields(Params) if f.name.startswith("sun_"))

# Todo lo calibrado con sintéticos: gsd_cm y tol_orient_deg son datos/definiciones, no calibraciones.
PROVISIONALES = tuple(f.name for f in fields(Params)
                      if f.name not in ("version", "gsd_cm", "tol_orient_deg",
                                        "sev_grieta_baja_mm", "sev_grieta_media_mm"))


def _comprobar_nombres(datos):
    validos = {f.name for f in fields(Params)}
    desconocidos = sorted(set(datos) - validos)
    if desconocidos:
        raise ValueError(f"Parámetro(s) desconocido(s): {', '.join(desconocidos)}. "
                         f"Disponibles: {', '.join(sorted(validos))}")


def aplicar_texto(p, items):
    """Aplica una lista de 'clave=valor' (por ejemplo desde un cuadro de texto) y devuelve un Params nuevo."""
    tipos = {f.name: f.type for f in fields(Params)}
    cambios = {}
    for it in items or []:
        clave, sep, valor = it.partition("=")
        clave = clave.strip()
        if not sep:
            raise ValueError(f"Formato inválido '{it}': use clave=valor")
        if clave not in tipos:
            raise ValueError(f"Parámetro desconocido: {clave}")
        try:
            cambios[clave] = (int if tipos[clave] in (int, "int") else float)(valor)
        except ValueError:
            raise ValueError(f"El valor '{valor}' de {clave} no es un número") from None
    return p.con(**cambios)
