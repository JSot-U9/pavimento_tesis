# Manual de usuario (breve)

Herramienta de apoyo a la tesis **«Metodología para la detección de deterioros y fallas estructurales en pavimentos
flexibles de zonas altoandinas mediante bandas RGB y procesamiento en Python»** (UNSAAC, 2026). Para instalarla vea
`INSTALACION.md`.

> **Dos reglas que conviene recordar**
> 1. La **severidad oficial** es la de la ficha de campo. La «severidad (ORIENTATIVA)» del programa solo sirve de apoyo.
> 2. Mientras los umbrales del motor no se calibren con ortomosaicos **reales**, todo resultado sale marcado
>    **PROVISIONAL**. No lo cite como evidencia final.

Los tres tramos de la tesis (≈ 1.2 km cada uno) se registran con los códigos **T1, T2 y T3**.

## El flujo completo

```
1 Tramo ─► 2 Ortomosaico ─► 3 Eje de vía ─► 4 ROI ─► 5 Fichas ─► 6 Análisis ─► 7 Validación ─► 8 Reportes
```
Arriba de la ventana está el **tramo activo**: todas las pestañas trabajan con el tramo elegido.

### 1 · Tramo (pestaña *Tramos*)
1. **Nuevo** → complete la Ficha 1 (código `T1`, vía, ubicación, progresivas, ancho de calzada…). Los errores se
   muestran **todos juntos**, junto al campo correspondiente.
2. **Guardar**. Repita para T2 y T3.

### 2 · Ortomosaico (pestaña *Tramos*)
1. Con el tramo elegido: **Asignar ortomosaico…** y elija el archivo (GeoTIFF, PNG o JPG).
2. Si el archivo no trae la resolución, el programa la pide (**GSD en cm/píxel**). Si no está georreferenciado
   verá un aviso: podrá trabajar, pero **no podrá exportar a QGIS con coordenadas del mapa**.
3. El programa nunca carga el ortomosaico entero: dibuja una miniatura y lee solo lo que se ve.

### 3 · Eje de vía (pestaña *Tramos* o el visor)
El eje es una polilínea a lo largo de la calzada; de él salen la **progresiva**, el **lado de la vía** y el ángulo con el
que se decide si una grieta es longitudinal o transversal.
- **Importar** desde CSV, GeoJSON o GeoPackage (de QGIS), o
- **Dibujar** en el visor (pestaña *Análisis* → herramienta *Dibujar eje*): clic = vértice, doble clic o Enter =
  terminar, Retroceso = quitar el último, Esc = cancelar.

### 4 · ROI (pestaña *Análisis*, panel ROI)
Una **ROI** es un rectángulo del ortomosaico donde el campo registró algo (o nada: tipo `sano`).
1. **Importar** las ROI desde la capa de QGIS (CSV/GeoJSON/GPKG) — hay **vista previa** con errores y advertencias antes de
   confirmar — o dibujarlas con *Dibujar ROI*.
2. Asigne el **rol**: *calibración* (se usan para ajustar los umbrales) o *prueba* (las únicas que cuentan en la
   validación). **Que no se solapen una de calibración con una de prueba**: el programa lo detecta y bloquea la validación.
   «Asignar roles» reparte automáticamente (estratificado y reproducible).

### 5 · Fichas (pestaña *Fichas*)
Vuelos UAV (F5), condiciones ambientales (F8), GCP (F9), inspecciones y **patologías** (F2) con su **severidad** (F3) y
**medidas de campo** (F4; el ancho siempre en **mm**). Vincule cada patología a su ROI. Estos datos son la referencia
contra la que se valida y aparecen en el reporte.

### 6 · Análisis (pestaña *Análisis*)
1. Elija el alcance: **ROI** seleccionada, **todas las ROI de un rol**, la **ventana** visible o el **tramo** entero.
2. **Analizar**. Corre en segundo plano: hay barra de progreso y **Cancelar**.
3. Resultados: tabla de detecciones, resumen por tipo y medidas de la detección elegida. Si los parámetros siguen sin
   calibrar, todo dice **PROVISIONAL**.

### 7 · Validación y estadística (pestañas *Validación* y *Estadística*)
1. **Validación → Validar y guardar**: compara lo detectado con el campo en las ROI de **prueba**. Para cada ROI y cada
   tipo resulta **una** de: VP (detectó y había), FP (detectó y no había), FN (no detectó y había), VN (ni había ni detectó).
   Los **FP y FN se registran** (se guardan por ROI y tipo).
2. **Calibración** (opcional, solo con las ROI de calibración): propone umbrales y muestra el *antes/después*.
   **No se guarda nada hasta que usted confirma**; después valide de nuevo con las ROI de prueba.
3. **Estadística**: sensibilidad, especificidad, precisión y concordancia (%) con **intervalo de Wilson al 95 %**;
   **kappa** (mínimo aceptable 0.60); error de las medidas contra la Ficha 4; Tablas 2-4; comparación descriptiva entre
   tramos. Un valor **n/d** significa «no hay casos para calcularlo» (nunca 0). Con **n < 5** el intervalo no es fiable.
   Las pruebas avanzadas (McNemar, Bland-Altman, correlaciones…) están ocultas; se muestran con la casilla de arriba.

### 8 · Reportes (pestaña *Reportes*)
**Reporte del tramo activo**
1. Marque los formatos: **PDF** (informe completo), **Excel** (una hoja por tabla, con filtros) y/o **CSV** (detecciones y
   validación). Escriba, si quiere, título, autor e institución para la portada.
2. Elija la **carpeta de destino**.
3. **Vista previa…** muestra qué ejecuciones se usan, cuántas detecciones hay, las **conclusiones** (solo cifras
   calculadas) y las advertencias. Si no hay validación, el reporte lo dice y **no emite conclusiones de desempeño**.
4. **Generar**. Al terminar aparecen los archivos; doble clic para abrirlos.

Detalles útiles:
- **Los falsos positivos no entran al conteo** de las Tablas 2-4 (casilla activa por defecto), pero **siguen registrados**:
  en el Excel/CSV de detecciones la columna «Incluida en el conteo» dice *No* y «Estado de validación» dice *FP*.
- **CSV para Excel en español**: marque la casilla para usar «;» como separador y la coma como decimal. Los CSV llevan
  codificación UTF-8 con BOM (las tildes se ven bien en Excel).
- Si un archivo no se puede escribir porque está **abierto en Excel o en el visor de PDF**, el programa lo dice y
  genera los demás; cierre el archivo y vuelva a generar.

**Exportar a QGIS**
1. Elija **GeoPackage** (un archivo con tres capas) o **GeoJSON** (un archivo por capa) y las capas: **detecciones**, **ROI**,
   **eje de vía**.
2. **Exportar…** El archivo queda en el **CRS del ortomosaico** (o en WGS84 si lo pide) y se verifica volviéndolo a leer.
3. En QGIS: *Capa → Añadir capa → Añadir capa vectorial*. Los atributos incluyen tipo, longitud, ancho, área, % de área
   afectada, progresiva, lado, severidad (ORIENTATIVA), estado de validación y si entra al conteo.
4. Sin georreferenciación no se exporta (se explica por qué). La opción «coordenadas de imagen» genera las capas en píxeles
   (con y invertida), que **no se superponen** a otras capas en QGIS.

**Respaldo de la base de datos**
- Se crea una **copia automática diaria** al abrir el programa (carpeta `respaldos` junto a la base de datos; se conservan las
  últimas 10). **Crear respaldo ahora** hace una copia manual; **Guardar copia en…** la escribe donde usted elija
  (por ejemplo, un pendrive).
- **Restaurar**: elija el respaldo y confirme. Antes de reemplazar, el programa guarda una copia de la base actual
  (`…_antes_de_restaurar.db`), así que nada se pierde.
- Haga una copia a otro disco **antes de cada salida a campo o de la entrega de resultados**.

## Si algo falla
- Los mensajes dicen **qué pasó y qué hacer** (archivo abierto en otro programa, disco lleno, memoria insuficiente…).
- Los detalles técnicos quedan en el **archivo de registro** (ruta en `INSTALACION.md`); adjúntelo si pide ayuda.
- El programa sigue abierto después de un error; sus datos guardados están en la base de datos y en `respaldos`.

## Glosario mínimo
| Término | Significado |
|---|---|
| ROI | región de interés (rectángulo) en el ortomosaico |
| Rol *calibración* / *prueba* | ROI para ajustar umbrales / ROI para medir el desempeño |
| VP, FP, FN, VN | verdadero positivo, falso positivo, falso negativo, verdadero negativo |
| Concordancia (%) | (VP + VN) / total × 100 |
| Kappa | acuerdo entre campo y programa descontando el azar (≥ 0.60 = aceptable) |
| IC de Wilson | intervalo de confianza al 95 % de una proporción |
| PROVISIONAL | calculado con umbrales aún no calibrados con datos reales |
| GSD | tamaño del píxel en el terreno (cm/píxel) |
