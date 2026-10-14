"""
Novedades de un pedido: qué secciones de su ficha han cambiado desde la última vez que ESTA
persona lo abrió. Se enseñan como una marca "nuevo" en la cabecera de la sección (ficha) y
como una marca en la fila del pedido (lista).

De dónde sale: de la auditoría, que ya apunta todo lo que le pasa a un pedido (y a sus
facturas) con quién lo hizo y cuándo. Aquí solo se mira lo ocurrido DESPUÉS de la última
visita (tabla vistas_pedido) y hecho por OTRA persona: lo que haces tú no es novedad para ti.

Reglas:
  - La primera vez que alguien abre un pedido no hay novedades (no hay con qué comparar).
  - Al abrir la ficha se apunta la visita: la próxima vez ya no salen las mismas.
  - Los mensajes y el chat interno no entran aquí: ya tienen su contador de no leídos.
  - El cliente solo ve novedades de lo que le interesa: proforma, documentos, facturas e incidencias.
"""
import re
from collections import defaultdict

from flask_babel import lazy_gettext as _l

from app.extensions import db
from app.models import Factura, RegistroAuditoria, VistaPedido, ahora

_CAMBIO_ESTADO = re.compile(r"^(\w+) → (\w+)")

# Estado al que llega el pedido → sección de la ficha a la que afecta
_SECCION_DE_ESTADO = {
    "proforma_enviada": "proforma", "cambios_solicitados": "proforma", "proforma_solicitada": "proforma",
    "en_validacion": "fotos", "validado": "fotos",
    "enviado": "envio",
}

SECCIONES_CLIENTE = {"proforma", "documentos", "facturas", "incidencias"}

# En el orden de la ficha (para el texto de la marca de la lista de pedidos)
NOMBRES_SECCION = {"incidencias": _l("incidencias"), "contenido": _l("contenido"), "lotes": _l("lotes"), "proforma": _l("proforma"), "fotos": _l("fotos"),
                   "documentos": _l("documentos"), "facturas": _l("facturas"), "envio": _l("datos de envío")}


def seccion_de(registro):
    """A qué sección de la ficha afecta una entrada de auditoría de un pedido (None = a ninguna).
    Va por el texto del detalle: si se cambia cómo se registra algo en la auditoría, hay que
    repasarlo aquí (lo comprueba tests/test_novedades.py)."""
    if registro.entidad == "Factura":
        return "facturas"
    detalle = registro.detalle or ""
    if registro.accion == "crear":
        return None
    cambio = _CAMBIO_ESTADO.match(detalle)
    if cambio:
        origen, destino = cambio.groups()
        if destino == "aceptado" and "proforma" in detalle:          # el cliente la ha aceptado
            return "proforma"
        if destino == "en_preparacion" and origen == "en_validacion":  # el FAS lo ha devuelto
            return "fotos"
        return _SECCION_DE_ESTADO.get(destino)
    if "lotes reservados:" in detalle or "reserva de lotes liberada" in detalle:
        return "lotes"
    if detalle.startswith("datos de envío"):
        return "envio"
    if detalle.startswith("documento "):
        return "documentos"
    if detalle.startswith("incidencia "):
        return "incidencias"
    if "foto" in detalle:
        return "fotos"
    return "contenido"            # precios, cantidades, kits o productos añadidos o quitados


def secciones_visibles(usuario) -> set:
    """Las secciones de las que este usuario puede tener novedades (las que ve en la ficha)."""
    if usuario.es_cliente:
        return set(SECCIONES_CLIENTE)
    visibles = {"contenido", "proforma", "documentos", "envio", "incidencias"}
    if usuario.puede("pedidos.ver_lotes"):
        visibles.add("lotes")
    if usuario.puede("pedidos.fotos.ver"):
        visibles.add("fotos")
    if usuario.puede("facturas.ver"):
        visibles.add("facturas")
    return visibles


def novedades_de(usuario, pedidos) -> dict:
    """{pedido_id: {secciones con novedades}} para estos pedidos (los que no tienen, no salen).
    Tres consultas en total, sean los pedidos que sean (para la lista)."""
    ids = [p.id for p in pedidos]
    if not ids:
        return {}
    visto = dict(db.session.execute(
        db.select(VistaPedido.pedido_id, VistaPedido.fecha)
        .where(VistaPedido.usuario_id == usuario.id, VistaPedido.pedido_id.in_(ids))).all())
    if not visto:
        return {}
    desde = min(visto.values())
    de_otros = db.or_(RegistroAuditoria.usuario_id.is_(None), RegistroAuditoria.usuario_id != usuario.id)
    # (registro, id del pedido al que pertenece): los del pedido y los de sus facturas
    filas = db.session.execute(
        db.select(RegistroAuditoria, RegistroAuditoria.entidad_id)
        .where(RegistroAuditoria.entidad == "Pedido", RegistroAuditoria.entidad_id.in_(list(visto)),
               RegistroAuditoria.fecha > desde, de_otros)).all()
    filas += db.session.execute(
        db.select(RegistroAuditoria, Factura.pedido_id)
        .join(Factura, Factura.id == RegistroAuditoria.entidad_id)
        .where(RegistroAuditoria.entidad == "Factura", Factura.pedido_id.in_(list(visto)),
               RegistroAuditoria.fecha > desde, de_otros,
               # el cliente: solo las facturas que ya le hemos enviado
               Factura.enviada_el.isnot(None) if usuario.es_cliente else db.true())).all()
    visibles = secciones_visibles(usuario)
    resultado = defaultdict(set)
    for registro, pedido_id in filas:
        if registro.fecha <= visto[pedido_id]:
            continue
        seccion = seccion_de(registro)
        if seccion in visibles:
            resultado[pedido_id].add(seccion)
    return dict(resultado)


def resumen_novedades(usuario, pedidos) -> dict:
    """Lo mismo que novedades_de, listo para pintar la marca "nuevo" de una fila:
    {pedido_id: {"ancla": primera sección con novedad, "texto": "documentos, lotes"}} (en el
    orden de la ficha). El ancla es a dónde lleva la marca al pulsarla."""
    resultado = {}
    for pedido_id, secciones in novedades_de(usuario, pedidos).items():
        en_orden = [s for s in NOMBRES_SECCION if s in secciones]
        resultado[pedido_id] = {"ancla": en_orden[0], "texto": ", ".join(str(NOMBRES_SECCION[s]) for s in en_orden)}
    return resultado


def marcar_visto(usuario, pedido):
    """Apunta que este usuario ha abierto el pedido ahora (sin commit: lo hace quien llama)."""
    vista = db.session.scalar(db.select(VistaPedido).filter_by(usuario_id=usuario.id, pedido_id=pedido.id))
    if vista is None:
        db.session.add(VistaPedido(usuario_id=usuario.id, pedido_id=pedido.id, fecha=ahora()))
    else:
        vista.fecha = ahora()
