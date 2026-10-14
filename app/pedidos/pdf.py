"""
Genera el PDF con el estado de los pedidos.

Usamos fpdf2 porque funciona en Python puro: no necesita DLL (ni Pillow, que
aquí no usamos porque no metemos imágenes).

Fuente: DejaVu Sans Condensed (licencia libre, en app/pedidos/fuentes/). Es Unicode:
admite cualquier carácter que aparezca en nombres de productos o clientes (β, Ł, ü…).
Las fuentes "core" del PDF (Helvetica) solo cubren windows-1252 y un producto
llamado "Kit β-hCG" hacía fallar la exportación entera.
"""
import os

from flask_babel import gettext as _, lazy_gettext as _l
from fpdf import FPDF
from fpdf.fonts import FontFace

from app.utils import ahora_local

AZUL = (166, 28, 146)       # color corporativo (#a61c92), igual que la barra de la web
GRIS_CLARO = (242, 244, 247)


def _euros(valor):
    # Mismo formato que la web (filtro "euros" de app/__init__.py): depende del idioma
    from flask import current_app
    return current_app.jinja_env.filters["euros"](valor)


CARPETA_FUENTES = os.path.join(os.path.dirname(__file__), "fuentes")
FUENTE = "DejaVu"


class _PDFPedidos(FPDF):
    titulo = _l("Estado de pedidos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_font(FUENTE, "", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed.ttf"))
        self.add_font(FUENTE, "B", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed-Bold.ttf"))

    def header(self):
        self.set_font(FUENTE, "B", 14)
        self.set_text_color(*AZUL)
        self.cell(0, 8, str(self.titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0)
        self.ln(1)

    def footer(self):
        self.set_y(-12)
        self.set_font(FUENTE, size=8)
        self.set_text_color(120)
        self.cell(0, 8, _("Generado el %(fecha)s", fecha=f"{ahora_local():%d/%m/%Y %H:%M}"), align="L")
        self.cell(0, 8, _("Página %(pagina)s/%(total)s", pagina=self.page_no(), total="{nb}"), align="R")


def generar_pdf_pedidos(pedidos, filtros_texto, ver_importes=True,
                        nombre_estado=lambda p: p.estado_nombre) -> bytes:
    pdf = _PDFPedidos(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Resumen de filtros aplicados y número de pedidos
    pdf.set_font(FUENTE, size=9)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 5, _("Filtros: %(filtros)s  ·  %(n)s pedidos",
                           filtros=filtros_texto or _("ninguno"), n=len(pedidos)),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(2)

    columnas = [_("Ref. interna"), _("Fecha"), _("Cliente"), _("Ref. empresa"), _("Productos"),
                _("Estado"), _("Entrega estimada")]
    anchos = [26, 19, 50, 30, 85, 25, 22]
    if ver_importes:
        columnas.append(_("Total"))
        anchos.append(22)

    cabecera = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL)
    pdf.set_font(FUENTE, size=8)
    with pdf.table(col_widths=anchos, headings_style=cabecera, line_height=5,
                   cell_fill_color=GRIS_CLARO, cell_fill_mode="ROWS",
                   text_align=["LEFT"] * (len(columnas) - 1) + ["RIGHT" if ver_importes else "LEFT"]) as tabla:
        fila = tabla.row()
        for c in columnas:
            fila.cell(c)
        for p in pedidos:
            fila = tabla.row()
            fila.cell(p.referencia_interna or f"#{p.id}")
            fila.cell(p.fecha.strftime("%d/%m/%Y"))
            fila.cell(p.cliente.nombre)
            fila.cell(p.referencia or "—")
            fila.cell(p.resumen_contenido("\n") or "—")      # kits (con sus productos) y sueltos
            fila.cell(nombre_estado(p))
            # igual que en la web: la fecha estimada solo tiene sentido mientras está en camino
            fila.cell(p.fecha_entrega_estimada.strftime("%d/%m/%Y")
                      if p.fecha_entrega_estimada and p.estado == "enviado" else "—")
            if ver_importes:
                fila.cell(_euros(p.total))

    if ver_importes and pedidos:
        pdf.ln(3)
        pdf.set_font(FUENTE, "B", 10)
        pdf.cell(0, 6, _("Total: %(importe)s", importe=_euros(sum(p.total for p in pedidos))), align="R")

    return bytes(pdf.output())
