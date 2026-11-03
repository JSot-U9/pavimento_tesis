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
