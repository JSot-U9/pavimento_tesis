"""
sun.py
======
Método 'sun': detección de grietas según Yao Sun (2009), «Automated Pavement Distress Detection Using Advanced
Image Processing Techniques» (Univ. de Toledo), cap. 3-6 y apéndice (código Matlab). Se registra en el pipeline con

    pipeline.registrar_metodo('sun', f, preparacion=PreparacionSun)

y cumple el contrato  f(rgb, valido, params, eje, origen, nucleo=None, contexto=None) -> list[Deteccion].

CADENA DE PROCESO
  1. Realce (ec. 1):  f* = f - f_blur + m   (gaussiana grande; m = media de la calzada).
  2. Umbral fractal (ec. 4-9): manta de cobertura sobre bloques de 3x3, k por mínimos cuadrados en las
     escalas eps = 2..9;  T = fix(alfa * kmin + beta).  Grieta = píxel con f* < T.
     (alfa = 0.2247, beta = 40: las constantes del CÓDIGO de Sun, a petición; el texto de la tesis dice 0.22 y 45.)
  3. Cierre morfológico con disco (une huecos pequeños).
  4. Limpieza de ruido de Sun: un píxel brillante se elimina si sus 8 puntos a distancia d son oscuros
     (conserva grietas finas; el filtro de mediana las rompe).
  5. Conexión de puntos de ruptura: REESCRITA (ver más abajo).
  6. Esqueleto y eliminación de componentes pequeños.
  7. Medidas, ancho, orientación respecto al eje de vía y severidad ORIENTATIVA: se REUTILIZA `grietas.analizar_grietas`
     del método 'actual', de modo que ambos métodos reportan las mismas columnas.

DECISIONES (todas documentadas en GUIA_ARQUITECTURA.md)
  * kmin GLOBAL por región, no por tesela. T depende del mínimo de k de TODA la imagen: si cada tesela usara el
    suyo, el resultado dependería del tamaño de tesela. `PreparacionSun` hace dos pasadas previas sobre las
    teselas (1: media de gris de la calzada; 2: kmin con esa media) y el pipeline entrega el resultado como
    `contexto`. Los bloques 3x3 se anclan a coordenadas globales múltiplos de 3 y pertenecen a la tesela que
    contiene su esquina superior izquierda. Solo cuentan bloques con sus 9 píxeles en la calzada válida.
  * TOPE DEL UMBRAL (mejora, parámetro `sun_contraste_min`): con el relleno de ceros, k ~ 4 x (gris del bloque más
    oscuro), así que T = 0.2247 k + 40 ~ 0.9 x (tono más oscuro) + 40. En una imagen CON grietas, T queda por
    debajo del asfalto; en una SIN grietas (ROI sana) el tono más oscuro es ~ el asfalto y T lo supera: toda la
    imagen sería «grieta». Es una limitación del método original (supone que cada imagen tiene una grieta). Aquí
    T efectivo = min(T, media - sun_contraste_min); si el tope actúa se advierte. Con 0 se anula casi por completo.
  * Fuera del bloque 3x3 los vecinos valen 0, igual que el Matlab de Sun (con ese relleno k crece con el nivel de
    gris y T queda ligado a los tonos más oscuros de la imagen; sin él, T sería casi constante).
  * Los límites fijos del Matlab (425/480 px, franjas de 40/20 px, 3 líneas de barrido en columnas 20/220/420)
    y sus errores (limpieza de ruido que cruza row(i)/col(j), `BW` sin definir) NO se portan: los tamaños salen del
    GSD (parámetros `sun_*_m`) y la clasificación longitudinal/transversal usa la orientación respecto al eje de
    vía, como el método 'actual'.
  * Mejora respecto a Sun: sus puentes solo avanzaban a la derecha (transversales) o hacia abajo (longitudinales;
    en el apéndice solo existe el transversal). Aquí cada extremo de esqueleto se une a la grieta más cercana
    delante de SU propia tangente, sea cual sea la orientación.
  * Sun solo detecta grietas lineales: 'sun' no reporta piel de cocodrilo ni baches.
"""
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree
from skimage.morphology import skeletonize

from app.nucleo.estructuras import TIPOS_GRIETA
from app.nucleo.grietas import analizar_grietas
from app.nucleo.preprocesado import blur_grande

VENTANA = 3                                   # lado del bloque de la manta (Lseg del Matlab)
ESCALAS = tuple(range(2, 10))                 # eps = 2..9
_LOG_ESC = np.log10(np.asarray(ESCALAS, np.float64))
FILAS_POR_LOTE = 200                          # bloques por lote: acota la memoria de la manta


# ====================================================================================== manta fractal
def _vecinos(P):
    """Máximo y mínimo de los 4 vecinos de cada píxel de bloques (n, 3, 3) ya rellenados con ceros (n, 5, 5)."""
    cuatro = (P[:, 0:3, 1:4], P[:, 2:5, 1:4], P[:, 1:4, 0:3], P[:, 1:4, 2:5])
    mx, mn = cuatro[0], cuatro[0]
    for c in cuatro[1:]:
        mx, mn = np.maximum(mx, c), np.minimum(mn, c)
    return mx, mn


def k_de_bloques(bloques, vecinos_superficie=0):
    """Parámetro k de la manta de cobertura para cada bloque 3x3.

    bloques : array (n, 3, 3) de niveles de gris (0-255).
    vecinos_superficie : 0 = los vecinos son los píxeles de la imagen original (como el Matlab de Sun);
                         1 = los vecinos son las superficies u, b del paso anterior (ecuaciones 4-5 del texto).
    Fuera del bloque los vecinos valen 0. Las superficies saturan en 255 (tipo uint8 del Matlab)."""
    g = bloques.astype(np.float32)
    n = g.shape[0]
    P = np.zeros((n, 5, 5), np.float32)
    P[:, 1:4, 1:4] = g
    mx0, mn0 = _vecinos(P)
    U, B = g.copy(), g.copy()
    areas = []
    for eps in range(2, 10):
        if vecinos_superficie:
            PU = np.zeros((n, 5, 5), np.float32)
            PB = np.zeros((n, 5, 5), np.float32)
            PU[:, 1:4, 1:4], PB[:, 1:4, 1:4] = U, B
            mx, _ = _vecinos(PU)
            _, mn = _vecinos(PB)
        else:
            mx, mn = mx0, mn0
        U = np.minimum(np.maximum(mx, U + 1.0), 255.0)
        B = np.minimum(mn, B + 1.0)
        areas.append((U - B).sum(axis=(1, 2)) / (2.0 * eps))          # A(eps) = V(eps) / (2 eps)
    y = np.log10(np.stack(areas, axis=1).astype(np.float64))          # (n, 8)
    xm, ym = _LOG_ESC.mean(), y.mean(axis=1)
    pendiente = ((_LOG_ESC - xm) * (y - ym[:, None])).sum(axis=1) / ((_LOG_ESC - xm) ** 2).sum()
    return 10.0 ** (ym - pendiente * xm)                              # k = 10^(intercepto)


def _bloques_validos(valido, origen, nucleo):
    """(filas, columnas) locales de la esquina superior izquierda de los bloques 3x3 anclados a coordenadas globales
    múltiplos de 3, con esquina dentro del núcleo, completos dentro de la ventana y con sus 9 píxeles válidos."""
    H, W = valido.shape
    ox, oy = origen
    nx0, ny0, nx1, ny1 = (0, 0, W, H) if nucleo is None else nucleo
    c0 = (-ox) % VENTANA
    r0 = (-oy) % VENTANA
    rs = np.arange(r0, H - VENTANA + 1, VENTANA)
    cs = np.arange(c0, W - VENTANA + 1, VENTANA)
    rs, cs = rs[(rs >= ny0) & (rs < ny1)], cs[(cs >= nx0) & (cs < nx1)]
    return rs, cs


def kmin_ventana(gris, valido, origen=(0, 0), nucleo=None, vecinos_superficie=0):
    """Mínimo de k entre los bloques 3x3 de la ventana (None si no hay bloques válidos)."""
    rs, cs = _bloques_validos(valido, origen, nucleo)
    if rs.size == 0 or cs.size == 0:
        return None
    mejor = None
    v = valido.astype(np.uint8)
    for i in range(0, rs.size, FILAS_POR_LOTE):
        rr = rs[i:i + FILAS_POR_LOTE]
        idx_r = rr[:, None, None, None] + np.arange(VENTANA)[None, None, :, None]
        idx_c = cs[None, :, None, None] + np.arange(VENTANA)[None, None, None, :]
        ok = v[idx_r, idx_c].reshape(len(rr), len(cs), -1).all(axis=2)
        if not ok.any():
            continue
        bl = gris[idx_r, idx_c][ok]                                    # (m, 3, 3)
        k = k_de_bloques(bl, vecinos_superficie)
        k = k[np.isfinite(k)]
        if k.size:
            mejor = float(k.min()) if mejor is None else min(mejor, float(k.min()))
    return mejor


def umbral_de_kmin(kmin, p):
    """T = fix(alfa * kmin + beta)  (fix de Matlab = truncar hacia cero), SIN el tope."""
    return float(math.trunc(p.sun_alfa * kmin + p.sun_beta))


def umbral_efectivo(kmin, media, p):
    """(T efectivo, limitado): T de Sun acotado a media - sun_contraste_min (ver la descripción del módulo)."""
    t = umbral_de_kmin(kmin, p)
    tope = float(media) - p.sun_contraste_min
    return (tope, True) if t > tope else (t, False)


# ====================================================================================== realce
def realzar(gris, valido, media, p):
    """f* = f - f_blur + m (ec. 1 de Sun) con la media `m` dada. Fuera de la calzada se usa `m` para no crear bordes falsos."""
    g = np.where(valido, gris.astype(np.float32), np.float32(media))
    sigma = max(5.0, p.iluminacion_sigma_m / p.gsd_m)
    sigma = min(sigma, max(3.0, min(g.shape) / 3.0))
    fondo = blur_grande(g, sigma)
    return np.clip(g - fondo + media, 0, 255).astype(np.uint8)


def _gris(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


# ====================================================================================== preparación (kmin global)
class PreparacionSun:
    """Estadísticos GLOBALES de la región que necesita el método. El pipeline recorre las teselas `etapas` veces:

        para etapa en 1..etapas:  para cada tesela:  acumular(etapa, rgb, valido, p, origen, nucleo)
                                  cerrar(etapa)
        contexto -> dict(media, kmin, umbral_sun, umbral, limitado, advertencia)

    Etapa 1: media de gris de la calzada válida (la `m` de la ec. 1).  Etapa 2: kmin con esa media."""
    etapas = 2

    def __init__(self, p):
        self.p = p
        self._suma, self._n = 0.0, 0
        self.media = None
        self.kmin = None

    def acumular(self, etapa, rgb, valido, origen=(0, 0), nucleo=None):
        gris = _gris(rgb)
        nx0, ny0, nx1, ny1 = (0, 0, gris.shape[1], gris.shape[0]) if nucleo is None else nucleo
        if etapa == 1:
            v = valido[ny0:ny1, nx0:nx1]
            self._suma += float(gris[ny0:ny1, nx0:nx1][v].sum(dtype=np.float64))
            self._n += int(v.sum())
        else:
            if self.media is None:
                return
            k = kmin_ventana(realzar(gris, valido, self.media, self.p), valido, origen, nucleo,
                             self.p.sun_vecinos_superficie)
            if k is not None:
                self.kmin = k if self.kmin is None else min(self.kmin, k)

    def cerrar(self, etapa):
        if etapa == 1:
            self.media = self._suma / self._n if self._n else None

    @property
    def contexto(self):
        if self.media is None or self.kmin is None:
            return None
        t, limitado = umbral_efectivo(self.kmin, self.media, self.p)
        adv = (f"método 'sun': el umbral de Sun (T = {umbral_de_kmin(self.kmin, self.p):.0f}) superaba la media de gris "
               f"({self.media:.0f}) menos el contraste mínimo; se limitó a {t:.0f} (imagen sin grietas marcadas)"
               if limitado else "")
        return {"media": self.media, "kmin": self.kmin, "umbral_sun": umbral_de_kmin(self.kmin, self.p),
                "umbral": t, "limitado": limitado, "advertencia": adv}


def contexto_local(rgb, valido, p, origen=(0, 0), nucleo=None):
    """Contexto calculado SOLO con esta ventana (análisis de una ventana suelta, sin pipeline por teselas)."""
    prep = PreparacionSun(p)
    for etapa in (1, 2):
        prep.acumular(etapa, rgb, valido, origen, nucleo)
        prep.cerrar(etapa)
    return prep.contexto


# ====================================================================================== morfología y ruido
def _px(metros, gsd_m, minimo=1, maximo=60):
    return int(min(maximo, max(minimo, round(metros / gsd_m))))


def cierre(mascara, radio_px):
    """Cierre morfológico (dilatar y luego erosionar) con un disco."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radio_px + 1, 2 * radio_px + 1))
    return cv2.morphologyEx(mascara.astype(np.uint8), cv2.MORPH_CLOSE, k)


def quitar_ruido(mascara, d):
    """Limpieza de ruido de Sun (cap. 4.2): un píxel brillante se elimina si los 8 puntos a distancia `d`
    (±d en filas, columnas y diagonales) son oscuros. Los píxeles a menos de `d` del borde no se tocan."""
    m = mascara.astype(bool)
    H, W = m.shape
    salida = m.copy()
    if H <= 2 * d or W <= 2 * d:
        return salida.astype(np.uint8)
    c = m[d:H - d, d:W - d]
    alguno = np.zeros_like(c)
    for dy in (-d, 0, d):
        for dx in (-d, 0, d):
            if dy == 0 and dx == 0:
                continue
            alguno |= m[d + dy:H - d + dy, d + dx:W - d + dx]
    salida[d:H - d, d:W - d] = c & alguno
    return salida.astype(np.uint8)


# ====================================================================================== puntos de ruptura (reescrito)
def _extremos(esq):
    vecinos = cv2.filter2D(esq.astype(np.float32), -1, np.ones((3, 3), np.float32),
                           borderType=cv2.BORDER_CONSTANT) - 1.0
    return esq & (vecinos == 1)


def conectar_rupturas(mascara, gsd_m, p):
    """Une los puntos de ruptura de las grietas.

    Cada extremo del esqueleto busca, DELANTE de su tangente local, el píxel de otra grieta más cercano dentro de
    una caja de `sun_hueco_max_m` de largo y ±`sun_hueco_lateral_m` de ancho; si lo encuentra traza el puente.
    Los tamaños salen del GSD. Devuelve (mascara_conectada uint8, n_puentes)."""
    m = mascara.astype(np.uint8)
    esq = skeletonize(m > 0)
    if not esq.any():
        return m, 0
    n, lab = cv2.connectedComponents(esq.astype(np.uint8), connectivity=8)
    ys, xs = np.nonzero(esq)
    etiqueta = lab[ys, xs]
    pts = np.stack([xs, ys], 1).astype(np.float64)
    arbol = cKDTree(pts)
    tamano = np.bincount(lab.ravel(), minlength=n)
    ext = _extremos(esq)
    ey, ex = np.nonzero(ext)
    gap = max(2.0, p.sun_hueco_max_m / gsd_m)
    lat = max(1.5, p.sun_hueco_lateral_m / gsd_m)
    r_tan = max(3.0, 0.02 / gsd_m)
    frag_min = max(3, int(math.ceil(0.02 / gsd_m)))
    salida = m.copy()
    puentes = 0
    for x, y in zip(ex, ey):
        lbl = lab[y, x]
        if tamano[lbl] < frag_min:
            continue
        propios = arbol.query_ball_point([x, y], r_tan)
        propios = [i for i in propios if etiqueta[i] == lbl and (pts[i, 0] != x or pts[i, 1] != y)]
        if not propios:
            continue
        t = np.array([x, y], float) - pts[propios].mean(axis=0)
        nt = float(np.hypot(*t))
        if nt < 1e-6:
            continue
        t /= nt
        cand = [i for i in arbol.query_ball_point([x, y], gap + lat) if etiqueta[i] != lbl]
        if not cand:
            continue
        v = pts[cand] - np.array([x, y], float)
        avance = v @ t
        lateral = np.abs(v[:, 0] * t[1] - v[:, 1] * t[0])
        ok = (avance > 0.5) & (avance <= gap) & (lateral <= lat)
        if not ok.any():
            continue
        sel = np.nonzero(ok)[0]
        mejor = sel[np.argmin(np.hypot(v[sel, 0], v[sel, 1]))]
        qx, qy = pts[cand[mejor]]
        cv2.line(salida, (int(x), int(y)), (int(qx), int(qy)), 1, 1)
        puentes += 1
    return salida, puentes


def _filtrar_componentes(esq, minimo_px):
    n, lab, st, _ = cv2.connectedComponentsWithStats(esq.astype(np.uint8), connectivity=8)
    keep = st[:, cv2.CC_STAT_AREA] >= minimo_px
    keep[0] = False
    return keep[lab]


# ====================================================================================== método
def _metodo_sun(rgb, valido, p, eje, origen, nucleo=None, contexto=None):
    """Método 'sun' sobre una ventana. `contexto` = {'media', 'kmin', 'umbral'} global de la región (lo entrega el
    pipeline); si falta, se calcula con esta ventana sola."""
    gris = _gris(rgb)
    if contexto is None:
        contexto = contexto_local(rgb, valido, p, origen, nucleo)
    if contexto is None:
        return []
    gsd = p.gsd_m
    realzada = realzar(gris, valido, contexto["media"], p)
    binaria = ((realzada < contexto["umbral"]) & valido).astype(np.uint8)
    cerrada = cierre(binaria, _px(p.sun_cierre_m, gsd, 1, 25))
    limpia = quitar_ruido(cerrada, _px(p.sun_ruido_dist_m, gsd, 1, 20))
    conectada, _ = conectar_rupturas(limpia, gsd, p)
    esq = _filtrar_componentes(skeletonize(conectada > 0), _px(p.sun_componente_min_m, gsd, 3, 1000))
    if nucleo is not None:                                   # el esqueleto se recorta al núcleo (sin solapes)
        recorte = np.zeros(esq.shape, bool)
        recorte[nucleo[1]:nucleo[3], nucleo[0]:nucleo[2]] = True
        esq = esq & recorte
    dets = analizar_grietas(esq, limpia, conectada, None, gris, realzada, gsd, p, eje, origen)
    for d in dets:
        d.metodo = "sun"
    return dets


def registrar():
    """Registra 'sun' en el pipeline (lo llama pipeline al final de su importación)."""
    from app.nucleo import pipeline
    pipeline.registrar_metodo("sun", _metodo_sun, preparacion=PreparacionSun, tipos=TIPOS_GRIETA)
