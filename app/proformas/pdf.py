"""
PDF de la proforma (sin precios): logo, datos de Yikon y del cliente, productos
agrupados por kit con su caducidad prevista, plazo de entrega y notas.

Mismas piezas que el PDF de pedidos (fpdf2 + fuente DejaVu, Unicode).
El logo necesita Pillow (fpdf2 lo usa para leer imágenes). Si en algún equipo Pillow no
funciona (p. ej. Windows con las DLL bloqueadas), la proforma se genera igual con el
nombre de la empresa en texto en lugar del logo: nunca falla por el logo.
"""
import os

from flask import current_app, url_for
from flask_babel import gettext as _
from fpdf import FPDF
from fpdf.fonts import FontFace

from app import datos_empresa
from app.pedidos.pdf import AZUL, CARPETA_FUENTES, FUENTE, GRIS_CLARO
from app.utils import hora_local

TINTE = (246, 232, 244)   # magenta muy claro para las filas de kit


class _PDFProforma(FPDF):
    def __init__(self, proforma):
        super().__init__(orientation="P", format="A4")
        self.proforma = proforma
        self.add_font(FUENTE, "", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed.ttf"))
        self.add_font(FUENTE, "B", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(15, 15, 15)

    def footer(self):
        self.set_y(-13)
        self.set_draw_color(*AZUL)
        self.line(15, self.get_y(), self.w - 15, self.get_y())
        self.set_font(FUENTE, size=7.5)
        self.set_text_color(120)
        self.cell(0, 7, f"{datos_empresa.nombre()} · " + _("Proforma %(numero)s", numero=self.proforma.numero_y_version),
                  align="L")
        self.cell(0, 7, _("Página %(pagina)s/%(total)s", pagina=self.page_no(), total="{nb}"), align="R")


def _logo(pdf):
    """Logo arriba a la izquierda; si no se puede dibujar, el nombre en el color de la marca."""
    ruta = os.path.join(current_app.static_folder, "img", "yikon-logo.png")
    try:
        pdf.image(ruta, x=15, y=12, w=48)
        return
    except Exception:                        # Pillow no disponible o imagen ilegible
        current_app.logger.warning("Proforma sin logo (no se pudo leer la imagen; ¿Pillow instalado?)")
    pdf.set_xy(15, 14)
    pdf.set_font(FUENTE, "B", 16)
    pdf.set_text_color(*AZUL)
    pdf.cell(60, 8, "YIKON GENOMICS")
    pdf.set_text_color(0)


def generar_pdf_proforma(proforma) -> bytes:
    pedido, cliente = proforma.pedido, proforma.pedido.cliente
    pdf = _PDFProforma(proforma)
    pdf.add_page()

    # ---- Cabecera: logo + datos de Yikon (izquierda) · PROFORMA y número (derecha)
    _logo(pdf)
    pdf.set_xy(15, 36)
    pdf.set_font(FUENTE, "B", 9)
    pdf.cell(95, 5, datos_empresa.nombre(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FUENTE, size=8)
    pdf.set_text_color(90)
    for linea in datos_empresa.lineas_cabecera():         # (Ajustes → Datos de Yikon)
        pdf.cell(95, 4.2, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    fin_izquierda = pdf.get_y()

    pdf.set_xy(115, 13)
    pdf.set_font(FUENTE, "B", 22)
    pdf.set_text_color(*AZUL)
    pdf.cell(80, 11, _("PROFORMA"), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_font(FUENTE, size=9)
    datos = [(_("Nº"), proforma.numero_y_version),
             (_("Fecha"), hora_local(proforma.fecha).strftime("%d/%m/%Y")),
             (_("Válida hasta"), proforma.valida_hasta.strftime("%d/%m/%Y")),
             (_("Pedido"), pedido.referencia_interna or f"#{pedido.id}")]
    if pedido.referencia:
        datos.append((_("Su referencia"), pedido.referencia))
    for etiqueta, valor in datos:
        pdf.set_x(115)
        pdf.set_text_color(110)
        pdf.cell(35, 5.2, etiqueta, align="R")
        pdf.set_text_color(0)
        pdf.set_font(FUENTE, "B", 9)
        pdf.cell(45, 5.2, valor, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FUENTE, size=9)

    # ---- Cliente
    pdf.set_y(max(fin_izquierda, pdf.get_y()) + 6)
    y = pdf.get_y()
    pdf.set_fill_color(*GRIS_CLARO)
    lineas_cliente = [cliente.razon_social or "", (_("CIF") + ": " + cliente.cif) if cliente.cif else "",
                      cliente.direccion or "", cliente.ciudad or "",
                      (_("Contacto") + ": " + cliente.persona_contacto) if cliente.persona_contacto else ""]
    lineas_cliente = [x for x in lineas_cliente if x]
    alto = 11 + 4.5 * len(lineas_cliente)
    pdf.rect(15, y, pdf.w - 30, alto, style="F")
    pdf.set_xy(19, y + 2.5)
    pdf.set_font(FUENTE, size=7.5)
    pdf.set_text_color(110)
    pdf.cell(0, 4, _("CLIENTE"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(19)
    pdf.set_text_color(0)
    pdf.set_font(FUENTE, "B", 10.5)
    pdf.cell(0, 5.5, cliente.nombre, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FUENTE, size=8.5)
    for linea in lineas_cliente:
        pdf.set_x(19)
        pdf.cell(0, 4.5, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(y + alto + 6)

    # ---- Productos (agrupados por kit) con la caducidad prevista
    cabecera = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL)
    fila_kit = FontFace(emphasis="BOLD", fill_color=TINTE)
    pdf.set_font(FUENTE, size=8.5)
    with pdf.table(col_widths=(27, 75, 26, 18, 34), text_align=("LEFT", "LEFT", "LEFT", "RIGHT", "CENTER"),
                   headings_style=cabecera, line_height=5.2, borders_layout="HORIZONTAL_LINES",
                   first_row_as_headings=True) as tabla:
        encabezado = tabla.row()
        for texto in (_("Referencia"), _("Producto"), _("Marca"), _("Cantidad"), _("Caducidad prevista")):
            encabezado.cell(texto)
        grupo_actual = object()
        for l in proforma.lineas:
            if l.grupo != grupo_actual:
                grupo_actual = l.grupo
                fila = tabla.row(style=fila_kit)
                fila.cell(l.grupo or _("Productos sueltos"), colspan=5)
            fila = tabla.row()
            fila.cell(l.referencia)
            fila.cell(l.nombre)
            fila.cell(l.marca or "—")
            fila.cell(str(l.cantidad))
            if l.caducidad:
                fila.cell(l.caducidad.strftime("%d/%m/%Y"))
            else:
                fila.cell(_("a confirmar") if l.sin_stock else "—")

    # ---- Plazo, notas y avisos
    pdf.ln(5)
    if proforma.plazo_entrega:
        pdf.set_font(FUENTE, "B", 9)
        pdf.cell(45, 5.5, _("Plazo de entrega estimado:"))
        pdf.set_font(FUENTE, size=9)
        pdf.multi_cell(0, 5.5, proforma.plazo_entrega, new_x="LMARGIN", new_y="NEXT")
    if proforma.notas:
        pdf.ln(1)
        pdf.set_font(FUENTE, "B", 9)
        pdf.cell(0, 5.5, _("Notas"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FUENTE, size=9)
        pdf.multi_cell(0, 5, proforma.notas, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(*AZUL)
    pdf.set_font(FUENTE, size=7.8)
    pdf.set_text_color(80)
    avisos = [
        _("Documento informativo, sin precios y sin valor de factura."),
        _("La caducidad prevista es la del lote que saldría con el stock a fecha de emisión; "
          "puede variar si cambia el stock. «—» = no aplica; «a confirmar» = pendiente de reposición."),
        _("Para aceptar esta proforma o pedir cambios, entre en la plataforma: %(enlace)s",
          enlace=url_for("pedidos.detalle", id=pedido.id, _external=True)),
    ]
    pdf.multi_cell(0, 4.2, "\n".join(avisos), border="L", padding=(1, 3, 1, 3), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    return bytes(pdf.output())
