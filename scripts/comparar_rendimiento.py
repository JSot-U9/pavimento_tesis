"""
Comparación RIGUROSA de tiempo y RAM entre métodos de detección (Fase 7).

Cada método corre en un PROCESO APARTE (así el pico de uno no contamina al otro) y se reporta el pico de memoria
residente del proceso (ru_maxrss en Linux/macOS; en Windows, el pico de GetProcessMemoryInfo) y los segundos.

Uso:
    python -m scripts.comparar_rendimiento                         # vía sintética 20 000 x 2 000 px
    python -m scripts.comparar_rendimiento --ancho 100000 --alto 2000
    python -m scripts.comparar_rendimiento --ortomosaico T1.tif --gsd-cm 0.8 --region 0 0 20000 2000
    python -m scripts.comparar_rendimiento --metodos actual sun --json salida.json

Los números salen de la medición (nada escrito a mano). La vía sintética sirve para verificar la mecánica; para la
tesis, mida sobre los ortomosaicos reales de T1–T3.
"""
import argparse
import json
import os
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _pico_proceso_mb():
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return v / (1024 * 1024) if sys.platform == "darwin" else v / 1024
    except ImportError:
        pass
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class C(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                        ("e", ctypes.c_size_t), ("f", ctypes.c_size_t)]
        c = C()
        c.cb = ctypes.sizeof(c)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.PeakWorkingSetSize / (1024 * 1024)
    return None


def _hijo(a):
    """Corre UN método y escribe un JSON en la última línea de stdout."""
    import time
    sys.path.insert(0, RAIZ)
    from app.nucleo.eje_via import EjeVia
    from app.nucleo.parametros import Params
    from app.nucleo.pipeline import analizar_region
    if a.ortomosaico:
        from app.nucleo.lectura import abrir
        lector = abrir(a.ortomosaico, gsd_cm=a.gsd_cm)
        x0, y0, x1, y1 = a.region or (0, 0, lector.ancho, lector.alto)
        p = Params(gsd_cm=a.gsd_cm or lector.gsd_cm)
    else:
        from tests.sintetico import LectorViaLarga
        lector = LectorViaLarga(ancho=a.ancho, alto=a.alto)
        x0, y0, x1, y1 = 0, 0, a.ancho, a.alto
        p = Params()
    eje = EjeVia([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)], p.gsd_m)
    base = _pico_proceso_mb()
    t0 = time.perf_counter()
    r = analizar_region(lector, (x0, y0, x1, y1), p, eje=eje, tesela_px=a.tesela, metodo=a.metodo)
    seg = time.perf_counter() - t0
    mpx = (x1 - x0) * (y1 - y0) / 1e6
    print(json.dumps({"metodo": a.metodo, "segundos": seg, "mpx": mpx, "s_por_mpx": seg / mpx,
                      "pico_mb": _pico_proceso_mb(), "n_detecciones": len(r.detecciones), "n_teselas": r.n_teselas,
                      "pico_antes_mb": base}))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metodos", nargs="+", default=["actual", "sun"])
    ap.add_argument("--ancho", type=int, default=20_000)
    ap.add_argument("--alto", type=int, default=2_000)
    ap.add_argument("--ortomosaico")
    ap.add_argument("--gsd-cm", type=float)
    ap.add_argument("--region", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--tesela", type=int, default=2048)
    ap.add_argument("--json", help="guarda los resultados en este archivo")
    ap.add_argument("--hijo", dest="metodo", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.metodo:                                                     # modo proceso hijo
        return _hijo(a)
    res = []
    for m in a.metodos:
        cmd = [sys.executable, "-m", "scripts.comparar_rendimiento", "--hijo", m, "--ancho", str(a.ancho),
               "--alto", str(a.alto), "--tesela", str(a.tesela)]
        if a.ortomosaico:
            cmd += ["--ortomosaico", a.ortomosaico]
            if a.gsd_cm:
                cmd += ["--gsd-cm", str(a.gsd_cm)]
            if a.region:
                cmd += ["--region", *map(str, a.region)]
        r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": RAIZ})
        if r.returncode != 0:
            sys.exit(f"Falló el método '{m}':\n{r.stderr[-1500:]}")
        res.append(json.loads(r.stdout.strip().splitlines()[-1]))
    print(f"{'método':<8} {'segundos':>9} {'s/Mpx':>7} {'pico RAM (MB)':>14} {'detecciones':>12}")
    for x in res:
        pico = "n/d" if x["pico_mb"] is None else f"{x['pico_mb']:.0f}"
        print(f"{x['metodo']:<8} {x['segundos']:>9.1f} {x['s_por_mpx']:>7.2f} {pico:>14} {x['n_detecciones']:>12}")
    if len(res) == 2 and res[0]["s_por_mpx"] > 0:
        print(f"Tiempo '{res[1]['metodo']}' / '{res[0]['metodo']}': {res[1]['s_por_mpx'] / res[0]['s_por_mpx']:.2f}")
    print("PROVISIONAL en lo que respecta a los umbrales; las medidas de tiempo/RAM dependen de esta máquina.")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
    return res


if __name__ == "__main__":
    main()
