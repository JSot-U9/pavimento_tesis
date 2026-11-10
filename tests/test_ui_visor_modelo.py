"""Geometría del visor y lectura por ventanas, sin pantalla."""
import time

import numpy as np
import pytest

from app.nucleo.lectura import LectorArray
from app.ui import imagen_visor as iv
from app.ui import visor_modelo as vm


def test_ajuste_conversiones_y_limites():
    m = vm.ModeloVisor(2400, 1400, 800, 600)
    assert m.escala == pytest.approx(800 / 2400) and m.region_visible() == (0, 0, 2400, 1400)
    assert m.pantalla_a_imagen(400, 300) == pytest.approx((1200, 700))
    px, py = m.imagen_a_pantalla(*m.pantalla_a_imagen(123, 45))
    assert (px, py) == pytest.approx((123, 45))
    m.zoom(100)                                                     # no pasa del máximo
    assert m.escala == vm.ESCALA_MAX
    m.zoom(1e-9)                                                    # ni baja del mínimo
    assert m.escala == pytest.approx(m.escala_min())
    m.zoom_a(1.0)
    m.desplazar(1e6, 1e6)                                           # no se sale de la imagen
    assert m.ox == 0 and m.oy == 0
    m.desplazar(-1e6, -1e6)
    assert m.ox == pytest.approx(2400 - 800) and m.oy == pytest.approx(1400 - 600)


def test_zoom_mantiene_fijo_el_punto_bajo_el_cursor():
    m = vm.ModeloVisor(10000, 8000, 800, 600)
    m.zoom_a(0.5, 0, 0)
    antes = m.pantalla_a_imagen(321, 210)
    m.zoom(1.25, 321, 210)
    assert m.pantalla_a_imagen(321, 210) == pytest.approx(antes, abs=1e-6)


def test_region_visible_y_salida_coinciden_con_la_posicion_en_pantalla():
    m = vm.ModeloVisor(5000, 3000, 800, 600)
    m.zoom_a(0.4, 100, 100)
    m.desplazar(-37.5, -12.25)
    r = m.region_visible()
    w, h = m.salida_de_region(r)
    px, py = m.posicion_de_region(r)
    assert px <= 0 and py <= 0 and px + w >= 799 and py + h >= 599      # cubre toda la vista


def test_imagen_mas_pequena_que_la_vista_se_centra_y_redimensionar_conserva_centro():
    m = vm.ModeloVisor(100, 50, 800, 600)
    m.zoom_a(2.0)
    assert m.imagen_a_pantalla(0, 0)[0] > 0                         # centrada, con margen
    g = vm.ModeloVisor(10000, 10000, 500, 500)
    g.zoom_a(1.0)
    g.centrar_en(4000, 6000)
    g.redimensionar(1000, 700)
    assert g.pantalla_a_imagen(500, 350) == pytest.approx((4000, 6000), abs=1.0)


def test_enfocar_region():
    m = vm.ModeloVisor(10000, 2000, 1000, 600)
    m.enfocar_region((4000, 500, 4500, 800))
    x0, y0, x1, y1 = m.region_visible()
    assert x0 <= 4000 and x1 >= 4500 and y0 <= 500 and y1 >= 800


def test_escala_miniatura_acota_los_pixeles():
    assert vm.escala_miniatura(1000, 1000) == 1.0
    e = vm.escala_miniatura(100000, 2000)
    assert e * 100000 * e * 2000 == pytest.approx(4_000_000, rel=0.01) and 0 < e < 0.2
    m = vm.ModeloVisor(100000, 2000, 1000, 700)
    assert not m.necesita_fuente(1.0) and m.necesita_fuente(None)
    m.zoom_a(0.5)
    assert m.necesita_fuente(e)
    m.zoom_a(m.escala_min())
    assert not m.necesita_fuente(max(e, m.escala))


def test_dibujo_rectangulo_y_polilinea():
    assert vm.normalizar_rect((500.4, 90.6), (-20, 10), 400, 300) == (0, 10, 400, 91)
    assert vm.limpiar_polilinea([(0, 0), (0.2, 0.1), (10, 10), (10, 10), (20, 5)]) == [(0, 0), (10, 10), (20, 5)]


def _det(i, tipo, geom_tipo, geom):
    xs, ys = [p[0] for p in geom], [p[1] for p in geom]
    return {"id": i, "tipo": tipo, "geom_tipo": geom_tipo, "geom": geom, "bbox": (min(xs), min(ys), max(xs), max(ys))}


def test_seleccion_de_detecciones():
    linea = _det(1, "longitudinal", "polilinea_aprox", [(0, 100), (200, 100)])
    zona = _det(2, "piel_cocodrilo", "poligono", [(0, 0), (300, 0), (300, 300), (0, 300)])
    bache = _det(3, "bache", "poligono", [(100, 150), (160, 150), (160, 200), (100, 200)])
    dets = [zona, linea, bache]
    assert vm.deteccion_en_punto(dets, 100, 103, 5) == 1            # cerca de la línea (que está dentro de la zona)
    assert vm.deteccion_en_punto(dets, 130, 170, 5) == 3            # dentro del bache y de la zona: gana la pequeña
    assert vm.deteccion_en_punto(dets, 250, 250, 5) == 2
    assert vm.deteccion_en_punto(dets, 900, 900, 5) is None
    assert vm.deteccion_en_punto(dets, 100, 112, 5) == 2            # fuera de tolerancia de la línea: queda la zona


# ------------------------------------------------------------------------------------ lectura
def _imagen(w=3000, h=1200):
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[..., 0] = (np.arange(w) * 255 // w)[None, :]
    rgb[..., 1] = (np.arange(h) * 255 // h)[:, None]
    rgb[600:640, 1000:1100, 2] = 255
    return rgb


def test_fuente_array_zona_y_miniatura():
    rgb = _imagen()
    f = iv.FuenteImagen(lector=LectorArray(rgb))
    z = f.leer_zona((1000, 600, 1100, 640), (100, 40))
    assert z.shape == (40, 100, 3) and (z[..., 2] == 255).all()      # nativo, sin remuestreo
    z2 = f.leer_zona((1000, 600, 1100, 640), (400, 160))             # ampliación
    assert z2.shape == (160, 400, 3) and (z2[..., 2] == 255).all()
    z3 = f.leer_zona((0, 0, 3000, 1200), (300, 120))                 # reducción
    assert z3.shape == (120, 300, 3)
    mini, esc = f.miniatura()
    assert esc == 1.0 and mini.shape == rgb.shape                    # 3.6 Mpx < presupuesto: resolución completa
    mini, esc = f.miniatura(max_pixeles=360_000)
    assert esc == pytest.approx(0.316, abs=0.01) and mini.shape[0] * mini.shape[1] <= 360_000 * 1.02
    with pytest.raises(ValueError):
        f.leer_zona((5000, 5000, 6000, 6000), (10, 10))
    assert iv.a_ppm(z).startswith(b"P6 100 40 255\n") and len(iv.a_ppm(z)) == len(b"P6 100 40 255\n") + 100 * 40 * 3


def test_fuente_geotiff_lee_por_ventanas_sin_cargarlo_entero(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    rgb = _imagen(4000, 3000)
    ruta = str(tmp_path / "g.tif")
    with rasterio.open(ruta, "w", driver="GTiff", width=4000, height=3000, count=3, dtype="uint8", tiled=True,
                       blockxsize=256, blockysize=256, crs="EPSG:32719",
                       transform=from_origin(177000.0, 8503000.0, 0.005, 0.005)) as d:
        d.write(np.moveaxis(rgb, -1, 0))
    f = iv.FuenteImagen(ruta)
    assert (f.ancho, f.alto) == (4000, 3000)
    z = f.leer_zona((1000, 600, 1100, 640), (100, 40))
    assert np.array_equal(z, rgb[600:640, 1000:1100])
    r = f.leer_zona((0, 0, 4000, 3000), (400, 300))                  # decimada
    assert r.shape == (300, 400, 3) and abs(int(r[150, 200, 0]) - int(rgb[1500, 2000, 0])) <= 3
    mini, esc = f.miniatura(max_pixeles=120_000)
    assert mini.shape[1] == round(4000 * esc) and esc < 0.2
    f.cerrar()


def test_lector_asincrono_gana_la_ultima_peticion_y_no_bloquea():
    rgb = _imagen()
    lector = iv.LectorAsincrono(lambda: iv.FuenteImagen(lector=LectorArray(rgb)))
    t0 = time.perf_counter()
    lector.pedir_zona("a", (0, 0, 100, 100), (50, 50))
    lector.pedir_zona("b", (1000, 600, 1100, 640), (100, 40))
    assert time.perf_counter() - t0 < 0.05
    vistos, fin = [], time.time() + 10
    while time.time() < fin and not any(e[0] == "zona" and e[1] == "b" for e in vistos):
        vistos += lector.sondear()
        time.sleep(0.02)
    tipos = [e[0] for e in vistos]
    assert tipos[0] == "abierto" and "miniatura" in tipos
    zb = next(e for e in vistos if e[0] == "zona" and e[1] == "b")
    assert zb[3].shape == (40, 100, 3)
    lector.cerrar()


def test_lector_asincrono_informa_error_de_archivo(tmp_path):
    lector = iv.LectorAsincrono(lambda: iv.FuenteImagen(str(tmp_path / "no_existe.png")))
    fin, ev = time.time() + 5, []
    while time.time() < fin and not ev:
        ev = lector.sondear()
        time.sleep(0.02)
    assert ev and ev[0][0] == "error" and "No existe" in ev[0][1]
    lector.cerrar()


def test_zonas_poligono_aprox_se_tratan_como_poligono():
    """Las zonas fusionadas entre teselas llevan geom_tipo 'poligono_aprox' (envolvente convexa)."""
    z = _det(1, "piel_cocodrilo", "poligono_aprox", [(0, 0), (300, 0), (300, 300), (0, 300)])
    assert vm.distancia_a_deteccion(z, 150, 150) == 0.0          # dentro del polígono, no «cerca de una línea»
    assert vm.distancia_a_deteccion(z, 150, 400) == pytest.approx(100.0)
