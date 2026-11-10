"""F5 · validación: VP/FP/FN/VN por ROI y tipo con casos FORZADOS, geometría de referencia, solapes y e2e."""
import pytest

from app import basedatos, logica_deteccion as ld, logica_fichas as lf, logica_roi as lr
from app import logica_tramos as lt, logica_validacion as lv
from app.logica_comun import ErrorValidacion
from app.modelos import Deteccion, EjecucionAnalisis, Validacion
from app.nucleo.estructuras import TIPOS
from app.nucleo.parametros import Params
from tests.test_importacion import CSV_LEGADO, _csv


# ------------------------------------------------------------------ utilidades de prueba
def crear_ejecucion(tramo, roi, dets=(), provisional=True, metodo="actual", estado="completada", region=None,
                    alcance="roi"):
    """Inserta una ejecución con detecciones elegidas a mano (resultado conocido, sin correr el motor)."""
    with basedatos.nueva_sesion() as s:
        from sqlalchemy import select
        from app.modelos import Tramo
        t = s.scalar(select(Tramo).where(Tramo.codigo == tramo))
        r = region or (roi["x0"], roi["y0"], roi["x1"], roi["y1"])
        p = Params(gsd_cm=0.5)
        e = EjecucionAnalisis(tramo_id=t.id, roi_id=roi["id"] if alcance == "roi" else None, alcance=alcance,
                              metodo=metodo, x0=r[0], y0=r[1], x1=r[2], y1=r[3], params_json=p.a_dict(),
                              params_version=p.version, params_huella=p.huella(), provisional=provisional,
                              estado=estado)
        s.add(e)
        s.flush()
        for d in dets:
            geom = d.get("geom_px")
            s.add(Deteccion(ejecucion_id=e.id, roi_id=d.get("roi_id", roi["id"]), tipo=d["tipo"],
                            geom_tipo=d.get("geom_tipo", "polilinea_aprox"), geom_px=geom, x=0, y=0, w=1, h=1,
                            cx=0.0, cy=0.0, longitud_m=d.get("longitud_m"), ancho_mm=d.get("ancho_mm"),
                            area_m2=d.get("area_m2"), severidad_prelim=d.get("severidad_prelim")))
        s.flush()
        return e.id


@pytest.fixture
def rois_prueba(tramo, tmp_path):
    from app import logica_importacion as li
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    rois = {r["codigo"]: r for r in lr.listar_rois(tramo)}
    for r in rois.values():
        lr.cambiar_rol(r["id"], "prueba")
    return tramo, {k: lr.obtener_roi(v["id"]) for k, v in rois.items()}


def fila(res, roi_codigo, tipo):
    return next(f for f in res["filas"] if f["roi_codigo"] == roi_codigo and f["tipo"] == tipo)


# ------------------------------------------------------------------ casos forzados
def test_clasificar_unidad_las_cuatro_celdas():
    assert lv.clasificar_unidad(True, 3) == (1, 0, 0, 0)       # VP
    assert lv.clasificar_unidad(False, 2) == (0, 1, 0, 0)      # FP
    assert lv.clasificar_unidad(True, 0) == (0, 0, 1, 0)       # FN
    assert lv.clasificar_unidad(False, 0) == (0, 0, 0, 1)      # VN
    assert lv.clasificar_unidad(True, 1, solape=0.29, umbral=0.30) == (0, 0, 1, 0)   # mal ubicada
    assert lv.clasificar_unidad(True, 1, solape=0.30, umbral=0.30) == (1, 0, 0, 0)
    assert lv.clasificar_unidad(True, 0, solape=None) == (0, 0, 1, 0)


def test_vp_fp_fn_vn_forzados_por_roi_y_tipo(rois_prueba):
    tramo, r = rois_prueba
    # R01 transversal: detecta transversal (VP) y además longitudinal (FP)
    e1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}, {"tipo": "longitudinal"}])
    # R02 longitudinal: no detecta nada (FN)
    e2 = crear_ejecucion(tramo, r["R02"], [])
    # R05 sano: detecta bache (FP) ; R03 cocodrilo detecta cocodrilo; R04 bache no detecta
    e5 = crear_ejecucion(tramo, r["R05"], [{"tipo": "bache"}])
    e3 = crear_ejecucion(tramo, r["R03"], [{"tipo": "piel_cocodrilo"}])
    e4 = crear_ejecucion(tramo, r["R04"], [])
    res = lv.evaluar(tramo, [e1, e2, e3, e4, e5])
    assert len(res["filas"]) == 5 * 4 and res["guardado"] and res["provisional"]
    for f in res["filas"]:                                      # exactamente una celda por unidad
        assert f["vp"] + f["fp"] + f["fn"] + f["vn"] == 1
    g = lambda c, t: tuple(fila(res, c, t)[k] for k in ("vp", "fp", "fn", "vn"))
    assert g("R01", "transversal") == (1, 0, 0, 0)
    assert g("R01", "longitudinal") == (0, 1, 0, 0)
    assert g("R01", "bache") == (0, 0, 0, 1)
    assert g("R02", "longitudinal") == (0, 0, 1, 0)
    assert g("R05", "bache") == (0, 1, 0, 0)
    assert all(g("R05", t) != (1, 0, 0, 0) and g("R05", t)[2] == 0 for t in TIPOS)     # 'sano': sin FN ni VP
    assert g("R03", "piel_cocodrilo") == (1, 0, 0, 0)
    assert g("R04", "bache") == (0, 0, 1, 0)
    tot = res["totales"]
    assert tot["bache"] == {"vp": 0, "fp": 1, "fn": 1, "vn": 3, "n": 5}
    assert tot["longitudinal"] == {"vp": 0, "fp": 1, "fn": 1, "vn": 3, "n": 5}
    assert any("PROVISIONAL" in a for a in res["advertencias"])


def test_guardado_en_validacion_es_idempotente_y_marca_provisional(rois_prueba):
    tramo, r = rois_prueba
    e1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], provisional=False)
    res = lv.evaluar(tramo, [e1], umbral_solape=0.4)
    assert res["provisional"] is False and not any("PROVISIONAL" in a for a in res["advertencias"])
    assert res["sin_ejecucion"] == ["R02", "R03", "R04", "R05"]
    lv.evaluar(tramo, [e1], umbral_solape=0.4)                  # repetir no duplica
    filas = lv.listar_validacion(e1)
    assert len(filas) == 4 and {f["tipo"] for f in filas} == set(TIPOS)
    assert all(f["umbral_solape"] == 0.4 and f["roi_codigo"] == "R01" and f["rol"] == "prueba" for f in filas)
    lv.eliminar_validacion(e1)
    assert lv.listar_validacion(e1) == []


def test_solo_prueba_cuenta_y_calibracion_no_se_guarda(rois_prueba):
    tramo, r = rois_prueba
    lr.cambiar_rol(r["R03"]["id"], "calibracion")
    e1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])
    e2 = crear_ejecucion(tramo, r["R03"], [{"tipo": "piel_cocodrilo"}])
    res = lv.evaluar(tramo, [e1, e2])
    assert {f["roi_codigo"] for f in res["filas"]} == {"R01"}                # R03 (calibración) no entra
    cal = lv.evaluar(tramo, [e1, e2], rol="calibracion")
    assert {f["roi_codigo"] for f in cal["filas"]} == {"R03"} and cal["guardado"] is False
    assert lv.listar_validacion(e2) == []
    with pytest.raises(ErrorValidacion) as ei:
        lv.evaluar(tramo, [e2], rol="calibracion", guardar=True)
    assert "guardar" in ei.value.errores


def test_solape_calibracion_prueba_bloquea_o_advierte(rois_prueba):
    tramo, r = rois_prueba
    lr.cambiar_rol(r["R03"]["id"], "calibracion")
    # (R03 no toca a R01) R06 de calibración que pisa a R01 (prueba)
    lr.crear_roi(tramo, {"codigo": "R06", "tipo_campo": "transversal", "x0": 200, "y0": 100, "x1": 400, "y1": 300,
                         "rol": "calibracion"})
    e1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])
    with pytest.raises(ErrorValidacion) as ei:
        lv.evaluar(tramo, [e1])
    assert "R01" in ei.value.errores["rois"] and "R06" in ei.value.errores["rois"]
    assert lv.listar_validacion(e1) == []                                   # no guardó nada
    res = lv.evaluar(tramo, [e1], solapes="advertir")
    assert any("NO es independiente" in a for a in res["advertencias"])


def test_errores_de_uso(rois_prueba):
    tramo, r = rois_prueba
    e_mala = crear_ejecucion(tramo, r["R01"], [], estado="error")
    with pytest.raises(ErrorValidacion):
        lv.evaluar(tramo, [e_mala])
    with pytest.raises(ErrorValidacion):
        lv.evaluar(tramo, [], umbral_solape=0.5)                             # ninguna ejecución cubre
    for kw in ({"umbral_solape": 0}, {"umbral_solape": 1.5}, {"tolerancia_m": -1}, {"modo": "x"}, {"rol": "x"},
               {"solapes": "x"}):
        with pytest.raises(ErrorValidacion):
            lv.evaluar(tramo, [e_mala], **kw)
    lt.crear_tramo({"codigo": "VACIO"})
    with pytest.raises(ErrorValidacion):
        lv.evaluar("VACIO")                                                  # sin ROI de prueba


def test_sin_ejecuciones_explicitas_usa_la_ultima_completada_por_roi(rois_prueba):
    tramo, r = rois_prueba
    crear_ejecucion(tramo, r["R01"], [])                                     # vieja: no detecta
    nueva = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])      # reciente: detecta
    crear_ejecucion(tramo, r["R01"], [], estado="cancelada")                 # se ignora
    crear_ejecucion(tramo, r["R01"], [], metodo="sun")                       # otro método: se ignora
    res = lv.evaluar(tramo)
    assert res["ejecuciones"] == [nueva]
    assert fila(res, "R01", "transversal")["vp"] == 1
    assert any("varias ejecuciones" in a for a in res["advertencias"])


def test_ejecucion_de_tramo_completo_usa_la_roi_contenedora(rois_prueba):
    tramo, r = rois_prueba
    reg = (0, 0, 2400, 1400)
    eid = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal", "roi_id": r["R01"]["id"]},
                                            {"tipo": "bache", "roi_id": r["R04"]["id"]}],
                          region=reg, alcance="tramo")
    res = lv.validar_ejecucion(eid)
    assert len(res["filas"]) == 5 * 4 and res["sin_ejecucion"] == []
    assert fila(res, "R01", "transversal")["vp"] == 1 and fila(res, "R04", "bache")["vp"] == 1
    assert fila(res, "R02", "longitudinal")["fn"] == 1


def test_patologia_con_presencia_falsa_anula_el_tipo_de_campo_y_otra_lo_agrega(rois_prueba):
    tramo, r = rois_prueba
    assert lv.tipos_presentes({"tipo_campo": "sano"}, []) == set()
    assert lv.tipos_presentes({"tipo_campo": "bache"}, [{"tipo_motor": "bache", "presencia": False}]) == set()
    assert lv.tipos_presentes({"tipo_campo": "bache"}, [{"tipo_motor": "bache", "presencia": False},
                                                       {"tipo_motor": "bache", "presencia": True}]) == {"bache"}
    assert lv.tipos_presentes({"tipo_campo": "bache"}, [{"tipo_motor": "longitudinal", "presencia": True},
                                                       {"tipo_motor": None, "presencia": True}]) == {"bache", "longitudinal"}
    # contra la BD: ficha GLO con presencia=False en R02 (longitudinal) -> la referencia pasa a «ausente»
    insp = lf.crear("inspeccion", {"fecha": "2026-05-01", "observador": 1}, tramo)
    lf.registrar_patologia(insp["id"], {"codigo": "GLO", "roi_id": r["R02"]["id"], "presencia": False})
    e2 = crear_ejecucion(tramo, r["R02"], [])
    res = lv.evaluar(tramo, [e2])
    assert (fila(res, "R02", "longitudinal")["vn"], fila(res, "R02", "longitudinal")["fn"]) == (1, 0)


# ------------------------------------------------------------------ geometría de referencia
def test_geometria_referencia_crud_y_validaciones(rois_prueba):
    tramo, r = rois_prueba
    g = lv.registrar_geometria_referencia(r["R01"]["id"], "linea", [(300, 100), (300, 900)])
    assert g["tipo"] == "linea" and g["advertencias"] == [] and len(lv.listar_geometrias_referencia(r["R01"]["id"])) == 1
    g2 = lv.registrar_geometria_referencia(r["R01"]["id"], "linea", [(300, 100), (5000, 900)])
    assert "fuera de la ROI" in g2["advertencias"][0]
    lv.eliminar_geometria_referencia(g2["id"])
    for tipo, pts in (("curva", [(0, 0), (1, 1)]), ("linea", [(0, 0)]), ("poligono", [(0, 0), (1, 1)]),
                      ("linea", [(0, 0), (float("nan"), 1)]), ("linea", "abc")):
        with pytest.raises(ErrorValidacion):
            lv.registrar_geometria_referencia(r["R01"]["id"], tipo, pts)


def test_solape_dice_valores_conocidos():
    region = (0, 0, 200, 200)
    ref = [("linea", [(100, 10), (100, 190)])]
    assert lv.solape_dice(ref, ref, region, 0) == pytest.approx(1.0)
    assert lv.solape_dice(ref, [("linea", [(100, 10), (100, 190)])], region, 3) == pytest.approx(1.0)
    assert lv.solape_dice(ref, [("linea", [(150, 10), (150, 190)])], region, 3) == 0.0     # disjuntas
    near = lv.solape_dice(ref, [("linea", [(102, 10), (102, 190)])], region, 3)             # dentro de la tolerancia
    far = lv.solape_dice(ref, [("linea", [(112, 10), (112, 190)])], region, 3)
    assert near > 0.6 > far
    # polígonos: dos cuadrados de 100x100 desplazados 50 -> intersección 50x100 -> Dice = 2*5000/20000 = 0.5
    a = [("poligono", [(0, 0), (100, 0), (100, 100), (0, 100)])]
    b = [("poligono", [(50, 0), (150, 0), (150, 100), (50, 100)])]
    assert lv.solape_dice(a, b, region, 0) == pytest.approx(0.5, abs=0.03)
    assert lv.solape_dice([], [], region, 3) is None                                        # nada que comparar
    assert lv.solape_dice(ref, [], region, 3) == 0.0


def test_validacion_por_solape_con_geometria(rois_prueba):
    tramo, r = rois_prueba
    roi = r["R01"]                                      # x 150..480, y 80..1080
    lv.registrar_geometria_referencia(roi["id"], "linea", [(300, 100), (300, 1000)])
    buena = [{"tipo": "transversal", "geom_px": [[300, 100], [300, 1000]]}]
    mala = [{"tipo": "transversal", "geom_px": [[440, 100], [440, 1000]]}]
    e_buena = crear_ejecucion(tramo, roi, buena)
    e_mala = crear_ejecucion(tramo, roi, mala)
    rb = lv.evaluar(tramo, [e_buena], tolerancia_m=0.05, guardar=False)
    rm = lv.evaluar(tramo, [e_mala], tolerancia_m=0.05, guardar=False)
    fb, fm = fila(rb, "R01", "transversal"), fila(rm, "R01", "transversal")
    assert fb["modo"] == "geometria" and fb["vp"] == 1 and fb["solape"] == pytest.approx(1.0)
    assert fm["modo"] == "geometria" and fm["vp"] == 0 and fm["fn"] == 1 and fm["solape"] == 0.0
    # los otros tipos de la ROI siguen por presencia
    assert fila(rb, "R01", "bache")["modo"] == "presencia"
    # modo 'presencia' ignora la geometría: la detección mal ubicada pasa a ser VP
    rp = lv.evaluar(tramo, [e_mala], modo="presencia", guardar=False)
    assert fila(rp, "R01", "transversal")["vp"] == 1 and fila(rp, "R01", "transversal")["solape"] is None
    # umbral configurable
    rl = lv.evaluar(tramo, [e_buena], umbral_solape=1.0, tolerancia_m=0.05, guardar=False)
    assert fila(rl, "R01", "transversal")["vp"] == 1
    # ROI de referencia geométrica sin detecciones -> FN con solape 0
    e_vacia = crear_ejecucion(tramo, roi, [])
    rv = lv.evaluar(tramo, [e_vacia], guardar=False)
    assert (fila(rv, "R01", "transversal")["fn"], fila(rv, "R01", "transversal")["solape"]) == (1, 0.0)


def test_poligono_aprox_cuenta_como_poligono_en_el_solape(rois_prueba):
    tramo, r = rois_prueba
    roi = r["R03"]                                      # cocodrilo x 950..1450, y 100..550
    cuadro = [[1000, 150], [1400, 150], [1400, 500], [1000, 500]]
    lv.registrar_geometria_referencia(roi["id"], "poligono", cuadro)
    eid = crear_ejecucion(tramo, roi, [{"tipo": "piel_cocodrilo", "geom_tipo": "poligono_aprox", "geom_px": cuadro}])
    res = lv.evaluar(tramo, [eid], guardar=False)
    assert fila(res, "R03", "piel_cocodrilo")["solape"] == pytest.approx(1.0)


# ------------------------------------------------------------------ extremo a extremo con el motor real
def test_e2e_motor_real_sobre_imagen_sintetica(tramo, tmp_path):
    from app import logica_importacion as li
    li.importar_rois(tramo, _csv(tmp_path, CSV_LEGADO))
    lt.definir_eje(tramo, [(0, 700), (2400, 700)])
    for r in lr.listar_rois(tramo):
        lr.cambiar_rol(r["id"], "prueba")
    ejec = ld.analizar_rois(tramo)
    res = lv.evaluar(tramo, [e["id"] for e in ejec])
    assert res["provisional"] is True
    for t in TIPOS:
        tot = res["totales"][t]
        assert tot["fp"] == 0 and tot["fn"] == 0, (t, tot)         # la imagen sintética se detecta sin errores
    assert sum(res["totales"][t]["vp"] for t in TIPOS) == 4
    assert len(lv.listar_validacion(tramo=tramo)) == 20


def test_opciones_y_grupos_validados(rois_prueba):
    tramo, r = rois_prueba
    assert lv.opciones_por_defecto() == {"umbral_solape": 0.30, "tolerancia_m": 0.10, "modo": "auto",
                                         "solapes": "bloquear"}
    assert lv.leer_opciones({"umbral_solape": "0,5"})["umbral_solape"] == 0.5
    with pytest.raises(ErrorValidacion) as e:
        lv.leer_opciones({"umbral_solape": "2", "tolerancia_m": "x", "modo": "zzz"})
    assert set(e.value.errores) == {"umbral_solape", "tolerancia_m", "modo"}          # todos los errores a la vez
    a1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}])
    a2 = crear_ejecucion(tramo, r["R01"], [])
    s1 = crear_ejecucion(tramo, r["R01"], [{"tipo": "transversal"}], metodo="sun")
    for e in (a1, a2, s1):
        lv.evaluar(tramo, [e])
    g = lv.grupos_validados(tramo)
    assert [x["metodo"] for x in g] == ["sun", "actual"]                              # más reciente primero
    assert g[1]["ejecuciones"] == [a2] and g[1]["n_rois"] == 1 and g[1]["provisional"] is True
