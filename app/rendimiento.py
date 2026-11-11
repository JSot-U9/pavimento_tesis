"""
rendimiento.py
==============
Medición del tiempo y de la memoria (RAM) de un cálculo, para comparar métodos (F7). Sin BD ni Tk: se puede usar en
el hilo de trabajo.

`MedidorPico` muestrea la memoria residente (RSS) del PROCESO cada `intervalo` s en un hilo auxiliar y guarda
el pico y la base. Lo que se informa es el AUMENTO del pico sobre la base («RAM adicional»), en MB.

Límites (se muestran en la interfaz y en el reporte):
  * es RSS del proceso: incluye lo que otros hilos reserven en ese intervalo, y el sistema operativo puede no
    devolver enseguida la memoria liberada, de modo que ejecutar dos métodos uno tras otro en el mismo proceso
    subestima algo al segundo. Para una comparación rigurosa de memoria use `python -m scripts.comparar_rendimiento`,
    que lanza cada método en un proceso aparte.
  * Linux: /proc/self/statm. Windows: GetProcessMemoryInfo (ctypes). Otros sistemas: no hay medición (None).
"""
import os
import sys
import threading
import time


def rss_mb():
    """Memoria residente actual del proceso en MB, o None si no se puede medir en este sistema."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm") as f:
                paginas = int(f.read().split()[1])
            return paginas * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Contadores(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = Contadores()
            c.cb = ctypes.sizeof(c)
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
                                                          ctypes.byref(c), c.cb)
            return c.WorkingSetSize / (1024 * 1024) if ok else None
    except Exception:
        return None
    return None


class MedidorPico:
    """Uso:  with MedidorPico() as m: ...trabajo...;  m.segundos, m.base_mb, m.pico_mb, m.adicional_mb."""

    def __init__(self, intervalo=0.05, leer=rss_mb):
        self.intervalo, self._leer = intervalo, leer
        self.base_mb = self.pico_mb = None
        self.segundos = 0.0
        self._parar = threading.Event()
        self._hilo = None
        self._t0 = 0.0

    def _muestrear(self):
        while not self._parar.is_set():
            v = self._leer()
            if v is not None and (self.pico_mb is None or v > self.pico_mb):
                self.pico_mb = v
            self._parar.wait(self.intervalo)

    def __enter__(self):
        self.base_mb = self.pico_mb = self._leer()
        self._t0 = time.perf_counter()
        if self.base_mb is not None:
            self._hilo = threading.Thread(target=self._muestrear, daemon=True, name="medidor-ram")
            self._hilo.start()
        return self

    def __exit__(self, *exc):
        self.segundos = time.perf_counter() - self._t0
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2.0)
        v = self._leer()
        if v is not None and (self.pico_mb is None or v > self.pico_mb):
            self.pico_mb = v
        return False

    @property
    def adicional_mb(self):
        if self.base_mb is None or self.pico_mb is None:
            return None
        return max(0.0, self.pico_mb - self.base_mb)
