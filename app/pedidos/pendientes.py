"""
Pendientes: lo que cada persona TIENE QUE HACER, para el bloque "Pendientes" de la página de
inicio. No es lo mismo que las novedades (app/pedidos/novedades.py):

  - Novedad  = algo ha cambiado desde tu última visita. Se apaga al verlo.
  - Pendiente = hay algo por hacer. No se va hasta que se hace: sale del ESTADO del pedido,
    nadie lo marca a mano.

Qué le sale a cada uno lo deciden sus permisos (app/permisos.py), y siempre dentro de lo que
puede ver (alcance.filtrar_pedidos: el FAS sus clientes, el cliente su empresa):

  Proformas por enviar ............ quien envía proformas (admin, Facturación, FAS)
  Pedidos aceptados sin empezar ... quien prepara (admin, Almacén) y el FAS (para seguirlos)
  Devueltos por el FAS ............ quien sube las fotos (admin, Almacén) y el FAS
  Lotes por asignar ............... quien reserva lotes (admin, Facturación, Almacén, FAS)
  Listos para enviar .............. quien envía (admin, Almacén) y el FAS
  Por facturar .................... quien registra facturas (admin, Facturación)
  Facturas por revisar ............ quien las revisa (admin, FAS: las de sus clientes)
  Facturas devueltas / por enviar . quien registra facturas (admin, Facturación)
  Pendientes de tu validación ..... quien valida (FAS, admin)
  Proformas por responder ......... el cliente
  Enviados, por marcar recibidos .. el cliente
  Mensajes sin leer ............... todos
  Incidencias abiertas ............ quien las resuelve (admin, Facturación, Almacén, FAS: las de sus clientes)

Para añadir un tipo de pendiente: una función _grupo(...) más en pendientes_de().
"""
from flask import url_for
from flask_babel import lazy_gettext as _l, gettext as _, ngettext
from sqlalchemy.orm import selectinload

from app.alcance import filtrar_facturas, filtrar_pedidos
from app.extensions import db
from app.models import Cliente, KitPedido, Pedido
from app.permisos import NOMBRE_FAS

MAXIMO_POR_GRUPO = 6       # en el inicio; el resto, con el enlace "Ver todos"


def _pedidos(*estados):
    """Los pedidos en esos estados que ve el usuario conectado, el más antiguo primero
    (lo que más lleva esperando, arriba)."""
    return db.session.scalars(
        filtrar_pedidos(db.select(Pedido).where(Pedido.estado.in_(estados)))
        .options(selectinload(Pedido.cliente)).order_by(Pedido.fecha, Pedido.id)).all()


def _fila(pedido, detalle="", ancla=""):
    # "pedido": para que el mosaico de Yikon añada qué lleva y cuánto hace que espera
    return {"texto": pedido.referencia_interna or f"#{pedido.id}", "cliente": pedido.cliente.nombre, "pedido": pedido,
            "detalle": detalle, "url": url_for("pedidos.detalle", id=pedido.id) + (f"#{ancla}" if ancla else "")}


# El ORDEN de los grupos (y de sus pestañas): el de la vida de un pedido. Para cambiarlo, se
# mueven las claves de esta lista. Al final, lo que no depende de Yikon y los mensajes del cliente.
ORDEN = ["incidencias", "proformas", "aceptados", "lotes", "preparacion", "validar", "devueltos", "enviar",
         "facturar", "facturas_revisar", "facturas_devueltas", "facturas_enviar", "esperando", "responder", "recibir", "mensajes"]

# El nombre de cada grupo en su pestaña del mosaico (el título completo es más largo)
NOMBRES_CORTOS = {"incidencias": _l("Incidencias"), "proformas": _l("Proformas"), "aceptados": _l("Sin empezar"), "preparacion": _l("En preparación"),
                  "devueltos": _l("Devueltos"),
                  "lotes": _l("Sin lote"), "enviar": _l("Por enviar"), "validar": _l("Por validar"),
                  "facturar": _l("Por facturar"), "facturas_revisar": _l("Facturas por revisar"),
                  "facturas_devueltas": _l("Facturas devueltas"), "facturas_enviar": _l("Facturas por enviar"), "esperando": _l("Esperando al cliente"),
                  "responder": _l("Proformas"), "recibir": _l("Por recibir"), "mensajes": _l("Mensajes")}


def _corto(texto, largo=50):
    linea = " ".join((texto or "").split())
    return linea if len(linea) <= largo else linea[:largo - 1].rstrip() + "…"


def _grupo(clave, titulo, icono, filas, ver_todos=None):
    """Un grupo del bloque. Los vacíos van con total 0: pendientes_de() decide si se enseñan."""
    # "todas": para que el mosaico de Yikon cuente los retrasados de todo el grupo y los suba arriba
    return {"clave": clave, "titulo": titulo, "corto": NOMBRES_CORTOS[clave], "icono": icono, "total": len(filas),
            "filas": filas[:MAXIMO_POR_GRUPO], "todas": filas, "ver_todos": ver_todos}


def _lotes_por_asignar():
    """Pedidos ya comprometidos (proforma enviada o más allá) con unidades sin lote: lo que
    salió "a confirmar" o lo que se creó sin stock. [(pedido, unidades que faltan)]"""
    from app.inventario.stock import unidades_por_articulo
    pedidos = db.session.scalars(
        filtrar_pedidos(db.select(Pedido).where(Pedido.estado.in_(
            ["proforma_enviada", "aceptado", "en_preparacion", "en_validacion", "validado"])))
        .options(selectinload(Pedido.cliente), selectinload(Pedido.reservas), selectinload(Pedido.lineas),
                 selectinload(Pedido.kits).selectinload(KitPedido.kit))
        .order_by(Pedido.fecha, Pedido.id)).all()
    resultado = []
    for p in pedidos:
        faltan = sum(unidades_por_articulo(p).values()) - sum(r.cantidad for r in p.reservas)
        if faltan > 0:
            resultado.append((p, faltan))
    return resultado


def _facturas(fase):
    """Facturas que aún no tiene el cliente, en esa fase (app/facturas/routes.py, FASES), las que
    ve el usuario (FAS: de sus clientes), la más antigua primero."""
    from app.facturas.routes import FASES
    from app.models import Factura
    return db.session.scalars(
        filtrar_facturas(db.select(Factura).where(*FASES[fase]))
        .options(selectinload(Factura.cliente), selectinload(Factura.pedido))
        .order_by(Factura.creado, Factura.id)).all()


def _fila_factura(factura):
    """Una línea de una factura: lleva a su pedido (donde se revisa, se corrige y se envía) o, si no
    tiene pedido, a la lista de facturas. Sin "pedido": el retraso del mosaico va por el estado del pedido."""
    url = (url_for("pedidos.detalle", id=factura.pedido_id) + "#facturas" if factura.pedido_id
           else url_for("facturas.lista", q=factura.numero))
    # "pedido_novedades": para la marca "nuevo" (sus novedades son las de su pedido)
    return {"texto": factura.numero, "cliente": factura.cliente.nombre, "detalle": "", "url": url,
            "pedido_novedades": factura.pedido}


def _mensajes_sin_leer(usuario):
    """Una fila por conversación con mensajes sin leer (del pedido, interna o general)."""
    from app.mensajes import servicio
    filas = []
    for hilo, n in sorted(servicio.no_leidos_por_hilo(usuario).items()):
        tipo, _sep, id_ = hilo.partition("-")
        cuantos = ngettext("%(num)s mensaje", "%(num)s mensajes", n)
        if tipo == "cliente":
            cliente = db.session.get(Cliente, int(id_))
            filas.append({"texto": _("Conversación general"), "cliente": cliente.nombre, "detalle": cuantos,
                          "url": url_for("mensajes.conversacion", cliente_id=cliente.id)})
        else:
            pedido = db.session.get(Pedido, int(id_))
            interno = tipo == "interno"
            filas.append(_fila(pedido, cuantos + (" · " + _("chat interno") if interno else ""),
                               "interno" if interno else "mensajes"))
    return filas


def pendientes_de(usuario, con_vacios=False) -> list:
    """Los grupos de pendientes de este usuario, en el orden en que se hace el trabajo:
    [{"clave", "titulo", "icono", "total", "filas": [{"texto", "cliente", "detalle", "url"}], "ver_todos"}]
    Solo los grupos con algo, salvo con_vacios=True (todos los que le tocan, aunque estén a 0)."""
    puede = usuario.puede
    # El FAS también ve lo que la oficina tiene pendiente con SUS clientes (aceptados, devueltos,
    # lotes, envíos): no lo hace él, pero así sigue cómo van sus pedidos.
    es_fas = usuario.rol == "fas"
    grupos = []
    if puede("pedidos.incidencias.resolver"):
        # Problemas que ha avisado el cliente ("Hay un problema con este pedido"): lo primero, porque
        # el cliente está esperando. Sin reloj de retraso (no va por el estado del pedido).
        from app import incidencias
        grupos.append(_grupo("incidencias", _("Incidencias abiertas"), "fa-exclamation-triangle", [
            {"texto": i.pedido.referencia_interna or f"#{i.pedido.id}", "cliente": i.pedido.cliente.nombre,
             "nota": str(i.motivo_nombre).lower(), "detalle": f"«{_corto(i.texto)}»", "pedido_novedades": i.pedido,
             "url": url_for("pedidos.detalle", id=i.pedido_id) + "#incidencias"}
            for i in incidencias.abiertas()]))
    if puede("pedidos.proforma.enviar"):
        filas = [_fila(p, _("el cliente ha pedido cambios") if p.estado == "cambios_solicitados" else "", "proforma")
                 for p in _pedidos("proforma_solicitada", "cambios_solicitados")]
        grupos.append(_grupo("proformas", _("Proformas por enviar"), "fa-file-signature", filas,
                             url_for("pedidos.lista", estado="proforma_pendiente")))
    if puede("pedidos.preparar") or es_fas:
        grupos.append(_grupo("aceptados", _("Pedidos aceptados sin empezar"), "fa-box-open",
                             [_fila(p) for p in _pedidos("aceptado")], url_for("pedidos.lista", estado="aceptado")))
    if puede("pedidos.fotos.subir") or es_fas:
        # En preparación: empezados y sin enviar a validar. Los devueltos van aparte, en su grupo.
        en_preparacion = _pedidos("en_preparacion")
        grupos.append(_grupo("preparacion", _("En preparación"), "fa-boxes",
                             [_fila(p, "", "fotos") for p in en_preparacion if not p.devuelto],
                             url_for("pedidos.lista", estado="en_preparacion")))
        devueltos = [p for p in en_preparacion if p.devuelto]
        titulo = _("Devueltos por ti, pendientes de corregir") if es_fas else _("Devueltos por %(rol)s", rol=NOMBRE_FAS)
        grupos.append(_grupo("devueltos", titulo, "fa-undo", [
            _fila(p, f"«{p.ultima_revision.comentario}»" if p.ultima_revision and p.ultima_revision.comentario else "", "fotos")
            for p in devueltos]))
    if puede("pedidos.lotes"):
        # (Almacén, solo los ya aceptados: los que ve; Facturación y el FAS, también las proformas enviadas)
        grupos.append(_grupo("lotes", _("Lotes por asignar"), "fa-lock", [
            _fila(p, ngettext("falta %(num)s unidad", "faltan %(num)s unidades", n), "lotes")
            for p, n in _lotes_por_asignar()]))
    if puede("pedidos.enviar") or es_fas:
        grupos.append(_grupo("enviar", _("Listos para enviar"), "fa-truck",
                             [_fila(p) for p in _pedidos("validado")], url_for("pedidos.lista", estado="validado")))
    if puede("facturas.editar"):
        from app.facturas.routes import select_por_facturar
        pedidos = db.session.scalars(select_por_facturar().options(selectinload(Pedido.cliente))).all()
        grupos.append(_grupo("facturar", _("Por facturar"), "fa-file-invoice", [
            dict(_fila(p, "", "facturas"), nota=str(p.estado_nombre).lower()) for p in pedidos],
            url_for("facturas.por_facturar")))
    if puede("facturas.revisar"):
        grupos.append(_grupo("facturas_revisar", _("Facturas por revisar"), "fa-search",
                             [_fila_factura(f) for f in _facturas("en_revision")],
                             url_for("facturas.lista", estado="en_revision")))
    if puede("facturas.editar"):
        grupos.append(_grupo("facturas_devueltas", _("Facturas devueltas"), "fa-undo", [
            dict(_fila_factura(f), nota=_("devuelta por %(nombre)s", nombre=f.revisado_por.nombre) if f.revisado_por else "",
                 detalle=f"«{f.revision_comentario}»" if f.revision_comentario else "")
            for f in _facturas("devueltas")], url_for("facturas.lista", estado="devueltas")))
        grupos.append(_grupo("facturas_enviar", _("Facturas por enviar"), "fa-paper-plane", [
            dict(_fila_factura(f), nota=_("aprobada por %(nombre)s", nombre=f.revisado_por.nombre)
                 if f.revision == "aprobada" and f.revisado_por else _("sin revisión"))
            for f in _facturas("por_enviar")], url_for("facturas.lista", estado="por_enviar")))
    if puede("pedidos.validar"):
        grupos.append(_grupo("validar", _("Pendientes de tu validación"), "fa-camera", [
            _fila(p, ngettext("%(num)s foto", "%(num)s fotos", len(p.fotos)), "fotos") for p in _pedidos("en_validacion")]))
    if usuario.es_cliente and puede("pedidos.proforma.responder"):
        grupos.append(_grupo("responder", _("Proformas por responder"), "fa-file-signature",
                             [_fila(p, "", "proforma") for p in _pedidos("proforma_enviada")]))
    if usuario.es_cliente and puede("pedidos.recibir"):
        grupos.append(_grupo("recibir", _("Enviados: marque como recibido cuando llegue"), "fa-flag-checkered",
                             [_fila(p) for p in _pedidos("enviado")]))
    if not usuario.es_cliente:
        # Lo que no depende de Yikon sino del cliente: que responda a la proforma o confirme la
        # recepción. No es tarea de nadie de la oficina, pero es donde más se atascan los pedidos.
        grupos.append(_grupo("esperando", _("Esperando al cliente"), "fa-hourglass-half", [
            dict(_fila(p, "", "proforma" if p.estado == "proforma_enviada" else ""),
                 nota=_("proforma sin respuesta") if p.estado == "proforma_enviada" else _("envío sin confirmar"))
            for p in _pedidos("proforma_enviada", "enviado")]))
    if puede("mensajes.ver") and usuario.es_cliente:
        # Los mensajes de Yikon no van aquí: tienen su botón flotante en todas las páginas
        grupos.append(_grupo("mensajes", _("Mensajes sin leer"), "fa-comments", _mensajes_sin_leer(usuario),
                             url_for("mensajes.lista")))
    # con_vacios: el mosaico de Yikon enseña siempre todas sus pestañas, también las que están a 0
    grupos.sort(key=lambda g: ORDEN.index(g["clave"]))
    return grupos if con_vacios else [g for g in grupos if g["total"]]
