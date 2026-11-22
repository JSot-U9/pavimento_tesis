"""
logica_tutorial.py
==================
Contenido y estado del MODO TUTORIAL (sin Tk): los pasos, la carpeta de práctica con el ejemplo sintético y la
comprobación de qué pasos ya están hechos.

El tutorial trabaja en una base de datos de práctica (`<carpeta de la BD real>/tutorial/pavimento_tutorial.db`):
los datos reales del usuario no se tocan. Cada vez que se inicia (o se reinicia) se borra y se vuelve a generar.

Qué paso está «hecho» se decide mirando la base de datos con las funciones `logica_*` (no hay un contador aparte):
así el tutorial reconoce el avance tanto si el usuario hace el paso a mano como si pulsa «Hacerlo por mí».
"""
import glob
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app import (basedatos, ejemplo_sintetico, logica_configuracion, logica_deteccion, logica_roi, logica_tramos,
                 logica_validacion)

TRAMO_COD = "T1"
DATOS_TRAMO = {"codigo": TRAMO_COD, "via": "Tramo sintético", "progresiva_ini_m": 0, "progresiva_fin_m": 12}
OPCIONES_ROI = {"sistema": "auto", "si_existe": "error", "estricto": True, "capa": "", "epsg": ""}
N_ROI = 5
NOMBRE_BD = "pavimento_tutorial.db"


@dataclass(frozen=True)
class Paso:
    id: str
    titulo: str
    pestana: Optional[str]            # 'tramos' | 'analisis' | 'validacion' | 'estadistica' | 'metodos' | 'reportes' | None
    que: str                          # qué es y por qué se hace (concepto)
    como: Tuple[str, ...]             # instrucciones para hacerlo a mano
    ver: str                          # qué se debería ver al terminar
    accion: Optional[str] = None      # nombre de la acción de «Hacerlo por mí» (None = paso informativo)
    archivo: Optional[str] = None     # clave del archivo de ejemplo que el paso usa ('ortomosaico' | 'eje' | 'rois')

    @property
    def informativo(self) -> bool:
        return self.accion is None


PASOS: Tuple[Paso, ...] = (
    Paso("bienvenida", "Bienvenida: qué vamos a hacer", None,
         "Este tutorial lo guía por todo el flujo del programa con un EJEMPLO SINTÉTICO: la imagen de una calzada de 12 m "
         "con deterioros dibujados a propósito (una grieta transversal, una longitudinal, piel de cocodrilo y un bache) "
         "más un trozo sano. Como usted sabe qué hay y dónde, puede comprobar si el programa lo encuentra.\n\n"
         "Trabaja en una base de datos de PRÁCTICA: sus datos reales no se tocan.\n\n"
         "Palabras que se usarán: ortomosaico (la foto aérea del tramo), GSD (cuánto mide un píxel en el terreno), "
         "eje de vía (la línea central de la carretera), ROI (región de interés: un rectángulo de la imagen donde "
         "el inspector de campo vio algo).",
         ("Lea cada paso. Pulse «Hacerlo por mí» para que el programa lo ejecute y usted vea el resultado, o hágalo a "
          "mano siguiendo las instrucciones.",
          "Cuando el paso diga «Completado», pulse «Siguiente».",
          "Puede volver atrás, repetir o salir cuando quiera con «Salir del tutorial»."),
         "El orden del trabajo es: Tramo → Ortomosaico → Eje → ROI → Roles → Análisis → Validación → Estadística → "
         "Métodos → Reportes."),
    Paso("tramo", "1. Crear el tramo", "tramos",
         "Un tramo es el segmento de carretera que se estudia (Ficha 1 de la tesis). Todo lo demás (la imagen, el eje, "
         "las regiones, los análisis) cuelga de él.",
         ("En la pestaña «Tramos» pulse «Nuevo tramo».",
          "Escriba Código = T1, Vía = Tramo sintético, progresiva inicial = 0 y progresiva final = 12 (metros).",
          "Pulse «Guardar tramo»."),
         "T1 aparece en la tabla de tramos y en el selector «Tramo activo» de arriba.", accion="crear_tramo"),
    Paso("ortomosaico", "2. Asignar el ortomosaico", "tramos",
         "El ortomosaico es la foto aérea corregida del tramo. El GSD (cm/px) dice cuánto mide un píxel en el terreno: "
         "con él el programa convierte píxeles en metros y milímetros. Aquí 0.5 cm/px, así que 2400 px = 12 m.",
         ("En el recuadro «Ortomosaico» pulse «Examinar…» y elija el archivo indicado abajo.",
          "Escriba GSD = 0.5 (un PNG no trae la resolución).",
          "Pulse «Asignar ortomosaico»."),
         "El recuadro muestra «2400 × 1400 px · 0.5 cm/px» y la pestaña «Análisis» ya dibuja la imagen.",
         accion="asignar_ortomosaico", archivo="ortomosaico"),
    Paso("eje", "3. Importar el eje de vía", "tramos",
         "El eje de vía es la línea central de la carretera. Con él el programa decide si una grieta es longitudinal "
         "(paralela al eje) o transversal (lo cruza) y da la progresiva (la distancia a lo largo del tramo).",
         ("En el recuadro «Eje de vía» pulse «Importar eje (CSV / GeoJSON / GPKG)…».",
          "Elija el archivo indicado abajo; revise la vista previa y confirme."),
         "El recuadro describe el eje importado (vértices, origen y progresiva inicial).",
         accion="importar_eje", archivo="eje"),
    Paso("rois", "4. Importar las ROI de campo", "analisis",
         "Una ROI es un rectángulo de la imagen donde el inspector de campo registró algo, con el tipo y la severidad "
         "que vio. Es la «respuesta correcta» con la que el programa será comparado después. Aquí hay 5: una por "
         "cada deterioro y una de pavimento sano.",
         ("Abra la pestaña «Análisis» y, a la izquierda, la subpestaña «ROI».",
          "Pulse «Importar…», elija el archivo indicado abajo, revise la vista previa y confirme."),
         "La tabla lista R01 a R05 y el visor las dibuja como rectángulos sobre la imagen.",
         accion="importar_rois", archivo="rois"),
    Paso("roles", "5. Repartir las ROI en calibración y prueba", "analisis",
         "Para no engañarse, las ROI se reparten en dos grupos: «calibración» (sirven para ajustar los umbrales) y "
         "«prueba» (se usan solo para medir el desempeño con ROI que el programa nunca usó para ajustarse). Nunca se "
         "calibra con las de prueba.",
         ("En la subpestaña «ROI» pulse «Asignar roles…».",
          "Deje la proporción en 0.5 y la semilla en 42 (así el reparto es reproducible) y pulse «Asignar»."),
         "Cada ROI muestra su rol; el resumen indica cuántas quedaron en calibración y cuántas en prueba.",
         accion="asignar_roles"),
    Paso("analizar", "6. Analizar las ROI de prueba", "analisis",
         "El programa recorre la imagen por teselas, detecta grietas, piel de cocodrilo y baches, y mide longitud, "
         "ancho y área. Corre en segundo plano: la ventana no se congela y puede cancelar.",
         ("En la subpestaña «Análisis», en «Qué analizar» elija «Todas las ROI de un rol» y el rol «prueba».",
          "En «Método y parámetros» deje el método «actual».",
          "Pulse «Analizar» y espere a que termine la barra de avance."),
         "El desplegable «Ejecución» lista las ejecuciones y las detecciones aparecen en la tabla y sobre la imagen.",
         accion="analizar"),
    Paso("resultados", "7. Leer los resultados", "analisis",
         "Cada fila es una detección: su tipo (longitudinal o transversal según su ángulo respecto al eje), la "
         "progresiva y el lado de la vía, y sus medidas (longitud en m, ancho en mm, área en m²). La severidad es "
         "solo orientativa: la oficial es la de la ficha de campo. El aviso PROVISIONAL recuerda que los umbrales "
         "aún no se calibraron con datos reales.",
         ("Elija una ejecución en el desplegable «Ejecución».",
          "Haga clic en una detección de la tabla: el visor la resalta.",
          "En el visor, la rueda del ratón acerca o aleja, arrastrar mueve y la tecla 0 ajusta la imagen."),
         "La grieta transversal sale casi vertical y la longitudinal casi horizontal; la piel de cocodrilo aparece "
         "como una zona con muchas celdas y el bache con su área."),
    Paso("validar", "8. Validar contra el campo", "validacion",
         "Validar es comparar lo que el programa detectó con lo que vio el inspector. Para cada ROI y tipo hay cuatro "
         "casos: VP (detectó y sí había), FP (detectó y no había), FN (había y no lo detectó) y VN (no había y no "
         "detectó).",
         ("Abra la pestaña «Validación».",
          "Pulse «Validar y guardar» (usa la última ejecución de cada ROI de prueba)."),
         "Una tabla con VP/FP/FN/VN por ROI y tipo, y los totales debajo.", accion="validar"),
    Paso("estadistica", "9. Estadística", "estadistica",
         "Con los VP, FP, FN y VN se calculan sensibilidad (¿encuentra lo que existe?), especificidad, precisión, "
         "exactitud, F1, concordancia en % y kappa, con intervalos de confianza de Wilson al 95 %. Con tan pocas "
         "unidades los intervalos salen muy anchos: es lo esperado; con los datos reales de los tres tramos serán "
         "más informativos. Donde no hay datos suficientes el programa muestra «n/d», nunca un 0 engañoso.",
         ("Abra la pestaña «Estadística».",
          "Recorra «Métricas por tipo» y «Concordancia (kappa)»."),
         "Una tabla de métricas con sus intervalos de confianza y el aviso PROVISIONAL."),
    Paso("metodos", "10. Comparar dos métodos", "metodos",
         "El programa trae un segundo método de detección de grietas (Sun, 2009). Esta pestaña ejecuta los dos con "
         "las mismas ROI de prueba, los mismos parámetros y la misma referencia de campo, y los compara.",
         ("Abra la pestaña «Métodos» y deje A = actual y B = sun.",
          "Pulse «Analizar y validar con ambos» y espere."),
         "Métricas por método, tiempo y memoria, y una conclusión con las cifras calculadas. Con datos sintéticos y "
         "pocas unidades NO se puede concluir cuál método es mejor; solo se comprueba que el flujo funciona.",
         accion="comparar"),
    Paso("reportes", "11. Generar los reportes", "reportes",
         "Un reporte reúne todo lo anterior en un PDF, un Excel y tablas CSV. Las cifras salen de los mismos cálculos "
         "que usted vio en pantalla.",
         ("Abra la pestaña «Reportes» y revise el recuadro «Reporte del tramo activo».",
          "Elija una carpeta de destino, pulse «Vista previa…» para revisar y luego «Generar»."),
         "La lista de archivos generados (PDF, XLSX y CSV); «Abrir archivo» abre el seleccionado.", accion="reportes"),
    Paso("fin", "Fin: qué sigue", None,
         "Ya recorrió todo el flujo. Para trabajar con sus datos reales: salga del tutorial (vuelve su base de datos), "
         "cree su tramo con el ortomosaico real (GeoTIFF si puede), importe su eje y sus ROI, cargue las fichas de "
         "campo, calibre con las ROI de calibración y valide con las de prueba. Los umbrales seguirán PROVISIONALES "
         "hasta que los calibre con esos datos.",
         ("«Salir del tutorial» devuelve su base de datos real.",
          "«Reiniciar tutorial» borra la práctica y empieza de nuevo."),
         "Los archivos de práctica quedan en la carpeta del tutorial por si quiere abrirlos."),
)
IDS = tuple(p.id for p in PASOS)


# ---------------------------------------------------------------------------------------- carpeta de práctica
def carpeta_tutorial(ruta_bd_real: Optional[str]) -> str:
    """Carpeta de práctica: junto a la BD real (o en la carpeta temporal si la BD es ':memory:' o no se conoce)."""
    if not ruta_bd_real or ruta_bd_real == ":memory:":
        return os.path.join(tempfile.gettempdir(), "pavimento_tutorial")
    return os.path.join(os.path.dirname(os.path.abspath(ruta_bd_real)), "tutorial")


def rutas(carpeta: str) -> Dict[str, str]:
    ej = os.path.join(carpeta, "ejemplo")
    return {"carpeta": carpeta, "bd": os.path.join(carpeta, NOMBRE_BD), "reportes": os.path.join(carpeta, "reportes"),
            "ortomosaico": os.path.join(ej, ejemplo_sintetico.NOMBRE_IMAGEN),
            "rois": os.path.join(ej, ejemplo_sintetico.NOMBRE_ROIS), "eje": os.path.join(ej, ejemplo_sintetico.NOMBRE_EJE)}


def preparar(carpeta: str) -> Dict[str, str]:
    """Deja la carpeta de práctica limpia: sin BD ni reportes anteriores y con los tres archivos del ejemplo.
    No abre la BD (lo hace quien llama). Si la BD de práctica está abierta, la cierra antes de borrarla."""
    r = rutas(carpeta)
    if basedatos.ruta_actual() and os.path.abspath(basedatos.ruta_actual()) == os.path.abspath(r["bd"]):
        basedatos.cerrar()
    os.makedirs(carpeta, exist_ok=True)
    for f in glob.glob(r["bd"] + "*"):
        os.remove(f)
    shutil.rmtree(os.path.join(carpeta, "respaldos"), ignore_errors=True)
    shutil.rmtree(r["reportes"], ignore_errors=True)
    os.makedirs(r["reportes"], exist_ok=True)
    ejemplo_sintetico.obtener(os.path.dirname(r["ortomosaico"]))     # copia de ejemplo/ (o lo genera si falta)
    return r


# ---------------------------------------------------------------------------------------- oferta del tutorial
def debe_ofrecer() -> bool:
    """¿Conviene ofrecer el tutorial al abrir el programa? Sí si la base de datos no tiene ningún tramo (usuario nuevo) y
    nadie pidió «no volver a preguntar»."""
    return not logica_configuracion.obtener("tutorial_no_preguntar") and not logica_tramos.listar_tramos()


def no_volver_a_ofrecer():
    logica_configuracion.establecer("tutorial_no_preguntar", True)


def volver_a_ofrecer():
    logica_configuracion.establecer("tutorial_no_preguntar", False)


# ---------------------------------------------------------------------------------------- estado de los pasos
def _tramo_tutorial() -> Optional[dict]:
    return next((t for t in logica_tramos.listar_tramos() if t["codigo"] == TRAMO_COD), None)


def estado_pasos(carpeta_reportes: Optional[str] = None) -> Dict[str, bool]:
    """{id_paso: ¿ya está hecho?} según lo que hay en la base de datos. Los pasos informativos devuelven False
    (los marca como vistos el presentador)."""
    ok = {i: False for i in IDS}
    t = _tramo_tutorial()
    if t is None:
        return ok
    ok["tramo"] = True
    ok["ortomosaico"] = bool(t.get("ortomosaico_ruta")) and bool(t.get("gsd_cm"))
    res = logica_tramos.resumen_tramo(t["id"])
    ok["eje"] = res["ejes"] > 0
    rois = logica_roi.listar_rois(t["id"])
    ok["rois"] = len(rois) >= N_ROI
    ok["roles"] = bool(rois) and all(r["rol"] in ("calibracion", "prueba") for r in rois)
    ejec = [e for e in logica_deteccion.listar_ejecuciones(t["id"], estado="completada")]
    ok["analizar"] = any(e["metodo"] == "actual" for e in ejec)
    ok["validar"] = bool(logica_validacion.ejecuciones_validadas(t["id"], metodo="actual", rol="prueba"))
    ok["metodos"] = any(e["metodo"] == "sun" for e in ejec) and bool(
        logica_validacion.ejecuciones_validadas(t["id"], metodo="sun", rol="prueba"))
    if carpeta_reportes:
        ok["reportes"] = bool(glob.glob(os.path.join(carpeta_reportes, "*.pdf")))
    return ok
