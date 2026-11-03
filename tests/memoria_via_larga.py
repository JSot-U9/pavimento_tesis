"""
Script de medición (lo usa tests/test_memoria.py): procesa una vía sintética de 100 000 x 2 000 px
(200 Mpx, 500 m a 0.5 cm/px) sin archivo, por teselas, y reporta el pico de memoria del proceso.
Uso:  python -m tests.memoria_via_larga [ancho] [alto]
"""
import json
import sys
import time

from app.nucleo.eje_via import EjeVia
from app.nucleo.parametros import Params
from app.nucleo.pipeline import analizar_region
from tests.sintetico import LectorViaLarga


def pico_memoria_mb():
    try:
        import resource                      # solo Linux/macOS
    except ImportError:
        return None
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return pico / (1024 * 1024) if sys.platform == "darwin" else pico / 1024


def main(ancho=100_000, alto=2_000):
    lector = LectorViaLarga(ancho=ancho, alto=alto)
    p = Params()
    eje = EjeVia([(0, alto / 2), (ancho, alto / 2)], p.gsd_m)
    t0 = time.time()
    res = analizar_region(lector, (0, 0, ancho, alto), p, eje=eje, tesela_px=2048)
    print(json.dumps({
        "pico_mb": pico_memoria_mb(), "segundos": round(time.time() - t0, 1), "n_teselas": res.n_teselas,
        "n_detecciones": len(res.detecciones), "esperadas": len(lector.posiciones_grietas()),
        "tipos": sorted({d.tipo for d in res.detecciones}),
        "progresivas": [d.progresiva_m for d in res.detecciones],
        "anchos_mm": [d.ancho_mm for d in res.detecciones],
        "calidad": res.calidad.calidad,
    }))


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
