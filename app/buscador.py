"""
Buscador global (la caja de la barra superior).

Busca a la vez en todo lo que el usuario PUEDE VER: pedidos, clientes, tickets, lotes,
productos y kits, facturas, documentos internos y usuarios. Cada grupo:
  1) solo aparece si el usuario tiene el permiso de esa sección (User.puede), y
  2) pasa por el mismo filtro de alcance que su lista (filtrar_pedidos, filtrar_clientes,
     filtrar_facturas, filtrar_tickets...): el FAS solo encuentra lo de sus clientes y el
     cliente solo lo de su empresa. Aquí NO se decide quién ve qué: se reutiliza lo que hay.

buscar() devuelve los grupos con resultados; la página (/buscar) y el desplegable de
sugerencias (/buscar/sugerencias) pintan lo mismo con distinto límite.
Para añadir un tipo nuevo: una función _algo(q, limite) y una línea en BUSCADORES.
"""
from flask import url_for
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy import or_

from app.alcance import filtrar_clientes, filtrar_facturas, filtrar_pedidos
from app.extensions import db
from app.utils import es_entero, limpiar_busqueda, patron_like
from app.models import (Cliente, DocumentoInterno, Factura, Kit, KitPedido, LineaPedido, Pedido, Producto, Ticket,
                        User, VersionDocumento)

MIN_LETRAS = 2       # con menos no se busca (saldría media base de datos)
MAX_TEXTO = 80


def _contiene(q, *columnas):
    patron = patron_like(q)
    return or_(*[c.ilike(patron, escape="\\") for c in columnas])


def _grupo(clave, titulo, icono, select, limite, fila, url_todos=None, contar=None):
    """Ejecuta la consulta (ya filtrada por alcance) y devuelve el grupo, o None si no hay nada."""
    total = db.session.scalar(db.select(db.func.count()).select_from(select.order_by(None).subquery()))
    if not total:
        return None
    objetos = db.session.scalars(select.limit(limite)).all()
    return {"clave": clave, "titulo": titulo, "icono": icono, "total": total,
            "resultados": [fila(o) for o in objetos], "url_todos": url_todos}


def _pedidos(q, limite):
    if not current_user.puede("pedidos.ver"):
        return None
    condicion = _contiene(q, Pedido.referencia_interna, Pedido.referencia, Pedido.numero_seguimiento)
    if es_entero(q.lstrip("#")):                      # "#12" o "12": también por número interno
        condicion = or_(condicion, Pedido.id == int(q.lstrip("#")[:9]))
    select = filtrar_pedidos(db.select(Pedido)).where(condicion).order_by(Pedido.fecha.desc(), Pedido.id.desc())
    es_cliente = current_user.es_cliente
    return _grupo("pedidos", _("Pedidos"), "fa-clipboard-list", select, limite, lambda p: {
        "titulo": p.referencia_interna or f"#{p.id}",
        "subtitulo": " · ".join(filter(None, [None if es_cliente else p.cliente.nombre,
                                              _("su ref. %(ref)s", ref=p.referencia) if p.referencia else None,
                                              p.fecha.strftime("%d/%m/%Y")])),
        "insignia": str(p.estado_nombre_para(current_user)),
        "url": url_for("pedidos.detalle", id=p.id)}, url_for("pedidos.lista", q=q))


def pedidos_que_contienen(q):
    """Condición SQL: pedidos que llevan un kit o un producto cuyo nombre o referencia contiene q.
    La usan este buscador y el filtro ?contiene= de la lista de pedidos (el "ver todos")."""
    return or_(Pedido.kits.any(KitPedido.kit.has(_contiene(q, Kit.nombre, Kit.referencia))),
               Pedido.lineas.any(LineaPedido.producto.has(_contiene(q, Producto.nombre, Producto.referencia))))


def _pedidos_con_producto(q, limite):
    """Pedidos por lo que LLEVAN: buscar "PGT-A" saca los pedidos con ese kit o producto.
    El subtítulo dice qué es lo que coincide y cuántas unidades, para que se entienda por qué sale."""
    if not current_user.puede("pedidos.ver"):
        return None
    select = filtrar_pedidos(db.select(Pedido)).where(pedidos_que_contienen(q)) \
        .order_by(Pedido.fecha.desc(), Pedido.id.desc())
    es_cliente, texto = current_user.es_cliente, q.lower()

    def coincide(*campos):
        return any(texto in (c or "").lower() for c in campos)

    def lleva(p):
        """"2 × PGT-A completo" (kits primero). Los productos, cada uno una vez y solo si no van
        dentro de un kit que ya sale: "PGT-A completo" lleva el "Kit PGT-A 24", no hace falta repetirlo."""
        kits = [kp for kp in p.kits if coincide(kp.kit.nombre, kp.kit.referencia)]
        partes = [f"{kp.cantidad} × {kp.kit.nombre}" for kp in kits]
        unidades = {}
        for linea in p.lineas:
            if linea.kit_pedido in kits:
                continue
            if coincide(linea.producto.nombre, linea.producto.referencia):
                unidades[linea.producto.nombre] = unidades.get(linea.producto.nombre, 0) + linea.cantidad
        partes += [f"{n} × {nombre}" for nombre, n in unidades.items()]
        return ", ".join(partes[:3]) + ("…" if len(partes) > 3 else "")

    return _grupo("pedidos_producto", _("Pedidos con este producto"), "fa-box-open", select, limite, lambda p: {
        "titulo": p.referencia_interna or f"#{p.id}",
        "subtitulo": " · ".join(filter(None, [lleva(p), None if es_cliente else p.cliente.nombre,
                                              p.fecha.strftime("%d/%m/%Y")])),
        "insignia": str(p.estado_nombre_para(current_user)),
        "url": url_for("pedidos.detalle", id=p.id)}, url_for("pedidos.lista", contiene=q))


def _clientes(q, limite):
    if not current_user.puede("clientes.ver"):
        return None
    select = filtrar_clientes(db.select(Cliente)).where(_contiene(
        q, Cliente.nombre, Cliente.razon_social, Cliente.cif, Cliente.ciudad, Cliente.persona_contacto,
        Cliente.email, Cliente.prefijo)).order_by(Cliente.activo.desc(), Cliente.nombre)
    return _grupo("clientes", _("Clientes"), "fa-building", select, limite, lambda c: {
        "titulo": c.nombre, "subtitulo": " · ".join(filter(None, [c.cif, c.ciudad, c.persona_contacto])),
        "insignia": None if c.activo else _("inactivo"),
        "url": url_for("clientes.detalle", id=c.id)}, url_for("clientes.lista", q=q, estado="todos"))


def _tickets(q, limite):
    if not current_user.puede("soporte.ver"):
        return None
    from app.soporte.servicio import filtrar_tickets
    select = filtrar_tickets(db.select(Ticket)).where(_contiene(q, Ticket.numero, Ticket.asunto, Ticket.referencia)) \
        .order_by(Ticket.actualizado.desc())
    es_cliente = current_user.es_cliente
    return _grupo("tickets", _("Tickets ChromGo"), "fa-life-ring", select, limite, lambda t: {
        "titulo": f"{t.numero} · {t.asunto}",
        "subtitulo": " · ".join(filter(None, [None if es_cliente else t.cliente.nombre, t.referencia])),
        "insignia": str(t.estado_nombre),
        "url": url_for("soporte.detalle", id=t.id)}, url_for("soporte.lista", q=q, estado="todos"))


def _lotes(q, limite):
    """Códigos de lote (cada código una vez): llevan a "¿Dónde está este lote?"."""
    if not current_user.puede("pedidos.ver_lotes"):
        return None
    from app.inventario.rastreo import rastrear
    rastros, _clientes_, _hay_mas = rastrear(q)        # ya aplica el alcance (el FAS: solo lo enviado a sus clientes)
    if not rastros:
        return None
    por_codigo = {}
    for r in rastros:
        por_codigo.setdefault(r["lote"].codigo, []).append(r)
    resultados = [{
        "titulo": codigo,
        "subtitulo": ", ".join(sorted({r["lote"].articulo.nombre for r in rs}))[:120],
        "insignia": _("%(n)s enviadas", n=sum(r["enviadas"] for r in rs)) if any(r["enviadas"] for r in rs) else None,
        "url": url_for("inventario.rastrear_lote", q=codigo)} for codigo, rs in por_codigo.items()]
    return {"clave": "lotes", "titulo": _("Lotes"), "icono": "fa-barcode", "total": len(resultados),
            "resultados": resultados[:limite], "url_todos": url_for("inventario.rastrear_lote", q=q)}


def _productos(q, limite):
    if current_user.puede("productos.ver"):
        editar = current_user.puede("productos.editar")
        select = db.select(Producto).where(_contiene(q, Producto.referencia, Producto.nombre, Producto.categoria)) \
            .order_by(Producto.activo.desc(), Producto.nombre)
        return _grupo("productos", _("Productos"), "fa-box", select, limite, lambda p: {
            "titulo": p.nombre, "subtitulo": " · ".join(filter(None, [p.referencia, p.categoria])),
            "insignia": None if p.activo else _("inactivo"),
            "url": url_for("productos.editar", id=p.id) if editar else url_for("productos.lista", q=p.referencia)},
            url_for("productos.lista", q=q))
    if current_user.puede("productos.catalogo"):       # el cliente: solo lo activo, y va a su catálogo
        select = db.select(Producto).filter_by(activo=True).where(_contiene(q, Producto.referencia, Producto.nombre)) \
            .order_by(Producto.nombre)
        return _grupo("productos", _("Productos"), "fa-box", select, limite, lambda p: {
            "titulo": p.nombre, "subtitulo": p.referencia, "insignia": None,
            "url": url_for("productos.catalogo")}, url_for("productos.catalogo"))
    return None


def _kits(q, limite):
    if not current_user.puede("productos.ver"):
        return None
    editar = current_user.puede("productos.editar")
    select = db.select(Kit).where(_contiene(q, Kit.referencia, Kit.nombre)).order_by(Kit.activo.desc(), Kit.nombre)
    return _grupo("kits", _("Kits"), "fa-cubes", select, limite, lambda k: {
        "titulo": k.nombre, "subtitulo": k.referencia, "insignia": None if k.activo else _("inactivo"),
        "url": url_for("productos.editar_kit", id=k.id) if editar else url_for("productos.kits")},
        url_for("productos.kits"))


def _facturas(q, limite):
    if current_user.puede("facturas.ver"):
        destino = lambda f: url_for("facturas.lista", q=f.numero)        # noqa: E731
        todos = url_for("facturas.lista", q=q)
    elif current_user.puede("facturas.ver_propias"):
        destino = lambda f: url_for("facturas.mias")                     # noqa: E731
        todos = url_for("facturas.mias")
    else:
        return None
    select = filtrar_facturas(db.select(Factura)).where(_contiene(q, Factura.numero)) \
        .order_by(Factura.fecha_emision.desc(), Factura.id.desc())
    es_cliente = current_user.es_cliente
    return _grupo("facturas", _("Facturas"), "fa-file-invoice-dollar", select, limite, lambda f: {
        "titulo": f.numero,
        "subtitulo": " · ".join(filter(None, [None if es_cliente else f.cliente.nombre,
                                              f.fecha_emision.strftime("%d/%m/%Y") if f.fecha_emision else None])),
        "insignia": _("vencida") if f.esta_vencida else None, "url": destino(f)}, todos)


def _documentos(q, limite):
    if not current_user.puede("documentos.ver"):
        return None
    select = db.select(DocumentoInterno).where(or_(
        _contiene(q, DocumentoInterno.titulo, DocumentoInterno.descripcion),
        DocumentoInterno.versiones.any(VersionDocumento.nombre_original.ilike(patron_like(q), escape="\\")))).order_by(DocumentoInterno.titulo)
    return _grupo("documentos", _("Documentos internos"), "fa-folder-open", select, limite, lambda d: {
        "titulo": d.titulo, "subtitulo": str(d.categoria_nombre),
        "insignia": d.vigente.extension.upper() if d.vigente else None,
        "url": url_for("documentos.detalle", id=d.id)}, url_for("documentos.lista", q=q))


def _usuarios(q, limite):
    if not current_user.puede("usuarios.gestionar"):
        return None
    select = db.select(User).where(_contiene(q, User.nombre, User.email)).order_by(User.activo.desc(), User.nombre)
    return _grupo("usuarios", _("Usuarios"), "fa-users-cog", select, limite, lambda u: {
        "titulo": u.nombre, "subtitulo": f"{u.email} · {u.rol_nombre}",
        "insignia": None if u.activo else _("desactivado"),
        "url": url_for("admin.editar_usuario", id=u.id)}, url_for("admin.usuarios", q=q))


# El orden en que salen los grupos
BUSCADORES = [_pedidos, _pedidos_con_producto, _clientes, _tickets, _lotes, _kits, _productos, _facturas, _documentos,
              _usuarios]


def limpiar(texto):
    return limpiar_busqueda(texto, MAX_TEXTO)


def buscar(q, limite=8):
    """[grupo, ...] con resultados para este usuario. Lista vacía si no hay o si q es muy corto."""
    q = limpiar(q)
    if len(q) < MIN_LETRAS:
        return []
    return [g for g in (b(q, limite) for b in BUSCADORES) if g]
