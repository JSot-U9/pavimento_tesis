# Ejemplo sintético (lo usa el tutorial)

| Archivo | Contenido |
|---|---|
| `ortomosaico_sintetico.png` | Imagen de 2400 × 1400 px a 0.5 cm/px (una calzada de 12 m) con deterioros dibujados a propósito. |
| `rois_ejemplo.csv` | 5 ROI de «campo»: R01 grieta transversal, R02 grieta longitudinal, R03 piel de cocodrilo, R04 bache, R05 pavimento sano. |
| `eje_ejemplo.csv` | Eje de vía horizontal: de (0, 700) a (2400, 700) px. |

El tutorial copia estos archivos a su carpeta de práctica; **no se modifican**. Si faltan, el programa los vuelve a generar
(`python scripts/generar_ejemplo.py ejemplo` los regenera idénticos). Para probarlo: botón **Tutorial** del programa,
tecla **F1**, `tutorial.bat` (Windows) o `./tutorial.sh` (Linux/macOS).
