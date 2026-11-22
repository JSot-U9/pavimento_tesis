# Prototipo original (referencia)

Esta carpeta guarda el **prototipo en un solo archivo** con el que se probó por primera vez la metodología, y de donde salió
el ejemplo sintético del tutorial:

| Archivo | Qué es |
|---|---|
| `generar_ejemplo.py` | Script original que dibuja el ortomosaico sintético y el CSV de ROI. **Hoy ese mismo código vive en `app/ejemplo_sintetico.py`** (misma imagen, píxel por píxel) y el tutorial lo usa. |
| `pavimento_rgb.py` | Prototipo de línea de comandos (detección + validación, sin base de datos ni interfaz). Lo reemplaza la aplicación (`main.py`); se conserva como referencia. |
| `salida_proto/` | Lo que produjo el prototipo con el ejemplo: CSV de calidad, detecciones, características, validación y una imagen anotada. |
| `README.md`, `requirements.txt` | Los del prototipo. |

No hace falta nada de esta carpeta para usar la aplicación ni el tutorial.
