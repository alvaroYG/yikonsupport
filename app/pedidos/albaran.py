"""
Albarán del pedido (PDF): la hoja que va DENTRO del paquete. Lo sacan admin y Almacén desde
Preparar o desde la ficha del pedido (permiso "pedidos.albaran"); el cliente no lo ve en la
plataforma ni se guarda en «Documentos».

  - Número de albarán = la referencia interna del pedido (YK-2026-DiNA-1).
  - Sin precios.
  - Envío y facturación: los de la ficha del cliente; al pasar a «Enviado» se copian en el
    pedido (Pedido.datos_albaran), así que el albarán de lo ya enviado no cambia aunque luego
    cambie su ficha.
  - Lotes: los reservados mientras se prepara; los que salieron de verdad una vez enviado.
  - Si no hay dirección de envío no se genera (la ruta avisa): un albarán sin dirección no sirve.

Mismas fuentes que pdf.py (DejaVu: admite β, Ł, ü…).
"""
import os
from datetime import date

from flask import current_app
from flask_babel import gettext as _
from fpdf import FPDF
from fpdf.fonts import FontFace

from app import datos_empresa
from app.extensions import db
from app.models import MovimientoInventario
from app.pedidos.pdf import AZUL, CARPETA_FUENTES, FUENTE, GRIS_CLARO

LOGO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "img", "yikon-logo.png")


def lineas_lugar(d) -> list:
    """Dirección, «CP Ciudad» y «Provincia, País» (lo que haya)."""
    return [x for x in (d.get("direccion"),
                        " ".join(y for y in (d.get("codigo_postal"), d.get("ciudad")) if y),
                        ", ".join(y for y in (d.get("provincia"), d.get("pais")) if y)) if x]


def contenido(pedido) -> list:
    """[(cantidad, referencia, descripción, es_de_kit)]: cada kit con sus productos debajo y los sueltos."""
    filas = []
    for k in pedido.kits:
        filas.append((k.cantidad, k.kit.referencia, k.kit.nombre, False))
        filas += [(l.cantidad, l.producto.referencia, l.producto.nombre, True) for l in k.lineas]
    filas += [(l.cantidad, l.producto.referencia, l.producto.nombre, False) for l in pedido.lineas_sueltas]
    return filas


def lotes(pedido) -> list:
    """[(artículo, lote, unidades)]: los que salieron (si ya se envió) o los reservados."""
    from app.inventario import reservas
    from app.inventario.stock import articulo_de, lotes_enviados
    if pedido.estado in ("enviado", "entregado"):
        filas = [(l["articulo"], l["lote"], l["unidades"]) for l in lotes_enviados(pedido)]
    else:
        plan, _problemas = reservas.plan_reservado(pedido, faltan=False, proforma=False)
        filas = [(articulo_de(clave), lote, n) for clave, reparto in plan.items() for lote, n in reparto]
    filas.sort(key=lambda f: (f[0].tipo_articulo != "kit", f[0].nombre.lower(), f[1].codigo if f[1] else ""))
    return filas


def fecha_del_albaran(pedido) -> date:
    """El día que salió (su primer movimiento de salida) o, si aún no ha salido, hoy."""
    if pedido.estado in ("enviado", "entregado"):
        salida = db.session.scalar(db.select(db.func.max(MovimientoInventario.fecha))
                                   .where(MovimientoInventario.pedido_id == pedido.id,
                                          MovimientoInventario.cantidad < 0))
        if salida:
            return salida.date()
    return date.today()


class _PDFAlbaran(FPDF):
    def __init__(self, referencia):
        super().__init__(format="A4")
        self.referencia = referencia
        self.add_font(FUENTE, "", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed.ttf"))
        self.add_font(FUENTE, "B", os.path.join(CARPETA_FUENTES, "DejaVuSansCondensed-Bold.ttf"))
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self):
        self.set_y(-13)
        self.set_font(FUENTE, size=8)
        self.set_text_color(120)
        self.cell(0, 6, _("Albarán %(ref)s", ref=self.referencia), align="L")
        self.set_x(self.l_margin)
        self.cell(0, 6, _("Página %(pagina)s/%(total)s", pagina=self.page_no(), total="{nb}"), align="R")


def _caja(pdf, x, y, ancho, titulo, lineas):
    """Un recuadro con título (Enviar a / Facturar a). Devuelve dónde acaba (y)."""
    pdf.set_xy(x, y)
    pdf.set_font(FUENTE, "B", 8)
    pdf.set_text_color(*AZUL)
    pdf.cell(ancho, 5, titulo.upper(), new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(0)
    for i, linea in enumerate(lineas):
        pdf.set_x(x)
        pdf.set_font(FUENTE, "B" if i == 0 else "", 10 if i == 0 else 9)
        pdf.multi_cell(ancho, 4.6, linea, new_x="LEFT", new_y="NEXT")
    return pdf.get_y()


def generar_albaran(pedido) -> bytes:
    datos = pedido.datos_para_albaran
    envio, fac = datos["envio"], datos["facturacion"]
    referencia = pedido.referencia_interna or f"#{pedido.id}"
    pdf = _PDFAlbaran(referencia)
    pdf.add_page()
    ancho = pdf.w - pdf.l_margin - pdf.r_margin

    # ---- Cabecera: Yikon (logo y datos) a la izquierda; «ALBARÁN», número y fecha a la derecha
    y0 = pdf.get_y()
    if os.path.exists(LOGO):
        try:
            pdf.image(LOGO, x=pdf.l_margin, y=y0, h=13)
            pdf.set_y(y0 + 15)
        except Exception:                      # (un logo que no se puede leer no impide el albarán)
            current_app.logger.warning("Albarán: no se ha podido poner el logo %s", LOGO)
    pdf.set_font(FUENTE, "B", 10)
    pdf.cell(100, 5, datos_empresa.datos()["razon_social"] or datos_empresa.nombre(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FUENTE, size=8)
    pdf.set_text_color(80)
    for linea in datos_empresa.lineas_cabecera():
        pdf.cell(100, 4, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    fin_izquierda = pdf.get_y()

    pdf.set_xy(pdf.w - pdf.r_margin - 75, y0)
    pdf.set_font(FUENTE, "B", 20)
    pdf.set_text_color(*AZUL)
    pdf.cell(75, 10, _("ALBARÁN"), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_font(FUENTE, "B", 11)
    pdf.cell(75, 6, _("Nº %(ref)s", ref=referencia), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font(FUENTE, size=9)
    pdf.cell(75, 5, _("Fecha: %(fecha)s", fecha=f"{fecha_del_albaran(pedido):%d/%m/%Y}"), align="R",
             new_x="LEFT", new_y="NEXT")
    pdf.set_y(max(fin_izquierda, pdf.get_y()) + 4)
    pdf.set_draw_color(*AZUL)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    # ---- Enviar a / Facturar a
    y = pdf.get_y()
    mitad = (ancho - 8) / 2
    a_enviar = [envio["destinatario"]] + lineas_lugar(envio)
    recibe = " · ".join(x for x in (envio.get("contacto"), envio.get("telefono")) if x)
    if recibe:
        a_enviar.append(_("Atención: %(quien)s", quien=recibe))
    a_facturar = [fac["razon_social"]] + ([_("CIF/NIF: %(cif)s", cif=fac["cif"])] if fac.get("cif") else []) \
        + lineas_lugar(fac)
    fin1 = _caja(pdf, pdf.l_margin, y, mitad, _("Enviar a"), a_enviar)
    fin2 = _caja(pdf, pdf.l_margin + mitad + 8, y, mitad, _("Facturar a"), a_facturar)
    pdf.set_y(max(fin1, fin2) + 4)

    # ---- Datos del pedido
    datos_pedido = [(_("Su nº de pedido"), pedido.referencia or "—"),
                    (_("Fecha del pedido"), f"{pedido.fecha:%d/%m/%Y}"),
                    (_("Uso"), pedido.uso_nombre or "—")]
    if pedido.transportista or pedido.numero_seguimiento:
        datos_pedido.append((_("Transporte"), " · ".join(x for x in (pedido.transportista, pedido.numero_seguimiento) if x)))
    pdf.set_font(FUENTE, size=8)
    with pdf.table(col_widths=[1] * len(datos_pedido), line_height=5, first_row_as_headings=True,
                   headings_style=FontFace(emphasis="BOLD", color=(90, 90, 90), fill_color=GRIS_CLARO)) as tabla:
        fila = tabla.row()
        for titulo, _valor in datos_pedido:
            fila.cell(titulo)
        fila = tabla.row()
        for _titulo, valor in datos_pedido:
            fila.cell(valor)
    pdf.ln(5)

    cabecera = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL)

    # ---- Contenido (sin precios)
    pdf.set_font(FUENTE, "B", 10)
    pdf.cell(0, 6, _("Contenido"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FUENTE, size=9)
    with pdf.table(col_widths=[18, 40, 122], headings_style=cabecera, line_height=5.5,
                   text_align=["RIGHT", "LEFT", "LEFT"]) as tabla:
        fila = tabla.row()
        for c in (_("Cantidad"), _("Referencia"), _("Descripción")):
            fila.cell(c)
        for cantidad, ref, nombre, de_kit in contenido(pedido):
            fila = tabla.row(style=FontFace(color=(90, 90, 90), size_pt=8) if de_kit else FontFace(emphasis="BOLD"))
            fila.cell(str(cantidad))
            fila.cell(ref or "")
            fila.cell(("    · " + nombre) if de_kit else nombre)
    pdf.ln(5)

    # ---- Lotes y caducidades
    filas_lotes = lotes(pedido)
    if filas_lotes:
        pdf.set_font(FUENTE, "B", 10)
        pdf.cell(0, 6, _("Lotes y caducidades"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FUENTE, size=9)
        with pdf.table(col_widths=[90, 40, 30, 20], headings_style=cabecera, line_height=5.5,
                       cell_fill_color=GRIS_CLARO, cell_fill_mode="ROWS",
                       text_align=["LEFT", "LEFT", "LEFT", "RIGHT"]) as tabla:
            fila = tabla.row()
            for c in (_("Artículo"), _("Lote"), _("Caducidad"), _("Uds.")):
                fila.cell(c)
            for articulo, lote, n in filas_lotes:
                fila = tabla.row()
                fila.cell(articulo.nombre)
                fila.cell(lote.codigo if lote else "—")
                fila.cell(f"{lote.caducidad:%d/%m/%Y}" if lote and lote.caducidad else "—")
                fila.cell(str(n))
        pdf.ln(5)

    # ---- Observaciones e instrucciones de entrega
    for titulo, texto in ((_("Observaciones"), pedido.observaciones), (_("Instrucciones de entrega"), envio.get("instrucciones"))):
        if texto:
            pdf.set_font(FUENTE, "B", 9)
            pdf.cell(0, 5, titulo, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(FUENTE, size=9)
            pdf.multi_cell(0, 4.6, texto, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

    # ---- Recibí conforme (firma y sello)
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    pdf.ln(3)
    y = pdf.get_y()
    pdf.set_draw_color(150)
    pdf.rect(pdf.l_margin, y, ancho, 32)
    pdf.set_xy(pdf.l_margin + 3, y + 2)
    pdf.set_font(FUENTE, "B", 9)
    pdf.cell(0, 5, _("Recibí conforme"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FUENTE, size=8)
    pdf.set_text_color(90)
    pdf.set_xy(pdf.l_margin + 3, y + 25)
    pdf.cell(ancho / 3, 5, _("Nombre:"))
    pdf.cell(ancho / 3, 5, _("Fecha:"))
    pdf.cell(ancho / 3 - 6, 5, _("Firma y sello:"))
    pdf.set_text_color(0)
    return bytes(pdf.output())
