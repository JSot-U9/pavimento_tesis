"""
Criterio de aceptación: un ortomosaico de 100 000 x 2 000 px se procesa sin superar ~2 GB de RAM.
Es lento (minutos), por eso está marcado 'lento' y no corre con `pytest` a secas:  pytest -m lento
Se mide en un SUBPROCESO para que el pico de memoria sea solo el del análisis.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
LIMITE_MB = 2048


def _correr(ancho, alto, timeout, metodo="actual"):
    r = subprocess.run([sys.executable, "-m", "tests.memoria_via_larga", str(ancho), str(alto), metodo],
                       cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(sys.platform == "win32", reason="mide el pico con el módulo 'resource' (Linux/macOS)")
@pytest.mark.parametrize("metodo", ["actual", "sun"])
def test_via_pequena_rapida(metodo):
    """Versión corta (20 000 x 2 000 px) para ver la mecánica sin esperar."""
    r = _correr(20_000, 2_000, timeout=900, metodo=metodo)
    assert r["pico_mb"] < LIMITE_MB
    assert r["n_detecciones"] == r["esperadas"]


@pytest.mark.lento
@pytest.mark.skipif(sys.platform == "win32", reason="mide el pico con el módulo 'resource' (Linux/macOS)")
@pytest.mark.parametrize("metodo", ["actual", "sun"])
def test_via_100000x2000_no_supera_2gb(metodo):
    r = _correr(100_000, 2_000, timeout=7200, metodo=metodo)
    print(metodo, r["pico_mb"], "MB;", r["segundos"], "s;", r["n_teselas"], "teselas")
    assert r["pico_mb"] < LIMITE_MB
    assert r["n_detecciones"] == r["esperadas"] == 10
    assert r["tipos"] == ["transversal"]
    assert r["progresivas"] == sorted(r["progresivas"])
    assert all(abs(a - 20.0) <= 2.0 for a in r["anchos_mm"])
    assert r["calidad"] == "Adecuada"
