"""
Catálogo propio de cada cliente (ficha del cliente → «Su catálogo»).

  - Dos modos: TODO el catálogo (lo de siempre: todo lo activo, también lo que se dé de alta después)
    o SOLO lo marcado (Cliente.catalogo_propio): una lista de kits y otra de productos.
  - Los kits deciden qué puede PEDIR el cliente (ventana «Hacer un pedido» y su validación).
    Los productos deciden qué ve en su página de Productos (con la SDS). Los productos de sus kits
    no hace falta marcarlos para poder pedir el kit.
  - Yikon no tiene límite: al hacer un pedido en nombre del cliente puede añadir cualquier cosa.
  - Quitar algo no toca los pedidos hechos. Si tiene una proforma abierta con un kit que se quita,
    se avisa al guardar.
Lo cambian admin y su Soporte de cliente (permiso "clientes.catalogo"); queda en la auditoría.
"""
from app.extensions import db
from app.models import ESTADOS_PROFORMA, Kit, KitPedido, Pedido, Producto


def kits_permitidos(cliente):
    """ids de los kits que puede pedir, o None si puede pedir todo lo activo."""
    if cliente is None or not cliente.catalogo_propio:
        return None
    return {k.id for k in cliente.kits_catalogo}


def kits_para(cliente):
    """Los kits activos que puede pedir este cliente, por nombre."""
    select = db.select(Kit).filter_by(activo=True).order_by(Kit.nombre)
    permitidos = kits_permitidos(cliente)
    if permitidos is not None:
        select = select.where(Kit.id.in_(permitidos or [0]))
    return db.session.scalars(select).all()


def productos_para(cliente):
    """Los productos activos que ve este cliente en su página de Productos, por nombre."""
    select = db.select(Producto).filter_by(activo=True).order_by(Producto.nombre)
    if cliente is not None and cliente.catalogo_propio:
        select = select.where(Producto.id.in_([p.id for p in cliente.productos_catalogo] or [0]))
    return db.session.scalars(select).all()


def guardar(cliente, propio, kit_ids, producto_ids):
    """Guarda (sin commit). Devuelve (texto para la auditoría o "", [pedidos con proforma abierta
    que llevan un kit que se ha quitado])."""
    antes_propio = cliente.catalogo_propio
    antes_kits = {k.id for k in cliente.kits_catalogo}
    antes_prod = {p.id for p in cliente.productos_catalogo}
    kits = db.session.scalars(db.select(Kit).where(Kit.id.in_(kit_ids or [0]))).all()
    productos = db.session.scalars(db.select(Producto).where(Producto.id.in_(producto_ids or [0]))).all()
    cliente.catalogo_propio = bool(propio)
    if propio:                                   # en "todo el catálogo" la lista se conserva por si vuelve
        cliente.kits_catalogo, cliente.productos_catalogo = kits, productos
    nuevos_kits = {k.id for k in cliente.kits_catalogo}
    partes = []
    if antes_propio != cliente.catalogo_propio:
        partes.append("catálogo: " + ("solo lo marcado" if cliente.catalogo_propio else "todo"))
    if cliente.catalogo_propio:
        quitados_k = sorted(k.referencia for k in db.session.scalars(
            db.select(Kit).where(Kit.id.in_((antes_kits - nuevos_kits) or [0]))))
        puestos_k = sorted(k.referencia for k in kits if k.id not in antes_kits)
        nuevos_prod = {p.id for p in productos}
        if puestos_k:
            partes.append("kits +" + ", +".join(puestos_k))
        if quitados_k:
            partes.append("kits −" + ", −".join(quitados_k))
        if nuevos_prod != antes_prod:
            partes.append(f"productos: {len(nuevos_prod)}")
    # Proformas abiertas con kits que ya no puede pedir
    afectados = []
    permitidos = kits_permitidos(cliente)
    if permitidos is not None:
        afectados = db.session.scalars(
            db.select(Pedido).where(Pedido.cliente_id == cliente.id, Pedido.estado.in_(ESTADOS_PROFORMA),
                                    Pedido.kits.any(KitPedido.kit_id.notin_(permitidos or [0])))
            .order_by(Pedido.id)).all()
    return "; ".join(partes), afectados


def tabla(cliente):
    """Para la ficha: los kits y productos activos con si están marcados y datos para decidir."""
    from app.models import ComponenteKit
    marcados_k = {k.id for k in cliente.kits_catalogo}
    marcados_p = {p.id for p in cliente.productos_catalogo}
    ultimos = dict(db.session.execute(
        db.select(KitPedido.kit_id, db.func.max(Pedido.fecha)).join(Pedido)
        .where(Pedido.cliente_id == cliente.id, Pedido.estado != "cancelado").group_by(KitPedido.kit_id)).all())
    kits = db.session.scalars(db.select(Kit).filter_by(activo=True).order_by(Kit.nombre)).all()
    en_kits = {}
    for c in db.session.scalars(db.select(ComponenteKit).where(ComponenteKit.kit_id.in_(marcados_k or [0]))):
        en_kits[c.producto_id] = en_kits.get(c.producto_id, 0) + 1
    productos = db.session.scalars(db.select(Producto).filter_by(activo=True).order_by(Producto.nombre)).all()
    return ([{"kit": k, "marcado": k.id in marcados_k, "ultimo": ultimos.get(k.id),
              "precio": k.precio_para(cliente)} for k in kits],
            [{"producto": p, "marcado": p.id in marcados_p, "en_kits": en_kits.get(p.id, 0)} for p in productos])
