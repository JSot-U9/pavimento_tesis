# Instalación en Windows (y Linux)

Herramienta de apoyo a la tesis «Detección de deterioros en pavimentos flexibles con ortomosaicos RGB». Funciona sin
internet. Hay dos formas de instalarla: **desde el código** (recomendada mientras la tesis esté en desarrollo) o
**como programa empaquetado** (`.exe`, sin instalar Python).

## A. Desde el código (Python)

1. **Instale Python 3.10 o superior** desde <https://www.python.org/downloads/>. En el instalador marque
   **«Add python.exe to PATH»** y, en «Customize installation», deje marcado **«tcl/tk and IDLE»** (es Tkinter, la
   interfaz). Compruebe en una consola (`Win + R` → `cmd`):
   ```
   python --version
   python -c "import tkinter; print('Tkinter OK')"
   ```
2. **Descomprima** `pavimento_tesis_F6.zip` en una carpeta sin espacios ni tildes, por ejemplo `C:\tesis\pavimento_tesis`.
3. **Cree un entorno virtual e instale las librerías** (una sola vez, necesita internet):
   ```
   cd C:\tesis\pavimento_tesis
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   Opcional, para leer GeoTIFF por ventanas y georreferenciar el ortomosaico (ver `README.md`): `pip install rasterio`.
4. **Compruebe la instalación**: `python -m pytest -q` (deben pasar todas; las que necesitan pantalla o librerías
   opcionales se omiten solas).
5. **Abra el programa**: `python main.py` (o `python main.py --bd D:\tesis\pavimento.db` para elegir dónde queda la base
   de datos).

En Linux: `sudo apt install python3-tk` y los mismos pasos con `source .venv/bin/activate`.

## B. Programa empaquetado (`.exe`) con PyInstaller

Se genera **una vez**, en un Windows con la instalación A funcionando:

```
.venv\Scripts\activate
pip install pyinstaller
pyinstaller --noconfirm pavimento_tesis.spec
```

El resultado es la carpeta `dist\pavimento_tesis\`. **Cópiela entera** (no solo el `.exe`) a otro equipo y abra
`pavimento_tesis.exe`. No necesita Python en el equipo de destino.

> **Estado de esta verificación:** el `.spec` **se compiló en Linux** y el ejecutable resultante abrió y creó su registro
> bajo pantalla virtual, pero **no se probó en Windows**. Si el `.exe` falla al arrancar con «No module named …», agregue ese módulo a
> `ocultos` en `pavimento_tesis.spec`, o cambie `console=False` por `console=True` para ver el mensaje, y vuelva a
> empaquetar. Mientras tanto, la opción A es la que está probada.

## Dónde queda cada cosa

| Qué | Dónde |
|---|---|
| Base de datos | donde indique `--bd`; por defecto `datos\pavimento.db` dentro de la carpeta desde la que abre el programa (o la variable de entorno `PAVIMENTO_BD`) |
| Respaldos | carpeta `respaldos\` junto al archivo `.db` (copia diaria automática al abrir; se conservan las últimas 10) |
| Registro de errores | `%LOCALAPPDATA%\pavimento_tesis\logs\pavimento_tesis.log` (Linux: `~/.local/state/pavimento_tesis/logs`); cambie la carpeta con `--log-dir` o `PAVIMENTO_LOG_DIR` |
| Reportes y exportaciones | la carpeta que elija en la pestaña **Reportes** |

## Problemas frecuentes

| Mensaje o síntoma | Causa y solución |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Reinstale Python marcando «tcl/tk and IDLE» (Linux: `sudo apt install python3-tk`). |
| `No module named 'reportlab'` / `'openpyxl'` | Falta `pip install -r requirements.txt` (con el entorno virtual activado). |
| «El archivo está abierto en otro programa» al generar un reporte | Cierre el Excel o el visor de PDF que tiene abierto el archivo anterior y vuelva a generar. |
| «Esquema más nuevo que el del programa» al abrir la BD | La base de datos la creó una versión más reciente del programa: actualice el programa o restaure un respaldo. |
| El programa no abre y no hay ventana | Revise el registro (ruta arriba) o ejecute `python main.py` desde la consola para ver el mensaje. |
| La ventana se ve muy pequeña/borrosa en pantallas de alta resolución | Clic derecho en `python.exe`/`pavimento_tesis.exe` → Propiedades → Compatibilidad → «Cambiar la configuración de PPP alto». |
