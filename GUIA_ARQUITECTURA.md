# Guía de arquitectura (estado: Fase 2)

Regla de capas del proyecto completo: `ui → logica_* → modelos/basedatos`; el **núcleo** (`app/nucleo/`) no conoce
la BD ni la UI. Las vistas nunca importan modelos ni `nueva_sesion`; solo llaman a `logica_*`.
**Hoy solo existe el núcleo y sus pruebas** (BD, lógica y UI llegan en F3–F6).

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

## Pendiente
`modelos.py`, `basedatos.py`, `logica_*`, `ui/`, `main.py`, `sun.py`, importadores, reportes (F3–F7).
