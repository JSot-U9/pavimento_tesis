"""
Regenera el ejemplo sintético del tutorial (imagen, ROI y eje) en una carpeta: idéntico al de `ejemplo/`.

    python scripts/generar_ejemplo.py            escribe en ./ejemplo
    python scripts/generar_ejemplo.py OTRA_CARPETA
"""
import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from app import ejemplo_sintetico                                  # noqa: E402

if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "ejemplo")
    for nombre, ruta in ejemplo_sintetico.generar(destino).items():
        print(f"{nombre:12s} {ruta}")
