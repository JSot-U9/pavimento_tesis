# Detección de deterioros en pavimentos flexibles (RGB) — herramienta de apoyo a la tesis

Tesis: *Metodología para la detección de deterioros y fallas estructurales en pavimentos flexibles de zonas
altoandinas mediante bandas RGB y procesamiento en Python* (UNSAAC, Cusco, 2026).

> Es una herramienta de **apoyo**. La severidad oficial es la de la ficha de campo; la `severidad_prelim` del
> programa es solo orientativa. Los umbrales calibrados con imágenes sintéticas son **provisionales**
> (ver `Params.provisionales()`): deben recalibrarse con los ortomosaicos reales antes de usarlos como evidencia.

## Estado: Fase 2 de 7 (núcleo de visión)

| Fase | Contenido | Estado |
|---|---|---|
| F1 | Plan, carpetas, esquema de BD | aprobada |
| **F2** | **Núcleo: motor modular, lectura por ventanas, ancho corregido, eje de vía local** | **hecha (este código)** |
| F3 | Modelos de BD, `logica_*` de tramos/fichas/ROI, importadores CSV/GeoJSON/GPKG | pendiente |
| F4 | UI Tkinter reciclada + visor + procesamiento en segundo plano | pendiente |
| F5 | Validación, calibración, estadística comparativa | pendiente |
| F6 | Reportes PDF/XLSX/CSV, exportación a QGIS, pulido | pendiente |
| F7 | Algoritmo de Sun y comparación de métodos | pendiente |

Todavía **no existen** `main.py`, base de datos, interfaz ni reportes. Lo que hay es `app/nucleo/` y sus pruebas.

## Instalación y pruebas

```
pip install -r requirements.txt
pytest                 # 75 pruebas, ~25 s
pytest -m lento        # además: vía de 100 000 x 2 000 px (~1 min), mide el pico de RAM
```

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

## Supuestos y límites conocidos
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
