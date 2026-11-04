"""
informe.py
==========
Convierte el informe de los importadores (`logica_importacion`) en algo que la interfaz pueda mostrar en una
vista previa: resumen, tabla de errores por fila, advertencias y si tiene sentido confirmar.
"""
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class InformeImportacion:
    titulo: str
    creados: int = 0
    actualizados: int = 0
    omitidos: int = 0
    errores: List[Tuple[int, str]] = field(default_factory=list)     # (fila, mensaje)
    advertencias: List[str] = field(default_factory=list)
    simulado: bool = False
    aplicado: bool = False
    estricto: bool = True

    @classmethod
    def desde_dict(cls, titulo, rep: dict, estricto=True):
        return cls(titulo=titulo, creados=rep.get("creados", 0), actualizados=rep.get("actualizados", 0),
                   omitidos=rep.get("omitidos", 0),
                   errores=[(int(e.get("fila", 0)), str(e.get("mensaje", ""))) for e in rep.get("errores", [])],
                   advertencias=[str(a) for a in rep.get("advertencias", [])],
                   simulado=bool(rep.get("simulado")), aplicado=bool(rep.get("aplicado")), estricto=estricto)

    @property
    def n_cambios(self):
        return self.creados + self.actualizados

    @property
    def puede_confirmar(self) -> bool:
        """Confirmar solo tiene sentido si habría algo que importar y no lo bloquea el modo estricto."""
        return self.n_cambios > 0 and (not self.errores or not self.estricto)

    def resumen(self) -> str:
        lineas = []
        if self.simulado:
            lineas.append(f"VISTA PREVIA (no se ha guardado nada): se crearían {self.creados}, se actualizarían "
                          f"{self.actualizados}, se omitirían {self.omitidos}.")
        else:
            lineas.append(f"Creados: {self.creados} · actualizados: {self.actualizados} · omitidos: {self.omitidos}.")
        if self.errores:
            lineas.append(f"{len(self.errores)} fila(s) con error." + (
                " En modo estricto NO se importaría nada hasta corregirlas." if self.estricto and self.simulado
                else (" En modo estricto no se importó nada." if self.estricto
                      else " Se importan solo las filas válidas.")))
        if self.advertencias:
            lineas.append(f"{len(self.advertencias)} advertencia(s).")
        return "\n".join(lineas)
