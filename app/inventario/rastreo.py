"""
Trazabilidad: "¿dónde está este lote?"

Dado un código de lote (o parte), dice qué queda en la oficina y a qué clientes y pedidos
se envió. Sirve, sobre todo, cuando un fabricante retira un lote: en un minuto se sabe a
quién avisar.

Se calcula con los movimientos de inventario (lo que REALMENTE salió con cada pedido, neto:
si un envío se anuló, no cuenta). Quién ve qué:
  - admin y Logística: todo (stock de la oficina y todos los envíos);
  - el FAS: solo los envíos a SUS clientes, y solo los lotes que les llegaron (no ve el
    inventario de la oficina).
"""
from flask_login import current_user

from app.alcance import filtrar_pedidos
from app.extensions import db
from app.models import Lote, MovimientoInventario, Pedido
from app.utils import limpiar_busqueda, patron_like

MAX_LOTES = 30      # lotes que se enseñan por búsqueda (si salen más, hay que afinar el código)


def _coincide(texto):
    return Lote.codigo.ilike(patron_like(texto), escape="\\")


def _orden(texto):
    """Primero el código exacto; luego alfabético, y a igual código el kit antes que sus productos."""
    return lambda l: (l.codigo.lower() != texto.lower(), l.codigo.lower(), l.kit_id is None, l.id)


def buscar_lotes(texto):
    """Lotes cuyo código contiene el texto; primero los que coinciden exactamente."""
    texto = limpiar_busqueda(texto, 60)
    if not texto:
        return []
    lotes = db.session.scalars(db.select(Lote).where(_coincide(texto)).order_by(Lote.codigo, Lote.id).limit(200)).all()
    return sorted(lotes, key=_orden(texto))


def _envios(texto):
    """Los envíos (netos de anulaciones) de TODOS los lotes que coinciden, a pedidos que el usuario
    puede ver, en dos consultas: {lote_id: [{"pedido", "unidades", "fecha"}]}, lo más reciente primero."""
    filas = db.session.execute(
        db.select(MovimientoInventario.lote_id, MovimientoInventario.pedido_id,
                  db.func.sum(MovimientoInventario.cantidad), db.func.max(MovimientoInventario.fecha))
        .join(Lote, Lote.id == MovimientoInventario.lote_id)
        .where(_coincide(texto), MovimientoInventario.pedido_id.is_not(None))
        # el alcance va en la propia consulta: el FAS solo cuenta los pedidos de sus clientes
        .where(MovimientoInventario.pedido_id.in_(filtrar_pedidos(db.select(Pedido.id))))
        .group_by(MovimientoInventario.lote_id, MovimientoInventario.pedido_id)
        .having(db.func.sum(MovimientoInventario.cantidad) < 0)).all()
    pedidos = {p.id: p for p in db.session.scalars(
        db.select(Pedido).where(Pedido.id.in_({f[1] for f in filas})))} if filas else {}
    por_lote = {}
    for lote_id, pedido_id, neto, fecha in filas:
        por_lote.setdefault(lote_id, []).append({"pedido": pedidos[pedido_id], "unidades": -neto, "fecha": fecha})
    for envios in por_lote.values():
        envios.sort(key=lambda e: e["fecha"], reverse=True)
    return por_lote


def envios_de(lote):
    """A qué pedidos (de los que el usuario puede ver) fue este lote: [{"pedido", "unidades", "fecha"}]."""
    return _envios(lote.codigo).get(lote.id, [])


def _cifras_oficina(ids):
    """{lote_id: {tipo de movimiento: unidades}} en una consulta (solo para quien ve el inventario)."""
    cifras = {}
    if ids:
        for lote_id, tipo, total in db.session.execute(
                db.select(MovimientoInventario.lote_id, MovimientoInventario.tipo, db.func.sum(MovimientoInventario.cantidad))
                .where(MovimientoInventario.lote_id.in_(ids))
                .group_by(MovimientoInventario.lote_id, MovimientoInventario.tipo)):
            cifras.setdefault(lote_id, {})[tipo] = total
    return cifras


def _rastro(lote, envios, por_tipo):
    datos = {"lote": lote, "envios": envios, "enviadas": sum(e["unidades"] for e in envios)}
    if por_tipo is not None:
        datos.update(entradas=por_tipo.get("entrada", 0), ajustes=por_tipo.get("ajuste", 0),
                     abiertos=por_tipo.get("apertura_kit", 0), en_oficina=sum(por_tipo.values()))
    return datos


def rastro(lote, con_oficina):
    """Todo lo de UN lote: {"lote", "envios", "enviadas", y si con_oficina: "entradas", "ajustes",
    "abiertos", "en_oficina"}. con_oficina=False para quien no ve el inventario (FAS)."""
    return _rastro(lote, envios_de(lote), _cifras_oficina([lote.id]).get(lote.id, {}) if con_oficina else None)


def rastrear(texto):
    """(rastros, clientes, hay_mas) para la página, el Excel y el buscador global.
    clientes = [{"cliente", "unidades", "pedidos"}] con todos los clientes a los que llegó
    alguno de los lotes encontrados (para avisarles), el que más unidades recibió primero."""
    texto = limpiar_busqueda(texto, 60)
    if not texto:
        return [], [], False
    con_oficina = current_user.puede("inventario.ver")
    por_lote = _envios(texto)
    if con_oficina:
        lotes = buscar_lotes(texto)
    else:
        # El FAS: solo los lotes que llegaron a sus clientes. Se parte de SUS envíos (y no de
        # "los 200 primeros lotes"), para que nunca se le escape uno suyo entre muchos parecidos.
        lotes = sorted(db.session.scalars(db.select(Lote).where(Lote.id.in_(por_lote))).all(), key=_orden(texto)) \
            if por_lote else []
    hay_mas = len(lotes) > MAX_LOTES
    lotes = lotes[:MAX_LOTES]
    cifras = _cifras_oficina([l.id for l in lotes]) if con_oficina else {}
    rastros = [_rastro(l, por_lote.get(l.id, []), cifras.get(l.id, {}) if con_oficina else None) for l in lotes]
    por_cliente = {}
    for r in rastros:
        for e in r["envios"]:
            c = por_cliente.setdefault(e["pedido"].cliente_id, {"cliente": e["pedido"].cliente, "unidades": 0, "pedidos": []})
            c["unidades"] += e["unidades"]
            if e["pedido"] not in c["pedidos"]:
                c["pedidos"].append(e["pedido"])
    clientes = sorted(por_cliente.values(), key=lambda c: (-c["unidades"], c["cliente"].nombre))
    return rastros, clientes, hay_mas
