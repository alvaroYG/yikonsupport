"""
Inicio del CLIENTE (rol "cliente"): lo que viene a mirar, sin tener que navegar.

Es un MOSAICO de casillas de tamaño fijo: no crece aunque haya cientos de pedidos, porque cada
casilla enseña solo los primeros y lleva a su lista completa.

  - pedidos_en_curso(): sus pedidos abiertos (la casilla grande enseña MAXIMO_EN_CURSO);
  - proximo_envio(): el pedido enviado que llega antes;
  - contactos(): quién lleva su cuenta en Yikon (va en la cabecera);
  - documentos_recientes(): las últimas facturas (con PDF) y documentos de sus pedidos;
  - actividad_reciente(): lo último que ha pasado en sus pedidos (sale de la auditoría).

Todo pasa por los filtros de alcance (app/alcance.py): solo sale lo de su empresa.
La plantilla es app/templates/main/_inicio_cliente.html.
"""
from flask import url_for
from flask_babel import gettext as _, lazy_gettext as _l, ngettext
from flask_login import current_user
from sqlalchemy.orm import selectinload

from app.alcance import filtrar_facturas, filtrar_pedidos
from app.extensions import db
from app.models import DocumentoPedido, Factura, Pedido, RegistroAuditoria

# Los pasos que ve el cliente, en orden: (estado tal como lo ve él, nombre, icono).
# El proceso interno (preparación, validación, listo para enviar) es un solo paso: "preparacion".
PASOS = [("proforma", _l("Proforma"), "fa-file-signature"), ("aceptado", _l("Aceptado"), "fa-check"),
         ("preparacion", _l("En preparación"), "fa-box-open"), ("enviado", _l("Enviado"), "fa-truck"),
         ("entregado", _l("Recibido"), "fa-flag-checkered")]
ESTADOS_CERRADOS = ("entregado", "cancelado")
MAXIMO_EN_CURSO = 8        # filas de la casilla "Tus pedidos en curso"
MAXIMO_DOCUMENTOS = 4
MAXIMO_ACTIVIDAD = 4


def paso_actual(pedido) -> int:
    """Posición en PASOS del paso en el que está el pedido (los tres estados de proforma son el 0)."""
    claves = [clave for clave, _nombre, _icono in PASOS]
    estado = pedido.estado_cliente
    return claves.index(estado) if estado in claves else 0


def contenido_corto(pedido) -> str:
    """'3 × PGT-A completo, 1 × Tubos': los kits sin desglosar (el detalle está en el pedido)."""
    partes = [f"{k.cantidad} × {k.kit.nombre}" for k in pedido.kits]
    partes += [f"{l.cantidad} × {l.producto.nombre}" for l in pedido.lineas_sueltas]
    return ", ".join(partes)


def accion_pendiente(pedido, sin_leer: int):
    """Lo que este pedido espera DEL CLIENTE, o None. Una sola cosa por pedido, la más importante:
    {"clave", "texto"}. En el inicio solo se SEÑALA (un punto en su línea); hacerlo, se hace
    dentro del pedido."""
    if pedido.estado == "proforma_enviada":
        return {"clave": "responder", "texto": _("Proforma por responder")}
    if pedido.estado == "enviado":
        return {"clave": "recibir", "texto": _("Pendiente de confirmar la recepción")}
    if sin_leer:
        return {"clave": "mensajes", "texto": ngettext("%(num)s mensaje nuevo", "%(num)s mensajes nuevos", sin_leer)}
    return None


def pedidos_en_curso() -> list:
    """Los pedidos que aún no se han recibido ni cancelado. Arriba, los que esperan algo del
    cliente ("accion"); dentro de cada grupo, primero los más avanzados."""
    from app.mensajes.servicio import no_leidos_por_hilo
    pedidos = db.session.scalars(
        filtrar_pedidos(db.select(Pedido)).where(Pedido.estado.notin_(ESTADOS_CERRADOS))
        .options(selectinload(Pedido.kits))).all()
    sin_leer = no_leidos_por_hilo(current_user, [f"pedido-{p.id}" for p in pedidos])
    filas = [{"pedido": p, "paso": paso_actual(p), "contenido": contenido_corto(p),
              "accion": accion_pendiente(p, sin_leer.get(f"pedido-{p.id}", 0))} for p in pedidos]
    return sorted(filas, key=lambda f: (f["accion"] is None, -f["paso"], -f["pedido"].id))


def contactos() -> list:
    """Las personas de Yikon asignadas a la empresa del cliente (las activas)."""
    empresa = current_user.empresa
    return [u for u in (empresa.logisticos if empresa else []) if u.activo]


def documentos_recientes() -> list:
    """Facturas con PDF y documentos de sus pedidos, mezclados, lo más reciente primero."""
    filas = []
    if current_user.puede("facturas.descargar"):
        facturas = db.session.scalars(
            filtrar_facturas(db.select(Factura)).where(Factura.pdf_archivo.isnot(None))
            .order_by(Factura.fecha_emision.desc()).limit(MAXIMO_DOCUMENTOS)).all()
        filas += [{"icono": "fa-file-invoice-dollar", "nombre": f.numero, "fecha": f.fecha_emision,
                   "pedido": f.pedido, "url": url_for("facturas.descargar_pdf", id=f.id)} for f in facturas]
    if current_user.puede("pedidos.documentos.ver"):
        documentos = db.session.scalars(
            db.select(DocumentoPedido).where(DocumentoPedido.pedido_id.in_(
                filtrar_pedidos(db.select(Pedido.id))))
            .order_by(DocumentoPedido.fecha.desc()).limit(MAXIMO_DOCUMENTOS)).all()
        filas += [{"icono": "fa-file-alt", "nombre": d.nombre_original, "fecha": d.fecha.date(),
                   "pedido": d.pedido,
                   "url": url_for("pedidos.descargar_documento", id=d.pedido_id, doc_id=d.id)} for d in documentos]
    return sorted(filas, key=lambda f: f["fecha"], reverse=True)[:MAXIMO_DOCUMENTOS]


def proximo_envio(en_curso):
    """De los pedidos ya enviados, el que llega antes (los que no tienen fecha, al final). O None."""
    enviados = [f["pedido"] for f in en_curso if f["pedido"].estado == "enviado"]
    if not enviados:
        return None
    return min(enviados, key=lambda p: (p.fecha_entrega_estimada is None, p.fecha_entrega_estimada or p.fecha, p.id))


def _texto_actividad(registro, referencia):
    """La frase para el cliente de una entrada de auditoría, o None si no es cosa suya
    (el proceso interno de preparación, los lotes, los precios...). (icono, texto)"""
    from app.pedidos.novedades import _CAMBIO_ESTADO
    detalle = registro.detalle or ""
    if registro.entidad == "Factura":
        return ("fa-file-invoice-dollar", _("Nueva factura en %(ref)s", ref=referencia)) if registro.accion == "crear" else None
    if detalle.startswith("documento adjuntado"):
        return "fa-paperclip", _("Documento nuevo en %(ref)s", ref=referencia)
    cambio = _CAMBIO_ESTADO.match(detalle)
    if not cambio:
        return None
    origen, destino = cambio.groups()
    if destino == "proforma_enviada":
        return "fa-file-signature", _("Tienes la proforma de %(ref)s", ref=referencia)
    if destino == "en_preparacion" and origen == "aceptado":
        return "fa-box-open", _("%(ref)s ha entrado en preparación", ref=referencia)
    if destino == "enviado":
        return "fa-truck", _("%(ref)s se ha enviado", ref=referencia)
    if destino == "cancelado":
        return "fa-times", _("%(ref)s se ha cancelado", ref=referencia)
    return None


def actividad_reciente() -> list:
    """Lo último que ha pasado en sus pedidos, hecho por OTROS (lo suyo no es novedad para él):
    [{"icono", "texto", "fecha", "url"}], lo más reciente primero. Sale de la auditoría."""
    pedidos = {p.id: p for p in db.session.scalars(filtrar_pedidos(db.select(Pedido)))}
    if not pedidos:
        return []
    de_otros = db.or_(RegistroAuditoria.usuario_id.is_(None), RegistroAuditoria.usuario_id != current_user.id)
    filas = db.session.execute(
        db.select(RegistroAuditoria, RegistroAuditoria.entidad_id)
        .where(RegistroAuditoria.entidad == "Pedido", RegistroAuditoria.entidad_id.in_(list(pedidos)), de_otros)
        .order_by(RegistroAuditoria.id.desc()).limit(60)).all()
    filas += db.session.execute(
        db.select(RegistroAuditoria, Factura.pedido_id)
        .join(Factura, Factura.id == RegistroAuditoria.entidad_id)
        .where(RegistroAuditoria.entidad == "Factura", Factura.pedido_id.in_(list(pedidos)), de_otros,
               Factura.enviada_el.isnot(None))                     # solo las que ya le hemos enviado
        .order_by(RegistroAuditoria.id.desc()).limit(20)).all()
    resultado = []
    for registro, pedido_id in sorted(filas, key=lambda f: f[0].id, reverse=True):
        pedido = pedidos[pedido_id]
        frase = _texto_actividad(registro, pedido.referencia_interna or f"#{pedido.id}")
        if frase:
            resultado.append({"icono": frase[0], "texto": frase[1], "fecha": registro.fecha,
                              "url": url_for("pedidos.detalle", id=pedido.id)})
        if len(resultado) == MAXIMO_ACTIVIDAD:
            break
    return resultado
