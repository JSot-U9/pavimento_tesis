import os
import struct

import numpy as np
import pytest

from app.crs import ErrorCRS, convertir, zona_utm
from app.geovector import (ErrorFormatoGeo, area_anillo, decodificar_wkb, leer_capa, leer_geojson, leer_gpkg,
                           listar_capas_gpkg, unir_lineas)

DATOS = os.path.join(os.path.dirname(__file__), "datos")


def test_zona_utm():
    assert zona_utm(32719) == (19, True) and zona_utm(32617) == (17, False) and zona_utm(4326) is None


def test_utm_valores_exactos_conocidos():
    e, n = convertir(-69.0, 0.0, 4326, 32719)                      # meridiano central en el ecuador
    assert (float(e), float(n)) == pytest.approx((500000.0, 10_000_000.0), abs=1e-6)
    e, _ = convertir(-68.0, 0.0, 4326, 32719)                      # 1° al este ≈ k0 · 111 319.5 m (orden de magnitud)
    assert float(e) - 500000 == pytest.approx(0.9996 * 111319.49, rel=1e-4)


def test_utm_contra_pyproj():
    pyproj = pytest.importorskip("pyproj")
    rng = np.random.default_rng(0)
    lon, lat = -72 + rng.uniform(-3, 3, 400), rng.uniform(-18, -9, 400)
    ex, ny = pyproj.Transformer.from_crs(4326, 32719, always_xy=True).transform(lon, lat)
    x, y = convertir(lon, lat, 4326, 32719)
    assert np.hypot(x - ex, y - ny).max() < 1e-3                 # < 1 mm
    lo, la = convertir(ex, ny, 32719, 4326)
    assert np.hypot((lo - lon), (la - lat)).max() * 111e3 < 1e-3
    a, b = convertir(ex, ny, 32719, 32718)                       # entre zonas
    a2, b2 = pyproj.Transformer.from_crs(32719, 32718, always_xy=True).transform(ex, ny)
    assert np.hypot(a - a2, b - b2).max() < 1e-3


def test_crs_no_soportado_explica_que_hacer():
    with pytest.raises(ErrorCRS, match="Reproyecte"):
        convertir(1, 2, 24879, 32719)


def test_gpkg_escrito_por_gdal():
    assert listar_capas_gpkg(os.path.join(DATOS, "oraculo.gpkg")) == ["rois"]
    c = leer_gpkg(os.path.join(DATOS, "oraculo.gpkg"))
    assert c.epsg == 32719 and len(c.features) == 4
    tipos = [f["geom"]["tipo"] for f in c.features]
    assert tipos == ["Polygon", "Polygon", "MultiLineString", "Point"]
    assert c.features[0]["props"]["codigo_roi"] == "R1"
    poli = c.features[1]["geom"]["coords"]
    assert len(poli) == 2 and area_anillo(poli[0]) == pytest.approx(25.0)      # con agujero
    assert c.features[3]["geom"]["coords"] == (5.0, 6.0)


def test_geojson_crs84_y_misma_geometria_que_el_gpkg():
    g = leer_geojson(os.path.join(DATOS, "oraculo.geojson"))
    assert g.epsg == 4326
    x, y = g.features[0]["geom"]["coords"][0][0]
    e, n = convertir(x, y, 4326, 32719)
    assert (float(e), float(n)) == pytest.approx((177000.0, 8500000.0), abs=1e-3)


def test_wkb_big_endian_con_z():
    wkb = struct.pack(">BIddd", 0, 1001, 3.0, 4.0, 5.0)           # ISO: PointZ
    assert decodificar_wkb(wkb) == {"tipo": "Point", "coords": (3.0, 4.0)}
    with pytest.raises(ErrorFormatoGeo, match="truncada"):
        decodificar_wkb(wkb[:-9])


def test_capa_formato_no_soportado_y_gpkg_invalido(tmp_path):
    with pytest.raises(ErrorFormatoGeo, match="no soportado"):
        leer_capa(str(tmp_path / "x.shp"))
    malo = tmp_path / "m.gpkg"
    malo.write_bytes(b"no es sqlite")
    with pytest.raises(ErrorFormatoGeo, match="GeoPackage"):
        leer_capa(str(malo))


def test_unir_lineas():
    assert unir_lineas([[(0, 0), (1, 1)], [(1, 1), (2, 0)]]) == [(0, 0), (1, 1), (2, 0)]
    with pytest.raises(ErrorFormatoGeo, match="no empalman"):
        unir_lineas([[(0, 0), (1, 1)], [(5, 5), (6, 6)]])
