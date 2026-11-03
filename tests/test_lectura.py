import cv2
import numpy as np
import pytest

from app.nucleo import lectura
from app.nucleo.estructuras import ErrorLectura
from app.nucleo.lectura import LectorArray, LectorOpenCV, abrir

rng = np.random.default_rng(0)
IMG = rng.integers(1, 255, (120, 200, 3), dtype=np.uint8)


def test_array_ventana_y_recorte():
    lec = LectorArray(IMG, gsd_cm=0.5)
    rgb, nd = lec.leer(10, 20, 60, 50)
    assert rgb.shape == (30, 50, 3) and nd is None
    assert np.array_equal(rgb, IMG[20:50, 10:60])
    rgb, _ = lec.leer(-50, -50, 30, 30)                      # se recorta al borde
    assert rgb.shape == (30, 30, 3)
    rgb[:] = 0                                               # es una copia
    assert IMG[0, 0].any()


def test_ventana_fuera_del_ortomosaico():
    with pytest.raises(ValueError, match="fuera del ortomosaico"):
        LectorArray(IMG).leer(500, 500, 600, 600)


def test_opencv_con_ruta_con_tildes(tmp_path):
    carpeta = tmp_path / "Cañón Pisaq"
    carpeta.mkdir()
    ruta = str(carpeta / "tramo ñ.png")
    ok, buf = cv2.imencode(".png", cv2.cvtColor(IMG, cv2.COLOR_RGB2BGR))
    buf.tofile(ruta)
    lec = abrir(ruta, gsd_cm=0.5)
    assert (lec.ancho, lec.alto, lec.gsd_cm) == (200, 120, 0.5)
    assert np.array_equal(lec.leer(0, 0, 200, 120)[0], IMG)


def test_opencv_rechaza_imagenes_demasiado_grandes(tmp_path):
    ruta = str(tmp_path / "a.png")
    cv2.imwrite(ruta, IMG)
    with pytest.raises(ErrorLectura, match="rasterio.*GeoTIFF"):
        LectorOpenCV(ruta, max_pixeles=1000)


def test_archivo_inexistente_y_formato_invalido(tmp_path):
    with pytest.raises(ErrorLectura, match="No existe"):
        abrir(str(tmp_path / "nada.tif"))
    malo = tmp_path / "malo.png"
    malo.write_bytes(b"no es una imagen")
    with pytest.raises(ErrorLectura, match="no soportado o archivo dañado"):
        abrir(str(malo))


def test_opencv_alfa_se_vuelve_nodata(tmp_path):
    bgra = np.dstack([cv2.cvtColor(IMG, cv2.COLOR_RGB2BGR), np.full(IMG.shape[:2], 255, np.uint8)])
    bgra[:10, :10, 3] = 0
    ruta = str(tmp_path / "a.png")
    cv2.imwrite(ruta, bgra)
    _, nd = LectorOpenCV(ruta).leer(0, 0, 200, 120)
    assert nd[:10, :10].all() and not nd[10:, 10:].any()


@pytest.mark.skipif(not lectura.HAY_RASTERIO, reason="rasterio no instalado")
def test_rasterio_ventanas_georreferencia_y_nodata(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    ruta = str(tmp_path / "orto.tif")
    afin = from_origin(180000.0, 8500000.0, 0.005, 0.005)
    with rasterio.open(ruta, "w", driver="GTiff", width=200, height=120, count=3, dtype="uint8",
                       crs="EPSG:32719", transform=afin, tiled=True, blockxsize=64, blockysize=64,
                       nodata=0) as ds:
        datos = np.moveaxis(IMG, -1, 0).copy()
        datos[:, :8, :8] = 0
        ds.write(datos)
    lec = abrir(ruta)
    assert isinstance(lec, lectura.LectorRasterio)
    assert (lec.ancho, lec.alto) == (200, 120) and lec.gsd_cm == pytest.approx(0.5)
    x, y = lec.transformacion.px_a_geo(0, 0)
    assert (float(x), float(y)) == (180000.0, 8500000.0)
    rgb, nd = lec.leer(50, 40, 150, 100)
    assert np.array_equal(rgb, IMG[40:100, 50:150])
    assert nd is None
    _, nd0 = lec.leer(0, 0, 30, 30)
    assert nd0[:8, :8].all() and not nd0[10:, 10:].any()
    lec.cerrar()


def test_abrir_aplica_gsd_indicado(tmp_path):
    ruta = str(tmp_path / "a.png")
    cv2.imwrite(ruta, IMG)
    assert abrir(ruta, gsd_cm=0.8).gsd_cm == 0.8
