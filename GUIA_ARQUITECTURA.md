# Guía de arquitectura (estado: Fase 6)

Regla de capas del proyecto completo: `ui → logica_* → modelos/basedatos`; el **núcleo** (`app/nucleo/`) no conoce
la BD ni la UI. Las vistas nunca importan modelos ni `nueva_sesion`; solo llaman a `logica_*`.
**Hoy existen el núcleo, la BD, la capa `logica_*`, la interfaz y el procesamiento en segundo plano** (validación, estadística y reportes llegan en F5–F6).

## Núcleo (`app/nucleo/`)

| Módulo | Responsabilidad |
|---|---|
| `parametros.py` | `Params` (dataclass versionada): valida, serializa a JSON, `huella()`, `con(**cambios)`, `aplicar_texto`; `PROVISIONALES` |
| `estructuras.py` | `Deteccion`, `Calidad`, `ResultadoAnalisis`, `AnalisisCancelado`, `ErrorLectura`; tabla indicador↔columna del cap. 3.2 |
| `lectura.py` | Lectores por ventanas con interfaz común: `LectorRasterio` (real), `LectorOpenCV` (completo, con tope), `LectorArray`; `abrir()` |
| `geo.py` | `Transformacion` afín píxel↔coordenadas (convención GDAL), sin depender de rasterio |
| `eje_via.py` | `EjeVia`: polilínea; `angulo_local_deg`, `progresiva_m`, `lado_via`, `distancia_lateral_m`, `desviacion_deg` |
| `calidad.py` | `mascara_valida`; calidad acumulada por teselas (`AcumuladorCalidad` → `consolidar`) |
| `preprocesado.py` | Normalización de iluminación (Sun 2009), MAD, utilidades |
| `medidas.py` | Longitud de esqueleto, contraste de Weber, **ancho por perfil de gris (FWHM)** con corrección de difuminado, respaldo por distancia |
| `grietas.py` | Black-hat + umbral mediana+k·MAD, esqueleto, orientación local, severidad orientativa |
| `cocodrilo.py` | Celdas → zonas; área, n.º de celdas, densidad, longitud (sin ancho) |
| `baches.py` | Regiones LAB distintas del pavimento local; longitud y ancho en m, área, contraste |
| `caracteristicas.py` | Estadísticos R, G, B y textura GLCM de una región |
| `fusion.py` | Une las piezas de grietas/cocodrilo cortadas por bordes de tesela |
| `pipeline.py` | `analizar_region()`: teselas, progreso, cancelación, calidad, fusión, progresiva; registro de métodos |

## Flujo de `analizar_region`

```
region ─► teselas (núcleo) ─► por cada una: leer ventana con margen
          ─► calidad (solo núcleo) ─► método.f(rgb, valido, p, eje, origen, nucleo)
          ─► conservar piezas con centroide en el núcleo, marcar bordes cortados
          ─► (al final) fusionar piezas ─► progresiva, lado de vía, area_px ─► ResultadoAnalisis
```
Solo hay una ventana en memoria a la vez: el pico de RAM no depende de la longitud del ortomosaico.
El margen (1 m) da contexto al procesamiento pero **no se mide**: así las teselas no se solapan.

## Contrato de un método de detección (para 'sun', F7)
`f(rgb, valido, params, eje, origen, nucleo=None) -> list[Deteccion]`, con coordenadas globales (`origen` es la
esquina de la ventana) y medición solo dentro de `nucleo`. Se registra con `pipeline.registrar_metodo(nombre, f)`.

## Cambios respecto al plan de la F1 (y por qué)
- **Lectura**: la cadena es rasterio → OpenCV (con tope), no rasterio → Pillow → OpenCV: Pillow tampoco permite
  lectura parcial de PNG/JPG, por lo que no aporta.
- **Módulos añadidos** al listado de la F1: `medidas.py`, `caracteristicas.py`, `fusion.py` (para mantener funciones
  cortas y separar responsabilidades).
- **Tesela mínima** (2 × margen): con teselas más pequeñas que el margen el recorte por núcleo degrada la detección.
- **`ttkbootstrap` se elimina** (no está en las dependencias permitidas); se hará en F4.
- La validación usará el **rectángulo de la ROI** como referencia (cobertura), no geometrías digitalizadas.

## Capa de datos (F3)

| Módulo | Responsabilidad |
|---|---|
| `modelos.py` | Esquema SQLAlchemy (17 tablas, ver F1); `Base.a_dict()` |
| `basedatos.py` | `inicializar(ruta)`, `nueva_sesion()` (commit/rollback), versión de esquema (`PRAGMA user_version`), claves foráneas y SAVEPOINT activos |
| `crs.py` | Conversión 4326 ↔ UTM WGS84 (Krüger) en Python puro |
| `geovector.py` | Lectura de GeoJSON y GeoPackage (parser WKB propio): sin shapely/fiona/GDAL |
| `logica_comun.py` | `Campo`/`validar` (todos los errores juntos), `ErrorValidacion`, lectura tolerante de CSV |
| `logica_tramos.py` | Ficha 1, ortomosaico (tamaño/GSD/transformación/EPSG), eje de vía (px o mapa) |
| `logica_fichas.py` | CRUD dirigido por esquema (`vuelo`, `condicion`, `gcp`, `catalogo`, `inspeccion`) y patologías con geometría y severidad |
| `logica_roi.py` | ROI, progresivas desde el eje, reparto calibración/prueba estratificado y reproducible, solapes |
| `logica_importacion.py` | ROI, eje, fichas y patologías desde CSV/GeoJSON/GPKG; `simular` y `estricto` |
| `logica_deteccion.py` | `preparar_analisis` → `ejecutar_trabajo` (hilo) → `guardar_resultado`; consultas |
| `logica_configuracion.py` | Parámetros base, tesela/margen, kappa mínimo, bandera `provisional` |

Reglas: el hilo de trabajo no toca la BD; las sesiones no se anidan (SQLite en memoria comparte la conexión);
los importadores usan `_crear*` con la sesión recibida y SAVEPOINT por fila.

## Cambios respecto al plan de la F1
- `lectura.py` ganó el atributo `epsg` (necesario para importar capas en otro CRS).
- `CaracteristicaROI.valores` guarda los estadísticos en un JSON (R/G/B + textura) en vez de 20 columnas.
- La ROI importada de un GPKG/GeoJSON se convierte a rectángulo; el polígono es solo registro.

## Interfaz y segundo plano (F4)

```
main.py ─► basedatos.inicializar(ruta) ─► ui.ventana_principal.VentanaPrincipal
ui/vista_*.py, panel_roi.py, dialogo_*.py   widgets (Tk/ttk)          ─┐ solo pintan y recogen texto crudo
ui/presentadores/p_*.py                      lógica de UI SIN Tk       ─┤ llaman a logica_* (dicts) → Resultado
app/tareas.py                                hilo + cola + Event       ─┘ sin Tk ni BD
```

| Módulo | Responsabilidad |
|---|---|
| `tareas.py` | `GestorTareas`: un hilo (`ejecutar_trabajo`), cola de `Mensaje` (inicio/progreso/resultado/cancelado/error/fin), `cancelar()` con `threading.Event`, `sondear()` sin bloqueo |
| `ui/estilos.py` | tema `clam`, paleta neutra, estilos con nombre; `hacer_dpi_consciente()` (Windows) |
| `ui/widgets.py` | `FormularioEsquema` (desde `esquema_*`; errores por campo + resumen con TODAS las líneas), `TablaTreeview`, `FrameDesplazable`, `Banner` |
| `ui/dialogo_reporte.py` | `DialogoInforme`, `DialogoImportar`, `flujo_importacion` (vista previa `simular=True` → confirmar → importar) |
| `ui/visor.py` | Canvas: miniatura + zona visible, zoom/pan, dibujo de ROI/eje/ventana, superposición de ROI, eje y detecciones, selección |
| `ui/visor_modelo.py` | geometría del visor sin Tk: escala, región visible, conversiones, hit-test de detecciones |
| `ui/imagen_visor.py` | `FuenteImagen` (miniatura y lectura decimada de zona) y `LectorAsincrono` (hilo del visor: solo lee imagen) |
| `ui/presentadores/` | `base` (`Resultado`, `proteger`, `Contexto`), `formularios`, `informe`, `p_tramos`, `p_fichas`, `p_roi`, `p_analisis` |
| `ui/vista_tramos.py`, `vista_fichas.py`, `vista_analisis.py`, `panel_roi.py`, `dialogo_parametros.py` | pestañas y paneles |

Reglas verificadas por `tests/test_ui_capas.py` (AST): las vistas no importan `modelos`/`basedatos`/`sqlalchemy`; presentadores y
modelo del visor no importan Tk; el núcleo y `logica_*` no importan la UI.

### Flujo de un análisis
```
UI (principal)  PresentadorAnalisis.iniciar ─► logica_deteccion.preparar_analisis (lee BD) ─► GestorTareas.iniciar
hilo "analisis" ejecutar_trabajo(trabajo, Event, progreso) ─► Mensaje en la cola     (no toca BD ni Tk)
UI (principal)  after(100 ms) ─► sondear(): progreso → barra · resultado → guardar_resultado (BD) · cancelado/error → registrar_incidencia
```
`Contexto` (tramo activo + eventos `tramos`, `rois`, `eje`, `ortomosaico`, `ejecuciones`, `fichas`, `bd`) mantiene sincronizadas las pestañas.
Las tablas (`TablaTreeview`) solo avisan cuando la selección difiere de la que la vista ya conoce (el evento de Tk es asíncrono).

## Cambios respecto al plan de la F1 (F4)
- `dialogo_reporte.py` se usa como informe de importación (aún no hay reportes). La cervecera no estaba disponible: los cuatro módulos reciclables se escribieron nuevos.
- Se añadió `panel_roi.py`, `dialogo_parametros.py`, `visor_modelo.py`, `imagen_visor.py` y la carpeta `presentadores/` para poder probar la lógica de la UI sin pantalla.

## Validación, calibración y estadística (F5)

```
ui/vista_validacion.py ─► p_validacion.py / p_calibracion.py ─► logica_validacion · logica_calibracion
ui/vista_estadistica.py ─► p_estadistica.py ───────────────────► logica_estadistica ─► graficos (Figure, sin pyplot)
```

| Módulo | Responsabilidad |
|---|---|
| `logica_validacion.py` | `evaluar(tramo, ejecucion_ids, rol, …)` → filas VP/FP/FN/VN por (ROI, tipo), totales, `provisional`, advertencias; guarda en `Validacion` (solo prueba, idempotente); bloquea solapes calibración/prueba; CRUD de `GeometriaReferencia`; `grupos_validados` / `ejecuciones_validadas` (última ejecución por ROI); núcleo puro: `clasificar_unidad`, `evaluar_roi`, `solape_dice`, `tipos_presentes` |
| `logica_calibracion.py` | `preparar_calibracion` (hilo principal, lee la BD → `PlanCalibracion`), `ejecutar_calibracion` (SIN BD: núcleo + cálculo puro, apta para el hilo de trabajo), `busqueda_coordenada` (pura, probada con óptimo conocido), `aplicar_calibracion(confirmar=True)` = único punto que llama a `guardar_params_base(calibrado=True)` |
| `logica_estadistica.py` | funciones puras (`wilson`, `metricas_binarias`, `kappa`, `matriz_confusion`, `error_medidas`, `mcnemar`, `ic_f1_bootstrap`) y consultas (`metricas_validacion`, `concordancia_tipo`, `concordancia_severidad`, `error_de_medidas`, `tablas_conteo`, `comparar_ejecuciones`, `comparacion_tramos` descriptiva entre tramos) |
| `graficos.py` | `fig_*` devuelven `matplotlib.figure.Figure` (sin pyplot): la UI las embebe y el PDF de la F6 las guardará con `savefig` |
| `tareas.py` | además de `GestorTareas`: `Calculo(etiqueta, funcion(cancelar, progreso))`, `ejecutar_calculo`, `gestor_de_calculos()` |
| `ui/widget_figura.py` | `VisorFigura` (`FigureCanvasTkAgg`, se adapta al hueco) |
| `ui/presentadores/p_validacion.py`, `p_calibracion.py`, `p_estadistica.py` | lógica de las pestañas sin Tk |

Reglas que se mantienen: la UI solo llama a `logica_*`; el hilo de trabajo no toca la BD (la calibración se **prepara** en el hilo
principal y solo corre núcleo en el hilo); devolver `None` (no 0) ante división por cero; todo resultado con ejecuciones provisionales
se rotula PROVISIONAL; `logica_estadistica` no depende de la UI (las funciones puras ni siquiera necesitan la BD).
`Contexto` gana los eventos `validacion` (nueva validación guardada) y `params` (parámetros base calibrados guardados).
`Configuracion` gana `umbral_solape`, `tolerancia_ref_m`, `objetivo_calibracion` y `estadistica_avanzada` (la UI oculta McNemar, Bland-Altman, correlaciones, pruebas pareadas y el IC bootstrap del F1 salvo que sea True; la lógica los calcula siempre).

### Flujo de una calibración
```
UI (principal)  PresentadorCalibracion.iniciar ─► logica_calibracion.preparar_calibracion (lee BD, solo ROI de calibración)
                                                 ─► gestor_de_calculos().iniciar([Calculo(ejecutar_calibracion)])
hilo            búsqueda por coordenadas: por candidato, ejecutar_trabajo en cada ROI de calibración (sin BD)
UI (principal)  sondear(): progreso · resultado (antes/después) ─► el usuario confirma ─► aplicar_calibracion ─► guardar_params_base(calibrado=True)
```

## Cambios respecto al plan de la F1 (F5)
- Validación por unidad (ROI, tipo) con presencia por ROI como método principal; la geometría de referencia es opcional (Dice con tolerancia).
- Tres claves nuevas en `Configuracion`; el esquema de BD (v1) no cambia: `Validacion` y `GeometriaReferencia` ya existían.
- Corrección de la F4: el visor trata `poligono_aprox` como polígono (ver README).

## Reportes, exportación y respaldo (F6)
- `logica_reportes.recopilar(...)` junta todo en un único dict `datos` (lee la BD, **hilo principal**); `reportes_tablas.py` es la única
  fuente de columnas y filas; `reportes_pdf.py` (reportlab + figuras de `graficos.py`) y `reportes_xlsx.py` (openpyxl) solo escriben.
  `escribir_reportes(datos, ...)` no toca BD ni Tk y corre en `tareas.gestor_de_calculos()` mediante `Calculo`.
- `logica_estadistica.tablas_conteo(..., excluir_fp=True)` filtra las detecciones de unidades FP del conteo sin borrarlas.
- `logica_exportacion.py`: GPKG con sqlite3 (OGC 12-128r18, WKB little endian, cabecera GP con envolvente, WKT1 UTM); GeoJSON; `verificar_gpkg` relee con `leer_gpkg`.
- `logica_respaldo.py` (API de respaldo de SQLite, copia diaria, rotación, restauración con copia previa), `registro.py` (RotatingFileHandler 1 MB × 5,
  excepthooks, env `PAVIMENTO_LOG`), `errores.py` (mensajes amigables), `main.py` los une.
- Capas: `ui/vista_reportes.py` → `ui/presentadores/p_reportes.py` → `logica_*`. Vistas y presentadores no importan modelos ni sqlalchemy (`test_ui_capas.py`).
- Claves nuevas en `Configuracion`: `respaldo_automatico`, `respaldos_a_conservar`. El esquema de BD no cambia.

## Cambios respecto al plan de la F1 (F6)
- Corrección de la F5: leyenda de la gráfica de métricas (ver README). El núcleo no cambió.

## Pendiente
Método `sun.py` y su comparación (F7).
