from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app import archivos

from app.auditoria import cambios, registrar
from app.extensions import db
from app.models import (ComponenteKit, Kit, KitPedido, LineaPedido, Lote, MovimientoInventario, PrecioCliente,
                        Producto, ahora)
from app.permisos import requiere_permiso
from app.productos.forms import KitForm, ProductoForm
from app.utils import limpiar_busqueda, ordenar, paginar, patron_like

bp = Blueprint("productos", __name__)

# "categoria" es el nombre del campo en la base de datos; en pantalla se llama "Marca".
# Tiene que coincidir con los nombres de los campos del formulario y del modelo.
CAMPOS = ["referencia", "nombre", "categoria", "codigo_hs", "precio", "iva_pct", "controlar_stock", "stock_minimo", "activo"]


@bp.route("/")
@requiere_permiso("productos.ver")
def lista():
    q = limpiar_busqueda(request.args.get("q"), 100)
    select = db.select(Producto).order_by(Producto.categoria, Producto.nombre)
    if q:
        patron = patron_like(q)
        select = select.where(Producto.nombre.ilike(patron, escape="\\") | Producto.referencia.ilike(patron, escape="\\")
                              | Producto.categoria.ilike(patron, escape="\\"))
    # Pulsando las cabeceras (?orden=…): ver utils.ordenar. Sin eso, por marca y nombre, como siempre.
    select, orden = ordenar(select, {
        "referencia": db.func.lower(Producto.referencia), "nombre": db.func.lower(Producto.nombre),
        "marca": db.func.lower(Producto.categoria), "precio": Producto.precio, "iva": Producto.iva_pct,
        "sds": db.case((Producto.sds_archivo.isnot(None), 0), else_=1),       # con ficha primero
    }, desempate=Producto.id)
    return render_template("productos/lista.html", title=_("Productos"),
                           pagina=paginar(select), q=q, orden=orden)


@bp.route("/nuevo", methods=["GET", "POST"])
@requiere_permiso("productos.editar")
def nuevo():
    form = ProductoForm()
    if form.validate_on_submit():
        producto = Producto()
        form.populate_obj(producto)
        producto.categoria = producto.categoria or None
        _guardar_sds(form, producto)
        db.session.add(producto)
        db.session.flush()
        registrar("crear", producto, producto.referencia + (" · con SDS" if producto.sds_archivo else ""))
        db.session.commit()
        flash(_("Producto creado."), "success")
        return redirect(url_for("productos.lista"))
    return render_template("productos/form.html", title=_("Nuevo producto"), form=form)


@bp.route("/<int:id>/editar", methods=["GET", "POST"])
@requiere_permiso("productos.editar")
def editar(id):
    producto = db.get_or_404(Producto, id)
    form = ProductoForm(obj=producto, producto=producto)
    if request.method == "GET":
        form.iva_pct.data = producto.iva_pct  # para que el desplegable marque el valor
    from app.inventario.reservas import pedidos_abiertos_con_reservas
    if form.is_submitted() and producto.controlar_stock and not form.controlar_stock.data \
            and (reservado := pedidos_abiertos_con_reservas(producto=producto)):
        # Sus lotes reservados se quedarían colgados (el pedido ya no sacaría este producto)
        form.controlar_stock.errors = list(form.controlar_stock.errors) + [
            _("Hay pedidos con lotes de este producto reservados (%(pedidos)s). Envíalos o libera antes la reserva.",
              pedidos=", ".join(reservado[:5]))]
    elif form.validate_on_submit():
        detalle = cambios(producto, form, CAMPOS)
        form.populate_obj(producto)
        producto.categoria = producto.categoria or None
        anterior = _guardar_sds(form, producto)
        if form.sds_leida:
            detalle = "; ".join(x for x in (detalle, f"SDS: {producto.sds_nombre}") if x)
        registrar("editar", producto, detalle)
        db.session.commit()
        archivos.borrar(anterior)          # la SDS sustituida ya no la usa nadie
        flash(_("Producto actualizado."), "success")
        return redirect(url_for("productos.lista"))
    return render_template("productos/form.html", title=_("Editar %(ref)s", ref=producto.referencia), form=form,
                           producto=producto)

def _guardar_sds(form, producto):
    """Si han subido una SDS nueva, la guarda y devuelve el nombre en disco de la anterior
    (se borra cuando el cambio ya está guardado)."""
    if not form.sds_leida:
        return None
    nombre, ext, datos = form.sds_leida
    anterior = producto.sds_archivo
    producto.sds_archivo = archivos.escribir(datos, "sds", ext)
    producto.sds_nombre, producto.sds_tamano, producto.sds_fecha = nombre, len(datos), ahora()
    return anterior


# --------------------------------------------------------------------------- #
# Catálogo para el cliente y descarga de las SDS
# --------------------------------------------------------------------------- #
@bp.route("/catalogo")
@requiere_permiso("productos.catalogo")
def catalogo():
    """Productos y kits activos en una sola lista (se filtra en el navegador), con la SDS
    de cada producto. Precios solo si su empresa tiene activado "ve precios"."""
    from app.catalogo_cliente import kits_para, productos_para
    # Su catálogo (ficha del cliente → «Su catálogo»): todo lo activo o solo lo que tenga marcado
    productos, kits = productos_para(current_user.empresa), kits_para(current_user.empresa)
    ver_precios = current_user.puede("pedidos.ver_importes")
    empresa = current_user.empresa
    precios_kit = {k.id: k.precio_para(empresa) for k in kits} if ver_precios else {}
    marcas = sorted({p.categoria for p in productos if p.categoria}, key=str.lower)
    return render_template("productos/catalogo.html", title=_("Productos"), productos=productos, kits=kits,
                           marcas=marcas, ver_precios=ver_precios, precios_kit=precios_kit)


@bp.route("/<int:id>/sds")
@requiere_permiso("productos.sds")
def descargar_sds(id):
    producto = db.get_or_404(Producto, id)
    # El cliente solo la de productos activos (los que ve en su catálogo)
    if not producto.sds_archivo or (not producto.activo and not current_user.puede("productos.ver")):
        abort(404)
    return archivos.descargar(producto.sds_archivo, producto.sds_nombre or f"SDS_{producto.referencia}.pdf")


def _contar(modelo, **filtro):
    """Cuántas filas de `modelo` cumplen el filtro (p. ej. líneas de pedido de este producto)."""
    return db.session.scalar(db.select(db.func.count()).select_from(modelo).filter_by(**filtro))


@bp.route("/<int:id>/borrar", methods=["POST"])
@requiere_permiso("productos.editar")
def borrar(id):
    """Borra un producto SOLO si no se ha usado nunca. Si ya aparece en pedidos, kits
    o inventario no se borra (esos registros apuntarían a algo que no existe)."""
    producto = db.get_or_404(Producto, id)
    usos = []
    if _contar(LineaPedido, producto_id=id):
        usos.append(_("pedidos"))
    if _contar(ComponenteKit, producto_id=id):
        usos.append(_("kits"))
    if _contar(MovimientoInventario, producto_id=id) or _contar(Lote, producto_id=id):
        usos.append(_("inventario"))
    if usos:
        flash(_("No se puede borrar %(ref)s porque ya se ha usado en: %(usos)s. "
                "Desactívalo en su lugar (desmarca «Activo»).", ref=producto.referencia, usos=", ".join(usos)),
              "warning")
        return redirect(url_for("productos.editar", id=id))
    registrar("borrar", producto, producto.referencia)
    db.session.delete(producto)
    db.session.commit()
    flash(_("Producto %(ref)s borrado.", ref=producto.referencia), "success")
    return redirect(url_for("productos.lista"))

# --------------------------------------------------------------------------- #
# Kits (agrupaciones de productos)
# --------------------------------------------------------------------------- #
@bp.route("/kits")
@requiere_permiso("productos.ver")
def kits():
    """Lista de kits con buscador (también por los productos que lleva: «YK001» saca todos los
    kits con ese índice), ordenable por las cabeceras y paginada. Los inactivos, siempre al final."""
    q = limpiar_busqueda(request.args.get("q"), 100)
    select = db.select(Kit).order_by(Kit.activo.desc(), Kit.nombre)
    if q:
        patron = patron_like(q)
        lleva = Kit.componentes.any(ComponenteKit.producto.has(
            Producto.referencia.ilike(patron, escape="\\") | Producto.nombre.ilike(patron, escape="\\")))
        select = select.where(Kit.referencia.ilike(patron, escape="\\") | Kit.nombre.ilike(patron, escape="\\")
                              | Kit.descripcion.ilike(patron, escape="\\") | lleva)
    n_productos = db.select(db.func.count(ComponenteKit.id)).where(ComponenteKit.kit_id == Kit.id).scalar_subquery()
    select, orden = ordenar(select, {
        "referencia": db.func.lower(Kit.referencia), "nombre": db.func.lower(Kit.nombre),
        "productos": n_productos, "precio": Kit.precio, "iva": Kit.iva_pct,
    }, desempate=Kit.id, antes=(Kit.activo.desc(),))
    return render_template("productos/kits.html", title=_("Kits"), pagina=paginar(select), q=q, orden=orden)


def _guardar_componentes(kit, form):
    """Sustituye la lista de productos del kit por la del formulario. Devuelve un texto
    para la auditoría con lo que ha cambiado."""
    antes = {c.producto_id: c.cantidad for c in kit.componentes}
    orden_antes = [c.producto_id for c in kit.componentes]
    despues = form.productos_del_kit()               # en el orden de las filas del formulario
    posicion = {pid: i for i, pid in enumerate(despues)}
    for c in list(kit.componentes):
        if c.producto_id not in despues:
            kit.componentes.remove(c)
        else:
            c.cantidad, c.orden = despues[c.producto_id], posicion[c.producto_id]
    existentes = {c.producto_id for c in kit.componentes}
    for pid, cant in despues.items():
        if pid not in existentes:
            kit.componentes.append(ComponenteKit(producto_id=pid, cantidad=cant, orden=posicion[pid]))
    cambios = [] if antes == despues else [f"productos: {antes} → {despues}"]
    if [p for p in orden_antes if p in despues] != [p for p in despues if p in orden_antes]:
        cambios.append("orden cambiado")
    return "; ".join(cambios)


@bp.route("/kits/nuevo", methods=["GET", "POST"])
@requiere_permiso("productos.editar")
def nuevo_kit():
    form = KitForm()
    if form.validate_on_submit():
        kit = Kit(referencia=form.referencia.data, nombre=form.nombre.data,
                  descripcion=form.descripcion.data or None, precio=form.precio.data,
                  iva_pct=form.iva_pct.data, activo=form.activo.data,
                  cerrado=form.cerrado.data, stock_minimo=form.stock_minimo.data or 0)
        db.session.add(kit)
        _guardar_componentes(kit, form)
        db.session.flush()
        registrar("crear", kit, f"{kit.referencia} · {len(kit.componentes)} productos")
        db.session.commit()
        flash(_("Kit %(ref)s creado.", ref=kit.referencia), "success")
        return redirect(url_for("productos.kits"))
    return render_template("productos/kit_form.html", title=_("Nuevo kit"), form=form)


@bp.route("/kits/<int:id>/editar", methods=["GET", "POST"])
@requiere_permiso("productos.editar")
def editar_kit(id):
    kit = db.get_or_404(Kit, id)
    if request.method == "GET":
        form = KitForm(obj=kit, kit=kit, formdata=None)
        # rellenar las filas con los productos actuales del kit
        while len(form.componentes) < len(kit.componentes):
            form.componentes.append_entry()
        opciones = form.componentes[0].producto_id.choices
        for fila, c in zip(form.componentes, kit.componentes):
            fila.producto_id.choices = opciones
            fila.producto_id.data, fila.cantidad.data = c.producto_id, c.cantidad
        form.iva_pct.data = kit.iva_pct
    else:
        form = KitForm(kit=kit)
    from app.inventario.stock import pedidos_con_kit_fuera
    pasa_a_montado = form.is_submitted() and kit.cerrado and not form.cerrado.data
    fuera = pedidos_con_kit_fuera(kit) if pasa_a_montado else []
    from app.inventario.reservas import pedidos_abiertos_con_reservas
    cambia_tipo = form.is_submitted() and bool(kit.cerrado) != bool(form.cerrado.data)
    if cambia_tipo and (reservado := pedidos_abiertos_con_reservas(kit=kit)):
        # Cambiaría de qué sale el pedido (del kit o de sus productos): sus reservas no valdrían
        form.cerrado.errors = list(form.cerrado.errors) + [
            _("Hay pedidos con lotes reservados que llevan este kit (%(pedidos)s). Envíalos o libera antes la reserva.",
              pedidos=", ".join(reservado[:5]))]
    elif pasa_a_montado and kit.stock:
        # Si pasara a "montado" con stock propio, ese stock quedaría escondido
        form.cerrado.errors = list(form.cerrado.errors) + [
            _("Este kit tiene %(n)s unidades en el inventario. Para que pase a montado, primero déjalo a 0 "
              "(ábrelo o haz un ajuste en Inventario).", n=kit.stock)]
    elif fuera:
        # Tampoco si hay envíos suyos sin anular: al anularlos, los kits volverían a su lote
        form.cerrado.errors = list(form.cerrado.errors) + [
            _("Hay pedidos enviados con este kit cerrado (%(pedidos)s). Si se anulara su envío, los kits "
              "volverían al inventario del kit: por eso no puede pasar a montado.", pedidos=", ".join(fuera[:5]))]
    elif form.validate_on_submit():
        form.stock_minimo.data = form.stock_minimo.data or 0
        detalle = cambios(kit, form, ["referencia", "nombre", "precio", "iva_pct", "activo", "cerrado", "stock_minimo"])
        kit.referencia, kit.nombre = form.referencia.data, form.nombre.data
        kit.descripcion = form.descripcion.data or None
        kit.precio, kit.iva_pct, kit.activo = form.precio.data, form.iva_pct.data, form.activo.data
        kit.cerrado, kit.stock_minimo = form.cerrado.data, form.stock_minimo.data
        cambio_productos = _guardar_componentes(kit, form)
        registrar("editar", kit, "; ".join(x for x in (detalle, cambio_productos) if x))
        db.session.commit()
        flash(_("Kit actualizado. Los pedidos ya hechos no cambian."), "success")
        return redirect(url_for("productos.kits"))
    return render_template("productos/kit_form.html", title=_("Editar %(ref)s", ref=kit.referencia), form=form,kit=kit)

@bp.route("/kits/<int:id>/borrar", methods=["POST"])
@requiere_permiso("productos.editar")
def borrar_kit(id):
    """Borra un kit SOLO si ningún pedido lo lleva. Sus productos NO se borran;
    sí su composición y los precios especiales de los clientes."""
    kit = db.get_or_404(Kit, id)
    if _contar(MovimientoInventario, kit_id=id) or _contar(Lote, kit_id=id):
        flash(_("No se puede borrar %(ref)s porque ya se ha usado en: %(usos)s. "
                "Desactívalo en su lugar (desmarca «Activo»).", ref=kit.referencia, usos=_("inventario")),
              "warning")
        return redirect(url_for("productos.editar_kit", id=id))
    if _contar(KitPedido, kit_id=id):
        flash(_("No se puede borrar %(ref)s porque ya se ha usado en: %(usos)s. "
                "Desactívalo en su lugar (desmarca «Activo»).", ref=kit.referencia, usos=_("pedidos")),
              "warning")
        return redirect(url_for("productos.editar_kit", id=id))
    registrar("borrar", kit, kit.referencia)
    db.session.execute(db.delete(PrecioCliente).filter_by(kit_id=id))
    db.session.delete(kit)                 # sus componentes se borran con él (cascade)
    db.session.commit()
    flash(_("Kit %(ref)s borrado.", ref=kit.referencia), "success")
    return redirect(url_for("productos.kits"))