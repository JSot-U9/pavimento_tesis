import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import basedatos
from app.modelos import ROI, Deteccion, EjecucionAnalisis, Patologia, Tramo


def test_inicializa_y_siembra_catalogo(bd):
    from app import logica_fichas
    cat = {c["codigo"]: c["tipo_motor"] for c in logica_fichas.listar("catalogo")}
    assert cat == {"GLO": "longitudinal", "GTR": "transversal", "GPC": "piel_cocodrilo", "HUE": "bache"}


def test_persistencia_en_archivo_y_version(tmp_path):
    ruta = str(tmp_path / "sub" / "t.db")
    basedatos.inicializar(ruta)
    with basedatos.nueva_sesion() as s:
        s.add(Tramo(codigo="A"))
    basedatos.inicializar(ruta)                       # reabrir: los datos siguen y el catálogo no se duplica
    with basedatos.nueva_sesion() as s:
        assert s.scalar(select(Tramo.codigo)) == "A"
        assert len(s.execute(text("select * from catalogo_patologia")).all()) == 4
        assert s.execute(text("PRAGMA user_version")).scalar() == basedatos.VERSION_ESQUEMA
    basedatos.cerrar()


def test_esquema_mas_nuevo_se_rechaza(tmp_path):
    ruta = str(tmp_path / "n.db")
    basedatos.inicializar(ruta)
    with basedatos.nueva_sesion() as s:
        s.execute(text("PRAGMA user_version=99"))
    with pytest.raises(basedatos.ErrorBD, match="más nuevo"):
        basedatos.inicializar(ruta)
    basedatos.cerrar()


def test_sin_inicializar_da_mensaje_claro():
    basedatos.cerrar()
    with pytest.raises(basedatos.ErrorBD, match="inicializar"):
        with basedatos.nueva_sesion():
            pass


def test_rollback_ante_excepcion(bd):
    with pytest.raises(RuntimeError):
        with basedatos.nueva_sesion() as s:
            s.add(Tramo(codigo="X"))
            s.flush()
            raise RuntimeError
    with basedatos.nueva_sesion() as s:
        assert s.scalar(select(Tramo.id)) is None


def test_claves_foraneas_y_checks_activos(bd):
    with pytest.raises(IntegrityError):
        with basedatos.nueva_sesion() as s:
            s.add(ROI(tramo_id=99, codigo="R", tipo_campo="bache", x0=0, y0=0, x1=9, y1=9))
    with pytest.raises(IntegrityError):               # rectángulo invertido
        with basedatos.nueva_sesion() as s:
            t = Tramo(codigo="Y")
            s.add(t)
            s.flush()
            s.add(ROI(tramo_id=t.id, codigo="R", tipo_campo="bache", x0=9, y0=0, x1=9, y1=9))


def test_borrar_roi_deja_detecciones_sin_roi_y_borrar_tramo_cascada(tramo):
    from app import logica_deteccion, logica_roi, logica_tramos
    r = logica_roi.crear_roi(tramo, {"codigo": "R1", "tipo_campo": "transversal", "x0": 150, "y0": 80, "x1": 480, "y1": 1080})
    e = logica_deteccion.analizar(tramo, roi_id=r["id"])
    assert e["n_detecciones"] >= 1
    logica_roi.eliminar_roi(r["id"])
    with basedatos.nueva_sesion() as s:
        assert s.scalar(select(EjecucionAnalisis.roi_id)) is None
        assert all(d.roi_id is None for d in s.scalars(select(Deteccion)))
    logica_tramos.eliminar_tramo(tramo, confirmar=True)
    with basedatos.nueva_sesion() as s:
        assert s.scalar(select(Deteccion.id)) is None and s.scalar(select(EjecucionAnalisis.id)) is None


def test_capas_el_nucleo_no_conoce_bd_ni_logica():
    import pathlib
    import re
    base = pathlib.Path(__file__).resolve().parent.parent / "app" / "nucleo"
    malos = [f.name for f in base.glob("*.py")
             if re.search(r"^\s*(from|import)\s+app\.(modelos|basedatos|logica_\w+|geovector|crs|ui)", f.read_text(encoding="utf-8"), re.M)]
    assert malos == []
