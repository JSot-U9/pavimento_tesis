"""
p_tutorial.py
=============
Lógica del panel del MODO TUTORIAL, sin Tk: en qué paso va el usuario, qué pasos están hechos, qué texto se muestra y
cómo se ejecuta «Hacerlo por mí». Los pasos y su estado salen de `logica_tutorial`; las acciones automáticas las
entrega la ventana principal (manejan las vistas reales, así el usuario ve el programa hacer el trabajo).
"""
from typing import Callable, Dict, List, Optional

from app import logica_tutorial as lt
from app.ui.presentadores.base import Resultado, proteger

def debe_ofrecer() -> bool:
    """¿Ofrecer el tutorial al abrir? (BD sin tramos y sin «no volver a preguntar»). Nunca falla: ante un error, no ofrece."""
    r = proteger(lt.debe_ofrecer)
    return bool(r.ok and r.datos)


def recordar_no_preguntar() -> Resultado:
    return proteger(lt.no_volver_a_ofrecer)


ICONO_HECHO, ICONO_PENDIENTE, ICONO_ACTUAL = "✔", "○", "▶"


class PresentadorTutorial:
    def __init__(self, ctx, carpeta: str, acciones: Optional[Dict[str, Callable[[], None]]] = None):
        self.ctx = ctx
        self.rutas = lt.rutas(carpeta)
        self.acciones = acciones or {}
        self.pasos = lt.PASOS
        self.indice = 0
        self.vistos = set()                       # pasos informativos que el usuario ya recorrió
        self._hechos: Dict[str, bool] = {i: False for i in lt.IDS}
        self.refrescar()

    # ---------------------------------------------------------------- estado
    def refrescar(self) -> Dict[str, bool]:
        """Vuelve a mirar la base de datos. Si falla (p. ej. durante un cambio de base de datos) deja lo anterior."""
        r = proteger(lt.estado_pasos, self.rutas["reportes"])
        if r.ok:
            self._hechos = dict(r.datos)
        return self._hechos

    def hecho(self, i: Optional[int] = None) -> bool:
        p = self.pasos[self.indice if i is None else i]
        return (p.id in self.vistos) if p.informativo else self._hechos.get(p.id, False)

    @property
    def paso(self) -> lt.Paso:
        return self.pasos[self.indice]

    @property
    def total(self) -> int:
        return len(self.pasos)

    def n_hechos(self) -> int:
        return sum(1 for i in range(self.total) if self.hecho(i))

    def fraccion(self) -> float:
        return self.n_hechos() / self.total

    def primer_pendiente(self) -> Optional[int]:
        """Índice del primer paso con acción que aún no está hecho (None si todos lo están)."""
        for i, p in enumerate(self.pasos):
            if not p.informativo and not self.hecho(i):
                return i
        return None

    def bloqueo(self, i: Optional[int] = None) -> str:
        """Texto que explica por qué el paso i no se puede hacer todavía ('' si se puede)."""
        i = self.indice if i is None else i
        for j in range(i):
            if not self.pasos[j].informativo and not self.hecho(j):
                return f"Primero complete el paso «{self.pasos[j].titulo}»."
        return ""

    # ---------------------------------------------------------------- navegación
    def ir_a(self, i: int) -> bool:
        if not 0 <= i < self.total:
            return False
        self.indice = i
        if self.paso.id == "fin":                          # el último paso solo informa
            self.vistos.add("fin")
        return True

    def siguiente(self) -> bool:
        if self.indice >= self.total - 1:
            return False
        if self.paso.informativo:
            self.vistos.add(self.paso.id)
        return self.ir_a(self.indice + 1)

    def anterior(self) -> bool:
        return self.ir_a(self.indice - 1)

    def puede_siguiente(self) -> bool:
        return self.indice < self.total - 1

    def siguiente_recomendado(self) -> bool:
        """¿Conviene pulsar «Siguiente» ya? (el paso está hecho o es informativo)."""
        return self.puede_siguiente() and (self.paso.informativo or self.hecho())

    # ---------------------------------------------------------------- textos
    def lista(self) -> List[tuple]:
        """[(indice, icono, titulo)] para la lista de pasos."""
        out = []
        for i, p in enumerate(self.pasos):
            icono = ICONO_HECHO if self.hecho(i) else (ICONO_ACTUAL if i == self.indice else ICONO_PENDIENTE)
            out.append((i, icono, p.titulo))
        return out

    def titulo_paso(self) -> str:
        return f"Paso {self.indice + 1} de {self.total}"

    def texto_estado(self) -> str:
        if self.paso.informativo:
            return "Paso informativo: léalo y pulse «Siguiente»."
        return "✔ Completado: pulse «Siguiente»." if self.hecho() else "Pendiente."

    def archivo_del_paso(self) -> str:
        c = self.paso.archivo
        return self.rutas[c] if c else ""

    def texto_progreso(self) -> str:
        return f"{self.n_hechos()} de {self.total} pasos completados"

    # ---------------------------------------------------------------- «Hacerlo por mí»
    def hacer(self) -> Resultado:
        """Ejecuta la acción automática del paso actual. Devuelve Resultado (error si falta un paso previo)."""
        p = self.paso
        if p.informativo or p.accion not in self.acciones:
            return Resultado(False, mensaje="Este paso no tiene acción automática.", errores={"": "Este paso no tiene acción automática."})
        if self.hecho():
            return Resultado(True, mensaje="Este paso ya está completado.")
        b = self.bloqueo()
        if b:
            return Resultado(False, mensaje=b, errores={"": b})
        r = proteger(self.acciones[p.accion])
        if r.ok and isinstance(r.datos, Resultado):       # la acción devolvió el Resultado de un presentador
            r = r.datos
        self.refrescar()
        return r
