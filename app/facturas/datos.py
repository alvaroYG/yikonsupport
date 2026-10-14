"""
"Preparar factura": los datos de la factura de un pedido, para que Aina la haga a mano.

La plataforma NO hace la factura (es un tema delicado): enseña los datos para revisarlos y
descarga un Excel BÁSICO, sin pinta de factura, con solo tres bloques:

  - Seller / Billing address / Delivery address (la de entrega = la de facturación; Aina la
    cambia si hace falta). El vendedor sale de Ajustes → Datos de Yikon (app/datos_empresa.py).
  - Los productos, con las columnas del FORMATO del cliente (ficha del cliente → Facturación):
    A kits sin precio, B kits con precio por línea, C lista con precio unitario.
  - Los totales según su régimen de IVA y sus gastos de envío pactados (con fórmulas, para que
    se recalculen si Aina toca algo).

Nada más: ni nº, ni fecha, ni banco, ni HS Code; eso lo pone Aina en su plantilla.
La pantalla va en el idioma de la web; el Excel, en inglés (como las facturas).
"""
from datetime import date
from decimal import Decimal

from app.inventario.reservas import reservas_de


from flask_babel import lazy_gettext as _l

def _lotes(reservas, clave, usadas):
    """Los lotes de esa clave, solo la primera vez que sale (un mismo producto puede ir suelto
    y en un kit: sus lotes se enseñan una vez)."""
    if clave in usadas:
        return []
    usadas.add(clave)
    return reservas.get(clave, [])


def filas_productos(pedido) -> list:
    """Una fila por producto: [{"producto", "unidad", "referencia", "item", "cantidad", "unitario", "precio",
    "lotes": [(lote, unidades)], "primera", "grupo"}]. "producto" y "unidad" (el kit y cuántos) solo en
    la primera fila de cada kit; "grupo" = cuántas filas ocupa.

    Precios (formatos B y C): los productos de un kit no tienen precio propio en el pedido (lo paga el
    kit), así que llevan el de catálogo (avisos_kits() dice si no suman el precio del kit). Los sueltos,
    el del pedido. "precio" es el de la línea SIN descuento: el descuento va en los totales."""
    reservas, usadas, filas = reservas_de(pedido), set(), []
    for k in pedido.kits:
        lotes_kit = _lotes(reservas, ("kit", k.kit_id), usadas) if k.kit.cerrado else []
        if not k.lineas:          # un kit sin productos (raro): al menos su fila, con su precio
            filas.append({"producto": k.kit.nombre, "unidad": k.cantidad, "referencia": k.kit.referencia,
                          "item": k.kit.nombre, "cantidad": k.cantidad, "unitario": Decimal(k.precio_unitario or 0),
                          "precio": k.subtotal, "lotes": lotes_kit, "primera": True, "grupo": 1})
        for i, l in enumerate(k.lineas):
            lotes = lotes_kit if i == 0 else []
            if not k.kit.cerrado:
                lotes = _lotes(reservas, ("producto", l.producto_id), usadas)
            unitario = Decimal(l.producto.precio or 0)
            filas.append({"producto": k.kit.nombre if i == 0 else "", "unidad": k.cantidad if i == 0 else "",
                          "referencia": l.producto.referencia, "item": l.producto.nombre, "cantidad": l.cantidad,
                          "unitario": unitario, "precio": (unitario * l.cantidad).quantize(Decimal("0.01")),
                          "lotes": lotes, "primera": i == 0, "grupo": len(k.lineas)})
    for l in pedido.lineas_sueltas:
        unitario = Decimal(l.precio_unitario or 0)
        filas.append({"producto": l.producto.nombre, "unidad": l.cantidad, "referencia": l.producto.referencia,
                      "item": l.producto.nombre, "cantidad": l.cantidad, "suelto": True, "unitario": unitario,
                      "precio": (unitario * l.cantidad).quantize(Decimal("0.01")),
                      "lotes": _lotes(reservas, ("producto", l.producto_id), usadas), "primera": True, "grupo": 1})
    return filas


def avisos_kits(pedido) -> list:
    """Kits cuyos productos, a precio de catálogo, no suman lo que cuesta el kit en el pedido:
    [(nombre del kit, suma de catálogo, precio del kit en el pedido)]."""
    avisos = []
    for k in pedido.kits:
        if not k.lineas:
            continue
        suma = sum((Decimal(l.producto.precio or 0) * l.cantidad for l in k.lineas), Decimal("0")).quantize(Decimal("0.01"))
        if suma != k.subtotal:
            avisos.append((k.kit.nombre, suma, k.subtotal))
    return avisos


IVA_ESPANA = Decimal("21")


def totales(pedido, regimen="es", envio=None) -> dict:
    """Precio total sin descuento, % de descuento (si hay descuentos por línea, el equivalente
    sobre el total), subtotal, envío, % de IVA (None si hay varios tipos), IVA y total.
    Fuera de España (UE o exportación) no hay IVA. En España el envío también lleva IVA."""
    bruto = (sum((k.subtotal for k in pedido.kits), Decimal("0"))
             + sum((Decimal(l.cantidad or 0) * Decimal(l.precio_unitario or 0) for l in pedido.lineas_sueltas),
                   Decimal("0"))).quantize(Decimal("0.01"))
    neto = pedido.base_imponible
    descuento = ((1 - neto / bruto) * 100).quantize(Decimal("0.01")) if bruto else Decimal("0")
    envio = Decimal(envio or 0).quantize(Decimal("0.01"))
    tipos = {Decimal(x.iva_pct) for x in [*pedido.kits, *pedido.lineas_sueltas] if x.subtotal}
    iva_pct = tipos.pop() if len(tipos) == 1 else None
    con_iva = regimen == "es"
    iva = Decimal("0.00")
    if con_iva:
        iva = (pedido.total_iva + envio * (iva_pct or IVA_ESPANA) / 100).quantize(Decimal("0.01"))
    return {"bruto": bruto, "descuento": descuento, "neto": neto, "envio": envio, "con_iva": con_iva,
            "iva_pct": iva_pct, "iva": iva, "total": neto + envio + iva}


def lista_totales(t) -> list:
    """Las filas de totales que tocan, en el orden de las facturas: [(clave, valor)]. El descuento
    solo si hay, el envío si se cobra y el IVA si es en España. iva_pct None = varios tipos."""
    filas = [("bruto", t["bruto"])]
    if t["descuento"]:
        filas += [("descuento", t["descuento"]), ("neto", t["neto"])]
    if t["envio"]:
        filas.append(("envio", t["envio"]))
    if t["con_iva"]:
        filas += [("iva_pct", t["iva_pct"]), ("iva", t["iva"])]
    filas.append(("total", t["total"]))
    return filas


# Nombres de los totales: en el Excel, como en las facturas (inglés); en pantalla, traducidos
TOTALES_EXCEL = {"bruto": "Total price", "descuento": "Discount [%]", "neto": "Subtotal less discount",
                 "envio": "Shipment", "iva_pct": "% IVA", "iva": "Total tax", "total": "Total amount"}
TOTALES_PANTALLA = {"bruto": _l("Precio total"), "descuento": _l("Descuento"), "neto": _l("Subtotal con descuento"),
                    "envio": _l("Envío"), "iva_pct": _l("IVA"), "iva": _l("Importe del IVA"), "total": _l("Total")}

# Columnas de cada formato: en el Excel como en las facturas; en pantalla, traducidas.
# Claves de cada fila de filas_productos(). En A y B, "Product" ocupa tres columnas (A:C).
COLUMNAS = {
    "A": ["producto", "unidad", "referencia", "item", "cantidad"],
    "B": ["producto", "unidad", "referencia", "item", "cantidad", "precio"],
    "C": ["item", "referencia", "unitario", "cantidad", "precio"],
}
COLUMNAS_EXCEL = {"producto": "PRODUCT", "unidad": "Unit", "referencia": "Catalog No.", "item": "Item",
                  "cantidad": "Qty.", "unitario": "Unit Price", "precio": "Price"}
COLUMNAS_PANTALLA = {"producto": _l("Producto"), "unidad": _l("Unid."), "referencia": _l("Referencia"),
                     "item": _l("Artículo"), "cantidad": _l("Cant."), "unitario": _l("Precio unitario"),
                     "precio": _l("Precio")}


def datos_para_facturar(pedido, hoy=None, envio=None) -> dict:
    """Todo lo de "Preparar factura" con el formato, el IVA y el envío del cliente.
    envio: otro importe de envío solo para esta factura (None = el pactado con el cliente)."""
    hoy = hoy or date.today()
    c = pedido.cliente
    formato = c.formato_factura if c.formato_factura in COLUMNAS else "A"
    regimen = c.regimen_iva or "es"
    envio_pactado = c.gastos_envio
    if envio is None:
        envio = envio_pactado
    contacto = " · ".join(x for x in (c.persona_contacto, c.telefono) if x)
    # La dirección del cliente tal cual sale en el Excel (una línea por fila, sin las vacías)
    direccion = [x for x in (c.razon_social or c.nombre, c.direccion, c.ciudad, contacto,
                             f"VAT: {c.cif}" if c.cif else "") if x]
    t = totales(pedido, regimen, envio)
    return {
        "formato": formato, "regimen": regimen, "configurado": bool(c.formato_factura and c.regimen_iva),
        "envio_pactado": envio_pactado, "envio_cambiado": envio != envio_pactado,
        "numero": pedido.referencia_interna or f"#{pedido.id}", "fecha": hoy, "direccion": direccion,
        "falta_direccion": not (c.direccion and c.cif),
        "columnas": COLUMNAS[formato], "filas": filas_productos(pedido),
        "totales": t, "lista_totales": lista_totales(t),
        "avisos": avisos_kits(pedido) if formato != "A" else [],
    }


# --------------------------------------------------------------------------- #
# El Excel básico
# --------------------------------------------------------------------------- #
def excel_para_facturar(datos, vendedor) -> bytes:
    """Una hoja con Seller / Billing address / Delivery address, los productos y los totales.
    vendedor: las líneas del bloque "Seller." (datos_empresa.lineas_vendedor())."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    from app.excel import FORMATO_EUROS

    formato, columnas = datos["formato"], datos["columnas"]
    agrupado = formato in ("A", "B")              # A y B: "PRODUCT" ocupa A:C, como en la plantilla
    # Columna de Excel de cada dato de la tabla
    col, n = {}, 1
    for clave in columnas:
        col[clave] = n
        n += 3 if (agrupado and clave == "producto") else 1
    ultima = n - 1
    col_valor = ultima if "precio" in columnas else ultima + 1   # A no tiene precios: totales a la derecha
    anchos = {"producto": 12, "unidad": 7, "referencia": 16, "item": 44, "cantidad": 7, "unitario": 13, "precio": 14}

    libro = Workbook()
    ws = libro.active
    ws.title = datos["numero"][:31]
    negrita, cabecera_fondo = Font(bold=True), PatternFill("solid", fgColor="EFE3EE")
    linea = Side(style="thin", color="BFBFBF")
    borde = Border(top=linea, bottom=linea, left=linea, right=linea)

    # Anchos: "producto" reparte su ancho en A:C
    for clave, c0 in col.items():
        if agrupado and clave == "producto":
            for k in range(3):
                ws.column_dimensions[get_column_letter(c0 + k)].width = anchos["producto"]
        else:
            ws.column_dimensions[get_column_letter(c0)].width = anchos[clave]
    if col_valor > ultima:
        ws.column_dimensions[get_column_letter(col_valor)].width = 14

    # 1. Seller / Billing / Delivery, uno al lado del otro. Cada uno empieza donde hay sitio para que
    #    su texto se vea entero (Excel lo deja pasar a las celdas vacías de la derecha)
    inicios = [1, col["referencia"], col["cantidad"]] if agrupado else [1, col["referencia"], col["precio"]]
    bloques = [("Seller.", vendedor), ("Billing Address.", datos["direccion"]), ("Delivery address", datos["direccion"])]
    for (titulo, lineas), c0 in zip(bloques, inicios):
        ws.cell(row=1, column=c0, value=titulo).font = negrita
        for i, texto in enumerate(lineas, start=2):
            ws.cell(row=i, column=c0, value=texto)
    fila = 2 + max(len(vendedor), len(datos["direccion"])) + 1

    # 2. La tabla de productos
    for clave in columnas:
        nombre = "Total Price" if (clave == "precio" and formato == "C") else COLUMNAS_EXCEL[clave]
        celda = ws.cell(row=fila, column=col[clave], value=nombre)
        celda.font, celda.fill, celda.border = negrita, cabecera_fondo, borde
        if agrupado and clave == "producto":
            ws.merge_cells(start_row=fila, start_column=col[clave], end_row=fila, end_column=col[clave] + 2)
    primera = fila + 1
    for f in datos["filas"]:
        fila += 1
        for clave in columnas:
            if agrupado and clave in ("producto", "unidad") and not f["primera"]:
                continue                                     # el kit y cuántos: solo en su primera fila
            valor = f[clave]
            celda = ws.cell(row=fila, column=col[clave], value=float(valor) if clave in ("unitario", "precio") else valor)
            celda.border = borde
            if clave in ("unitario", "precio"):
                celda.number_format = FORMATO_EUROS
            if agrupado and clave in ("producto", "unidad"):
                celda.alignment = Alignment(vertical="center")
                if clave == "producto":
                    celda.font = negrita
                fin_col = col[clave] + (2 if clave == "producto" else 0)
                if f["grupo"] > 1 or fin_col > col[clave]:
                    ws.merge_cells(start_row=fila, start_column=col[clave],
                                   end_row=fila + f["grupo"] - 1, end_column=fin_col)
    ultima_fila = fila

    # 3. Totales: nombre a la izquierda de la columna de importes; fórmulas donde se puede
    letra = get_column_letter(col_valor)
    refs, t = {}, datos["totales"]
    for clave, valor in datos["lista_totales"]:
        fila += 1
        etiqueta = "Total before discount" if (clave == "bruto" and formato == "C") else TOTALES_EXCEL[clave]
        nombre = ws.cell(row=fila, column=col_valor - 1, value=etiqueta + ":")
        # Alineado a la derecha: el texto se ve entero, ocupando las celdas vacías de su izquierda
        nombre.font, nombre.alignment = negrita, Alignment(horizontal="right")
        celda = ws.cell(row=fila, column=col_valor)
        refs[clave] = f"{letra}{fila}"
        neto = refs.get("neto", refs.get("bruto"))
        if clave == "bruto":
            celda.value = (f"=SUM({letra}{primera}:{letra}{ultima_fila})" if "precio" in columnas and datos["filas"]
                           else float(valor))
        elif clave == "descuento":
            celda.value, celda.number_format = float(valor), '0.##" %"'
        elif clave == "neto":
            celda.value = f"={refs['bruto']}*(1-{refs['descuento']}/100)"
        elif clave == "envio":
            celda.value = float(valor)
        elif clave == "iva_pct":
            # Varios tipos de IVA: no hay un % que aplicar; el importe va calculado
            celda.value = float(valor) if valor is not None else "mixed"
            celda.number_format = '0.##" %"'
        elif clave == "iva":
            if t["iva_pct"] is not None:
                base = neto + (f"+{refs['envio']}" if "envio" in refs else "")
                celda.value = f"=ROUND(({base})*{refs['iva_pct']}/100,2)"
            else:
                celda.value = float(valor)
        elif clave == "total":
            partes = [neto] + [refs[k] for k in ("envio", "iva") if k in refs]
            celda.value, celda.font = "=" + "+".join(partes), negrita
        if clave not in ("descuento", "iva_pct"):
            celda.number_format = FORMATO_EUROS

    # Para imprimirlo o verlo en PDF: apaisado y todo a lo ancho de una página
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
