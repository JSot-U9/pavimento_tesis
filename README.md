# Detección de deterioros en pavimentos flexibles (RGB) — herramienta de apoyo a la tesis

Tesis: *Metodología para la detección de deterioros y fallas estructurales en pavimentos flexibles de zonas
altoandinas mediante bandas RGB y procesamiento en Python* (UNSAAC, Cusco, 2026).

> Es una herramienta de **apoyo**. La severidad oficial es la de la ficha de campo; la `severidad_prelim` del
> programa es solo orientativa. Los umbrales calibrados con imágenes sintéticas son **provisionales**
> (ver `Params.provisionales()`): deben recalibrarse con los ortomosaicos reales antes de usarlos como evidencia.

## Estado: Fase 4 de 7 (interfaz, visor y procesamiento en segundo plano)

| Fase | Contenido | Estado |
|---|---|---|
| F1 | Plan, carpetas, esquema de BD | aprobada |
| F2 | Núcleo: motor modular, lectura por ventanas, ancho corregido, eje de vía local | hecha |
| F3 | Modelos de BD, `logica_*` de tramos/fichas/ROI/detección, importadores CSV/GeoJSON/GPKG | hecha |
| **F4** | **UI Tkinter/ttk + visor por ventanas + procesamiento en segundo plano** | **hecha (este código)** |
| F5 | Validación, calibración, estadística comparativa | pendiente |
| F6 | Reportes PDF/XLSX/CSV, exportación a QGIS, pulido | pendiente |
| F7 | Algoritmo de Sun y comparación de métodos | pendiente |

Ya existen `main.py`, la interfaz (`app/ui/`) y `app/tareas.py`. **Todavía no hay** validación, estadística, reportes, exportación a QGIS ni el método 'sun' (F5–F7).

## Instalación y pruebas

```
pip install -r requirements.txt
pytest                 # 186 con pantalla; sin pantalla se omiten 8 (las de widgets con Tk). ~1 min
xvfb-run -a pytest     # Linux sin pantalla: ejecuta también las 8 pruebas de widgets
pytest -m lento        # además: vía de 100 000 x 2 000 px (~1 min), mide el pico de RAM
python main.py [--bd RUTA]               # abre la aplicación (BD: --bd > $PAVIMENTO_BD > ./datos/pavimento.db)
xvfb-run -a -s "-screen 0 1440x900x24" python scripts/captura_pantallas.py   # recorre la UI y guarda capturas/ (requiere Pillow)
```
Requiere **Tkinter** (Windows: viene con Python; Linux: `sudo apt install python3-tk`). Pillow solo se usa en el script de capturas.

## Uso de la aplicación (F4)

`python main.py` abre la ventana (sin login). Arriba se elige el **tramo activo**; las pestañas lo comparten.

| Pestaña | Qué hace |
|---|---|
| **Tramos** | CRUD de la Ficha 1 (formulario generado desde `esquema_tramo`), asignar ortomosaico (GSD/EPSG si el archivo no los trae), eje de vía (importar CSV/GeoJSON/GPKG o dibujarlo en el visor) |
| **Fichas** | Vuelos, condiciones ambientales, GCP, catálogo, inspecciones y patologías (con geometría y severidad); importación CSV con vista previa |
| **Análisis** | Visor + panel **ROI** (lista, formulario, roles calibración/prueba, importación con vista previa) + panel **Análisis** (alcance, método, parámetros, Analizar/Cancelar) + tabla de detecciones, resumen por tipo y medidas de la detección elegida |

**Visor** (`app/ui/visor.py`): nunca carga el ortomosaico entero. Dibuja una miniatura (≤ 4 Mpx, calculada en un hilo) y
lee del archivo solo la zona visible, ya remuestreada al tamaño de pantalla (con GeoTIFF + rasterio la lectura decimada
usa las *overviews*: si el archivo no las tiene, créelas con `gdaladdo` o desde QGIS para acelerar la miniatura).
Herramientas: *Mover/seleccionar* (arrastrar; clic en una detección muestra sus medidas), *Dibujar ROI* (rectángulo),
*Dibujar eje* (clic = vértice; doble clic o Enter = terminar; Retroceso = quitar el último; Esc = cancelar), *Ventana de
análisis*. Rueda = zoom en el cursor; botón central = desplazar. Las detecciones usan `COLORES` del núcleo.
Medido con un GeoTIFF de 60 000 × 2 000 px: miniatura 1.7 s, zona 1:1 de 1200×840 px en 6 ms, zona decimada en 0.2 s.

**Segundo plano** (`app/tareas.py`): un hilo ejecuta SOLO `logica_deteccion.ejecutar_trabajo`; la UI sondea la cola con
`after` (100 ms) y, en el hilo principal, llama a `guardar_resultado` (o a `registrar_incidencia` si se canceló o falló).
Cancelar usa `threading.Event`. «Todas las ROI de un rol» encadena varios trabajos; si se cancela, el que corre se detiene
y los que esperaban se descartan. Los parámetros se editan en un diálogo con aviso PROVISIONAL y valen solo para la sesión.

## Uso del núcleo

```python
from app.nucleo.lectura import abrir
from app.nucleo.parametros import Params
from app.nucleo.eje_via import EjeVia
from app.nucleo.pipeline import analizar_region

lector = abrir("tramo1.tif")                              # GeoTIFF: lectura por ventanas (rasterio)
p = Params(gsd_cm=0.5)
eje = EjeVia(vertices_px=[(0, 1000), (50000, 1200), (100000, 900)], gsd_m=p.gsd_m)   # polilínea del eje
res = analizar_region(lector, (0, 0, lector.ancho, lector.alto), p, eje=eje,
                      progreso=lambda f, t: print(f"{f:.0%} {t}"))
for d in res.detecciones:
    print(d.tipo, d.progresiva_m, d.longitud_m, d.ancho_mm, d.ancho_m, d.area_m2)
print(res.calidad)
```

`analizar_region` acepta un ROI (`(x0, y0, x1, y1)`) o el ortomosaico completo, un `threading.Event` para
cancelar y un `metodo` ('actual'; 'sun' llegará en la F7).

## Uso de la capa de datos (F3)

```python
from app import basedatos, logica_tramos, logica_importacion, logica_roi, logica_deteccion

basedatos.inicializar("datos/pavimento.db")                       # crea el esquema y siembra el catálogo
logica_tramos.crear_tramo({"codigo": "T1", "progresiva_ini_m": 0, "progresiva_fin_m": 1000})
logica_tramos.asignar_ortomosaico("T1", "orto_t1.tif")             # GeoTIFF: toma GSD, georreferencia y EPSG
logica_importacion.importar_eje("T1", "eje.gpkg")                  # capa de 1 línea exportada de QGIS
rep = logica_importacion.importar_rois("T1", "rois.gpkg", simular=True)   # vista previa; luego sin simular
logica_roi.asignar_roles("T1", proporcion_calibracion=0.5, semilla=42)    # reparto calibración / prueba
ejecuciones = logica_deteccion.analizar_rois("T1", rol="calibracion")
```

- Todas las funciones `logica_*` devuelven **diccionarios** (las vistas no importan modelos). Los errores de datos
  son `ErrorValidacion` (con `.errores = {campo: mensaje}`, todos juntos) o `ErrorNoEncontrado`.
- **Hilos**: `preparar_analisis` y `guardar_resultado` van en el hilo principal; `ejecutar_trabajo` (solo núcleo) es el
  que se pone en un hilo en la F4.
- **Importadores** (`logica_importacion`): ROI (CSV en px —formato del motor anterior—, CSV en coordenadas, GeoJSON,
  GPKG), eje de vía, fichas (`vuelo`, `condicion`, `gcp`, `catalogo`, `inspeccion`) y patologías (F2+F3+F4 en un CSV).
  `simular=True` es una vista previa fiel (deshace todo); `estricto=True` (defecto) no importa nada si una fila falla.
  CSV: UTF-8 o Windows-1252, separador `,` `;` o tab, coma decimal. Capas: se convierten al EPSG del ortomosaico
  (4326 ↔ UTM WGS84, en Python puro, error < 1 mm contra pyproj).

## Qué se verificó (datos sintéticos; no hay aún datos reales)

| Criterio | Resultado |
|---|---|
| Ortomosaico de 100 000 × 2 000 px (GeoTIFF real, rasterio) | pico **635 MB** de RAM, 42 s, 10/10 grietas |
| Mismo tamaño, lector sintético sin archivo | pico **545 MB**, 52 s |
| Ancho de grieta, anchos conocidos 15–60 mm (3–12 px) | error ≤ 2 mm (< 0.4 px), con contraste alto y bajo |
| Ancho en el límite de 2 px (10 mm) | sobrestima ~2 mm (límite del método); < 2 px se marca «no resoluble» |
| Piel de cocodrilo | ya no reporta `ancho_mm` (antes 1695); reporta área, n.º de celdas, densidad |
| Eje con curva en L | clasificación correcta con ángulo local; el ángulo único (motor anterior) clasifica mal |
| Calidad de imagen sintética nítida | «Adecuada» (antes «No adecuada» por un umbral de nitidez en 20) |
| Mismo resultado con teselas de 1000 / 600 px y con una sola | longitudes, anchos, áreas y celdas coinciden |

### Sobre el «1.6x» de sobreestimación del ancho
En `generar_ejemplo.py` las polilíneas de grosor 5 y 4 se dibujan realmente con **35.1 y 25.0 mm** (área
dibujada / longitud), no 25 y 20 mm. Contra esa verdad, el motor anterior sobrestimaba ~1.15–1.2x
(40 y 29–31 mm) y el método nuevo da 34.7 y 25.0 mm. Con grietas sintéticas de ancho exacto el sesgo del
motor anterior era de +2 a +4.5 mm (≈ 0.5–1 px).

### Verificación de la F3
| Criterio | Resultado |
|---|---|
| UTM ↔ WGS84 (`crs.py`) frente a pyproj, 400 puntos aleatorios en 3 zonas | error máx. 0.0002 mm (directo) y 0.003 mm (ida y vuelta) |
| GeoPackage y GeoJSON escritos por GDAL (`tests/datos/oraculo.*`) | se leen con polígonos con agujero, multilíneas y puntos |
| ROI importada en WGS84 desde GeoJSON sobre un GeoTIFF UTM 32719 | coincide con la ROI en píxeles (±1 px) |
| Importación estricta / parcial / simulada | atómica; la simulación no deja rastro |
| Análisis de punta a punta (CSV → BD → detecciones) sobre las 5 ROI sintéticas | R01 transversal, R02 longitudinal, R03 piel de cocodrilo, R04 bache, R05 sin detecciones |
| Ejecución guardada con sus `Params` (JSON) | reproducible; marcada `provisional` hasta calibrar |

## Verificación de la F4
| Criterio | Resultado |
|---|---|
| `pytest` completo | **186 pasan** (142 anteriores + 44 nuevas); sin pantalla: 178 pasan y 8 se omiten |
| Ventana con DISPLAY virtual (xvfb) | abre, recorre las 3 pestañas, analiza ROI sintéticas desde la UI y selecciona detecciones con eventos de ratón reales |
| La UI no se congela | prueba con un trabajo lento: `analizar()` vuelve en < 0.5 s y el bucle de Tk sigue latiendo (huecos < 0.5 s) |
| Cancelar | detiene el hilo, deja una ejecución `cancelada` en la BD y restablece los botones |
| Capas | prueba AST: `app/ui` no importa `modelos`, `basedatos`, `sqlalchemy` ni `nueva_sesion`; presentadores y modelo del visor no importan Tk; `tareas.py` no importa Tk ni BD |
| Capturas | `capturas/*.png` (9 vistas) |

### Error encontrado y corregido en la F4
`<<TreeviewSelect>>` de Tk se entrega de forma **asíncrona**: una bandera «silencio» no basta y un cambio hecho por programa
disparaba el callback tarde, borrando el formulario (p. ej. al dibujar una ROI). `TablaTreeview` compara ahora con la
selección ya conocida (`widgets.py`; cubierto por `test_ui_humo.py`). No se modificó el núcleo ni `logica_*`.

## Supuestos y límites conocidos (F4)
- **No llegaron adjuntos el plan de la F1 ni la cervecera**: `estilos.py`, `widgets.py`, `ventana_principal.py` y
  `dialogo_reporte.py` están escritos desde cero siguiendo lo pedido (ttk, tema `clam`, sin ttkbootstrap ni paleta de
  cervecería). **Supuesto**: `dialogo_reporte.py` se usa como diálogo de informe de importación (vista previa/confirmar),
  porque en la F4 aún no hay reportes (F6). Si quiere conservar el aspecto de la cervecera, pásela y se adapta.
- **Validación por etapas en `logica_*`**: los formatos de un formulario se informan todos juntos, pero las reglas que
  dependen de la BD (código no está en el catálogo, ROI de otro tramo, «tipo obligatorio» de la ROI) las comprueba la
  lógica en una etapa posterior. Los presentadores unen las etapas donde es posible (patología + geometría + severidad;
  tipo de ROI); el resto aparece tras corregir los formatos.
- Los parámetros editados en el diálogo valen para la sesión; no se guardan como base (`guardar_params_base` queda para la F5).
- Los nodata del ortomosaico se ven negros en el visor. Un TIFF de 1–2 bandas o sin 3 bandas RGB se rechaza con mensaje.
- Sin rasterio, el visor usa el lector OpenCV del núcleo (decodifica la imagen completa; tope de 120 Mpx).
- Botón central = desplazar; en macOS el botón central/derecho puede numerarse distinto (no probado en macOS).
- Probado en Linux con xvfb y Python 3.12/Tk 8.6; **no probado en Windows** (se llama a `SetProcessDpiAwareness` solo allí).
- Al cerrar con un análisis en curso se cancela y espera hasta 8 s para registrar la incidencia.
- Cambiar de base de datos desde el menú exige que no haya análisis en curso.

## Supuestos y límites conocidos (F3)
- **Catálogo de patologías (Ficha 2)**: solo se siembran 4 códigos con equivalencia en el motor (`GLO`, `GTR`, `GPC`,
  `HUE`). **Supuesto** a confirmar: que esos códigos y significados son los de tu ficha. Los otros 17 se cargan con
  `importar_fichas('catalogo', csv)`.
- **Anchos de la Ficha 4 en mm** (también en baches); las detecciones guardan `ancho_m` solo para baches.
- **ROI**: el motor analiza el rectángulo envolvente; el polígono (si es una ROI rotada) se guarda solo como registro.
- `ROI.severidad_campo` es la copia de la capa GIS; la severidad **oficial** es la tabla `Severidad` (Ficha 3).
- `pct_area_afectada` = área de la detección / área de la ROI (solo si la detección cae en una ROI).
- Un PNG/JPG no tiene georreferenciación: solo admite ROI/eje en píxeles (`sistema='px'`).
- Sin migraciones aún (esquema v1): un cambio de esquema en fases futuras exigirá migrar o recrear la BD.
- CRS distintos de 4326 y WGS84/UTM (PSAD56, SIRGAS…) no se convierten: se pide reproyectar en QGIS.
- `umbral_concordancia` (kappa mínimo) viene en 0.60 por defecto: **confirmar con el asesor**.

## Supuestos y límites conocidos (núcleo, F2)
- **Longitud representativa de grietas** (piel de cocodrilo) = longitud total de grietas dentro de la zona.
- **Severidad**: de grietas lineales solo orientativa, con los criterios de la Ficha 3 (≤1 / 1–3 / >3 mm). A 0.5 cm/px
  el ancho no se resuelve por debajo de ~2 px (10 mm), así que casi toda grieta detectada saldrá «Alta»: los
  umbrales son configurables. Cocodrilo y baches no se estiman (criterios cualitativos / profundidad).
- **`ancho_sigma_px = 0.9`** (corrección de difuminado) está calibrado con sintéticos: debe contrastarse con
  mediciones de fisurómetro de la Ficha 4.
- Sin eje de vía el análisis asume eje horizontal y lo advierte.
- Una grieta fragmentada por bajo contraste sale en varias detecciones.
- El lector sin rasterio (OpenCV/Pillow) decodifica la imagen **completa**: se rechaza por encima de 120 Mpx
  con instrucciones para usar rasterio o convertir a GeoTIFF con teselas desde QGIS.
- Tesela mínima = 512 px o el doble del margen de contexto (1 m por defecto).
