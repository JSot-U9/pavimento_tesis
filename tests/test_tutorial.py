"""Modo tutorial: contenido de los pasos y estado (sin Tk), presentador (sin Tk) y recorrido completo con la interfaz real."""
import hashlib
import os

import cv2
import numpy as np
import pytest

from app import basedatos, ejemplo_sintetico as ej, logica_comparacion, logica_deteccion, logica_importacion, logica_roi
from app import logica_tramos, logica_tutorial as lt, logica_validacion
from app.ui.presentadores.base import Contexto, Resultado
from app.ui.presentadores.p_tutorial import PresentadorTutorial

ACCIONES_VALIDAS = {"crear_tramo", "asignar_ortomosaico", "importar_eje", "importar_rois", "asignar_roles", "analizar",
                    "validar", "comparar", "reportes"}


# ============================================================================================ ejemplo sintético
def test_ejemplo_es_determinista_y_coincide_con_lo_descrito(tmp_path):
    a = ej.generar(str(tmp_path / "a"))
    b = ej.generar(str(tmp_path / "b"))
    img = cv2.imread(a["ortomosaico"])
    assert img.shape == (ej.ALTO, ej.ANCHO, 3)
    assert hashlib.md5(img.tobytes()).hexdigest() == hashlib.md5(cv2.imread(b["ortomosaico"]).tobytes()).hexdigest()
    filas = open(a["rois"], encoding="utf-8").read().strip().splitlines()
    assert len(filas) == 1 + lt.N_ROI and filas[1].startswith("R01,")
    assert open(a["eje"], encoding="utf-8").read() == "x,y\n0,700\n2400,700\n"


def test_los_deterioros_estan_donde_dice_el_csv(tmp_path):
    """Dentro de cada ROI con deterioro la imagen es más oscura/irregular que en la ROI sana."""
    r = ej.generar(str(tmp_path))
    g = cv2.cvtColor(cv2.imread(r["ortomosaico"]), cv2.COLOR_BGR2GRAY).astype(float)
    filas = [f.split(",") for f in open(r["rois"], encoding="utf-8").read().strip().splitlines()[1:]]
    minimo = {f[0]: g[int(f[5]):int(f[5]) + int(f[7]), int(f[4]):int(f[4]) + int(f[6])].min() for f in filas}
    assert minimo["R05"] > max(minimo["R01"], minimo["R02"], minimo["R03"], minimo["R04"]) + 20


# ============================================================================================ pasos y carpeta
def test_pasos_bien_formados():
    assert len(set(lt.IDS)) == len(lt.IDS) and lt.IDS[0] == "bienvenida" and lt.IDS[-1] == "fin"
    assert {p.accion for p in lt.PASOS if p.accion} <= ACCIONES_VALIDAS
    assert {p.accion for p in lt.PASOS if p.accion} == ACCIONES_VALIDAS            # ninguna acción sin paso
    for p in lt.PASOS:
        assert p.titulo and p.que and p.como and p.ver, p.id
        assert p.archivo in (None, "ortomosaico", "eje", "rois")
        assert p.pestana in (None, "tramos", "analisis", "validacion", "estadistica", "metodos", "reportes")
        assert p.informativo == (p.accion is None)


def test_carpeta_tutorial_junto_a_la_bd_real_o_temporal(tmp_path):
    assert lt.carpeta_tutorial(str(tmp_path / "datos" / "pavimento.db")) == str(tmp_path / "datos" / "tutorial")
    assert lt.carpeta_tutorial(":memory:").endswith("pavimento_tutorial")
    assert lt.carpeta_tutorial(None).endswith("pavimento_tutorial")


def test_preparar_deja_todo_limpio_y_no_toca_otras_carpetas(tmp_path):
    carpeta = str(tmp_path / "datos" / "tutorial")
    real = tmp_path / "datos" / "pavimento.db"
    real.parent.mkdir()
    real.write_text("mi base de datos")
    r = lt.preparar(carpeta)
    assert all(os.path.isfile(r[k]) for k in ("ortomosaico", "rois", "eje")) and os.path.isdir(r["reportes"])
    # suciedad de un tutorial anterior (BD con WAL, reportes) → desaparece; la BD real queda intacta
    for extra in (r["bd"], r["bd"] + "-wal", os.path.join(r["reportes"], "viejo.pdf")):
        open(extra, "w").write("x")
    lt.preparar(carpeta)
    assert not os.path.exists(r["bd"]) and not os.path.exists(r["bd"] + "-wal")
    assert os.listdir(r["reportes"]) == []
    assert real.read_text() == "mi base de datos"


def test_preparar_cierra_la_bd_de_practica_si_esta_abierta(tmp_path):
    carpeta = str(tmp_path / "tut")
    r = lt.preparar(carpeta)
    basedatos.inicializar(r["bd"])
    lt.preparar(carpeta)
    assert basedatos.ruta_actual() is None and not os.path.exists(r["bd"])


# ============================================================================================ estado de los pasos
@pytest.fixture
def practica(tmp_path):
    r = lt.preparar(str(tmp_path / "tutorial"))
    basedatos.inicializar(r["bd"])
    yield r
    basedatos.cerrar()


def test_estado_vacio_y_avance_paso_a_paso(practica):
    assert not any(lt.estado_pasos(practica["reportes"]).values())
    t = logica_tramos.crear_tramo(dict(lt.DATOS_TRAMO))
    e = lt.estado_pasos()
    assert e["tramo"] and not e["ortomosaico"]
    logica_tramos.asignar_ortomosaico(t["id"], practica["ortomosaico"], gsd_cm=0.5)
    assert lt.estado_pasos()["ortomosaico"]
    assert not lt.estado_pasos()["eje"]
    logica_importacion.importar_eje(t["id"], practica["eje"])
    assert lt.estado_pasos()["eje"]
    logica_importacion.importar_rois(t["id"], practica["rois"])
    e = lt.estado_pasos()
    assert e["rois"] and not e["roles"]
    logica_roi.asignar_roles(t["id"], 0.5, 42)
    assert lt.estado_pasos()["roles"]
    assert not lt.estado_pasos()["analizar"]
    # análisis, validación y comparación con las funciones de la lógica (lo mismo que hacen los botones)
    res = logica_comparacion.ejecutar_y_validar(t["id"], metodos=("actual",))
    e = lt.estado_pasos()
    assert e["analizar"] and e["validar"] and not e["metodos"]
    logica_comparacion.ejecutar_y_validar(t["id"], metodos=("sun",))
    assert lt.estado_pasos()["metodos"]
    assert not lt.estado_pasos(practica["reportes"])["reportes"]
    open(os.path.join(practica["reportes"], "x.pdf"), "w").write("x")
    assert lt.estado_pasos(practica["reportes"])["reportes"]
    # los deterioros del ejemplo sí se encuentran con el método 'actual' (el tutorial promete eso)
    tot = res["actual"]["validacion"]["totales"]
    suma = {k: sum(t[k] for t in tot.values()) for k in ("vp", "fp", "fn", "vn")}
    assert suma["vp"] >= 2 and suma["fp"] == 0 and suma["fn"] == 0


# ============================================================================================ presentador (sin Tk)
class Falsa:
    """Acciones de prueba: registran la llamada y (opcionalmente) devuelven un Resultado."""
    def __init__(self):
        self.llamadas = []

    def accion(self, nombre, devuelve=None):
        def f():
            self.llamadas.append(nombre)
            return devuelve
        return f


@pytest.fixture
def pres(tmp_path, monkeypatch):
    hechos = {i: False for i in lt.IDS}
    monkeypatch.setattr(lt, "estado_pasos", lambda carpeta=None: dict(hechos))
    f = Falsa()
    acc = {a: f.accion(a) for a in ACCIONES_VALIDAS}
    p = PresentadorTutorial(Contexto(), str(tmp_path / "tut"), acc)
    p._hechos_falsos, p._f = hechos, f
    return p


def test_navegacion_con_limites_y_marca_de_pasos_informativos(pres):
    assert pres.indice == 0 and pres.total == len(lt.PASOS) and not pres.anterior()
    assert not pres.hecho()
    assert pres.siguiente() and pres.indice == 1
    assert pres.hecho(0)                                  # el informativo recorrido cuenta como visto
    pres.ir_a(pres.total - 1)
    assert pres.hecho() and not pres.siguiente() and not pres.ir_a(99) and not pres.ir_a(-1)


def test_hacer_exige_los_pasos_previos_y_llama_a_la_accion(pres):
    pres.ir_a(lt.IDS.index("rois"))
    r = pres.hacer()
    assert not r.ok and "Primero complete" in r.texto_errores()
    assert pres._f.llamadas == [] and "Primero complete" in pres.bloqueo()
    for i in ("tramo", "ortomosaico", "eje"):
        pres._hechos_falsos[i] = True
    pres.refrescar()
    assert pres.bloqueo() == ""
    assert pres.hacer().ok and pres._f.llamadas == ["importar_rois"]
    pres._hechos_falsos["rois"] = True
    pres.refrescar()
    r = pres.hacer()                                       # ya hecho: no repite la acción
    assert r.ok and pres._f.llamadas == ["importar_rois"] and "ya está completado" in r.mensaje


def test_hacer_devuelve_el_resultado_del_presentador_y_protege_errores(tmp_path, monkeypatch):
    monkeypatch.setattr(lt, "estado_pasos", lambda carpeta=None: {i: i == "tramo" for i in lt.IDS})
    mal = Resultado(False, errores={"": "no se pudo"}, mensaje="no se pudo")

    def roto():
        raise RuntimeError("boom")
    p = PresentadorTutorial(Contexto(), str(tmp_path / "t"), {"asignar_ortomosaico": lambda: mal, "importar_eje": roto})
    p.ir_a(lt.IDS.index("ortomosaico"))
    assert p.hacer().texto_errores() == "no se pudo"
    p.ir_a(lt.IDS.index("eje"))
    p._hechos["ortomosaico"] = True
    r = p.hacer()
    assert not r.ok and "boom" in r.texto_errores()
    p.ir_a(0)
    assert not p.hacer().ok                                # paso informativo: sin acción


def test_lista_iconos_progreso_y_siguiente_recomendado(pres):
    pres._hechos_falsos["tramo"] = True
    pres.refrescar()
    iconos = {i: ic for i, ic, _ in pres.lista()}
    assert iconos[0] == "▶" and iconos[1] == "✔" and iconos[2] == "○"
    assert pres.n_hechos() == 1 and 0 < pres.fraccion() < 1 and "1 de" in pres.texto_progreso()
    pres.ir_a(1)
    assert pres.siguiente_recomendado() and pres.texto_estado().startswith("✔")
    pres.ir_a(2)
    assert not pres.siguiente_recomendado() and pres.texto_estado() == "Pendiente."
    assert pres.primer_pendiente() == 2
    assert pres.archivo_del_paso().endswith("ortomosaico_sintetico.png")
    pres.ir_a(0)
    assert pres.archivo_del_paso() == "" and pres.texto_estado().startswith("Paso informativo")


# ============================================================================================ interfaz real
tk = pytest.importorskip("tkinter")
from tests import humo_ui as h                                              # noqa: E402


def _ventana(tmp_path):
    from app.ui.ventana_principal import VentanaPrincipal
    real = str(tmp_path / "datos" / "pavimento.db")
    basedatos.inicializar(real)
    try:
        v = VentanaPrincipal(ruta_bd=real, abrir_bd=basedatos.inicializar, geometria="1360x820")
    except tk.TclError as e:
        basedatos.cerrar()
        pytest.skip(f"sin pantalla: {e}")
    return v, real


@pytest.fixture
def silencio(monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    for n in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(messagebox, n, lambda *a, **k: None)


def test_tutorial_completo_con_la_interfaz_real_y_la_bd_real_queda_intacta(tmp_path, silencio):
    v, real = _ventana(tmp_path)
    try:
        # la BD real tiene un tramo propio: no debe verse ni cambiar durante el tutorial
        logica_tramos.crear_tramo({"codigo": "MIO", "via": "Mi tramo real"})
        v.ctx.emitir("tramos")
        v.update()
        v.iniciar_tutorial(confirmar=False)
        v.update()
        assert v.panel_tutorial is not None and "MODO TUTORIAL" in v.title()
        assert basedatos.ruta_actual() == os.path.abspath(v._rutas_tut["bd"]) or basedatos.ruta_actual() == v._rutas_tut["bd"]
        assert logica_tramos.listar_tramos() == []                              # práctica vacía al empezar
        pres = v.panel_tutorial.pres
        for i, paso in enumerate(pres.pasos):
            pres.ir_a(i)
            v.panel_tutorial.mostrar_paso(notificar=True)
            v.update()
            if paso.informativo:
                pres.siguiente() if i < pres.total - 1 else None
                continue
            v.panel_tutorial._hacer_clic()
            assert h.esperar(v, lambda: (pres.refrescar(), pres.hecho(i))[1], 240), f"el paso «{paso.id}» no se completó"
        assert pres.n_hechos() == pres.total
        assert h.esperar(v, lambda: not v._ocupado(), 60)
        assert [t["codigo"] for t in logica_tramos.listar_tramos()] == ["T1"]
        assert any(f.endswith(".pdf") for f in os.listdir(v._rutas_tut["reportes"]))
        # reiniciar: vuelve a empezar de cero
        v.reiniciar_tutorial(confirmar=False)
        v.update()
        assert logica_tramos.listar_tramos() == [] and v.panel_tutorial.pres.n_hechos() == 0
        # salir: vuelve la BD real, con su tramo, sin rastro de la práctica
        v.salir_tutorial(confirmar=False)
        v.update()
        assert v.panel_tutorial is None and v.ruta_bd == real and v.title() == "Detección de deterioros en pavimentos flexibles"
        assert [t["codigo"] for t in logica_tramos.listar_tramos()] == ["MIO"]
    finally:
        v.cerrar()
        basedatos.cerrar()


def test_el_tutorial_exige_una_bd_en_archivo_y_no_se_abre_dos_veces(tmp_path, silencio):
    from app.ui.ventana_principal import VentanaPrincipal
    basedatos.inicializar(":memory:")
    try:
        v = VentanaPrincipal(ruta_bd=":memory:", abrir_bd=basedatos.inicializar, geometria="1360x820")
    except tk.TclError as e:
        basedatos.cerrar()
        pytest.skip(f"sin pantalla: {e}")
    try:
        v.iniciar_tutorial(confirmar=False)
        assert v.panel_tutorial is None                                         # BD en memoria: no se puede volver a ella
    finally:
        v.cerrar()
        basedatos.cerrar()
    v, _ = _ventana(tmp_path)
    try:
        v.iniciar_tutorial(confirmar=False)
        panel = v.panel_tutorial
        v.iniciar_tutorial(confirmar=False)
        assert v.panel_tutorial is panel
        v.salir_tutorial(confirmar=False)
        v.salir_tutorial(confirmar=False)                                       # salir dos veces no falla
    finally:
        v.cerrar()
        basedatos.cerrar()


# ============================================================================================ integrado en el proyecto
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_la_carpeta_ejemplo_del_proyecto_es_identica_a_lo_que_genera_el_codigo(tmp_path):
    """Si alguien cambia el generador sin regenerar `ejemplo/` (o al revés), el tutorial mostraría cosas distintas."""
    inc = ej.carpeta_incluida()
    assert inc is not None and os.path.samefile(inc, os.path.join(RAIZ, "ejemplo"))
    gen = ej.generar(str(tmp_path))
    for clave, nombre in (("ortomosaico", ej.NOMBRE_IMAGEN), ("rois", ej.NOMBRE_ROIS), ("eje", ej.NOMBRE_EJE)):
        a = open(os.path.join(inc, nombre), "rb").read() if clave != "ortomosaico" else cv2.imread(os.path.join(inc, nombre)).tobytes()
        b = open(gen[clave], "rb").read() if clave != "ortomosaico" else cv2.imread(gen[clave]).tobytes()
        assert a == b, nombre


def test_obtener_copia_el_ejemplo_incluido_o_lo_genera_si_falta(tmp_path, monkeypatch):
    r = ej.obtener(str(tmp_path / "copia"))
    assert all(os.path.isfile(v) for v in r.values())
    assert open(r["ortomosaico"], "rb").read() == open(os.path.join(RAIZ, "ejemplo", ej.NOMBRE_IMAGEN), "rb").read()
    monkeypatch.setattr(ej, "carpeta_incluida", lambda: None)
    r2 = ej.obtener(str(tmp_path / "generado"))
    assert all(os.path.isfile(v) for v in r2.values())
    assert cv2.imread(r2["ortomosaico"]).shape == (ej.ALTO, ej.ANCHO, 3)


def test_archivos_del_proyecto_para_que_cualquiera_ejecute_el_tutorial():
    for rel in ("tutorial.bat", "tutorial.sh", "scripts/generar_ejemplo.py", "ejemplo/LEEME.md", "prototipo/pavimento_rgb.py",
                "prototipo/generar_ejemplo.py", "prototipo/LEEME_PROTOTIPO.md", "prototipo/salida_proto/detecciones.csv"):
        assert os.path.isfile(os.path.join(RAIZ, rel)), rel
    for lanzador in ("tutorial.bat", "tutorial.sh"):
        assert "--tutorial" in open(os.path.join(RAIZ, lanzador), encoding="utf-8").read()
    assert os.access(os.path.join(RAIZ, "tutorial.sh"), os.X_OK)
    assert '("ejemplo", "ejemplo")' in open(os.path.join(RAIZ, "pavimento_tesis.spec"), encoding="utf-8").read()
    assert os.path.getsize(os.path.join(RAIZ, "prototipo", "pavimento_rgb.py")) > 10000


# ============================================================================================ oferta del tutorial
def test_oferta_solo_con_bd_vacia_y_sin_no_volver_a_preguntar(tmp_path):
    basedatos.inicializar(str(tmp_path / "o.db"))
    try:
        from app.ui.presentadores import p_tutorial as pt
        assert lt.debe_ofrecer() and pt.debe_ofrecer()
        logica_tramos.crear_tramo({"codigo": "A", "via": "x"})
        assert not lt.debe_ofrecer()                                   # ya tiene datos: no es un usuario nuevo
        logica_tramos.eliminar_tramo("A")
        assert lt.debe_ofrecer()
        assert pt.recordar_no_preguntar().ok and not lt.debe_ofrecer() and not pt.debe_ofrecer()
        lt.volver_a_ofrecer()
        assert lt.debe_ofrecer()
    finally:
        basedatos.cerrar()


def test_oferta_no_falla_si_no_hay_bd():
    basedatos.cerrar()
    from app.ui.presentadores import p_tutorial as pt
    assert pt.debe_ofrecer() is False and not pt.recordar_no_preguntar().ok


def test_ventana_boton_f1_oferta_y_aviso_de_primera_vez(tmp_path, silencio, monkeypatch):
    from app.ui import dialogo_tutorial as dt
    v, real = _ventana(tmp_path)
    try:
        v.update()
        # aviso de «primera vez» visible en la pestaña Tramos mientras no hay tramos
        av = v.v_tramos.aviso_primera_vez
        assert "Tutorial" in av.cget("text") and av.winfo_manager() == "pack"
        # el botón siempre está y arranca el tutorial; con el tutorial activo se desactiva y el aviso desaparece
        assert "Tutorial" in str(v.btn_tutorial.cget("text"))
        v.btn_tutorial.invoke()
        v.update()
        assert v.panel_tutorial is not None and v.btn_tutorial.instate(["disabled"])
        assert av.winfo_manager() == ""
        v.salir_tutorial(confirmar=False)
        v.update()
        assert not v.btn_tutorial.instate(["disabled"]) and av.winfo_manager() == "pack"
        # F1 también lo abre
        v.focus_force()
        v.event_generate("<F1>")
        v.update()
        assert v.panel_tutorial is not None
        v.salir_tutorial(confirmar=False)

        # oferta al abrir: «Ahora no» no hace nada; «No volver a preguntar» se recuerda; «Sí» inicia el tutorial
        monkeypatch.setattr(dt.DialogoOfertaTutorial, "abrir", lambda self: "ahora_no")
        assert v.ofrecer_tutorial() == "ahora_no" and lt.debe_ofrecer()
        monkeypatch.setattr(dt.DialogoOfertaTutorial, "abrir", lambda self: "no_preguntar")
        assert v.ofrecer_tutorial() == "no_preguntar" and not lt.debe_ofrecer()
        llamado = []
        monkeypatch.setattr(dt.DialogoOfertaTutorial, "abrir", lambda self: llamado.append(1) or "si")
        assert v.ofrecer_tutorial() is None and not llamado              # pidió no preguntar: ni siquiera abre el diálogo
        lt.volver_a_ofrecer()
        assert v.ofrecer_tutorial() == "si" and v.panel_tutorial is not None
        v.salir_tutorial(confirmar=False)
        # con datos propios en la BD no se ofrece
        logica_tramos.crear_tramo({"codigo": "MIO", "via": "x"})
        llamado.clear()
        assert v.ofrecer_tutorial() is None and not llamado
    finally:
        v.cerrar()
        basedatos.cerrar()


def test_main_con_tutorial_abre_el_panel_y_sin_la_opcion_ofrece(tmp_path, silencio, monkeypatch):
    import main
    import time
    import app.ui.ventana_principal as vp
    from app.ui import dialogo_tutorial as dt, estilos
    monkeypatch.setattr(estilos, "hacer_dpi_consciente", lambda: None)
    monkeypatch.setenv("PAVIMENTO_LOG", "")
    ofrecido = []
    monkeypatch.setattr(dt.DialogoOfertaTutorial, "abrir", lambda self: ofrecido.append(1) or "ahora_no")
    resultado = {}
    original = vp.VentanaPrincipal.mainloop

    def bucle(self, n=0):
        for _ in range(30):
            self.update()
            time.sleep(0.05)
        resultado["panel"] = self.panel_tutorial is not None
        self.salir_tutorial(confirmar=False) if self.panel_tutorial else None
        self.destroy()
    monkeypatch.setattr(vp.VentanaPrincipal, "mainloop", bucle)
    try:
        assert main.main(["--bd", str(tmp_path / "a" / "p.db"), "--log-dir", str(tmp_path / "l1"), "--tutorial"]) == 0
    except tk.TclError as e:
        pytest.skip(f"sin pantalla: {e}")
    assert resultado["panel"] and not ofrecido
    assert main.main(["--bd", str(tmp_path / "b" / "p.db"), "--log-dir", str(tmp_path / "l2")]) == 0
    assert not resultado["panel"] and ofrecido == [1]                          # BD nueva y vacía: se ofrece
    monkeypatch.setattr(vp.VentanaPrincipal, "mainloop", original)
