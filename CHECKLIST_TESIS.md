# Checklist final de la tesis (cierre del proyecto, Fase 7)

> Estado de la herramienta: F1–F7 completas. Todo lo que hoy produce el programa se calculó con **datos sintéticos** y
> parámetros **PROVISIONALES**: sirve para demostrar el procedimiento, **no como evidencia**. La evidencia de la tesis sale de repetir
> el flujo con los ortomosaicos reales de **T1, T2 y T3** (≈ 1.2 km cada uno).
>
> Supuesto: agrupé los objetivos según el plan de tesis que leí (detección, medición, validación contra campo, comparación entre
> tramos, comparación de métodos). Ajuste los nombres a la redacción exacta de sus objetivos específicos.

## 1. Evidencia que genera cada módulo, por objetivo

| Objetivo | Módulo / pestaña | Evidencia que produce | Dónde queda |
|---|---|---|---|
| **Detectar deterioros** en ortomosaicos RGB | `nucleo/` (método 'actual'), pestaña *Análisis* | Detecciones por tipo (longitudinal, transversal, piel de cocodrilo, bache…), geometría, progresiva | tablas `detecciones`, GPKG/GeoJSON, hoja Detecciones |
| **Medir** longitud, ancho y área | `nucleo/ancho.py`, `grietas.py`, `bache.py` | Longitud (m), ancho (mm, corregido por GSD), área (m²), severidad **orientativa** | misma tabla; Tablas 2-4 en reportes |
| **Registrar la verdad de campo** | pestaña *Fichas*, importadores | Ficha 7 y geometría de referencia por ROI | `fichas`, `geometria_referencia` |
| **Validar** (nº detectado, FP, FN, concordancia %) | `logica_validacion`, pestaña *Validación* | VP/FP/FN/VN por ROI y tipo, concordancia (%), kappa (mín. 0.60) con IC de Wilson | `validaciones`, hoja Validación, PDF |
| **Calibrar umbrales** | `logica_calibracion` (ROI de rol *calibración*) | Antes/después de F1/sensibilidad/precisión por umbral; huella de Params usada | `calibraciones`, figura en PDF |
| **Comparar los tres tramos** (descriptivo) | `logica_estadistica.comparacion_tramos`, pestaña *Estadística* | Tablas 2-4 por tramo (FP excluidos del conteo, pero registrados) | hojas Tablas, PDF |
| **Comparar métodos** 'actual' vs 'sun' | `nucleo/sun.py`, `logica_comparacion`, pestaña *Métodos* | Métricas por método, McNemar, diferencias de medida (Bland-Altman), tiempo y RAM, conclusión con cifras | hojas «Métodos …», bloque en el PDF |
| **Reproducibilidad / trazabilidad** | `Params` versionados, huella, `ejecucion_analisis`, `rendimiento_ejecucion` | Cada resultado conserva método, Params, versión, duración y RAM | BD y registro (`log`) |
| **Eficiencia sobre ortomosaicos largos** | `scripts/comparar_rendimiento`, `tests/test_memoria.py` | 100 000 × 2 000 px: actual 491 MB / 74 s; sun 459 MB / 100 s (sintético) | salida del script |
| **Entrega y respaldo** | *Reportes*, GPKG, respaldo | PDF/XLSX/CSV, capas QGIS, copia de la BD | carpeta de salida, `respaldos/` |

## 2. Qué falta recalibrar con ortomosaicos reales de T1–T3

Todo lo siguiente está marcado PROVISIONAL en `Params.provisionales()` y debe ajustarse con las ROI de **calibración**
(y medirse después solo con las de **prueba**, sin reutilizarlas):

1. **GSD real** de cada ortomosaico (`gsd_cm`), y la alineación eje de vía–ortomosaico.
2. Umbrales del método 'actual' (black-hat, `grieta_k_mad`, tamaños mínimos, tolerancia de orientación longitudinal/transversal,
   criterios de piel de cocodrilo y baches, calidad de imagen).
3. Parámetros del método 'sun': `sun_alfa` (0.2247), `sun_beta` (40), `sun_contraste_min` (25) y las cinco distancias `sun_*_m`
   (convertidas desde píxeles de Sun suponiendo ≈ 0.8 cm/px).
4. Umbrales de severidad **orientativa** (la oficial es la de la ficha de campo).
5. Tolerancia de comparación con la referencia (`tolerancia_ref_m`) y umbral de solape (`umbral_solape`).
6. Medidas de **tiempo y RAM** en el equipo real donde se usará la herramienta (`python -m scripts.comparar_rendimiento --ortomosaico …`).
7. Confirmar que ≥ 10 unidades (ROI × tipo) por tramo: con menos, McNemar y los IC no concluyen nada.

## 3. Decisiones pendientes

| # | Decisión | Quién | Estado |
|---|---|---|---|
| 1 | Resolución real de las imágenes de Sun (¿≈ 0.8 cm/px?) para fijar las distancias `sun_*_m` | tesista | supuesto activo |
| 2 | Aceptar (o no) el tope de umbral `T ≤ media − sun_contraste_min` como mejora declarada en la tesis | tesista / asesor | usado por defecto; documentarlo en el texto |
| 3 | Si se citan estadísticos **más allá del plan** (McNemar, Bland-Altman, bootstrap): el plan pide análisis descriptivo y comparativo | asesor | ocultos en *Estadística*; la comparación de métodos los usa |
| 4 | Columnas exactas de la **Ficha 7** y de las **Tablas 2-4** | asesor | según el plan leído |
| 5 | Comparar solo los tipos que 'sun' detecta (grietas lineales) o tratar piel/baches como «no detectado» | tesista | hoy: solo tipos comunes |
| 6 | Qué ROI son de calibración y cuáles de prueba en cada tramo (nunca las mismas) | tesista | por definir al tener los datos |
| 7 | Probar el `.exe` (PyInstaller) en **Windows** | tesista | compilado y probado solo en Linux |
| 8 | Nombres, ubicación y progresivas de T1–T3, datos de campo | tesista | a cargar |
| 9 | Si la tesis exige otro formato de reporte (Ficha 7 en Excel con formato propio) | asesor | reporte genérico actual |

## 4. Cómo verificar que todo funciona antes de usar datos reales

```
xvfb-run -a pytest          # (o pytest en Windows/Linux con pantalla): suite completa
pytest -m lento             # vía de 100 000 x 2 000 px con ambos métodos
python -m scripts.comparar_rendimiento
```
Luego: crear T1–T3, asignar ortomosaico + eje + ROI, cargar fichas, calibrar con ROI de calibración, analizar/validar con las de prueba,
pestaña *Métodos* y *Reportes*. Lo que salga con la marca PROVISIONAL debe desaparecer solo cuando los parámetros estén calibrados con datos reales.
