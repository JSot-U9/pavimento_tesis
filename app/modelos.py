"""
modelos.py
==========
Esquema de la base de datos (SQLite + SQLAlchemy 2.x), aprobado en la Fase 1.

Correspondencia con las fichas de campo (numeración del anexo 7.5 de la tesis):
    Tramo (Ficha 1) · Inspeccion/Patologia (F2) · Severidad (F3) · Geometria (F4) · VueloUAV (F5)
    EjecucionAnalisis/Deteccion/CaracteristicaROI (F6, solo RGB) · Validacion (F7)
    CondicionAmbiental (F8) · GCP (F9)

Convenciones
  - Las coordenadas de ROI, ejes y geometrías se guardan en PÍXELES del ortomosaico (canónico para el
    motor); cuando hay georreferenciación se guarda además la versión en coordenadas del mapa.
  - Las vistas nunca importan este módulo: las funciones logica_* devuelven diccionarios (`a_dict`).
  - Borrado: al eliminar un tramo se eliminan sus fichas, ROI y análisis; al eliminar una ROI, las
    detecciones/patologías que la referenciaban quedan sin ROI (SET NULL).
"""
from datetime import date, datetime, time
from typing import List, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, Time, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# --- dominios cerrados -------------------------------------------------------------------------
NIVELES_SEVERIDAD = ("Baja", "Media", "Alta")
ROLES_ROI = ("calibracion", "prueba", "sin_asignar")
LADOS = ("derecha", "izquierda", "centro")
ORIGENES_ROI = ("manual", "csv", "geojson", "gpkg")
ESTADOS_EJECUCION = ("completada", "cancelada", "error")
ALCANCES = ("tramo", "roi", "ventana")


def _ahora():
    return datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    def a_dict(self):
        """Todas las columnas como diccionario (valores simples; JSON ya deserializado)."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ===================================================================================== Ficha 1
class Tramo(Base):
    __tablename__ = "tramo"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    via: Mapped[Optional[str]] = mapped_column(String(120))
    ruta: Mapped[Optional[str]] = mapped_column(String(60))
    ubicacion: Mapped[Optional[str]] = mapped_column(String(200))
    progresiva_ini_m: Mapped[Optional[float]] = mapped_column(Float)
    progresiva_fin_m: Mapped[Optional[float]] = mapped_column(Float)
    longitud_m: Mapped[Optional[float]] = mapped_column(Float)
    ancho_calzada_m: Mapped[Optional[float]] = mapped_column(Float)
    ancho_berma_m: Mapped[Optional[float]] = mapped_column(Float)
    n_carriles: Mapped[Optional[int]] = mapped_column(Integer)
    este_ini: Mapped[Optional[float]] = mapped_column(Float)
    norte_ini: Mapped[Optional[float]] = mapped_column(Float)
    este_fin: Mapped[Optional[float]] = mapped_column(Float)
    norte_fin: Mapped[Optional[float]] = mapped_column(Float)
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    # ortomosaico asociado (se completa con logica_tramos.asignar_ortomosaico)
    ortomosaico_ruta: Mapped[Optional[str]] = mapped_column(String(500))
    gsd_cm: Mapped[Optional[float]] = mapped_column(Float)
    ancho_px: Mapped[Optional[int]] = mapped_column(Integer)
    alto_px: Mapped[Optional[int]] = mapped_column(Integer)
    transformacion: Mapped[Optional[list]] = mapped_column(JSON)       # [a, b, c, d, e, f] (convención GDAL)
    epsg: Mapped[Optional[int]] = mapped_column(Integer)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_ahora)

    ejes: Mapped[List["EjeVia"]] = relationship(back_populates="tramo", cascade="all, delete-orphan",
                                                passive_deletes=True)
    vuelos: Mapped[List["VueloUAV"]] = relationship(back_populates="tramo", cascade="all, delete-orphan",
                                                    passive_deletes=True)
    condiciones: Mapped[List["CondicionAmbiental"]] = relationship(cascade="all, delete-orphan",
                                                                   passive_deletes=True)
    gcps: Mapped[List["GCP"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    inspecciones: Mapped[List["Inspeccion"]] = relationship(back_populates="tramo", cascade="all, delete-orphan",
                                                            passive_deletes=True)
    rois: Mapped[List["ROI"]] = relationship(back_populates="tramo", cascade="all, delete-orphan",
                                             passive_deletes=True)
    ejecuciones: Mapped[List["EjecucionAnalisis"]] = relationship(back_populates="tramo",
                                                                  cascade="all, delete-orphan",
                                                                  passive_deletes=True)


class EjeVia(Base):
    """Eje de vía: polilínea. Se conserva el historial; el vigente es el de mayor id."""
    __tablename__ = "eje_via"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    vertices_px: Mapped[list] = mapped_column(JSON)                    # [[x, y], ...] en píxeles
    vertices_geo: Mapped[Optional[list]] = mapped_column(JSON)         # [[E, N], ...] si se dibujó en el mapa
    progresiva_inicial_m: Mapped[float] = mapped_column(Float, default=0.0)
    origen: Mapped[str] = mapped_column(String(20), default="manual")
    creado: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    tramo: Mapped[Tramo] = relationship(back_populates="ejes")


# ===================================================================================== Fichas 5, 8, 9
class VueloUAV(Base):                                                  # Ficha 5
    __tablename__ = "vuelo_uav"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    codigo: Mapped[str] = mapped_column(String(40))
    fecha: Mapped[Optional[date]] = mapped_column(Date)
    hora_inicio: Mapped[Optional[time]] = mapped_column(Time)
    hora_fin: Mapped[Optional[time]] = mapped_column(Time)
    dron: Mapped[Optional[str]] = mapped_column(String(80))
    camara: Mapped[Optional[str]] = mapped_column(String(80))
    altura_m: Mapped[Optional[float]] = mapped_column(Float)
    gsd_cm: Mapped[Optional[float]] = mapped_column(Float)
    traslape_frontal_pct: Mapped[Optional[float]] = mapped_column(Float)
    traslape_lateral_pct: Mapped[Optional[float]] = mapped_column(Float)
    velocidad_ms: Mapped[Optional[float]] = mapped_column(Float)
    n_fotos: Mapped[Optional[int]] = mapped_column(Integer)
    n_gcp: Mapped[Optional[int]] = mapped_column(Integer)
    operador: Mapped[Optional[str]] = mapped_column(String(80))
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    tramo: Mapped[Tramo] = relationship(back_populates="vuelos")
    __table_args__ = (UniqueConstraint("tramo_id", "codigo", name="uq_vuelo_tramo_codigo"),)


class CondicionAmbiental(Base):                                        # Ficha 8
    __tablename__ = "condicion_ambiental"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    vuelo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vuelo_uav.id", ondelete="SET NULL"))
    fecha: Mapped[Optional[date]] = mapped_column(Date)
    hora: Mapped[Optional[time]] = mapped_column(Time)
    temperatura_c: Mapped[Optional[float]] = mapped_column(Float)
    humedad_pct: Mapped[Optional[float]] = mapped_column(Float)
    cielo: Mapped[Optional[str]] = mapped_column(String(40))
    viento_ms: Mapped[Optional[float]] = mapped_column(Float)
    lluvia: Mapped[Optional[str]] = mapped_column(String(40))
    humedad_pavimento: Mapped[Optional[str]] = mapped_column(String(40))
    sombras: Mapped[Optional[str]] = mapped_column(String(40))
    observaciones: Mapped[Optional[str]] = mapped_column(Text)


class GCP(Base):                                                       # Ficha 9
    __tablename__ = "gcp"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    vuelo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vuelo_uav.id", ondelete="SET NULL"))
    codigo: Mapped[str] = mapped_column(String(40))
    ubicacion: Mapped[Optional[str]] = mapped_column(String(200))
    este: Mapped[Optional[float]] = mapped_column(Float)
    norte: Mapped[Optional[float]] = mapped_column(Float)
    altitud: Mapped[Optional[float]] = mapped_column(Float)
    tipo: Mapped[Optional[str]] = mapped_column(String(40))            # control / verificación
    metodo: Mapped[Optional[str]] = mapped_column(String(60))
    precision_m: Mapped[Optional[float]] = mapped_column(Float)
    usado_ortomosaico: Mapped[Optional[bool]] = mapped_column(Boolean)
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("tramo_id", "codigo", name="uq_gcp_tramo_codigo"),)


# ===================================================================================== Fichas 2, 3, 4
class CatalogoPatologia(Base):
    """Catálogo de la Ficha 2. `tipo_motor` es el tipo del motor de detección al que equivale (solo 4)."""
    __tablename__ = "catalogo_patologia"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    grupo: Mapped[Optional[str]] = mapped_column(String(80))
    tipo_motor: Mapped[Optional[str]] = mapped_column(String(20))      # longitudinal|transversal|piel_cocodrilo|bache
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Inspeccion(Base):
    """Una pasada de inspección de campo por un observador (1 = principal, 2 = segundo observador)."""
    __tablename__ = "inspeccion"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    fecha: Mapped[Optional[date]] = mapped_column(Date)
    responsable: Mapped[Optional[str]] = mapped_column(String(80))
    observador: Mapped[int] = mapped_column(Integer, default=1)
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    tramo: Mapped[Tramo] = relationship(back_populates="inspecciones")
    patologias: Mapped[List["Patologia"]] = relationship(back_populates="inspeccion", cascade="all, delete-orphan",
                                                         passive_deletes=True)
    __table_args__ = (CheckConstraint("observador IN (1, 2)", name="ck_inspeccion_observador"),)


class Patologia(Base):
    __tablename__ = "patologia"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspeccion_id: Mapped[int] = mapped_column(ForeignKey("inspeccion.id", ondelete="CASCADE"), index=True)
    roi_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roi.id", ondelete="SET NULL"), index=True)
    codigo: Mapped[str] = mapped_column(ForeignKey("catalogo_patologia.codigo"))
    progresiva_m: Mapped[Optional[float]] = mapped_column(Float)
    lado: Mapped[Optional[str]] = mapped_column(String(10))
    este: Mapped[Optional[float]] = mapped_column(Float)
    norte: Mapped[Optional[float]] = mapped_column(Float)
    altitud: Mapped[Optional[float]] = mapped_column(Float)
    presencia: Mapped[bool] = mapped_column(Boolean, default=True)
    foto: Mapped[Optional[str]] = mapped_column(String(300))
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    inspeccion: Mapped[Inspeccion] = relationship(back_populates="patologias")
    geometria: Mapped[Optional["Geometria"]] = relationship(back_populates="patologia", uselist=False,
                                                            cascade="all, delete-orphan", passive_deletes=True)
    severidad: Mapped[Optional["Severidad"]] = relationship(back_populates="patologia", uselist=False,
                                                            cascade="all, delete-orphan", passive_deletes=True)


class Geometria(Base):                                                 # Ficha 4 (medidas de campo)
    __tablename__ = "geometria"
    id: Mapped[int] = mapped_column(primary_key=True)
    patologia_id: Mapped[int] = mapped_column(ForeignKey("patologia.id", ondelete="CASCADE"), unique=True)
    area_m2: Mapped[Optional[float]] = mapped_column(Float)
    longitud_m: Mapped[Optional[float]] = mapped_column(Float)
    ancho_prom_mm: Mapped[Optional[float]] = mapped_column(Float)      # SIEMPRE en mm (también en baches)
    ancho_max_mm: Mapped[Optional[float]] = mapped_column(Float)
    profundidad_cm: Mapped[Optional[float]] = mapped_column(Float)
    perimetro_m: Mapped[Optional[float]] = mapped_column(Float)
    pct_area: Mapped[Optional[float]] = mapped_column(Float)
    separacion_m: Mapped[Optional[float]] = mapped_column(Float)
    orientacion_deg: Mapped[Optional[float]] = mapped_column(Float)
    patologia: Mapped[Patologia] = relationship(back_populates="geometria")


class Severidad(Base):                                                 # Ficha 3 (la severidad OFICIAL)
    __tablename__ = "severidad"
    id: Mapped[int] = mapped_column(primary_key=True)
    patologia_id: Mapped[int] = mapped_column(ForeignKey("patologia.id", ondelete="CASCADE"), unique=True)
    nivel: Mapped[str] = mapped_column(String(10))
    criterio: Mapped[Optional[str]] = mapped_column(String(200))
    observador: Mapped[int] = mapped_column(Integer, default=1)
    patologia: Mapped[Patologia] = relationship(back_populates="severidad")
    __table_args__ = (CheckConstraint("nivel IN ('Baja', 'Media', 'Alta')", name="ck_severidad_nivel"),)


# ===================================================================================== ROI
class ROI(Base):
    """Región de interés: rectángulo en píxeles (lo que analiza el motor) + polígono opcional."""
    __tablename__ = "roi"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    codigo: Mapped[str] = mapped_column(String(40))
    patologia_codigo: Mapped[Optional[str]] = mapped_column(ForeignKey("catalogo_patologia.codigo"))
    tipo_campo: Mapped[str] = mapped_column(String(20))                # tipos del motor + 'sano'
    severidad_campo: Mapped[Optional[str]] = mapped_column(String(10))  # copia de la capa GIS; la oficial: Severidad
    x0: Mapped[int] = mapped_column(Integer)
    y0: Mapped[int] = mapped_column(Integer)
    x1: Mapped[int] = mapped_column(Integer)
    y1: Mapped[int] = mapped_column(Integer)
    poligono_px: Mapped[Optional[list]] = mapped_column(JSON)
    poligono_geo: Mapped[Optional[list]] = mapped_column(JSON)
    progresiva_ini_m: Mapped[Optional[float]] = mapped_column(Float)
    progresiva_fin_m: Mapped[Optional[float]] = mapped_column(Float)
    rol: Mapped[str] = mapped_column(String(15), default="sin_asignar")
    origen: Mapped[str] = mapped_column(String(10), default="manual")
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    tramo: Mapped[Tramo] = relationship(back_populates="rois")
    __table_args__ = (
        UniqueConstraint("tramo_id", "codigo", name="uq_roi_tramo_codigo"),
        CheckConstraint("rol IN ('calibracion', 'prueba', 'sin_asignar')", name="ck_roi_rol"),
        CheckConstraint("x1 > x0 AND y1 > y0", name="ck_roi_rectangulo"),
    )

    @property
    def region(self):
        return (self.x0, self.y0, self.x1, self.y1)


class GeometriaReferencia(Base):
    """OPCIONAL (F5): línea o polígono digitalizado del deterioro dentro de una ROI. Si no existe, la
    validación usa el rectángulo de la ROI como referencia gruesa."""
    __tablename__ = "geometria_referencia"
    id: Mapped[int] = mapped_column(primary_key=True)
    roi_id: Mapped[int] = mapped_column(ForeignKey("roi.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(10))                      # 'linea' | 'poligono'
    puntos_px: Mapped[list] = mapped_column(JSON)
    origen: Mapped[Optional[str]] = mapped_column(String(20))


# ===================================================================================== Análisis (Ficha 6)
class EjecucionAnalisis(Base):
    __tablename__ = "ejecucion_analisis"
    id: Mapped[int] = mapped_column(primary_key=True)
    tramo_id: Mapped[int] = mapped_column(ForeignKey("tramo.id", ondelete="CASCADE"), index=True)
    roi_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roi.id", ondelete="SET NULL"), index=True)
    alcance: Mapped[str] = mapped_column(String(10))                   # tramo | roi | ventana
    metodo: Mapped[str] = mapped_column(String(20), default="actual")  # actual | sun
    x0: Mapped[int] = mapped_column(Integer)
    y0: Mapped[int] = mapped_column(Integer)
    x1: Mapped[int] = mapped_column(Integer)
    y1: Mapped[int] = mapped_column(Integer)
    params_json: Mapped[dict] = mapped_column(JSON)                    # valores exactos usados (reproducible)
    params_version: Mapped[int] = mapped_column(Integer)
    params_huella: Mapped[str] = mapped_column(String(20))
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)   # umbrales aún no calibrados con datos reales
    preprocesamiento: Mapped[str] = mapped_column(String(2), default="Sí")
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    duracion_s: Mapped[Optional[float]] = mapped_column(Float)
    n_teselas: Mapped[Optional[int]] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(12), default="completada")
    mensaje: Mapped[Optional[str]] = mapped_column(Text)
    # calidad de imagen (Ficha 6 / Tabla de variables)
    calidad: Mapped[Optional[str]] = mapped_column(String(15))
    nitidez: Mapped[Optional[float]] = mapped_column(Float)
    brillo_medio: Mapped[Optional[float]] = mapped_column(Float)
    fraccion_saturada: Mapped[Optional[float]] = mapped_column(Float)
    resolucion_cm_px: Mapped[Optional[float]] = mapped_column(Float)
    cobertura_pct: Mapped[Optional[float]] = mapped_column(Float)
    calzada_util_pct: Mapped[Optional[float]] = mapped_column(Float)
    advertencias: Mapped[Optional[str]] = mapped_column(Text)
    tramo: Mapped[Tramo] = relationship(back_populates="ejecuciones")
    detecciones: Mapped[List["Deteccion"]] = relationship(back_populates="ejecucion", cascade="all, delete-orphan",
                                                          passive_deletes=True)
    caracteristicas: Mapped[List["CaracteristicaROI"]] = relationship(cascade="all, delete-orphan",
                                                                      passive_deletes=True)
    __table_args__ = (
        CheckConstraint("estado IN ('completada', 'cancelada', 'error')", name="ck_ejecucion_estado"),
        CheckConstraint("alcance IN ('tramo', 'roi', 'ventana')", name="ck_ejecucion_alcance"),
    )


class RendimientoEjecucion(Base):
    """F7: RAM adicional medida durante una ejecución (el tiempo está en EjecucionAnalisis.duracion_s). Tabla aparte para
    no alterar el esquema v1: `create_all` la agrega a las bases ya existentes."""
    __tablename__ = "rendimiento_ejecucion"
    ejecucion_id: Mapped[int] = mapped_column(ForeignKey("ejecucion_analisis.id", ondelete="CASCADE"), primary_key=True)
    ram_base_mb: Mapped[Optional[float]] = mapped_column(Float)
    ram_pico_mb: Mapped[Optional[float]] = mapped_column(Float)
    ram_adicional_mb: Mapped[Optional[float]] = mapped_column(Float)


class Deteccion(Base):
    __tablename__ = "deteccion"
    id: Mapped[int] = mapped_column(primary_key=True)
    ejecucion_id: Mapped[int] = mapped_column(ForeignKey("ejecucion_analisis.id", ondelete="CASCADE"))
    roi_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roi.id", ondelete="SET NULL"))
    tipo: Mapped[str] = mapped_column(String(20))
    geom_tipo: Mapped[Optional[str]] = mapped_column(String(20))
    geom_px: Mapped[Optional[list]] = mapped_column(JSON)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
    cx: Mapped[float] = mapped_column(Float)
    cy: Mapped[float] = mapped_column(Float)
    este: Mapped[Optional[float]] = mapped_column(Float)               # centroide en el mapa (si hay georreferencia)
    norte: Mapped[Optional[float]] = mapped_column(Float)
    progresiva_m: Mapped[Optional[float]] = mapped_column(Float)
    lado_via: Mapped[Optional[str]] = mapped_column(String(10))
    longitud_m: Mapped[Optional[float]] = mapped_column(Float)
    ancho_mm: Mapped[Optional[float]] = mapped_column(Float)           # solo grietas lineales
    ancho_m: Mapped[Optional[float]] = mapped_column(Float)            # solo baches
    area_m2: Mapped[Optional[float]] = mapped_column(Float)
    area_px: Mapped[Optional[int]] = mapped_column(Integer)
    pct_area_afectada: Mapped[Optional[float]] = mapped_column(Float)  # area_m2 / área de la ROI (si se conoce)
    angulo_img_deg: Mapped[Optional[float]] = mapped_column(Float)
    angulo_eje_deg: Mapped[Optional[float]] = mapped_column(Float)
    desv_eje_deg: Mapped[Optional[float]] = mapped_column(Float)
    contraste_weber: Mapped[Optional[float]] = mapped_column(Float)
    ramificada: Mapped[Optional[bool]] = mapped_column(Boolean)
    n_celdas: Mapped[Optional[int]] = mapped_column(Integer)
    celda_media_m2: Mapped[Optional[float]] = mapped_column(Float)
    densidad_pct: Mapped[Optional[float]] = mapped_column(Float)
    solidez: Mapped[Optional[float]] = mapped_column(Float)
    severidad_prelim: Mapped[Optional[str]] = mapped_column(String(30))   # ORIENTATIVA
    metodo_ancho: Mapped[Optional[str]] = mapped_column(String(30))
    advertencia: Mapped[Optional[str]] = mapped_column(Text)
    metodo: Mapped[str] = mapped_column(String(20), default="actual")
    ejecucion: Mapped[EjecucionAnalisis] = relationship(back_populates="detecciones")
    __table_args__ = (Index("ix_deteccion_ejec_tipo", "ejecucion_id", "tipo"), Index("ix_deteccion_roi", "roi_id"))


class CaracteristicaROI(Base):
    """Estadísticos R, G, B (media/mín/máx/desv.) y textura GLCM de una ROI en una ejecución."""
    __tablename__ = "caracteristica_roi"
    id: Mapped[int] = mapped_column(primary_key=True)
    ejecucion_id: Mapped[int] = mapped_column(ForeignKey("ejecucion_analisis.id", ondelete="CASCADE"), index=True)
    roi_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roi.id", ondelete="CASCADE"))
    valores: Mapped[dict] = mapped_column(JSON)                        # R_media, ..., tex_entropia


# ===================================================================================== Validación (F5)
class Validacion(Base):
    __tablename__ = "validacion"
    id: Mapped[int] = mapped_column(primary_key=True)
    ejecucion_id: Mapped[int] = mapped_column(ForeignKey("ejecucion_analisis.id", ondelete="CASCADE"), index=True)
    roi_id: Mapped[int] = mapped_column(ForeignKey("roi.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(20))
    vp: Mapped[int] = mapped_column(Integer, default=0)
    fp: Mapped[int] = mapped_column(Integer, default=0)
    fn: Mapped[int] = mapped_column(Integer, default=0)
    vn: Mapped[int] = mapped_column(Integer, default=0)
    solape: Mapped[Optional[float]] = mapped_column(Float)
    umbral_solape: Mapped[Optional[float]] = mapped_column(Float)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_ahora)


class Configuracion(Base):
    __tablename__ = "configuracion"
    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[Optional[object]] = mapped_column(JSON)
