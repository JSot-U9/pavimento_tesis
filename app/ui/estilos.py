"""
estilos.py
==========
Tema ttk 'clam' (sin ttkbootstrap) con una paleta neutra: gris claro, azul de acento y colores de estado.
Los colores de las detecciones NO se definen aquí: salen de `app.nucleo.estructuras.COLORES`.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# paleta
FONDO = "#f3f4f6"
FONDO_PANEL = "#ffffff"
BORDE = "#c8ccd2"
TEXTO = "#1f2933"
TEXTO_SUAVE = "#5f6b7a"
ACENTO = "#2b6cb0"
ACENTO_OSCURO = "#1e4e82"
ACENTO_CLARO = "#dbe9f7"
OK = "#2f855a"
ERROR = "#c53030"
ERROR_FONDO = "#fde8e8"
AVISO = "#8a5a00"
AVISO_FONDO = "#fff4d6"

# superposiciones del visor (las detecciones usan COLORES del núcleo)
COLOR_ROL = {"calibracion": "#2f855a", "prueba": "#2b6cb0", "sin_asignar": "#718096"}
COLOR_EJE = "#d69e2e"
COLOR_VENTANA = "#00a3a3"
COLOR_DIBUJO = "#ffffff"
COLOR_SELECCION = "#ffffff"
FONDO_VISOR = "#2d3138"

ALTO_FILA = 24


def fuente_base():
    """Fuente por defecto del sistema (Segoe UI en Windows, la de Tk en Linux/macOS), tamaño 10."""
    f = tkfont.nametofont("TkDefaultFont")
    return f.actual()["family"]


def aplicar(root: tk.Misc) -> ttk.Style:
    """Configura el tema y los estilos con nombre. Llamar una vez, con la raíz ya creada."""
    st = ttk.Style(root)
    st.theme_use("clam")
    fam = fuente_base()
    for nombre, tam in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10), ("TkHeadingFont", 10),
                        ("TkFixedFont", 10)):
        try:
            tkfont.nametofont(nombre).configure(size=tam)
        except tk.TclError:
            pass
    root.configure(background=FONDO)
    root.option_add("*Font", "TkDefaultFont")
    root.option_add("*TCombobox*Listbox.font", "TkDefaultFont")

    st.configure(".", background=FONDO, foreground=TEXTO, bordercolor=BORDE, lightcolor=FONDO, darkcolor=FONDO,
                 focuscolor=ACENTO, troughcolor="#e5e7eb")
    st.configure("TFrame", background=FONDO)
    st.configure("Panel.TFrame", background=FONDO_PANEL)
    st.configure("TLabel", background=FONDO, foreground=TEXTO)
    st.configure("Panel.TLabel", background=FONDO_PANEL)
    st.configure("Titulo.TLabel", font=(fam, 13, "bold"), foreground=ACENTO_OSCURO)
    st.configure("Subtitulo.TLabel", font=(fam, 10, "bold"))
    st.configure("Suave.TLabel", foreground=TEXTO_SUAVE)
    st.configure("Error.TLabel", foreground=ERROR)
    st.configure("Ok.TLabel", foreground=OK)
    st.configure("Aviso.TLabel", background=AVISO_FONDO, foreground=AVISO, padding=(8, 5))
    st.configure("ErrorCaja.TLabel", background=ERROR_FONDO, foreground=ERROR, padding=(8, 5))
    st.configure("Estado.TLabel", background="#e5e7eb", foreground=TEXTO_SUAVE, padding=(8, 3))

    st.configure("TButton", padding=(10, 4), background="#e8eaee", bordercolor=BORDE)
    st.map("TButton", background=[("active", "#d9dde3"), ("disabled", "#eceef1")],
           foreground=[("disabled", "#9aa3af")])
    st.configure("Accion.TButton", background=ACENTO, foreground="#ffffff", bordercolor=ACENTO_OSCURO)
    st.map("Accion.TButton", background=[("active", ACENTO_OSCURO), ("disabled", "#a9c3e0")],
           foreground=[("disabled", "#ffffff")])
    st.configure("Peligro.TButton", foreground=ERROR)
    st.configure("Herramienta.TButton", padding=(8, 3))
    st.configure("Herramienta.TRadiobutton", padding=(8, 3))
    st.configure("Toolbutton", padding=(8, 3))
    st.map("Toolbutton", background=[("selected", ACENTO_CLARO), ("active", "#e2e6ec")],
           bordercolor=[("selected", ACENTO)])

    st.configure("TEntry", fieldbackground="#ffffff", padding=3)
    st.configure("TCombobox", fieldbackground="#ffffff", padding=3)
    st.map("TCombobox", fieldbackground=[("readonly", "#ffffff"), ("disabled", "#eceef1")])
    st.configure("Error.TEntry", fieldbackground=ERROR_FONDO, bordercolor=ERROR)
    st.configure("Error.TCombobox", fieldbackground=ERROR_FONDO, bordercolor=ERROR)
    st.map("Error.TCombobox", fieldbackground=[("readonly", ERROR_FONDO)])
    st.configure("TSpinbox", fieldbackground="#ffffff", padding=3)

    st.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=ALTO_FILA,
                 bordercolor=BORDE)
    st.map("Treeview", background=[("selected", ACENTO)], foreground=[("selected", "#ffffff")])
    st.configure("Treeview.Heading", background="#e5e7eb", font=(fam, 10, "bold"), padding=(6, 4), relief="flat")
    st.map("Treeview.Heading", background=[("active", "#d9dde3")])

    st.configure("TNotebook", background=FONDO, tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", padding=(14, 6), background="#e5e7eb")
    st.map("TNotebook.Tab", background=[("selected", "#ffffff")], expand=[("selected", (0, 0, 0, 2))])
    st.configure("TLabelframe", background=FONDO, bordercolor=BORDE)
    st.configure("TLabelframe.Label", background=FONDO, foreground=ACENTO_OSCURO, font=(fam, 10, "bold"))
    st.configure("TProgressbar", background=ACENTO, troughcolor="#e5e7eb", thickness=14)
    st.configure("TPanedwindow", background=FONDO)
    st.configure("Sash", sashthickness=6)
    st.configure("TSeparator", background=BORDE)
    return st


def es_windows():
    return sys.platform.startswith("win")


def hacer_dpi_consciente():
    """Windows: evita la interfaz borrosa en pantallas con escala > 100 %. Llamar ANTES de crear Tk."""
    if es_windows():
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:                                   # noqa: BLE001 - versiones antiguas de Windows
            pass
