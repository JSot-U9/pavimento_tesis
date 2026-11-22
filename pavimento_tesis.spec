# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller · pavimento_tesis (Windows, también válido en Linux).

    pip install pyinstaller
    pyinstaller --noconfirm pavimento_tesis.spec
    -> dist/pavimento_tesis/pavimento_tesis.exe   (carpeta «onedir»: copie la carpeta entera)

Se usa «onedir» (no «onefile»): arranca más rápido y los antivirus lo marcan menos. La BD y el registro NO van dentro
del paquete: la BD se crea donde se indique con --bd (por defecto ./datos/pavimento.db junto al .exe) y el registro en
%LOCALAPPDATA%\\pavimento_tesis\\logs. Ver INSTALACION.md.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

bloque = None
datos = []
datos += collect_data_files("matplotlib")                      # fuentes y estilos de matplotlib
datos += collect_data_files("reportlab")                       # fuentes estándar y plantillas de reportlab
datos += collect_data_files("skimage")
datos += [("ejemplo", "ejemplo")]                              # ejemplo sintético del tutorial (imagen, ROI y eje)
ocultos = []
ocultos += collect_submodules("sqlalchemy.dialects.sqlite")    # el dialecto se carga por nombre
ocultos += collect_submodules("skimage.morphology") + collect_submodules("skimage.measure")
ocultos += collect_submodules("scipy.special") + ["scipy.spatial.transform._rotation_groups"]
ocultos += ["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder", "openpyxl.cell._writer"]

excluir = ["pytest", "sklearn", "statsmodels", "geopandas", "pyogrio", "pypdf", "IPython", "notebook", "PyQt5", "PyQt6",
           "PySide2", "PySide6", "wx"]          # solo sirven para las pruebas o no se usan

a = Analysis(["main.py"], pathex=["."], binaries=[], datas=datos, hiddenimports=ocultos, hookspath=[],
             runtime_hooks=[], excludes=excluir, noarchive=False, cipher=bloque)
pyz = PYZ(a.pure, a.zipped_data, cipher=bloque)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pavimento_tesis", debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False)          # console=True si necesita ver mensajes de arranque
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="pavimento_tesis")
