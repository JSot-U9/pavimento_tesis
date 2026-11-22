# pavimento_rgb — detección de deterioros en pavimentos flexibles con imágenes RGB

Programa asociado al plan de tesis *"Metodología para la detección de deterioros y fallas estructurales
en pavimentos flexibles de zonas altoandinas mediante bandas RGB y procesamiento en Python"*.

## Instalación
```
pip install -r requirements.txt
```

## Prueba rápida (datos sintéticos)
```
python generar_ejemplo.py ejemplo
python pavimento_rgb.py ejemplo/ortomosaico_sintetico.png --gsd 0.5 \
       --rois ejemplo/rois_ejemplo.csv --escaneo --tramo "Tramo de prueba" -o salida
```

## Uso con datos reales
```
python pavimento_rgb.py ortomosaico_tramo1.tif --gsd 0.5 --rois rois_tramo1.csv \
       --eje-via 0 --tramo "Av. Argentina - Tradecus Tours" -o salida_tramo1
```

| Opción | Significado |
|---|---|
| `--gsd` | Resolución en **cm/píxel** (se lee sola de un GeoTIFF proyectado si hay `rasterio`) |
| `--rois` | CSV de ROI de campo (ver abajo). Sin él, se analiza toda la imagen por teselas |
| `--escaneo` | Además de las ROI, analiza toda la imagen (las detecciones fuera de ROI quedan como `fuera_de_ROI`) |
| `--eje-via` | Ángulo del eje de la vía en la imagen, en grados (0 = horizontal, 90 = vertical) |
| `--margen-roi` | Contexto (m) alrededor de cada ROI; necesario para que los baches tengan pavimento de referencia |
| `--mascara-via` | PNG del mismo tamaño (blanco = calzada) para excluir bermas, veredas, etc. |
| `--param clave=valor` | Cambia cualquier umbral (ver clase `Params` en el código) |

### CSV de ROI de campo
Columnas: `codigo_roi, x, y, ancho, alto` (píxeles del ortomosaico) y opcionales
`tipo_campo, severidad_campo, tramo, imagen`.
`tipo_campo` admite: longitudinal, transversal, piel de cocodrilo, bache, sano.
Cada ROI debe corresponder a la ficha de campo (mismo `codigo_roi`), y conviene dibujarla con
un poco de pavimento sano alrededor. Se pueden obtener las coordenadas en QGIS.

## Qué calcula (ligado a la operacionalización de variables)
| Indicador de la tesis | Archivo / columna |
|---|---|
| Calidad de imagen (Adecuada / No adecuada), resolución cm/px, cobertura % | `calidad_imagen.csv` |
| Valores RGB (media, mín, máx, desv. estándar) y textura GLCM por ROI | `caracteristicas_roi.csv` |
| Presencia, número, longitud (m), ancho (mm), área (m²) | `detecciones.csv` |
| Clasificación longitudinal / transversal | `detecciones.csv` → `tipo`, `desv_eje_deg` |
| Contraste de la grieta respecto al pavimento | `detecciones.csv` → `contraste_weber` |
| Piel de cocodrilo: área afectada, n.º de celdas, densidad | `detecciones.csv` |
| Falsos positivos / negativos, concordancia %, kappa | `validacion_resumen.csv`, `validacion_roi.csv` |
| Imágenes anotadas | `anotadas/` |

Concordancia por tipo = VP / (VP + FP + FN). La validación es **por ROI**: una ROI de campo de tipo T
es VP si Python detecta T dentro de ella, FN si no; un tipo detectado que el campo no registró en esa
ROI cuenta como FP. El kappa compara la etiqueta de campo con la etiqueta dominante de Python
(bache > piel de cocodrilo > grieta de mayor longitud > sano).

## Método
1. **Preprocesamiento:** I − gauss(I) + media (normaliza iluminación, como Sun, 2009).
2. **Grietas:** black-hat morfológico + umbral robusto (mediana + k·MAD) + cierre morfológico para
   unir puntos de ruptura + esqueletonización. Longitud por esqueleto, ancho por transformada de
   distancia, orientación por PCA; |ángulo − eje| ≤ 45° → longitudinal, si no transversal.
3. **Piel de cocodrilo:** celdas cerradas (regiones rodeadas de grietas, < 0.09 m²); se agrupan y
   se exigen ≥ 4 celdas por zona.
4. **Baches:** regiones compactas cuya luminosidad/croma difiere del pavimento local (se excluyen
   marcas viales y se elimina lo delgado por apertura morfológica).

## Limitaciones (importantes para la tesis)
- **Resolución:** con GSD > 5 mm/px las grietas finas (< 10 mm) no se resuelven; el programa lo advierte.
- **Ancho de grieta:** es una estimación. En la prueba sintética salió ~1.5× mayor que el real.
  Calibrar con las mediciones del fisurómetro (Ficha 4).
- **Severidad:** `severidad_prelim` es solo orientativa (grietas lineales: ancho según ASTM D6433;
  cocodrilo: criterio propuesto; baches: requieren profundidad de campo). La severidad oficial es la
  de la ficha de campo. Verificar umbrales con la norma ASTM D6433-24.
- **Baches:** sombras, agua, parches y reparaciones pueden dar falsos positivos; una imagen RGB no da profundidad.
- **Umbrales** (nitidez, k·MAD, tamaños de celda y bache) están calibrados solo con datos sintéticos:
  deben ajustarse con imágenes reales de los tres tramos (prueba piloto) mediante `--param`.
- Los deterioros que cruzan el borde de una tesela del escaneo se asignan por su centro (no se duplican),
  pero pueden medirse parcialmente.
