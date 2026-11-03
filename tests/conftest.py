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
