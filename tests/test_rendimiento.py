"""F7 · medición de tiempo/RAM (rendimiento.MedidorPico) y script de comparación rigurosa."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import rendimiento as rd

RAIZ = Path(__file__).resolve().parents[1]


def test_medidor_con_lector_falso_toma_pico_y_base():
    valores = iter([100.0, 100.0, 350.0, 200.0] + [200.0] * 1000)
    with rd.MedidorPico(intervalo=0.005, leer=lambda: next(valores)) as m:
        import time
        time.sleep(0.05)
    assert m.base_mb == 100.0 and m.pico_mb == 350.0 and m.adicional_mb == 250.0 and m.segundos >= 0.05


def test_medidor_sin_medicion_devuelve_none():
    with rd.MedidorPico(leer=lambda: None) as m:
        pass
    assert m.base_mb is None and m.adicional_mb is None and m.segundos >= 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="usa /proc")
def test_medidor_real_ve_una_reserva_grande():
    """En un proceso limpio: dentro de la suite completa, el montón ya liberado por otras pruebas se reutiliza y no sube el RSS."""
    codigo = ("import time, numpy as np\n"
              "from app import rendimiento as rd\n"
              "with rd.MedidorPico(intervalo=0.01) as m:\n"
              "    a = np.ones(120 * 1024 * 1024 // 8); time.sleep(0.1); assert a.sum() > 0\n"
              "print(m.adicional_mb)\n")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120,
                       env={**__import__("os").environ, "PYTHONPATH": str(RAIZ)})
    assert r.returncode == 0, r.stderr[-800:]
    assert float(r.stdout.strip()) >= 80


def test_script_compara_ambos_metodos_en_procesos_aparte(tmp_path):
    salida = tmp_path / "r.json"
    r = subprocess.run([sys.executable, "-m", "scripts.comparar_rendimiento", "--ancho", "6000", "--alto", "1000",
                        "--json", str(salida)], cwd=RAIZ, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-1500:]
    res = json.loads(salida.read_text())
    assert [x["metodo"] for x in res] == ["actual", "sun"]
    assert all(x["segundos"] > 0 and x["n_detecciones"] >= 1 for x in res)
    assert "PROVISIONAL" in r.stdout
