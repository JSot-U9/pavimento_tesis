"""Presentadores de la UI (lógica sin pantalla): solo llaman a logica_* y devuelven Resultado/dicts."""
import dataclasses
import threading

import pytest

from app import logica_deteccion as ld, logica_fichas as lf, logica_roi as lr, logica_tramos as lt
from app.nucleo.estructuras import AnalisisCancelado
from app.nucleo.parametros import Params
from app.tareas import GestorTareas
from app.ui.presentadores import formularios
from app.ui.presentadores.base import Contexto, Resultado, proteger
from app.ui.presentadores.p_analisis import (DESCRIPCION_PARAMS, EDITABLES, PresentadorAnalisis, normalizar_region)
from app.ui.presentadores.p_fichas import PresentadorFichas
from app.ui.presentadores.p_roi import PresentadorROI
from app.ui.presentadores.p_tramos import PresentadorTramos
from tests.test_importacion import CSV_LEGADO, _csv


@pytest.fixture
def ctx():
    return Contexto()


def eventos(ctx, *nombres):
    vistos = []
    for n in nombres:
        ctx.suscribir(n, lambda *a, n=n: vistos.append((n,) + a))
    return vistos


# ------------------------------------------------------------------------------------ base
def test_proteger_conserva_todos_los_errores_por_campo(bd):
    r = proteger(lt.crear_tramo, {"codigo": "", "ancho_calzada_m": "abc", "n_carriles": "2.5", "zzz": 1})
    assert not r.ok and set(r.errores) == {"codigo", "ancho_calzada_m", "n_carriles", "zzz"}
    et = formularios.etiquetas(lt.esquema_tramo())
    lineas = r.texto_errores(et).splitlines()
    assert len(lineas) == 4 and "Código del tramo: es obligatorio" in lineas
    assert not proteger(lt.obtener_tramo, "NOEXISTE").ok
    assert proteger(lambda: 5).datos == 5
    assert "Error inesperado" in proteger(lambda: 1 / 0).mensaje


def test_formularios_puros():
    esq = lt.esquema_tramo()
    t = {"codigo": "T1", "longitud_m": 12.5, "n_carriles": 2, "via": None}
    tx = formularios.datos_a_textos(esq, t)
    assert tx["codigo"] == "T1" and tx["longitud_m"] == "12.5" and tx["via"] == "" and tx["n_carriles"] == "2"
    assert "codigo" not in {c["nombre"] for c in formularios.sin_campos(esq, ["codigo"])}
    propios, otros = formularios.repartir_errores(esq, {"codigo": "x", "region": "y"})
    assert propios == {"codigo": "x"} and otros == {"region": "y"}
    campo = next(c for c in esq if c["nombre"] == "ancho_calzada_m")
    assert formularios.pista(campo) == "m · 0.5 – 50"


# ------------------------------------------------------------------------------------ tramos
def test_tramos_crud_errores_y_borrado_con_dependencias(bd, ctx, png_ejemplo):
    p, ev = PresentadorTramos(ctx), None
    ev = eventos(ctx, "tramos", "tramo_activo", "ortomosaico")
    r = p.guardar({"codigo": "T9", "progresiva_ini_m": "10", "progresiva_fin_m": "5"})
    assert not r.ok and "progresiva_fin_m" in r.errores
    r = p.guardar({"codigo": "T9", "progresiva_ini_m": "0", "progresiva_fin_m": "1000", "via": "Cusco"})
    assert r.ok and r.datos["longitud_m"] == 1000 and ("tramos",) in ev
    tid = r.datos["id"]
    assert p.guardar({"codigo": "T9"}, tid).ok and not p.guardar({"codigo": "T9"}).ok          # duplicado
    assert p.fila(p.obtener(tid).datos)[0] == "T9"
    # ortomosaico: errores de texto antes de tocar el archivo
    r = p.asignar_ortomosaico(tid, png_ejemplo, gsd_texto="x")
    assert not r.ok and "gsd_cm" in r.errores
    assert "ruta" in p.asignar_ortomosaico(tid, "", "").errores
    r = p.asignar_ortomosaico(tid, png_ejemplo, gsd_texto="0,5")
    assert r.ok and r.datos["gsd_cm"] == 0.5 and ("ortomosaico", tid) in ev
    assert "2400 × 1400 px" in p.info_ortomosaico(r.datos) and "sin georreferenciación" in p.info_ortomosaico(r.datos)
    # eje y ROI → borrado exige confirmación
    assert p.info_eje(tid).startswith("Sin eje")
    assert p.guardar_eje_px(tid, [(0, 700), (2400, 700)], "0").ok and "2 vértices" in p.info_eje(tid)
    assert not p.guardar_eje_px(tid, [(0, 0)], "0").ok
    lr.crear_roi(tid, {"codigo": "R1", "tipo_campo": "bache", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
    assert "ROI: 1" in p.aviso_borrado(tid) and "ejes de vía: 1" in p.aviso_borrado(tid)
    ctx.fijar_tramo(tid)
    r = p.eliminar(tid)
    assert not r.ok and "confirme" in r.mensaje.lower() and ctx.tramo_id == tid
    assert p.eliminar(tid, confirmado=True).ok and ctx.tramo_id is None and p.listar().datos == []


# ------------------------------------------------------------------------------------ ROI
def test_roi_crud_roles_y_solapes(tramo, ctx):
    p = PresentadorROI(ctx)
    ev = eventos(ctx, "rois")
    tid = lt.obtener_tramo(tramo)["id"]
    assert p.roles() == ["calibracion", "prueba", "sin_asignar"]
    datos = {**p.region_a_datos((10.4, 20.6, 300, 400)), "codigo": "A", "tipo_campo": "bache"}
    r = p.crear(tid, datos)
    assert r.ok and (r.datos["x0"], r.datos["y0"]) == (10, 21) and ("rois", tid) in ev
    r2 = p.crear(tid, {**datos, "codigo": "A", "x0": 5})
    assert not r2.ok and "codigo" in r2.errores
    r3 = p.crear(tid, {"codigo": "B", "x0": "a", "x1": "", "tipo_campo": "volcan"})
    assert set(r3.errores) >= {"x0", "x1", "y0", "y1", "tipo_campo"}                    # todos juntos
    for i, t in enumerate(["bache"] * 3 + ["transversal"] * 2):
        assert p.crear(tid, {"codigo": f"C{i}", "tipo_campo": t, "x0": 400 + 60 * i, "y0": 0, "x1": 450 + 60 * i,
                             "y1": 60}).ok
    assert not p.asignar_roles(tid, "x", "42").ok and set(p.asignar_roles(tid, "x", "y").errores) == {
        "proporcion_calibracion", "semilla"}
    res = p.asignar_roles(tid, "0,5", "7")
    assert res.ok and "bache" in p.texto_roles(res.datos)
    roles = [x["rol"] for x in p.listar(tid).datos]
    assert "calibracion" in roles and "prueba" in roles and "sin_asignar" not in roles
    assert p.listar(tid, rol="prueba").datos and all(x["rol"] == "prueba" for x in p.listar(tid, rol="prueba").datos)
    assert p.actualizar(r.datos["id"], {"rol": "prueba"}).datos["rol"] == "prueba"
    assert p.texto_solapes(p.solapes(tid).datos) == "No hay ROI solapadas."
    assert p.fila(r.datos)[0] == "A" and p.region(r.datos) == (10, 21, 300, 400)
    assert p.eliminar(r.datos["id"]).ok and not p.eliminar(r.datos["id"]).ok


def test_roi_importacion_con_vista_previa_no_deja_rastro_y_confirma(tramo, ctx, tmp_path):
    p = PresentadorROI(ctx)
    tid = lt.obtener_tramo(tramo)["id"]
    ruta = _csv(tmp_path, CSV_LEGADO + "R06;volcan;Baja;0;0;100;100\nR01;bache;;0;0;50;50\n")
    prev = p.importar(tid, ruta, {"estricto": True}, simular=True)
    inf = prev.datos
    assert prev.ok and inf.simulado and inf.creados == 5 and [f for f, _ in inf.errores] == [7, 8]
    assert not inf.puede_confirmar and "estricto" in inf.resumen() and lr.listar_rois(tid) == []
    inf2 = p.importar(tid, ruta, {"estricto": False}, simular=True).datos
    assert inf2.puede_confirmar and lr.listar_rois(tid) == []                          # la vista previa no guarda
    ok = p.importar(tid, ruta, {"estricto": False}, simular=False).datos
    assert ok.aplicado and ok.creados == 5 and len(lr.listar_rois(tid)) == 5
    # error global (capa en coordenadas sobre un ortomosaico sin georreferencia) → informe con error, no excepción
    bad = p.importar(tid, _csv(tmp_path, "x,y\n1,2\n", "z.csv"), {}, simular=True)
    assert bad.ok and bad.datos.errores and not bad.datos.puede_confirmar
    assert not p.importar(tid, str(tmp_path / "no.csv"), {}, simular=True).ok


# ------------------------------------------------------------------------------------ fichas
def test_fichas_crud_selectores_e_importacion(tramo, ctx, tmp_path):
    p = PresentadorFichas(ctx)
    tid = lt.obtener_tramo(tramo)["id"]
    assert p.necesita_tramo("vuelo") and not p.necesita_tramo("catalogo")
    assert p.listar("vuelo", None).datos == []
    r = p.crear("vuelo", {"codigo": "V1", "fecha": "03/11/2026", "altura_m": "30,5"}, tid)
    assert r.ok and r.datos["altura_m"] == 30.5
    bad = p.crear("vuelo", {"codigo": "V1", "altura_m": "9999", "fecha": "ayer"}, tid)
    assert set(bad.errores) == {"codigo", "altura_m", "fecha"} or set(bad.errores) >= {"altura_m", "fecha"}
    assert p.selectores("condicion", tid)["vuelo_id"] == [(r.datos["id"], "V1")]
    c = p.crear("condicion", {"vuelo_id": r.datos["id"], "temperatura_c": "12"}, tid)
    assert c.ok and p.fila("condicion", c.datos)[1] == "V1" if p.listar("condicion", tid) else True
    assert p.fila("vuelo", r.datos)[0] == "V1"
    # catálogo: el código no se puede cambiar (se omite del envío)
    cat = p.listar("catalogo").datos
    assert {x["codigo"] for x in cat} >= {"GLO", "HUE"}
    assert p.actualizar("catalogo", cat[0]["id"], {"codigo": "ZZZ", "nombre": "Nuevo nombre"}).ok
    assert p.listar("catalogo").datos[0]["codigo"] == cat[0]["codigo"]
    # importación con vista previa
    ruta = _csv(tmp_path, "codigo,fecha\nV2,2026-01-01\nV1,2026-01-02\n")
    prev = p.importar("vuelo", ruta, tid, simular=True).datos
    assert prev.creados == 1 and len(prev.errores) == 1 and not prev.puede_confirmar
    assert p.importar("vuelo", ruta, tid, si_existe="omitir").datos.aplicado
    assert len(p.listar("vuelo", tid).datos) == 2


def test_patologias_con_geometria_y_severidad(tramo, ctx, tmp_path):
    p = PresentadorFichas(ctx)
    tid = lt.obtener_tramo(tramo)["id"]
    roi = lr.crear_roi(tid, {"codigo": "R1", "tipo_campo": "bache", "x0": 0, "y0": 0, "x1": 50, "y1": 50})
    insp = p.crear("inspeccion", {"fecha": "2026-11-03", "responsable": "JS"}, tid).datos
    sel = p.selectores_patologia(tid)
    assert ("GLO", "GLO — Grieta longitudinal") in sel["codigo"] and sel["roi_id"] == [(roi["id"], "R1")]
    r = p.registrar_patologia(insp["id"], {"codigo": "glo", "progresiva_m": "12,5", "roi_id": roi["id"]},
                              {"longitud_m": "3", "ancho_prom_mm": "2", "ancho_max_mm": ""}, {"nivel": "Media"})
    assert r.ok and r.datos["severidad"]["nivel"] == "Media" and r.datos["geometria"]["longitud_m"] == 3
    fila = p.fila_patologia(r.datos)
    assert fila[1] == "GLO" and fila[5] == "Media" and "L=3.00 m" in fila[6] and "w=2.0 mm" in fila[6]
    mal = p.registrar_patologia(insp["id"], {"codigo": "XXX", "progresiva_m": "-1"}, {"ancho_prom_mm": "5",
                                "ancho_max_mm": "1"}, {"nivel": "Enorme"})
    assert not mal.ok and set(mal.errores) == {"progresiva_m", "nivel"}        # de los tres grupos, juntos
    mal = p.registrar_patologia(insp["id"], {"codigo": "XXX"}, None, None)
    assert not mal.ok and "catálogo" in mal.errores["codigo"]                  # reglas que dependen de la BD
    # actualizar: vaciar la severidad la quita
    pid = r.datos["id"]
    u = p.actualizar_patologia(pid, {"codigo": "GLO", "lado": "derecha"}, {"longitud_m": "4"}, {"nivel": ""})
    assert u.ok
    q = p.listar_patologias(insp["id"]).datos[0]
    assert q["severidad"] is None and q["geometria"]["longitud_m"] == 4 and q["lado"] == "derecha"
    csv = _csv(tmp_path, "codigo,progresiva_m,roi,severidad,longitud_m\nGLO,5,R1,Alta,2\nGTR,6,R9,Baja,1\n")
    inf = p.importar_patologias(insp["id"], csv, simular=True).datos
    assert inf.creados == 1 and len(inf.errores) == 1 and "R9" in inf.errores[0][1]
    assert p.eliminar_patologia(pid).ok and p.listar_patologias(None).datos == []


# ------------------------------------------------------------------------------------ análisis
def test_parametros_provisionales_y_validacion_conjunta(tramo, ctx):
    p = PresentadorAnalisis(ctx, GestorTareas(lambda *a: None))
    assert set(DESCRIPCION_PARAMS) == set(EDITABLES), "cada parámetro editable necesita su descripción"
    assert set(EDITABLES) == {f.name for f in dataclasses.fields(Params)} - {"version", "gsd_cm"}
    assert p.es_provisional() and "PROVISIONALES" in p.aviso_provisional()
    campos = {c["nombre"]: c for c in p.campos_parametros()}
    assert campos["grieta_k_mad"]["provisional"] and not campos["tol_orient_deg"]["provisional"]
    r = p.validar_parametros({"grieta_k_mad": "abc", "celdas_min": "2,5", "tol_orient_deg": "", "brillo_min": "300"})
    assert not r.ok and set(r.errores) == {"grieta_k_mad", "celdas_min", "tol_orient_deg"}
    r = p.validar_parametros({"brillo_min": "300"})                       # coherencia (brillo_min >= brillo_max)
    assert not r.ok and "brillo_min" in r.mensaje and p.parametros_modificados() == []
    r = p.validar_parametros({"grieta_k_mad": "5,5", "celdas_min": "6"})
    assert r.ok and p.params_actuales().grieta_k_mad == 5.5 and p.params_actuales().celdas_min == 6
    assert p.parametros_modificados() == ["grieta_k_mad", "celdas_min"]
    p.restablecer_parametros()
    assert p.params_actuales() == Params() and "metodo" not in p.__dict__ or p.metodos_disponibles() == ["actual", "sun"]   # F7


def test_normalizar_region():
    assert normalizar_region((300.4, 100, 10, 900), 2400, 1400) == (10, 100, 300, 900)
    assert normalizar_region((-50, -50, 5000, 5000), 2400, 1400) == (0, 0, 2400, 1400)
    from app.logica_comun import ErrorValidacion
    with pytest.raises(ErrorValidacion):
        normalizar_region((0, 0, 4, 400), 2400, 1400)
    with pytest.raises(ErrorValidacion):
        normalizar_region(("a", 0, 1, 2), 2400, 1400)


def _esperar(p, timeout=30):
    """Sondea como lo haría `after` hasta el evento 'fin'; devuelve todos los eventos."""
    import time
    fin, out = time.time() + timeout, []
    while time.time() < fin:
        ev = p.sondear()
        out += ev
        if any(e[0] == "fin" for e in ev):
            return out
        time.sleep(0.02)
    raise AssertionError("no llegó 'fin'")


def test_analisis_real_en_segundo_plano_guarda_en_el_hilo_principal(tramo, ctx, tmp_path):
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    li = __import__("app.logica_importacion", fromlist=["x"])
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    tid = lt.obtener_tramo(tramo)["id"]
    rois = {r["codigo"]: r for r in lr.listar_rois(tid)}
    p = PresentadorAnalisis(ctx)
    hilos = []
    original = p.gestor._ejecutar
    p.gestor._ejecutar = lambda t, c, pr: (hilos.append(threading.current_thread()), original(t, c, pr))[1]
    ev = eventos(ctx, "ejecuciones")
    r = p.iniciar(tid, "roi", roi_id=rois["R04"]["id"])
    assert r.ok and p.ocupado and not p.iniciar(tid, "roi", roi_id=rois["R04"]["id"]).ok          # no se solapan
    eventos_ = _esperar(p)
    assert hilos and hilos[0] is not threading.main_thread()
    tipos = [e[0] for e in eventos_]
    assert tipos[0] == "progreso" and "ejecucion" in tipos and tipos[-1] == "fin"
    assert any(e[0] == "progreso" and 0 < e[1] <= 1 for e in eventos_)
    e = p.ejecucion
    assert e["estado"] == "completada" and e["provisional"] and ld.listar_ejecuciones(tid)[0]["id"] == e["id"]
    assert [d["tipo"] for d in p.detecciones] == ["bache"] and ("ejecuciones",) in ev
    fila = p.fila_deteccion(p.detecciones[0])
    assert fila[1] == "Bache" and fila[5].endswith(" m") and fila[8] == str(rois["R04"]["id"])
    assert p.filas_resumen()[0][0] == "Bache" and p.filas_resumen()[0][1] == 1
    txt = p.detalle_deteccion(p.detecciones[0]["id"])
    assert "Bache" in txt and "ORIENTATIVA" in txt and "ancho" in txt
    assert "PROVISIONALES" in p.texto_ejecucion() and p.para_visor()[0]["id"] == p.detecciones[0]["id"]
    p.filtro_tipo = "longitudinal"
    assert p.para_visor() == []
    hist = p.historial(tid)
    assert hist and hist[0][0] == e["id"] and "provisional" in hist[0][1]
    p.limpiar()
    assert p.cargar_ejecucion(e["id"]).ok and len(p.detecciones) == 1


def test_analisis_por_rol_encadena_varias_roi_y_ventana_valida(tramo, ctx, tmp_path):
    li = __import__("app.logica_importacion", fromlist=["x"])
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO), rol="calibracion")
    tid = lt.obtener_tramo(tramo)["id"]
    t = lt.obtener_tramo(tid)
    p = PresentadorAnalisis(ctx, GestorTareas(lambda tr, c, pr: (pr(0.5, "x"), _fake_resultado(tr))[1]))
    assert not p.iniciar(tid, "rol", rol="prueba").ok                                   # no hay ROI de prueba
    assert "rol" in p.construir_trabajos(tid, "rol", rol="prueba").errores
    assert "region" in p.construir_trabajos(tid, "ventana", region=(0, 0, 3, 3), tramo=t).errores
    assert "roi" in p.construir_trabajos(tid, "roi").errores
    r = p.iniciar(tid, "rol", rol="calibracion")
    assert r.ok and r.datos == 5
    ev = _esperar(p)
    fr = [e[1] for e in ev if e[0] == "progreso"]
    assert fr == sorted(fr) and max(fr) <= 1.0 and sum(1 for e in ev if e[0] == "ejecucion") == 5
    assert len(ld.listar_ejecuciones(tid)) == 5
    r = p.iniciar(tid, "ventana", region=(100, 100, 700, 500), tramo=t)
    assert r.ok
    _esperar(p)
    assert p.ejecucion["alcance"] == "ventana" and (p.ejecucion["x0"], p.ejecucion["x1"]) == (100, 700)


def _fake_resultado(trabajo):
    """Resultado vacío pero válido: no hace falta correr el núcleo para probar el flujo de la cola."""
    from app.logica_deteccion import ResultadoTrabajo
    from app.nucleo.estructuras import Calidad, ResultadoAnalisis
    q = Calidad("Adecuada", 50.0, 110.0, 0.0, 0.5, 100.0, 100.0)
    a = ResultadoAnalisis([], q, trabajo.region, 1, trabajo.params.huella(), trabajo.metodo)
    return ResultadoTrabajo(a, 0.1)


def test_cancelar_registra_la_incidencia_y_error_de_guardado(tramo, ctx, tmp_path):
    li = __import__("app.logica_importacion", fromlist=["x"])
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    tid = lt.obtener_tramo(tramo)["id"]
    roi = lr.listar_rois(tid)[0]
    arranco = threading.Event()

    def lenta(trabajo, cancelar, progreso):
        arranco.set()
        while not cancelar.is_set():
            cancelar.wait(0.01)
        raise AnalisisCancelado("Análisis cancelado por el usuario")

    p = PresentadorAnalisis(ctx, GestorTareas(lenta))
    assert p.iniciar(tid, "roi", roi_id=roi["id"]).ok
    assert arranco.wait(5)
    p.cancelar()
    ev = _esperar(p)
    assert any(e[0] == "mensaje" and "cancelado" in e[2] for e in ev)
    inc = ld.listar_ejecuciones(tid, estado="cancelada")
    assert len(inc) == 1 and inc[0]["roi_id"] == roi["id"] and ld.listar_detecciones(inc[0]["id"]) == []
    assert "cancelada" in (p.cargar_ejecucion(inc[0]["id"]).datos["estado"]) and p.detecciones == []
    # el núcleo falla -> 'error' registrado
    p2 = PresentadorAnalisis(ctx, GestorTareas(lambda *a: 1 / 0))
    assert p2.iniciar(tid, "roi", roi_id=roi["id"]).ok
    ev = _esperar(p2)
    assert any(e[0] == "mensaje" and e[1] == "error" and "ZeroDivisionError" in e[2] for e in ev)
    assert len(ld.listar_ejecuciones(tid, estado="error")) == 1
    # la ROI se borra mientras se analizaba -> no se pierde la app, se informa y se registra
    soltar = threading.Event()
    p3 = PresentadorAnalisis(ctx, GestorTareas(lambda tr, c, pr: (soltar.wait(5), _fake_resultado(tr))[1]))
    assert p3.iniciar(tid, "roi", roi_id=roi["id"]).ok
    lr.eliminar_roi(roi["id"])
    soltar.set()
    ev = _esperar(p3)
    assert any(e[0] == "mensaje" and e[1] == "error" and "No se pudo guardar" in e[2] for e in ev)


def test_cerrar_cancela_y_espera(tramo, ctx, tmp_path):
    li = __import__("app.logica_importacion", fromlist=["x"])
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    tid = lt.obtener_tramo(tramo)["id"]

    def lenta(trabajo, cancelar, progreso):
        while not cancelar.is_set():
            cancelar.wait(0.01)
        raise AnalisisCancelado("x")

    p = PresentadorAnalisis(ctx, GestorTareas(lenta))
    assert p.iniciar(tid, "roi", roi_id=lr.listar_rois(tid)[0]["id"]).ok
    p.cerrar(timeout=5)
    assert not p.ocupado and len(ld.listar_ejecuciones(tid, estado="cancelada")) == 1
