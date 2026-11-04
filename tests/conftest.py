"""Fixtures compartidas: imagen sintética de ejemplo (5 ROI conocidas), lector y parámetros."""
import pytest

from app.nucleo.lectura import LectorArray
from app.nucleo.parametros import Params
from tests.sintetico import ortomosaico_ejemplo


@pytest.fixture(scope="session")
def ejemplo():
    rgb, rois = ortomosaico_ejemplo()
    return rgb, {r["codigo_roi"]: r for r in rois}


@pytest.fixture(scope="session")
def lector_ejemplo(ejemplo):
    return LectorArray(ejemplo[0], gsd_cm=0.5)


@pytest.fixture
def params():
    return Params()


def region_de(roi):
    return (roi["x"], roi["y"], roi["x"] + roi["ancho"], roi["y"] + roi["alto"])


# ------------------------------------------------------------------ F3: BD y tramo de prueba
import cv2
import numpy as np

from app import basedatos, logica_tramos


@pytest.fixture
def bd():
    basedatos.inicializar(":memory:")
    yield
    basedatos.cerrar()


@pytest.fixture(scope="session")
def png_ejemplo(ejemplo, tmp_path_factory):
    ruta = tmp_path_factory.mktemp("orto") / "ejemplo.png"
    cv2.imwrite(str(ruta), cv2.cvtColor(ejemplo[0], cv2.COLOR_RGB2BGR))
    return str(ruta)


@pytest.fixture
def tramo(bd, png_ejemplo):
    """Tramo T1 con el ortomosaico sintético (2400x1400 px, 0.5 cm/px, sin georreferencia)."""
    logica_tramos.crear_tramo({"codigo": "T1", "via": "Vía de prueba", "progresiva_ini_m": 0, "progresiva_fin_m": 12})
    logica_tramos.asignar_ortomosaico("T1", png_ejemplo, gsd_cm=0.5)
    return "T1"


@pytest.fixture
def tramo_geo(bd, tmp_path):
    """Tramo T2 con GeoTIFF UTM 32719 (norte arriba, origen E=177000 N=8503000, 0.5 cm/px)."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    ruta = str(tmp_path / "geo.tif")
    rgb = np.full((1400, 2400, 3), 110, np.uint8)
    with rasterio.open(ruta, "w", driver="GTiff", width=2400, height=1400, count=3, dtype="uint8", crs="EPSG:32719",
                       transform=from_origin(177000.0, 8503000.0, 0.005, 0.005)) as d:
        d.write(np.moveaxis(rgb, -1, 0))
    logica_tramos.crear_tramo({"codigo": "T2"})
    logica_tramos.asignar_ortomosaico("T2", ruta)
    return "T2"
