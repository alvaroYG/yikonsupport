from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _, lazy_gettext as _l
from flask_login import current_user

from app import archivos, avisos_internos, datos_empresa
from app.alcance import filtrar_facturas

from app.auditoria import cambios, registrar
from app.extensions import db
from app.facturas.forms import FacturaForm, FacturaPdfForm, FacturaPedidoForm
from app.models import ESTADOS_FACTURA, FORMATOS_FACTURA, REGIMENES_IVA, Cliente, Factura, Pedido, ahora
from app.permisos import requiere_permiso
from app.utils import ordenar, paginar

bp = Blueprint("facturas", __name__)

# Antes de llegar al cliente: filtros de la lista (y de Pendientes, app/pedidos/pendientes.py)
FASES = {
    "en_revision": (Factura.revision == "pendiente", Factura.enviada_el.is_(None)),
    "devueltas": (Factura.revision == "cambios", Factura.enviada_el.is_(None)),
    "por_enviar": (db.or_(Factura.revision.is_(None), Factura.revision == "aprobada"), Factura.enviada_el.is_(None)),
}
NOMBRES_FASES = {"en_revision": _l("En revisión"), "devueltas": _l("Devueltas"), "por_enviar": _l("Por enviar al cliente")}

CAMPOS = ["numero", "cliente_id", "fecha_emision", "fecha_vencimiento", "estado", "fecha_pago", "notas"]


def _guardar(form, factura):
    """Copia el formulario a la factura. Si han subido un PDF nuevo, lo guarda y devuelve
    el nombre en disco del PDF anterior (para borrarlo cuando el cambio se haya guardado)."""
    for campo in CAMPOS:
        valor = getattr(form, campo).data
        setattr(factura, campo, valor if valor != "" else None)
    factura.pedido_id = form.pedido_id.data or None
    anterior = None
    if form.pdf_leido:
        nombre, ext, datos = form.pdf_leido
        anterior = factura.pdf_archivo
        factura.pdf_archivo = archivos.escribir(datos, "factura", ext)
        factura.pdf_nombre, factura.pdf_tamano = nombre, len(datos)
    return anterior


def _facturas_filtradas():
    """Filtros de la URL (?estado=...&q=...). Los usan la lista y el Excel: exportas lo que ves."""
    # alcance: el FAS solo ve las de sus clientes (admin y Facturación, todas)
    # Las vencidas, primero; después, las más recientes
    vencida = db.case((db.and_(Factura.estado == "pendiente", Factura.enviada_el.isnot(None),
                               Factura.fecha_vencimiento < date.today()), 0), else_=1)
    select = filtrar_facturas(db.select(Factura)).order_by(vencida, Factura.fecha_emision.desc(), Factura.id.desc())
    estado = request.args.get("estado")
    if estado == "vencida":
        select = select.where(Factura.estado == "pendiente", Factura.enviada_el.isnot(None),
                              Factura.fecha_vencimiento < date.today())
    elif estado in FASES:          # antes de llegar al cliente: en revisión, devueltas, por enviar
        select = select.where(*FASES[estado])
    elif estado in ESTADOS_FACTURA:
        select = select.filter_by(estado=estado)
    q = request.args.get("q", "").strip()
    if q:
        select = select.where(Factura.numero.ilike(f"%{q}%"))
    # Cabeceras que ordenan (utils.ordenar): la lista y el Excel salen en el mismo orden
    select, orden = ordenar(select, {
        "numero": db.func.lower(Factura.numero),
        "cliente": db.select(db.func.lower(Cliente.nombre)).where(Cliente.id == Factura.cliente_id).scalar_subquery(),
        "pedido": db.select(db.func.lower(Pedido.referencia_interna)).where(Pedido.id == Factura.pedido_id).scalar_subquery(),
        "emision": Factura.fecha_emision, "vencimiento": Factura.fecha_vencimiento,
    }, desempate=Factura.id)
    return select, estado, q, orden


@bp.route("/")
@requiere_permiso("facturas.ver")
def lista():
    select, estado, q, orden = _facturas_filtradas()
    return render_template("facturas/lista.html", title=_("Facturas"), pagina=paginar(select),
                           estados=ESTADOS_FACTURA, estado=estado, q=q, fases=NOMBRES_FASES,
                           orden=orden)


@bp.route("/exportar.xlsx")
@requiere_permiso("facturas.ver")
def exportar_excel():
    from app.excel import MIMETYPE_XLSX, Columna, generar_excel
    select, _estado, _q, _orden = _facturas_filtradas()
    facturas = db.session.scalars(select.limit(20000)).all()
    columnas = [Columna(_("Número"), 16), Columna(_("Cliente"), 30), Columna(_("Pedido"), 14),
                Columna(_("Emisión"), 12, "fecha"), Columna(_("Vencimiento"), 12, "fecha"),
                Columna(_("Estado"), 16), Columna(_("Fecha de pago"), 12, "fecha")]
    filas = [[f.numero, f.cliente.nombre, (f.pedido.referencia_interna if f.pedido else ""),
              f.fecha_emision, f.fecha_vencimiento, str(ESTADOS_FACTURA.get(f.estado, f.estado))
              + (" (" + _("vencida") + ")" if f.esta_vencida else ""),
              f.fecha_pago] for f in facturas]
    datos = generar_excel(_("Facturas"), columnas, filas)
    return Response(datos, mimetype=MIMETYPE_XLSX, headers={
        "Content-Disposition": f'attachment; filename="facturas_{date.today():%Y%m%d}.xlsx"'})


@bp.route("/nueva", methods=["GET", "POST"])
@requiere_permiso("facturas.editar")
def nueva():
    # Atajo: registrar la factura de un pedido rellena el cliente y el pedido
    pedido_id = request.args.get("pedido_id", type=int)
    form = FacturaForm(pedido=db.session.get(Pedido, pedido_id) if pedido_id else None)
    if request.method == "GET" and pedido_id:
        pedido = db.get_or_404(Pedido, pedido_id)
        form.pedido_id.data, form.cliente_id.data = pedido.id, pedido.cliente_id
    if form.validate_on_submit():
        factura = Factura(revision="pendiente" if form.revisar.data else None)
        _guardar(form, factura)
        db.session.add(factura)
        db.session.flush()
        registrar("crear", factura, factura.numero + (" · con PDF" if factura.pdf_archivo else "")
                  + (" · pide revisión" if factura.revision else ""))
        if factura.revision == "pendiente":
            avisos_internos.factura_revisar(factura, current_user.nombre, excluir_id=current_user.id)
        db.session.commit()
        flash(_("Factura %(numero)s registrada.", numero=factura.numero), "success")
        return redirect(url_for("facturas.lista"))
    return render_template("facturas/form.html", title=_("Registrar factura"), form=form)


@bp.route("/<int:id>/editar", methods=["GET", "POST"])
@requiere_permiso("facturas.editar")
def editar(id):
    factura = db.get_or_404(Factura, id)
    form = FacturaForm(obj=factura, factura=factura)
    if request.method == "GET":
        form.pedido_id.data = factura.pedido_id or 0
    if form.validate_on_submit():
        detalle = cambios(factura, form, CAMPOS)
        anterior = _guardar(form, factura)
        if form.pdf_leido:
            detalle = "; ".join(x for x in (detalle, f"PDF: {factura.pdf_nombre}") if x)
        registrar("editar", factura, detalle)
        db.session.commit()
        archivos.borrar(anterior)          # el PDF sustituido ya no lo usa nadie
        flash(_("Factura actualizada."), "success")
        return redirect(url_for("facturas.lista"))
    return render_template("facturas/form.html", title=_("Factura %(numero)s", numero=factura.numero), form=form,
                           factura=factura)


@bp.route("/<int:id>/pagada", methods=["POST"])
@requiere_permiso("facturas.editar")
def marcar_pagada(id):
    factura = db.get_or_404(Factura, id)
    if factura.estado != "pagada":
        registrar("editar", factura, f"{factura.estado} → pagada")
        factura.estado, factura.fecha_pago = "pagada", date.today()
        db.session.commit()
        flash(_("Factura %(numero)s marcada como pagada.", numero=factura.numero), "success")
    return redirect(url_for("facturas.lista"))


# --------------------------------------------------------------------------- #
# El cliente: sus facturas y el PDF
# --------------------------------------------------------------------------- #
@bp.route("/mias")
@requiere_permiso("facturas.ver_propias")
def mias():
    """Las facturas de la empresa del cliente conectado (sin notas internas)."""
    select = (db.select(Factura).filter_by(cliente_id=current_user.cliente_id).where(Factura.enviada_el.isnot(None))
              .order_by(Factura.fecha_emision.desc(), Factura.id.desc()))
    return render_template("facturas/mias.html", title=_("Mis facturas"), pagina=paginar(select))


def puede_descargar(factura):
    """Admin y Facturación: todas. FAS: las de sus clientes. Cliente: las de su empresa.
    (Mismo criterio en la vista y en las plantillas.)"""
    if current_user.puede("facturas.ver"):
        return db.session.scalar(filtrar_facturas(db.select(Factura.id).filter_by(id=factura.id))) is not None
    return (current_user.puede("facturas.ver_propias") and current_user.cliente_id is not None
            and factura.cliente_id == current_user.cliente_id and factura.enviada)


@bp.route("/<int:id>/pdf")
@requiere_permiso("facturas.descargar")
def descargar_pdf(id):
    factura = db.get_or_404(Factura, id)
    # 404 y no 403: no confirmamos que exista una factura de otra empresa
    if not factura.pdf_archivo or not puede_descargar(factura):
        abort(404)
    return archivos.descargar(factura.pdf_archivo, factura.pdf_nombre or f"{factura.numero}.pdf")


# --------------------------------------------------------------------------- #
# Por facturar y "Preparar factura" (para la plantilla de Excel de Aina)
# --------------------------------------------------------------------------- #
ESTADOS_POR_FACTURAR = ("enviado", "entregado")


def select_por_facturar():
    """Pedidos enviados o recibidos sin ninguna factura (las anuladas no cuentan). Lo usa también
    la pestaña "Por facturar" de Pendientes (app/pedidos/pendientes.py)."""
    return (db.select(Pedido).where(Pedido.estado.in_(ESTADOS_POR_FACTURAR),
                                    ~Pedido.facturas.any(Factura.estado != "anulada"))
            .order_by(Pedido.fecha, Pedido.id))


@bp.route("/por-facturar")
@requiere_permiso("facturas.editar")
def por_facturar():
    return render_template("facturas/por_facturar.html", title=_("Por facturar"), pagina=paginar(select_por_facturar()))


@bp.route("/pedido/<int:pedido_id>/datos")
@requiere_permiso("facturas.editar")
def datos_pedido(pedido_id):
    from app.facturas.datos import COLUMNAS_PANTALLA, TOTALES_PANTALLA, datos_para_facturar
    pedido, envio = _pedido_y_envio(pedido_id)
    return render_template("facturas/datos.html", title=_("Preparar factura"), pedido=pedido,
                           datos=datos_para_facturar(pedido, envio=envio), formatos=FORMATOS_FACTURA,
                           regimenes=REGIMENES_IVA, nombres_columnas=COLUMNAS_PANTALLA, nombres_totales=TOTALES_PANTALLA)


def _pedido_y_envio(pedido_id):
    """El pedido (404 si aún es proforma) y el envío de ?envio=…: otro importe solo para esta
    factura, que no se guarda (vacío = sin envío; sin el parámetro, el pactado con el cliente)."""
    from app.utils import leer_precio
    pedido = db.get_or_404(Pedido, pedido_id)
    if pedido.estado in ESTADOS_SIN_FACTURA:
        abort(404)
    envio = None
    if "envio" in request.args:
        texto = request.args["envio"].strip()
        envio = leer_precio(texto) if texto else 0
        if envio is None:
            flash(_("Ese importe de envío no es válido."), "warning")
    return pedido, envio


@bp.route("/pedido/<int:pedido_id>/datos.xlsx")
@requiere_permiso("facturas.editar")
def datos_excel(pedido_id):
    """El Excel básico con los datos de la factura (no es la factura: Aina la hace en su plantilla)."""
    from flask import current_app

    from app.excel import MIMETYPE_XLSX
    from app.facturas.datos import datos_para_facturar, excel_para_facturar
    pedido, envio = _pedido_y_envio(pedido_id)
    datos = datos_para_facturar(pedido, envio=envio)
    contenido = excel_para_facturar(datos, datos_empresa.lineas_vendedor())
    nombre = "datos_" + "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in datos["numero"]) + ".xlsx"
    return Response(contenido, mimetype=MIMETYPE_XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@bp.route("/cliente/<int:cliente_id>/facturacion", methods=["POST"])
@requiere_permiso("facturas.editar")
def guardar_facturacion(cliente_id):
    """Formato de factura, régimen de IVA y gastos de envío pactados de un cliente. Se cambia desde
    "Preparar factura" (Aina) o desde la ficha del cliente."""
    from app.utils import leer_precio
    cliente = db.get_or_404(Cliente, cliente_id)
    formato, regimen = request.form.get("formato_factura"), request.form.get("regimen_iva")
    texto_envio = (request.form.get("gastos_envio") or "").strip()
    envio = leer_precio(texto_envio) if texto_envio else None
    if formato not in FORMATOS_FACTURA or regimen not in REGIMENES_IVA or (texto_envio and envio is None):
        flash(_("Revisa los datos de facturación: formato, IVA o importe de envío no válidos."), "danger")
    else:
        antes = (cliente.formato_factura, cliente.regimen_iva, cliente.gastos_envio)
        cliente.formato_factura, cliente.regimen_iva, cliente.gastos_envio = formato, regimen, envio or None
        cliente.revisar_facturas = request.form.get("revisar_facturas") == "1"
        registrar("editar", cliente, f"facturación: {antes[0] or '—'}/{antes[1] or '—'}/{antes[2] or '—'} → "
                                     f"{formato}/{regimen}/{cliente.gastos_envio or '—'}"
                                     + (" · revisa Soporte de cliente" if cliente.revisar_facturas else ""))
        db.session.commit()
        flash(_("Datos de facturación de %(cliente)s guardados.", cliente=cliente.nombre), "success")
    pedido_id = request.form.get("pedido_id", type=int)
    if pedido_id:
        return redirect(url_for("facturas.datos_pedido", pedido_id=pedido_id))
    return redirect(url_for("clientes.detalle", id=cliente.id) + "#facturacion")


# --------------------------------------------------------------------------- #
# Desde la ficha del pedido: registrar su factura y subir PDF a una ya registrada
# --------------------------------------------------------------------------- #
ESTADOS_SIN_FACTURA = ("proforma_solicitada", "proforma_enviada", "cambios_solicitados")   # aún no es pedido


def _volver_al_pedido(pedido_id):
    return redirect(url_for("pedidos.detalle", id=pedido_id) + "#facturas")


def _errores(form):
    for errores in form.errors.values():
        for e in errores:
            flash(e, "danger")


@bp.route("/pedido/<int:pedido_id>", methods=["POST"])
@requiere_permiso("facturas.editar")
def nueva_desde_pedido(pedido_id):
    """Registra la factura del pedido: nº, emisión, vencimiento y, si se adjunta, su PDF. Sin importes."""
    pedido = db.get_or_404(Pedido, pedido_id)
    if pedido.estado in ESTADOS_SIN_FACTURA:
        flash(_("Este pedido todavía es una proforma: aún no se puede facturar."), "warning")
        return _volver_al_pedido(pedido.id)
    form = FacturaPedidoForm()
    if not form.validate_on_submit():
        _errores(form)
        return _volver_al_pedido(pedido.id)
    factura = Factura(numero=form.numero.data, cliente=pedido.cliente, pedido=pedido,
                      fecha_emision=form.fecha_emision.data, fecha_vencimiento=form.fecha_vencimiento.data,
                      revision="pendiente" if form.revisar.data else None)
    if form.pdf_leido:
        nombre, ext, datos = form.pdf_leido
        factura.pdf_archivo = archivos.escribir(datos, "factura", ext)
        factura.pdf_nombre, factura.pdf_tamano = nombre, len(datos)
    db.session.add(factura)
    db.session.flush()
    registrar("crear", factura, f"{factura.numero} · desde el pedido {pedido.referencia_interna}"
              + (" · con PDF" if factura.pdf_archivo else "") + (" · pide revisión" if factura.revision else ""))
    if factura.revision == "pendiente":
        avisos_internos.factura_revisar(factura, current_user.nombre, excluir_id=current_user.id)
    db.session.commit()
    flash(_("Factura %(numero)s registrada.", numero=factura.numero), "success")
    return _volver_al_pedido(pedido.id)


@bp.route("/<int:id>/subir-pdf", methods=["POST"])
@requiere_permiso("facturas.editar")
def subir_pdf(id):
    """Sube o sustituye el PDF de una factura (desde la ficha del pedido o la lista)."""
    factura = db.get_or_404(Factura, id)
    form = FacturaPdfForm()
    if form.validate_on_submit():
        nombre, ext, datos = form.pdf_leido
        anterior = factura.pdf_archivo
        factura.pdf_archivo = archivos.escribir(datos, "factura", ext)
        factura.pdf_nombre, factura.pdf_tamano = nombre, len(datos)
        detalle = f"PDF: {nombre}"
        if factura.revision == "cambios":          # la corregida vuelve a revisión
            factura.revision = "pendiente"
            detalle += " · corregida, vuelve a revisión"
            avisos_internos.factura_revisar(factura, current_user.nombre, excluir_id=current_user.id)
        registrar("editar", factura, detalle)
        db.session.commit()
        archivos.borrar(anterior)
        flash(_("PDF de la factura %(numero)s guardado.", numero=factura.numero)
              + (" " + _("Vuelve a revisión.") if factura.revision == "pendiente" and "revisión" in detalle else ""), "success")
    else:
        _errores(form)
    if factura.pedido_id and request.form.get("volver") == "pedido":
        return _volver_al_pedido(factura.pedido_id)
    return redirect(url_for("facturas.lista"))


# --------------------------------------------------------------------------- #
# Revisión por Soporte de cliente y envío al cliente
#   registrar (con revisión) → En revisión → Aprobar → Por enviar → Enviada (el cliente la ve)
#                                   ↘ Pedir cambios → Devuelta → (PDF corregido) → En revisión
# --------------------------------------------------------------------------- #
def _factura_a_revisar(id):
    """La factura, si quien entra puede revisarla (FAS: solo de sus clientes; admin: todas)."""
    factura = db.session.scalar(filtrar_facturas(db.select(Factura).filter_by(id=id)))
    if factura is None:
        abort(404)
    return factura


def _volver(factura):
    if factura.pedido_id:
        return _volver_al_pedido(factura.pedido_id)
    return redirect(url_for("facturas.lista"))


@bp.route("/<int:id>/aprobar", methods=["POST"])
@requiere_permiso("facturas.revisar")
def aprobar(id):
    factura = _factura_a_revisar(id)
    if factura.revision != "pendiente" or factura.enviada:
        flash(_("Esta factura no está en revisión."), "warning")
        return _volver(factura)
    factura.revision, factura.revision_comentario = "aprobada", None
    factura.revisado_por_id, factura.revisado_el = current_user.id, ahora()
    registrar("editar", factura, "revisión: aprobada")
    db.session.commit()
    flash(_("Factura %(numero)s aprobada: ya se puede enviar al cliente.", numero=factura.numero), "success")
    return _volver(factura)


@bp.route("/<int:id>/devolver", methods=["POST"])
@requiere_permiso("facturas.revisar")
def devolver(id):
    factura = _factura_a_revisar(id)
    comentario = (request.form.get("comentario") or "").strip()
    if factura.revision != "pendiente" or factura.enviada:
        flash(_("Esta factura no está en revisión."), "warning")
    elif not comentario:
        flash(_("Escribe qué hay que cambiar para devolverla."), "danger")
    else:
        factura.revision, factura.revision_comentario = "cambios", comentario[:2000]
        factura.revisado_por_id, factura.revisado_el = current_user.id, ahora()
        registrar("editar", factura, f"revisión: pide cambios · «{comentario[:200]}»")
        avisos_internos.factura_devuelta(factura, comentario, current_user.nombre, excluir_id=current_user.id)
        db.session.commit()
        flash(_("Factura %(numero)s devuelta con tu comentario.", numero=factura.numero), "success")
    return _volver(factura)


@bp.route("/<int:id>/enviada", methods=["POST"])
@requiere_permiso("facturas.editar")
def marcar_enviada(id):
    """Aina la ha mandado por email: desde ahora el cliente también la ve en la plataforma."""
    factura = db.get_or_404(Factura, id)
    if factura.fase != "por_enviar":
        flash(_("Esta factura todavía no se puede enviar (está en revisión o devuelta) o ya está enviada."), "warning")
    elif not factura.pdf_archivo:
        flash(_("Sube el PDF antes de marcarla como enviada: es lo que verá el cliente."), "warning")
    else:
        factura.enviada_el = ahora()
        registrar("editar", factura, "enviada al cliente")
        db.session.commit()
        flash(_("Factura %(numero)s enviada: el cliente ya la ve.", numero=factura.numero), "success")
    if request.form.get("volver") == "inicio":
        return redirect(url_for("main.inicio"))
    if request.form.get("volver") == "lista":
        return redirect(url_for("facturas.lista", estado="por_enviar"))
    return _volver(factura)
