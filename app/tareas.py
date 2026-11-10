"""
tareas.py
=========
Procesamiento en segundo plano: UN hilo de trabajo, una cola de mensajes y cancelación.

Reglas (ver GUIA_ARQUITECTURA):
  - Este módulo NO usa Tk ni la base de datos. El hilo solo ejecuta `logica_deteccion.ejecutar_trabajo`
    (núcleo de visión); la interfaz recibe los mensajes por la cola (sondeándola con `after`) y es ella,
    en el hilo principal, la que llama a `guardar_resultado` / `registrar_incidencia`.
  - Cancelar = `threading.Event`: el núcleo lo consulta entre teselas y lanza `AnalisisCancelado`.
  - Se pueden encolar varios trabajos (p. ej. todas las ROI de calibración); se ejecutan uno tras otro.
    Si se cancela, el que corre se detiene y los que esperaban se descartan.

Mensajes (`Mensaje.tipo`):
    'inicio'     un trabajo empieza            (trabajo, indice, total)
    'progreso'   avance 0-1 y texto            (trabajo, fraccion, texto)
    'resultado'  terminó bien                  (trabajo, resultado)
    'cancelado'  se canceló                    (trabajo, texto)
    'error'      falló                         (trabajo, texto, detalle = traceback)
    'fin'        la tanda terminó (siempre el último mensaje de una tanda)
"""
import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from app import logica_deteccion
from app.nucleo.estructuras import AnalisisCancelado


@dataclass
class Mensaje:
    tipo: str
    trabajo: Any = None
    indice: int = 0
    total: int = 0
    fraccion: float = 0.0
    texto: str = ""
    resultado: Any = None
    detalle: str = ""


@dataclass
class Calculo:
    """Cálculo pesado genérico (F5: calibración, estadística). `funcion(cancelar, progreso) -> resultado`.
    REGLA: la función corre en el hilo de trabajo, así que no puede usar Tk ni la BD: todo lo que lea de la BD
    se prepara en el hilo principal antes de crear el Calculo (ver `logica_calibracion.preparar_calibracion`)."""
    etiqueta: str
    funcion: Callable[[Any, Callable], Any]


def ejecutar_calculo(calculo, cancelar, progreso):
    """Ejecutor para `GestorTareas(ejecutar=ejecutar_calculo)`: llama a la función del `Calculo`."""
    return calculo.funcion(cancelar, progreso)


def gestor_de_calculos() -> "GestorTareas":
    """Gestor (hilo + cola + cancelación) para `Calculo`s, con los mismos mensajes que el de análisis."""
    return GestorTareas(ejecutar=ejecutar_calculo)


class GestorTareas:
    """Hilo de trabajo + cola. `ejecutar` es inyectable para las pruebas (por defecto, el núcleo real)."""

    def __init__(self, ejecutar: Optional[Callable] = None):
        self._ejecutar = ejecutar or logica_deteccion.ejecutar_trabajo
        self._cola: "queue.Queue[Mensaje]" = queue.Queue()
        self._cancelar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._terminado = threading.Event()
        self._terminado.set()

    # ------------------------------------------------------------------------------ estado
    @property
    def ocupado(self) -> bool:
        return not self._terminado.is_set()

    @property
    def cancelando(self) -> bool:
        return self.ocupado and self._cancelar.is_set()

    # ------------------------------------------------------------------------------ control
    def iniciar(self, trabajos: List[Any]) -> None:
        """Encola `trabajos` y arranca el hilo. Lanza RuntimeError si ya hay una tanda en marcha."""
        trabajos = list(trabajos)
        if not trabajos:
            raise ValueError("No hay trabajos que ejecutar")
        with self._lock:
            if self.ocupado and self._hilo is not None:
                self._hilo.join(timeout=0.05)         # el hilo pudo haber puesto 'fin' y estar a punto de salir
            if self.ocupado:
                raise RuntimeError("Ya hay un análisis en curso")
            self._cancelar.clear()
            self._terminado.clear()
            self._hilo = threading.Thread(target=self._bucle, args=(trabajos,), name="analisis", daemon=True)
            self._hilo.start()

    def cancelar(self) -> None:
        """Pide detener el trabajo en curso (efectivo en el siguiente límite de tesela)."""
        self._cancelar.set()

    def sondear(self, maximo: int = 500) -> List[Mensaje]:
        """Vacía la cola SIN bloquear (para llamarla desde `after`). Une mensajes de progreso consecutivos
        del mismo trabajo: a la interfaz solo le interesa el último."""
        out: List[Mensaje] = []
        for _ in range(maximo):
            try:
                m = self._cola.get_nowait()
            except queue.Empty:
                break
            if m.tipo == "progreso" and out and out[-1].tipo == "progreso" and out[-1].trabajo is m.trabajo:
                out[-1] = m
            else:
                out.append(m)
        return out

    def esperar(self, timeout: Optional[float] = None) -> bool:
        """Bloquea hasta que termine la tanda (uso: pruebas y cierre de la ventana). True si terminó."""
        return self._terminado.wait(timeout)

    # ------------------------------------------------------------------------------ hilo
    def _bucle(self, trabajos):
        total = len(trabajos)
        try:
            for i, trabajo in enumerate(trabajos, start=1):
                if self._cancelar.is_set():
                    break
                self._cola.put(Mensaje("inicio", trabajo, i, total))
                try:
                    res = self._ejecutar(trabajo, self._cancelar,
                                         lambda f, t, tr=trabajo, i=i: self._cola.put(
                                             Mensaje("progreso", tr, i, total, float(f), str(t))))
                except AnalisisCancelado as e:
                    self._cola.put(Mensaje("cancelado", trabajo, i, total, texto=str(e) or "Análisis cancelado"))
                    break
                except BaseException as e:          # el hilo no debe morir en silencio
                    self._cola.put(Mensaje("error", trabajo, i, total, texto=f"{type(e).__name__}: {e}",
                                           detalle=traceback.format_exc()))
                    break
                self._cola.put(Mensaje("resultado", trabajo, i, total, 1.0, resultado=res))
        finally:
            self._cola.put(Mensaje("fin", total=total))
            self._terminado.set()
