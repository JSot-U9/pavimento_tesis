import pytest

from app.nucleo.parametros import PROVISIONALES, Params, aplicar_texto


def test_valores_por_defecto_son_validos():
    Params().validar()


def test_json_ida_y_vuelta_y_huella():
    p = Params().con(grieta_k_mad=5.0)
    q = Params.desde_json(p.a_json())
    assert q == p and q.huella() == p.huella()
    assert Params().huella() != p.huella()


def test_parametro_desconocido_da_mensaje_claro():
    with pytest.raises(ValueError, match="desconocido.*grieta_kmad"):
        Params().con(grieta_kmad=3)


def test_validacion_detecta_incoherencias():
    with pytest.raises(ValueError, match="brillo_min"):
        Params().con(brillo_min=200, brillo_max=100)
    with pytest.raises(ValueError, match="gsd_cm"):
        Params().con(gsd_cm=0)
    with pytest.raises(ValueError, match="sev_grieta_baja_mm"):
        Params().con(sev_grieta_baja_mm=5, sev_grieta_media_mm=3)


def test_version_no_soportada():
    with pytest.raises(ValueError, match="versión"):
        Params.desde_dict({"version": 99})


def test_aplicar_texto():
    p = aplicar_texto(Params(), ["nitidez_min=8", "celdas_min=6"])
    assert p.nitidez_min == 8.0 and p.celdas_min == 6 and isinstance(p.celdas_min, int)
    with pytest.raises(ValueError, match="clave=valor"):
        aplicar_texto(Params(), ["nitidez_min"])
    with pytest.raises(ValueError, match="no es un número"):
        aplicar_texto(Params(), ["nitidez_min=abc"])


def test_provisionales_incluyen_umbrales_de_calidad_y_excluyen_gsd():
    assert "nitidez_min" in PROVISIONALES and "ancho_sigma_px" in PROVISIONALES
    assert "gsd_cm" not in PROVISIONALES


# ---------------------------------------------------------------- F7: esquema v2 y migración
def _dict_v1():
    d = Params().a_dict()
    for k in [k for k in d if k.startswith("sun_")]:
        d.pop(k)
    d["version"] = 1
    return d


def test_version_actual_es_2_y_trae_los_parametros_de_sun():
    from app.nucleo.parametros import CAMPOS_V2, VERSION_PARAMS
    assert VERSION_PARAMS == 2 and Params().version == 2
    assert {"sun_alfa", "sun_beta", "sun_vecinos_superficie", "sun_contraste_min"} <= set(CAMPOS_V2)
    assert all(n in PROVISIONALES for n in CAMPOS_V2)


def test_un_dict_v1_se_lee_conserva_su_version_y_su_huella():
    import hashlib, json
    d = _dict_v1()
    p = Params.desde_dict(d)
    assert p.version == 1 and "sun_alfa" not in p.a_dict() and p.a_dict() == d
    # la huella es la que se habría guardado con el código de la Fase 6 (sha1 del JSON ordenado de los campos v1)
    esperado = hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    assert p.huella() == esperado and p.huella_nucleo() == esperado == Params().huella_nucleo()
    assert Params.desde_json(p.a_json()) == p


def test_migrar_v1_a_v2_agrega_defaults_de_sun_y_es_idempotente():
    p1 = Params.desde_dict(_dict_v1())
    p2 = p1.migrar()
    assert p2.version == 2 and p2.sun_alfa == 0.2247 and p2.migrar() is p2
    assert p2.huella_nucleo() == p1.huella_nucleo() and p2.huella() != p1.huella()
    assert p1.con(grieta_k_mad=5.0).version == 1                         # con() no migra a escondidas


def test_validacion_de_los_parametros_de_sun():
    for cambio in ({"sun_vecinos_superficie": 2}, {"sun_alfa": 0.0}, {"sun_beta": 300.0}, {"sun_cierre_m": 0.0},
                   {"sun_contraste_min": -1.0}):
        with pytest.raises(ValueError, match="sun_"):
            Params().con(**cambio)


def test_calibracion_del_metodo_actual_sobrevive_a_la_migracion_y_sun_siempre_es_provisional(bd):
    from app import logica_configuracion as cfg
    cfg.establecer("params_base", _dict_v1())
    cfg.establecer("params_calibrados_huella", Params.desde_dict(_dict_v1()).con(gsd_cm=Params().gsd_cm).huella())
    base = cfg.params_base()
    assert base.version == 2                                              # params_base() migra al leer
    assert cfg.es_provisional(base, "actual") is False                    # la calibración no se invalida
    assert cfg.es_provisional(base, "sun") is True
    assert cfg.es_provisional(base.con(grieta_k_mad=9.0), "actual") is True


def test_ejecucion_guardada_con_v1_sigue_legible(bd):
    """Una ejecución vieja (params_version 1) se relee con su versión y su huella originales."""
    from app import basedatos, logica_deteccion as ld, logica_tramos as lt
    from app.modelos import EjecucionAnalisis
    t = lt.crear_tramo({"codigo": "TV1"})
    p1 = Params.desde_dict(_dict_v1())
    with basedatos.nueva_sesion() as s:
        s.add(EjecucionAnalisis(tramo_id=t["id"], alcance="tramo", metodo="actual", x0=0, y0=0, x1=10, y1=10,
                                params_json=p1.a_dict(), params_version=1, params_huella=p1.huella(), provisional=True))
    e = ld.listar_ejecuciones("TV1")[0]
    q = ld.parametros_de_ejecucion(e["id"])
    assert q.version == 1 and q.huella() == e["params_huella"] and q == p1
