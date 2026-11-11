"""
Pruebas del método 'sun' (Fase 7).

Tres verificaciones independientes de la manta fractal:
  1. `matlab_literal`: transcripción línea a línea del apéndice de Sun (bucles, saturación uint8 de Matlab).
  2. `manta_referencia`: implementación de referencia en numpy/Python puro escrita desde las ecuaciones 4-9 del
     texto (bucles por píxel y ajuste con np.polyfit), sin compartir código con `sun.k_de_bloques`.
  3. Imágenes sintéticas con grietas de ancho y longitud conocidos, y comparación con el método 'actual'.
"""
import math
import threading

import numpy as np
import pytest

from app.nucleo import pipeline, sun
from app.nucleo.eje_via import EjeVia
from app.nucleo.estructuras import AnalisisCancelado
from app.nucleo.lectura import LectorArray
from app.nucleo.parametros import Params
from app.nucleo.pipeline import analizar_region
from tests.conftest import region_de
from tests.sintetico import a_uint8, asfalto, dibujar_grieta


# ====================================================================== referencias independientes
def matlab_literal(seg):
    """k de UN bloque 3x3 uint8, transcrito del apéndice de Sun (índices de Matlab = Python + 1)."""
    L = 3
    seg = np.asarray(seg, np.uint8)
    D = {e: np.zeros((L, L)) for e in range(2, 10)}
    for i in range(1, L + 1):
        for j in range(1, L + 1):
            U = [0.0] * 10
            B = [0.0] * 10
            U[1] = B[1] = float(seg[i - 1, j - 1])
            for k in range(1, 9):
                ax1 = 0 if i - 1 == 0 else int(seg[i - 2, j - 1])
                ax2 = 0 if i + 1 > 3 else int(seg[i, j - 1])
                ax3 = 0 if j - 1 == 0 else int(seg[i - 1, j - 2])
                ax4 = 0 if j + 1 > 3 else int(seg[i - 1, j])
                cx = max(max(max(ax1, ax2), ax4), ax3)
                U[k + 1] = float(min(max(cx, U[k] + 1), 255))          # max(uint8, double) satura en 255
                cn = min(min(min(ax1, ax2), ax4), ax3)
                B[k + 1] = float(min(cn, B[k] + 1))
            for e in range(2, 10):
                D[e][i - 1, j - 1] = U[e] - B[e]
    v = {e: D[e].sum() for e in range(2, 10)}
    a = {e: v[e] / (2 * e) for e in range(2, 10)}                       # a2 = v2/4 ... a9 = v9/18
    aa = [math.log10(a[e]) for e in range(2, 10)]
    ay = sum(aa) / 8
    at = sum(math.log10(e) for e in range(2, 10)) / 8
    x11 = sum((math.log10(i0 + 1) - at) * (aa[i0 - 1] - ay) for i0 in range(1, 9))
    x12 = sum((math.log10(j0) - at) ** 2 for j0 in range(2, 10))
    x1 = x11 / x12
    x0 = ay - x1 * at
    return 10 ** x0


def manta_referencia(bloque, superficies=False):
    """k por la definición del texto: manta u, b con vecinos a distancia < 1 DENTRO del bloque (fuera = 0), area
    A(eps) = V(eps)/(2 eps) y ajuste log A = D log eps + log k con np.polyfit."""
    g = np.asarray(bloque, float)
    vec = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    def v(m, i, j):
        return m[i][j] if 0 <= i < 3 and 0 <= j < 3 else 0.0

    u = [[g[i, j] for j in range(3)] for i in range(3)]
    b = [[g[i, j] for j in range(3)] for i in range(3)]
    log_eps, log_a = [], []
    for eps in range(2, 10):
        nu = [[0.0] * 3 for _ in range(3)]
        nb = [[0.0] * 3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                fuente_u = u if superficies else g
                fuente_b = b if superficies else g
                nu[i][j] = min(max(u[i][j] + 1, max(v(fuente_u, i + di, j + dj) for di, dj in vec)), 255.0)
                nb[i][j] = min(b[i][j] + 1, min(v(fuente_b, i + di, j + dj) for di, dj in vec))
        u, b = nu, nb
        vol = sum(u[i][j] - b[i][j] for i in range(3) for j in range(3))
        log_eps.append(math.log10(eps))
        log_a.append(math.log10(vol / (2 * eps)))
    D, logk = np.polyfit(log_eps, log_a, 1)
    return 10 ** logk


def ruido_referencia(m, d):
    """Regla de Sun por píxel (con el emparejamiento fila-columna CORRECTO que el Matlab no tiene)."""
    H, W = m.shape
    s = m.copy()
    for y in range(H):
        for x in range(W):
            if not m[y, x] or y < d or x < d or y >= H - d or x >= W - d:
                continue
            if all(not m[y + dy, x + dx] for dy in (-d, 0, d) for dx in (-d, 0, d) if (dy, dx) != (0, 0)):
                s[y, x] = 0
    return s


# ====================================================================== manta fractal
def _bloques_aleatorios(n, semilla=0):
    rng = np.random.default_rng(semilla)
    bl = [rng.integers(0, 256, (3, 3)) for _ in range(n // 2)]
    bl += [np.full((3, 3), v) for v in (0, 1, 40, 128, 254, 255)]                     # planos y saturados
    bl += [rng.integers(0, 4, (3, 3)), rng.integers(250, 256, (3, 3)), rng.integers(20, 60, (3, 3))]
    return np.array(bl, np.uint8)


def test_manta_vectorizada_igual_al_matlab_literal():
    bl = _bloques_aleatorios(120)
    k = sun.k_de_bloques(bl, 0)
    esperado = np.array([matlab_literal(b) for b in bl])
    assert np.allclose(k, esperado, rtol=1e-4)


@pytest.mark.parametrize("superficies", [0, 1])
def test_manta_igual_a_la_referencia_independiente(superficies):
    bl = _bloques_aleatorios(80, semilla=5)
    k = sun.k_de_bloques(bl, superficies)
    esperado = np.array([manta_referencia(b, bool(superficies)) for b in bl])
    assert np.allclose(k, esperado, rtol=1e-4)


def test_la_referencia_y_el_matlab_literal_coinciden_entre_si():
    for b in _bloques_aleatorios(30, semilla=9):
        assert matlab_literal(b) == pytest.approx(manta_referencia(b), rel=1e-9)


def test_k_crece_con_el_nivel_de_gris_por_el_relleno_de_ceros():
    """Con vecinos 0 fuera del bloque, k ~ proporcional al gris: por eso T queda ligado a los tonos oscuros."""
    k = sun.k_de_bloques(np.array([np.full((3, 3), g) for g in (20, 60, 120, 200)], np.uint8))
    assert np.all(np.diff(k) > 0) and k[-1] / k[0] > 4


def test_umbral_trunca_hacia_cero_como_fix():
    p = Params()
    assert sun.umbral_de_kmin(141.89166578750806, p) == math.trunc(0.2247 * 141.89166578750806 + 40) == 71.0
    assert sun.umbral_de_kmin(100.0, p.con(sun_alfa=0.3, sun_beta=45.0)) == 75.0


def test_el_umbral_se_acota_para_que_una_imagen_sin_grietas_no_sea_toda_grieta():
    p = Params()
    t, lim = sun.umbral_efectivo(429.3, 120.7, p)           # ROI sana: T de Sun = 136 > media
    assert lim and t == pytest.approx(120.7 - 25.0) and sun.umbral_de_kmin(429.3, p) == 136.0
    t2, lim2 = sun.umbral_efectivo(141.9, 113.0, p)          # imagen con grieta: T = 71, sin tope
    assert not lim2 and t2 == 71.0


def test_constantes_por_defecto_son_las_del_codigo_de_sun():
    p = Params()
    assert (p.sun_alfa, p.sun_beta) == (0.2247, 40.0) and p.sun_vecinos_superficie == 0
    assert {"sun_alfa", "sun_beta", "sun_cierre_m"} <= set(Params.provisionales())


def test_kmin_ventana_ignora_bloques_no_validos_y_respeta_el_anclaje_global():
    rng = np.random.default_rng(2)
    g = rng.integers(90, 130, (60, 60)).astype(np.uint8)
    g[10:13, 9:12] = 5                                                        # bloque muy oscuro
    v = np.ones((60, 60), bool)
    k_con = sun.kmin_ventana(g, v, origen=(0, 0))
    v2 = v.copy()
    v2[10, 9] = False                                                        # un píxel inválido anula el bloque
    k_sin = sun.kmin_ventana(g, v2, origen=(0, 0))
    assert k_sin > k_con
    # la rejilla está anclada a múltiplos de 3 globales: el bloque (9..11) solo existe con origen múltiplo de 3
    assert sun.kmin_ventana(g, v, origen=(1, 0)) > k_con
    assert sun.kmin_ventana(g, np.zeros((60, 60), bool)) is None


def test_kmin_solo_cuenta_bloques_del_nucleo():
    g = np.full((60, 60), 120, np.uint8)
    g[30:33, 30:33] = 5
    v = np.ones((60, 60), bool)
    assert sun.kmin_ventana(g, v, nucleo=(0, 0, 30, 60)) > sun.kmin_ventana(g, v, nucleo=(0, 0, 60, 60))


# ====================================================================== morfología y ruido
def test_limpieza_de_ruido_igual_a_la_regla_por_pixel():
    rng = np.random.default_rng(4)
    m = (rng.random((40, 50)) < 0.12).astype(np.uint8)
    m[20, 5:45] = 1                                                           # una línea fina
    for d in (1, 2, 3):
        assert np.array_equal(sun.quitar_ruido(m, d), ruido_referencia(m, d))


def test_limpieza_de_ruido_quita_puntos_y_conserva_lineas_finas():
    m = np.zeros((40, 60), np.uint8)
    m[20, 10:50] = 1
    m[5, 5] = 1                                                               # punto aislado
    m[35, 30] = 1
    s = sun.quitar_ruido(m, 2)
    assert s[5, 5] == 0 and s[35, 30] == 0 and s[20, 10:50].sum() >= 36
    assert s[20, 10:50].sum() == m[20, 10:50].sum() - 0 or s[20, 10:50].sum() >= 36


def test_cierre_une_un_hueco_pequeno():
    m = np.zeros((40, 80), np.uint8)
    m[18:23, 5:35] = 1
    m[18:23, 39:75] = 1
    c = sun.cierre(m, 5)
    assert c[20, 36] == 1 and c[2, 2] == 0


# ====================================================================== conexión de puntos de ruptura
P = Params()                      # GSD 0.5 cm: hueco máx 10 px, lateral ~6 px


def _linea(m, p0, p1):
    import cv2
    cv2.line(m, p0, p1, 1, 1)


def test_conecta_un_hueco_horizontal():
    m = np.zeros((60, 200), np.uint8)
    _linea(m, (10, 30), (80, 30))
    _linea(m, (88, 30), (190, 30))                                            # hueco de 7 px
    out, n = sun.conectar_rupturas(m, P.gsd_m, P)
    assert n >= 1 and out[30, 80:89].all()


def test_conecta_huecos_en_vertical_y_en_diagonal():
    m = np.zeros((200, 200), np.uint8)
    _linea(m, (30, 10), (30, 80))
    _linea(m, (30, 87), (30, 190))
    _linea(m, (100, 10), (140, 50))
    _linea(m, (146, 56), (190, 100))
    out, n = sun.conectar_rupturas(m, P.gsd_m, P)
    assert out[84, 30] == 1 and out[53, 143] == 1 and n >= 2


def test_no_conecta_si_el_hueco_supera_el_maximo():
    m = np.zeros((60, 200), np.uint8)
    _linea(m, (10, 30), (60, 30))
    _linea(m, (75, 30), (190, 30))                                            # hueco de 14 px > 10 px
    out, n = sun.conectar_rupturas(m, P.gsd_m, P)
    assert n == 0 and out[30, 67] == 0


def test_conecta_con_desalineacion_lateral_pequena_pero_no_grande():
    m = np.zeros((80, 200), np.uint8)
    _linea(m, (10, 30), (80, 30))
    _linea(m, (87, 33), (190, 33))                                           # 3 px de desvío: dentro de lo admitido
    out, n = sun.conectar_rupturas(m, P.gsd_m, P)
    assert n >= 1 and out[31:33, 83:86].any()
    m2 = np.zeros((80, 200), np.uint8)
    _linea(m2, (10, 30), (80, 30))
    _linea(m2, (87, 50), (190, 50))                                          # 20 px de desvío: otra grieta
    assert sun.conectar_rupturas(m2, P.gsd_m, P)[1] == 0


def test_los_tamanos_salen_del_gsd():
    """El mismo hueco FÍSICO (3.5 cm) se puentea a 0.5 cm/px (7 px) y a 1 cm/px (3.5 px), pero uno de 8 cm no."""
    for gsd in (0.5, 1.0):
        p = Params().con(gsd_cm=gsd)
        paso = lambda cm: int(round(cm / gsd))
        m = np.zeros((60, 400), np.uint8)
        _linea(m, (10, 30), (100, 30))
        _linea(m, (100 + paso(3.5), 30), (390, 30))
        assert sun.conectar_rupturas(m, p.gsd_m, p)[1] >= 1
        m2 = np.zeros((60, 400), np.uint8)
        _linea(m2, (10, 30), (100, 30))
        _linea(m2, (100 + paso(8.0), 30), (390, 30))
        assert sun.conectar_rupturas(m2, p.gsd_m, p)[1] == 0


def test_un_fragmento_diminuto_no_arrastra_puentes():
    m = np.zeros((60, 200), np.uint8)
    m[30, 100] = 1                                                            # mota aislada
    _linea(m, (120, 30), (190, 30))
    assert sun.conectar_rupturas(m, P.gsd_m, P)[1] == 0


def test_mascara_vacia():
    out, n = sun.conectar_rupturas(np.zeros((30, 30), np.uint8), P.gsd_m, P)
    assert n == 0 and not out.any()


# ====================================================================== grietas sintéticas de medida conocida
def _una_grieta(ancho_mm, metodo, p0=(80, 250), p1=(820, 262), alto=500, ancho_img=900, eje_deg=0.0, semilla=3):
    img = asfalto(alto, ancho_img, semilla)
    dibujar_grieta(img, p0, p1, ancho_mm / 5.0, contraste=70)
    lec = LectorArray(a_uint8(img), gsd_cm=0.5)
    eje = EjeVia.recto(eje_deg, ancho_img, alto, 0.005)
    return analizar_region(lec, (0, 0, ancho_img, alto), Params(), eje=eje, metodo=metodo)


@pytest.mark.parametrize("ancho_mm", [20, 40])
def test_sun_longitud_y_ancho_conocidos(ancho_mm):
    res = _una_grieta(ancho_mm, "sun")
    gr = [d for d in res.detecciones]
    assert len(gr) == 1 and gr[0].metodo == "sun" and gr[0].tipo == "longitudinal"
    esperado = math.hypot(740, 12) * 0.005                                    # 3.70 m
    assert gr[0].longitud_m == pytest.approx(esperado, rel=0.05)
    assert abs(gr[0].ancho_mm - ancho_mm) <= 2.0


def test_sun_clasifica_segun_el_eje_y_coincide_con_el_metodo_actual():
    """Misma grieta transversal (vertical) con eje horizontal: ambos métodos dicen 'transversal' y miden parecido."""
    a = _una_grieta(25, "actual", (450, 40), (462, 460))
    s = _una_grieta(25, "sun", (450, 40), (462, 460))
    assert [d.tipo for d in a.detecciones] == [d.tipo for d in s.detecciones] == ["transversal"]
    da, ds = a.detecciones[0], s.detecciones[0]
    assert ds.longitud_m == pytest.approx(da.longitud_m, rel=0.05)
    assert abs(ds.ancho_mm - da.ancho_mm) <= 1.5
    assert abs(ds.progresiva_m - da.progresiva_m) < 0.1 and ds.lado_via == da.lado_via


def test_sun_devuelve_las_mismas_columnas_que_actual():
    s = _una_grieta(25, "sun").detecciones[0].a_dict()
    a = _una_grieta(25, "actual").detecciones[0].a_dict()
    assert set(s) == set(a)
    for campo in ("ancho_mm", "area_m2", "contraste_weber", "severidad_prelim", "angulo_eje_deg", "progresiva_m",
                  "lado_via", "geom"):
        v = s[campo]
        assert v is not None and not (isinstance(v, (str, list)) and len(v) == 0), campo


def test_sun_une_una_grieta_con_huecos():
    img = asfalto(500, 900, 3)
    dibujar_grieta(img, (80, 250), (400, 254), 4.0, contraste=70)
    dibujar_grieta(img, (410, 254), (820, 262), 4.0, contraste=70)           # hueco de ~2 cm
    res = analizar_region(LectorArray(a_uint8(img), gsd_cm=0.5), (0, 0, 900, 500), Params(), metodo="sun")
    assert len(res.detecciones) == 1 and res.detecciones[0].longitud_m > 3.5


def test_sun_no_detecta_en_asfalto_sano_y_avisa_del_tope():
    lec = LectorArray(a_uint8(asfalto(500, 900, 8)), gsd_cm=0.5)
    res = analizar_region(lec, (0, 0, 900, 500), Params(), metodo="sun")
    assert res.detecciones == [] and any("se limitó" in a for a in res.advertencias)


def test_sin_el_tope_sun_original_marca_todo_el_asfalto_sano():
    """Documenta la limitación del método original: con sun_contraste_min = 0 la ROI sana sale llena de 'grietas'."""
    lec = LectorArray(a_uint8(asfalto(500, 900, 8)), gsd_cm=0.5)
    res = analizar_region(lec, (0, 0, 900, 500), Params().con(sun_contraste_min=0.0), metodo="sun")
    assert len(res.detecciones) >= 1


def test_sun_en_el_ejemplo_encuentra_las_dos_grietas_lineales(ejemplo, lector_ejemplo):
    res = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), metodo="sun")
    assert all(d.tipo in ("longitudinal", "transversal") for d in res.detecciones)
    act = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), metodo="actual")
    for roi, tipo in (("R01", "transversal"), ("R02", "longitudinal")):
        x0, y0, x1, y1 = region_de(ejemplo[1][roi])
        s = [d for d in res.detecciones if d.tipo == tipo and x0 <= d.cx < x1 and y0 <= d.cy < y1]
        a = [d for d in act.detecciones if d.tipo == tipo and x0 <= d.cx < x1 and y0 <= d.cy < y1]
        assert len(s) == len(a) == 1
        assert s[0].longitud_m == pytest.approx(a[0].longitud_m, rel=0.05)


# ====================================================================== kmin global y tamaño de tesela
def _contexto_por_teselas(rgb, p, tesela):
    from app.nucleo.calidad import mascara_valida
    m = int(math.ceil(1.0 / p.gsd_m))
    H, W = rgb.shape[:2]
    prep = sun.PreparacionSun(p)
    for etapa in (1, 2):
        for ty in range(0, H, tesela):
            for tx in range(0, W, tesela):
                tx1, ty1 = min(tx + tesela, W), min(ty + tesela, H)
                x0, y0, x1, y1 = max(0, tx - m), max(0, ty - m), min(W, tx1 + m), min(H, ty1 + m)
                v, _ = mascara_valida(rgb[y0:y1, x0:x1], p, None, None)
                prep.acumular(etapa, rgb[y0:y1, x0:x1], v, (x0, y0), (tx - x0, ty - y0, tx1 - x0, ty1 - y0))
        prep.cerrar(etapa)
    return prep.contexto


def test_el_contexto_global_no_depende_del_tamano_de_tesela(ejemplo):
    rgb = ejemplo[0]
    ctx = [_contexto_por_teselas(rgb, Params(), t) for t in (2400, 1600, 1000, 700, 512)]
    assert all(c["media"] == pytest.approx(ctx[0]["media"], rel=1e-9) for c in ctx)
    assert all(c["kmin"] == pytest.approx(ctx[0]["kmin"], rel=1e-6) for c in ctx)
    assert len({c["umbral"] for c in ctx}) == 1


def test_el_contexto_global_es_el_de_la_imagen_entera(ejemplo):
    """kmin por teselas = kmin de calcularlo de una vez sobre toda la imagen (la referencia 'sin teselas')."""
    from app.nucleo.calidad import mascara_valida
    import cv2
    rgb = ejemplo[0]
    p = Params()
    v, _ = mascara_valida(rgb, p, None, None)
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    media = float(g[v].mean(dtype=np.float64))
    k_total = sun.kmin_ventana(sun.realzar(g, v, media, p), v)
    assert _contexto_por_teselas(rgb, p, 700)["kmin"] == pytest.approx(k_total, rel=1e-3)


def test_sun_resultado_estable_al_cambiar_la_tesela(ejemplo, lector_ejemplo):
    """Las grietas principales (R01, R02) salen iguales con teselas de 1600, 1000 y 512 px. (Una grieta que casi roza
    un borde de tesela puede perder un fragmento < 15 cm: limitación del pipeline, igual que en 'actual'.)"""
    p = Params()
    base = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), p, metodo="sun", tesela_px=1600)
    for t in (1000, 512):
        otra = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), p, metodo="sun", tesela_px=t)
        assert otra.n_teselas > base.n_teselas
        for roi, tipo in (("R01", "transversal"), ("R02", "longitudinal")):
            x0, y0, x1, y1 = region_de(ejemplo[1][roi])
            a = [d for d in base.detecciones if d.tipo == tipo and x0 <= d.cx < x1 and y0 <= d.cy < y1]
            b = [d for d in otra.detecciones if d.tipo == tipo and x0 <= d.cx < x1 and y0 <= d.cy < y1]
            assert len(a) == len(b) == 1
            assert b[0].longitud_m == pytest.approx(a[0].longitud_m, rel=0.04)
            assert b[0].ancho_mm == pytest.approx(a[0].ancho_mm, abs=1.5)
            assert b[0].bordes_corte == []


def test_sin_contexto_la_ventana_se_analiza_con_sus_propios_estadisticos(ejemplo):
    from app.nucleo.calidad import mascara_valida
    rgb = ejemplo[0][0:800, 0:800]
    p = Params()
    v, _ = mascara_valida(rgb, p, None, None)
    eje = EjeVia.recto(0.0, 800, 800, p.gsd_m)
    solo = pipeline.analizar_ventana(rgb, v, p, eje, (0, 0), "sun")
    assert any(d.tipo == "transversal" for d in solo)
    assert sun.contexto_local(rgb, v, p) is not None


def test_pipeline_progreso_y_cancelacion_con_preparacion(lector_ejemplo):
    marcas = []
    analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), metodo="sun", tesela_px=800,
                    progreso=lambda f, t: marcas.append((f, t)))
    fr = [f for f, _ in marcas]
    assert fr == sorted(fr) and fr[-1] == 1.0 and len(fr) == 6 * 3
    assert any("preparación" in t for _, t in marcas)
    ev = threading.Event()
    with pytest.raises(AnalisisCancelado):
        analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), metodo="sun", tesela_px=800, cancelar=ev,
                        progreso=lambda f, t: ev.set())


def test_sin_calzada_valida_advierte_y_no_detecta():
    lec = LectorArray(np.zeros((600, 600, 3), np.uint8), gsd_cm=0.5)
    res = analizar_region(lec, (0, 0, 600, 600), Params(), metodo="sun")
    assert res.detecciones == [] and any("estadísticos globales" in a for a in res.advertencias)


def test_actual_no_cambia_con_la_refactorizacion(lector_ejemplo):
    res = analizar_region(lector_ejemplo, (0, 0, 2400, 1400), Params(), metodo="actual")
    assert {d.tipo for d in res.detecciones} == {"longitudinal", "transversal", "piel_cocodrilo", "bache"}
    assert all(d.metodo == "actual" for d in res.detecciones)


def test_sun_esta_registrado_con_su_preparacion():
    assert "sun" in pipeline.METODOS and pipeline.PREPARACIONES["sun"] is sun.PreparacionSun
    assert "actual" not in pipeline.PREPARACIONES
