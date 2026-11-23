"""F6 · respaldo y restauración de la BD, mensajes de error claros, registro a archivo y arranque de main.py."""
import errno
import logging
import os
import sqlite3
import time

import pytest

from app import basedatos, errores, logica_configuracion as cfg, logica_respaldo as lr, logica_tramos as lt, registro
from app.logica_comun import ErrorNoEncontrado, ErrorValidacion


@pytest.fixture
def bd_archivo(tmp_path):
    ruta = str(tmp_path / "datos" / "pavimento.db")
    basedatos.inicializar(ruta)
    lt.crear_tramo({"codigo": "T1", "via": "Vía uno"})
    yield ruta
    basedatos.cerrar()


# ------------------------------------------------------------------ respaldo
def test_crear_respaldo_contiene_los_datos_y_se_verifica(bd_archivo):
    r = lr.crear_respaldo()
    assert os.path.dirname(r["ruta"]) == os.path.join(os.path.dirname(bd_archivo), "respaldos")
    assert r["tramos"] == 1 and r["tamano"] > 0 and r["ruta"].endswith("_manual.db")
    v = lr.verificar_respaldo(r["ruta"])
    assert v["ok"] and v["problemas"] == [] and v["esquema"] == basedatos.VERSION_ESQUEMA
    con = sqlite3.connect(r["ruta"])
    assert con.execute("SELECT codigo FROM tramo").fetchall() == [("T1",)]
    con.close()
    assert not [f for f in os.listdir(os.path.dirname(r["ruta"])) if f.endswith(".tmp")]


def test_respaldo_en_modo_wal_con_la_bd_abierta_incluye_lo_confirmado(bd_archivo):
    lt.crear_tramo({"codigo": "T2"})                                  # queda en el -wal hasta el checkpoint
    r = lr.crear_respaldo()
    con = sqlite3.connect(r["ruta"])
    assert sorted(x[0] for x in con.execute("SELECT codigo FROM tramo")) == ["T1", "T2"]
    con.close()


def test_respaldo_a_destino_elegido_archivo_o_carpeta(bd_archivo, tmp_path):
    a = lr.crear_respaldo(str(tmp_path / "copia.db"))
    assert a["ruta"] == str(tmp_path / "copia.db") and os.path.exists(a["ruta"])
    carpeta = tmp_path / "otra"
    carpeta.mkdir()
    b = lr.crear_respaldo(str(carpeta))
    assert os.path.dirname(b["ruta"]) == str(carpeta)
    with pytest.raises(lr.ErrorRespaldo, match="propia base de datos"):
        lr.crear_respaldo(bd_archivo)


def test_bd_en_memoria_o_cerrada_no_se_respalda():
    basedatos.inicializar(":memory:")
    with pytest.raises(lr.ErrorRespaldo, match="en memoria"):
        lr.crear_respaldo()
    basedatos.cerrar()
    with pytest.raises(lr.ErrorRespaldo, match="no está abierta"):
        lr.crear_respaldo()


def test_verificar_rechaza_archivos_que_no_son_la_bd_del_programa(tmp_path):
    no_existe = lr.verificar_respaldo(str(tmp_path / "nada.db"))
    assert not no_existe["ok"] and "no existe" in no_existe["problemas"][0]
    texto = tmp_path / "t.db"
    texto.write_text("esto no es sqlite " * 50)
    assert "no es una base de datos SQLite válida" in " ".join(lr.verificar_respaldo(str(texto))["problemas"])
    otra = tmp_path / "otra.db"
    c = sqlite3.connect(str(otra))
    c.execute("CREATE TABLE x (a)")
    c.commit()
    c.close()
    assert "faltan tablas" in " ".join(lr.verificar_respaldo(str(otra))["problemas"])


def test_verificar_rechaza_esquema_mas_nuevo(bd_archivo, tmp_path):
    r = lr.crear_respaldo()
    c = sqlite3.connect(r["ruta"])
    c.execute("PRAGMA user_version=99")
    c.commit()
    c.close()
    v = lr.verificar_respaldo(r["ruta"])
    assert not v["ok"] and "más nuevo" in v["problemas"][0]


# ------------------------------------------------------------------ restauración
def test_restaurar_recupera_los_datos_y_guarda_copia_previa(bd_archivo):
    r = lr.crear_respaldo()
    lt.eliminar_tramo("T1", confirmar=True)
    lt.crear_tramo({"codigo": "T9"})
    out = lr.restaurar_respaldo(r["ruta"])
    assert [t["codigo"] for t in lt.listar_tramos()] == ["T1"]                # la BD quedó reabierta y restaurada
    assert out["tramos"] == 1 and out["copia_previa"].endswith("_antes_de_restaurar.db")
    previa = sqlite3.connect(out["copia_previa"])
    assert previa.execute("SELECT codigo FROM tramo").fetchall() == [("T9",)]  # nada se perdió: está en la copia previa
    previa.close()


def test_restaurar_archivo_invalido_no_toca_la_bd_actual(bd_archivo, tmp_path):
    malo = tmp_path / "malo.db"
    malo.write_text("basura" * 100)
    with pytest.raises(lr.ErrorRespaldo, match="No se puede restaurar"):
        lr.restaurar_respaldo(str(malo))
    assert [t["codigo"] for t in lt.listar_tramos()] == ["T1"]
    with pytest.raises(lr.ErrorRespaldo, match="propia base de datos"):
        lr.restaurar_respaldo(bd_archivo)


def test_restaurar_falla_en_el_reemplazo_y_la_bd_sigue_usable(bd_archivo, monkeypatch):
    r = lr.crear_respaldo()

    real = os.replace

    def falla(a, b):
        if os.path.abspath(b) == os.path.abspath(bd_archivo):          # solo el reemplazo de la BD; la copia previa sí se hace
            raise PermissionError(13, "en uso")
        return real(a, b)
    monkeypatch.setattr(lr.os, "replace", falla)
    with pytest.raises(lr.ErrorRespaldo, match="en uso por otro programa"):
        lr.restaurar_respaldo(r["ruta"])
    assert [t["codigo"] for t in lt.listar_tramos()] == ["T1"]               # reabierta tras el fallo
    assert not os.path.exists(bd_archivo + ".restaurando")


# ------------------------------------------------------------------ automático
def test_respaldo_automatico_una_vez_por_dia_y_respeta_la_configuracion(bd_archivo):
    a = lr.respaldo_automatico()
    assert a and a["ruta"].endswith("_automatico.db")
    assert lr.respaldo_automatico() is None                                   # ya hay uno de hoy
    for x in lr.listar_respaldos():
        os.remove(x["ruta"])
    cfg.establecer("respaldo_automatico", False)
    assert lr.respaldo_automatico() is None and lr.listar_respaldos() == []


def test_rotacion_solo_borra_automaticos_antiguos(bd_archivo):
    carpeta = lr.carpeta_respaldos()
    os.makedirs(carpeta, exist_ok=True)
    base = time.time()
    for i in range(5):
        for suf in ("automatico", "manual"):
            ruta = os.path.join(carpeta, f"pavimento_2020010{i + 1}_000000_{suf}.db")
            open(ruta, "wb").write(b"x")
            os.utime(ruta, (base - 1000 + i, base - 1000 + i))
    cfg.establecer("respaldos_a_conservar", 2)
    lr.respaldo_automatico()                                                 # crea el de hoy y rota
    nombres = [x["nombre"] for x in lr.listar_respaldos()]
    autos = [n for n in nombres if n.endswith("_automatico.db")]
    assert len(autos) == 2 and sum(n.endswith("_manual.db") for n in nombres) == 5
    with pytest.raises(ErrorValidacion):
        cfg.establecer("respaldos_a_conservar", 0)


def test_respaldo_automatico_nunca_lanza(bd_archivo, monkeypatch, caplog):
    monkeypatch.setattr(lr, "crear_respaldo", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disco roto")))
    with caplog.at_level(logging.ERROR):
        assert lr.respaldo_automatico() is None
    assert "No se pudo crear el respaldo automático" in caplog.text


# ------------------------------------------------------------------ mensajes de error
@pytest.mark.parametrize("exc,titulo,fragmento", [
    (ErrorValidacion({"codigo": "obligatorio"}), "Datos no válidos", "codigo: obligatorio"),
    (ErrorNoEncontrado("tramo 9 no existe"), "No encontrado", "tramo 9"),
    (PermissionError(13, "denegado", "x.xlsx"), "Sin permiso o archivo en uso", "Excel, QGIS o un visor de PDF"),
    (FileNotFoundError(2, "no", "ortho.tif"), "Archivo no encontrado", "ortho.tif"),
    (OSError(errno.ENOSPC, "No space"), "Disco lleno", "Libere espacio"),
    (MemoryError(), "Memoria insuficiente", "ROI o una ventana más pequeña"),
    (sqlite3.OperationalError("database is locked"), "Base de datos en uso", "bloqueada"),
    (sqlite3.DatabaseError("file is not a database"), "Base de datos dañada", "Restaurar respaldo"),
    (ImportError("falta", name="reportlab"), "Falta una librería", "pip install -r requirements.txt"),
    (lr.ErrorRespaldo("sin espacio para el respaldo"), "Respaldo", "sin espacio para el respaldo"),
    (RuntimeError("algo raro"), "Error inesperado", "RuntimeError: algo raro"),
])
def test_describir_errores_en_lenguaje_claro(exc, titulo, fragmento):
    t, msg, detalle = errores.describir(exc, ruta_log="/x/log.log")
    assert t == titulo and fragmento in msg and type(exc).__name__ in detalle
    if titulo in ("Error inesperado", "Memoria insuficiente", "Sin permiso o archivo en uso"):
        assert "/x/log.log" in msg


def test_los_errores_de_exportacion_y_reportes_son_valueerror_y_se_muestran_limpios():
    from app.logica_exportacion import ErrorExportacion
    from app.logica_reportes import ErrorReporte
    from app.ui.presentadores.base import proteger

    def falla():
        raise ErrorExportacion("el tramo no está georreferenciado")
    r = proteger(falla)
    assert not r.ok and r.mensaje == "el tramo no está georreferenciado" and "inesperado" not in r.mensaje
    assert issubclass(ErrorReporte, ValueError)
    assert errores.describir(ErrorExportacion("x"))[0] == "Exportación" and errores.describir(ErrorReporte("x"))[0] == "Reporte"


# ------------------------------------------------------------------ registro a archivo
@pytest.fixture(autouse=True)
def sin_dialogos(monkeypatch):
    """main._error_fatal abre un messagebox modal si hay pantalla (xvfb): en las pruebas no debe bloquear."""
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)


@pytest.fixture
def limpiar_logging():
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    import sys, threading
    hook, thook = sys.excepthook, threading.excepthook
    yield
    for h in list(raiz.handlers):
        if h not in antes:
            raiz.removeHandler(h)
            h.close()
    raiz.setLevel(nivel)
    sys.excepthook, threading.excepthook = hook, thook
    os.environ.pop("PAVIMENTO_LOG", None)


def test_registro_crea_archivo_escribe_y_es_idempotente(tmp_path, limpiar_logging):
    ruta = registro.configurar(str(tmp_path / "logs"), consola=False)
    assert ruta == str(tmp_path / "logs" / "pavimento_tesis.log") and os.environ["PAVIMENTO_LOG"] == ruta
    logging.getLogger("pavimento.prueba").warning("mensaje con tilde: ñandú")
    registro.configurar(str(tmp_path / "logs"), consola=False)
    marcados = [h for h in logging.getLogger().handlers if getattr(h, registro._MARCA, False)]
    assert len(marcados) == 1
    for h in marcados:
        h.flush()
    txt = open(ruta, encoding="utf-8").read()
    assert "ñandú" in txt and "WARNING" in txt and txt.count("Registro iniciado") == 2


def test_registro_excepciones_no_capturadas_quedan_en_el_archivo(tmp_path, limpiar_logging):
    import sys, threading
    ruta = registro.configurar(str(tmp_path / "logs"), consola=False)
    try:
        raise ValueError("fallo en el hilo principal")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    def hilo():
        raise RuntimeError("fallo en el hilo de trabajo")
    t = threading.Thread(target=hilo, name="analisis")
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    txt = open(ruta, encoding="utf-8").read()
    assert "fallo en el hilo principal" in txt and "Traceback" in txt
    assert "fallo en el hilo de trabajo" in txt and "analisis" in txt


def test_registro_sin_carpeta_escribible_usa_la_temporal(tmp_path, limpiar_logging):
    archivo = tmp_path / "es_un_archivo"
    archivo.write_text("x")
    ruta = registro.configurar(str(archivo / "logs"), consola=False)           # no se puede crear dentro de un archivo
    assert ruta and "pavimento_tesis_logs" in ruta and os.path.exists(ruta)


def test_carpeta_por_defecto_respeta_la_variable_de_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("PAVIMENTO_LOG_DIR", str(tmp_path / "x"))
    assert registro.carpeta_por_defecto() == str(tmp_path / "x")
    monkeypatch.delenv("PAVIMENTO_LOG_DIR")
    assert registro.carpeta_por_defecto().endswith(os.path.join("pavimento_tesis", "logs"))


# ------------------------------------------------------------------ main.py
def test_main_arranca_con_log_y_respaldo_automatico_y_cierra_la_bd(tmp_path, limpiar_logging, monkeypatch):
    pytest.importorskip("tkinter")
    import main
    import app.ui.ventana_principal as vp
    llamadas = {}

    class Falsa:
        def __init__(self, ruta_bd, abrir_bd):
            llamadas["ruta"] = ruta_bd

        def ofrecer_tutorial(self):
            pass

        def after(self, ms, fn):
            llamadas["after"] = fn.__name__               # main programa la oferta del tutorial

        def mainloop(self):
            llamadas["loop"] = True
    monkeypatch.setattr(vp, "VentanaPrincipal", Falsa)
    from app.ui import estilos
    monkeypatch.setattr(estilos, "hacer_dpi_consciente", lambda: None)
    bd = str(tmp_path / "d" / "p.db")
    assert main.main(["--bd", bd, "--log-dir", str(tmp_path / "logs"), "--verbose"]) == 0
    assert llamadas["loop"] and llamadas["after"] == "ofrecer_tutorial"
    assert os.path.exists(tmp_path / "logs" / "pavimento_tesis.log")
    assert any(f.endswith("_automatico.db") for f in os.listdir(tmp_path / "d" / "respaldos"))
    assert basedatos.ruta_actual() is None                                    # BD cerrada al salir


def test_main_error_de_la_ventana_se_registra_y_devuelve_1(tmp_path, limpiar_logging, monkeypatch, capsys):
    pytest.importorskip("tkinter")
    import main
    import app.ui.ventana_principal as vp

    class Rota:
        def __init__(self, **k):
            raise MemoryError()
    monkeypatch.setattr(vp, "VentanaPrincipal", Rota)
    from app.ui import estilos
    monkeypatch.setattr(estilos, "hacer_dpi_consciente", lambda: None)
    assert main.main(["--bd", str(tmp_path / "p.db"), "--log-dir", str(tmp_path / "logs")]) == 1
    assert "Memoria insuficiente" in capsys.readouterr().err
    assert "La aplicación terminó por un error" in open(tmp_path / "logs" / "pavimento_tesis.log", encoding="utf-8").read()


def test_main_con_bd_de_esquema_futuro_explica_como_restaurar(tmp_path, limpiar_logging, capsys):
    pytest.importorskip("tkinter")
    import main
    ruta = str(tmp_path / "f.db")
    basedatos.inicializar(ruta)
    basedatos.cerrar()
    c = sqlite3.connect(ruta)
    c.execute("PRAGMA user_version=99")
    c.commit()
    c.close()
    assert main.main(["--bd", ruta, "--log-dir", str(tmp_path / "logs")]) == 2
    err = capsys.readouterr().err
    assert "más nuevo" in err and "respaldos" in err
