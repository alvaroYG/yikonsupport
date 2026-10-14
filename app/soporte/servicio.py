"""
Soporte ChromGo: toda la lógica de los tickets (quién ve qué, crear, responder, cambiar estado,
"sin leer" y avisos por email). Las vistas (routes.py) solo llaman a estas funciones.

QUIÉN VE QUÉ (la regla importante, y vive solo aquí):
  - El equipo de soporte (permiso soporte.gestionar: admin y "Soporte ChromGo") ve todos los
    tickets y también las NOTAS INTERNAS de cada ticket.
  - El FAS ve los tickets de SUS clientes (los que tiene asignados) y sus notas internas, en
    las que puede escribir; responde al cliente, pero no cambia estado, prioridad ni asignación.
  - Un usuario de empresa cliente ve solo los tickets de SU empresa, y nunca las notas internas.
  - El resto: ninguno.

Los tickets van aparte de los Mensajes de pedidos (tablas propias): así nada de soporte
aparece en la página de Mensajes ni se mezcla con ella.
"""
from datetime import date

from flask import url_for
from flask_babel import force_locale, gettext as _
from flask_login import current_user
from sqlalchemy import case, false
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload

from app import archivos
from app.correo import enviar_tras_guardar
from app.extensions import db
from app.models import (ESTADOS_TICKET, PRIORIDADES_TICKET, AdjuntoTicket, Cliente, LecturaTicket, Ticket,
                        TicketMensaje, User, ahora)
from app.pedidos.documentos import EXTENSIONES_PERMITIDAS

MAX_TEXTO = 10000
MAX_ADJUNTOS = 5
# Capturas de pantalla, PDF, Excel/CSV... y además registros (.log) y exportaciones (.json, .tsv)
EXTENSIONES_ADJUNTO = EXTENSIONES_PERMITIDAS | {"log", "json", "tsv", "gif", "webp"}
ORDEN_PRIORIDAD = {"urgente": 0, "alta": 1, "normal": 2, "baja": 3}


# --------------------------------------------------------------------------- #
# Quién ve qué
# --------------------------------------------------------------------------- #
def es_equipo(usuario) -> bool:
    return usuario.puede("soporte.gestionar")


def ve_notas(usuario) -> bool:
    """¿Ve (y escribe) las notas internas? El equipo de soporte y el FAS; el cliente nunca."""
    return usuario.puede("soporte.notas") and not usuario.es_cliente


def filtrar_tickets(select, usuario=None):
    u = usuario or current_user
    if es_equipo(u):
        return select
    if u.rol == "fas" and u.puede("soporte.ver"):
        # los de los clientes que tiene asignados (la misma regla que en pedidos y mensajes)
        return select.where(Ticket.cliente.has(Cliente.logisticos.any(User.id == u.id)))
    if u.es_cliente and u.empresa is not None and u.empresa.activo and u.puede("soporte.ver"):
        return select.where(Ticket.cliente_id == u.cliente_id)
    return select.where(false())


def ticket_o_404(id):
    from flask import abort
    ticket = db.session.scalar(filtrar_tickets(db.select(Ticket).filter_by(id=id)))
    if ticket is None:
        abort(404)            # 404 y no 403: no confirmamos que exista
    return ticket


def mensajes_de(ticket, usuario, interno=False, despues=0):
    """Los mensajes que este usuario puede ver: interno=True, las notas internas (solo el equipo);
    interno=False, la conversación con el cliente."""
    if interno and not ve_notas(usuario):
        return []
    return db.session.scalars(
        db.select(TicketMensaje).filter_by(ticket_id=ticket.id, interno=interno).where(TicketMensaje.id > despues)
        .options(selectinload(TicketMensaje.autor), selectinload(TicketMensaje.adjuntos))
        .order_by(TicketMensaje.id)).all()


def usuarios_equipo():
    """A quién se puede asignar un ticket: admin y Soporte ChromGo activos."""
    return db.session.scalars(db.select(User).where(User.activo.is_(True), User.rol.in_(["admin", "soporte"]))
                              .order_by(User.nombre)).all()


def clientes_para_ticket():
    """Empresas para las que el equipo puede abrir un ticket."""
    return db.session.scalars(db.select(Cliente).filter_by(activo=True)
                              .order_by(Cliente.nombre)).all()


# --------------------------------------------------------------------------- #
# Sin leer
# --------------------------------------------------------------------------- #
def _pendientes(usuario, *columnas):
    """Mensajes de OTRAS personas posteriores a lo último que este usuario vio de ese ticket.
    El cliente no cuenta las notas internas (ni las ve)."""
    lectura = aliased(LecturaTicket)
    select = (db.select(*columnas).select_from(TicketMensaje).join(Ticket, Ticket.id == TicketMensaje.ticket_id)
              .outerjoin(lectura, (lectura.ticket_id == TicketMensaje.ticket_id) & (lectura.usuario_id == usuario.id))
              .where(TicketMensaje.autor_id != usuario.id)
              # cada conversación con su propio "hasta dónde he leído"
              .where(TicketMensaje.id > db.func.coalesce(
                  case((TicketMensaje.interno.is_(True), lectura.ultimo_interno_id), else_=lectura.ultimo_mensaje_id), 0)))
    if not ve_notas(usuario):
        select = select.where(TicketMensaje.interno.is_(False))
    if usuario.creado:
        select = select.where(TicketMensaje.fecha >= usuario.creado)
    return filtrar_tickets(select, usuario)


def tickets_con_novedades(usuario) -> int:
    """Cuántos tickets tienen algo nuevo para este usuario (para la campana y el menú)."""
    return db.session.scalar(_pendientes(usuario, db.func.count(db.distinct(TicketMensaje.ticket_id)))) or 0


def no_leidos_por_ticket(usuario, ids) -> dict:
    if not ids:
        return {}
    select = (_pendientes(usuario, TicketMensaje.ticket_id, db.func.count(TicketMensaje.id))
              .where(TicketMensaje.ticket_id.in_(list(ids))).group_by(TicketMensaje.ticket_id))
    return dict(db.session.execute(select).all())


def internos_sin_leer(usuario, ticket) -> int:
    if not ve_notas(usuario):
        return 0
    return db.session.scalar(_pendientes(usuario, db.func.count(TicketMensaje.id))
                             .where(TicketMensaje.ticket_id == ticket.id, TicketMensaje.interno.is_(True))) or 0


def _lectura(usuario_id, ticket_id):
    lectura = db.session.scalar(db.select(LecturaTicket).filter_by(usuario_id=usuario_id, ticket_id=ticket_id))
    if lectura is None:
        try:
            with db.session.begin_nested():       # dos pestañas a la vez: la segunda usa la de la primera
                lectura = LecturaTicket(usuario_id=usuario_id, ticket_id=ticket_id, ultimo_mensaje_id=0)
                db.session.add(lectura)
        except IntegrityError:
            lectura = db.session.scalar(db.select(LecturaTicket).filter_by(usuario_id=usuario_id, ticket_id=ticket_id))
    return lectura


def marcar_leido(usuario, ticket, interno=None):
    """Marca como leída una conversación del ticket (sin commit): interno=False la del cliente,
    interno=True las notas internas, None las dos (las internas solo si es del equipo)."""
    lectura = None
    for es_interno in (False, True):
        if (interno is not None and interno != es_interno) or (es_interno and not ve_notas(usuario)):
            continue
        ultimo = db.session.scalar(db.select(db.func.max(TicketMensaje.id))
                                   .filter_by(ticket_id=ticket.id, interno=es_interno))
        if not ultimo:
            continue
        lectura = lectura or _lectura(usuario.id, ticket.id)
        if es_interno:
            lectura.ultimo_interno_id = max(lectura.ultimo_interno_id or 0, ultimo)
            lectura.avisado_interno = False
        else:
            lectura.ultimo_mensaje_id = max(lectura.ultimo_mensaje_id or 0, ultimo)
            lectura.avisado = False


# --------------------------------------------------------------------------- #
# Crear, responder, cambiar
# --------------------------------------------------------------------------- #
def leer_adjuntos(ficheros):
    ficheros = [f for f in (ficheros or []) if f and getattr(f, "filename", "")]
    if len(ficheros) > MAX_ADJUNTOS:
        raise archivos.ArchivoNoValido(_("Como máximo %(n)s archivos por mensaje.", n=MAX_ADJUNTOS))
    return [archivos.leer_y_validar(f, EXTENSIONES_ADJUNTO) for f in ficheros]


def _siguiente_numero():
    """TK-<año>-0001, 0002... El máximo se calcula como NÚMERO (como texto, "9999" > "10000")."""
    prefijo = f"TK-{date.today().year}-"
    ultimo = db.session.scalar(db.select(db.func.max(db.cast(db.func.substr(Ticket.numero, len(prefijo) + 1), db.Integer)))
                               .where(Ticket.numero.like(prefijo + "%")))
    return f"{prefijo}{(ultimo or 0) + 1:04d}"


def _mensaje(ticket, autor, texto, adjuntos=(), interno=False, de_sistema=False):
    m = TicketMensaje(ticket=ticket, autor=autor, texto=texto or "", interno=interno, de_sistema=de_sistema,
                      de_cliente=autor.es_cliente)
    db.session.add(m)
    db.session.flush()
    for nombre, ext, datos in adjuntos:
        db.session.add(AdjuntoTicket(mensaje=m, nombre_original=nombre, tamano=len(datos),
                                     archivo=archivos.escribir(datos, f"ticket{ticket.id}", ext)))
    ticket.actualizado = ahora()
    return m


def crear(autor, cliente, asunto, categoria, prioridad, texto, referencia=None, adjuntos=()):
    ticket = Ticket(cliente=cliente, creado_por=autor, asunto=asunto.strip(), categoria=categoria,
                    prioridad=prioridad, referencia=(referencia or "").strip() or None, estado="abierto")
    for intento in range(3):
        # Si dos personas abren un ticket a la vez y les toca el mismo número, el segundo
        # choca con la restricción UNIQUE: se deshace solo ese intento y se prueba el siguiente
        ticket.numero = _siguiente_numero()
        try:
            with db.session.begin_nested():
                db.session.add(ticket)
                db.session.flush()
            break
        except IntegrityError:
            if intento == 2:
                raise
    m = _mensaje(ticket, autor, texto, adjuntos)
    marcar_leido(autor, ticket)
    _avisar(m, nuevo=True)
    return ticket


def _cambio_estado(ticket, autor, nuevo):
    """Cambia el estado dejando una línea en la conversación (la ve también el cliente)."""
    if nuevo == ticket.estado:
        return
    texto = _("Estado: %(antes)s → %(despues)s", antes=ESTADOS_TICKET[ticket.estado], despues=ESTADOS_TICKET[nuevo])
    ticket.estado = nuevo
    ticket.resuelto = ahora() if nuevo in ("resuelto", "cerrado") else None
    return _mensaje(ticket, autor, texto, de_sistema=True)


def responder(autor, ticket, texto, adjuntos=(), interno=False, dejar_en=None):
    """Un mensaje en el ticket, con los cambios automáticos de estado:
      - responde el cliente a un ticket "esperando al cliente" o "resuelto" → vuelve a "en curso";
      - responde el equipo de soporte → el estado que elija (dejar_en; por defecto "esperando
        al cliente"), y si nadie lo tenía asignado, se lo queda quien responde;
      - responde el FAS → el estado NO cambia (eso lo decide el equipo de soporte)."""
    if interno and not ve_notas(autor):
        raise ValueError("Las notas internas son solo para Yikon")
    if not interno and not (autor.es_cliente or autor.puede("soporte.responder")):
        raise ValueError("No puede escribir al cliente en este ticket")
    m = _mensaje(ticket, autor, texto, adjuntos, interno=interno)
    if not interno:
        if autor.es_cliente:
            if ticket.estado in ("esperando_cliente", "resuelto"):
                _cambio_estado(ticket, autor, "en_curso")
        elif es_equipo(autor):
            if ticket.asignado_a_id is None:
                ticket.asignado_a = autor
            _cambio_estado(ticket, autor, dejar_en if dejar_en in ESTADOS_TICKET else "esperando_cliente")
    marcar_leido(autor, ticket, interno=interno)
    _avisar(m)
    return m


def cambiar(ticket, autor, estado=None, prioridad=None, asignado=None, categoria=None):
    """Cambios del equipo desde el panel. El estado se apunta en la conversación con el cliente;
    prioridad, categoría y asignación, en las notas internas. Devuelve True si cambió algo."""
    from app.models import CATEGORIAS_TICKET
    cambios_internos = []
    if prioridad in PRIORIDADES_TICKET and prioridad != ticket.prioridad:
        cambios_internos.append(_("Prioridad: %(a)s → %(b)s", a=ticket.prioridad_nombre, b=PRIORIDADES_TICKET[prioridad]))
        ticket.prioridad = prioridad
    if categoria in CATEGORIAS_TICKET and categoria != ticket.categoria:
        cambios_internos.append(_("Categoría: %(a)s → %(b)s", a=ticket.categoria_nombre, b=CATEGORIAS_TICKET[categoria]))
        ticket.categoria = categoria
    if asignado is not False and (asignado.id if asignado else None) != ticket.asignado_a_id:
        cambios_internos.append(_("Asignado a: %(quien)s", quien=asignado.nombre if asignado else _("nadie")))
        ticket.asignado_a = asignado
    if cambios_internos:
        _mensaje(ticket, autor, " · ".join(cambios_internos), interno=True, de_sistema=True)
    m = _cambio_estado(ticket, autor, estado) if estado in ESTADOS_TICKET else None
    if m is not None:
        _avisar(m)            # p. ej. "Resuelto": que el cliente se entere
    marcar_leido(autor, ticket)
    return bool(cambios_internos or m is not None)


def cerrar_por_cliente(ticket, autor):
    """El cliente da la incidencia por solucionada: se cierra y se avisa a quien lo lleva."""
    m = _cambio_estado(ticket, autor, "cerrado")
    if m is not None:
        _avisar(m)
    marcar_leido(autor, ticket)


def ordenar(select):
    """Primero los activos; dentro, los más urgentes y luego los que se movieron hace menos."""
    return select.order_by(
        case((Ticket.estado.in_(["resuelto", "cerrado"]), 1), else_=0),
        case(ORDEN_PRIORIDAD, value=Ticket.prioridad, else_=9),
        Ticket.actualizado.desc(), Ticket.id.desc())


# --------------------------------------------------------------------------- #
# Avisos por email (uno hasta que entre a leerlo, igual que en Mensajes)
# --------------------------------------------------------------------------- #
def _lado_cliente(ticket):
    """Usuarios de la empresa que siguen el ticket: quien lo abrió y quien haya escrito en él.
    Si lo abrió el equipo en su nombre y aún no ha escrito nadie: todos los de la empresa con acceso."""
    ids = {ticket.creado_por_id} | {m.autor_id for m in ticket.mensajes if m.de_cliente}
    candidatos = db.session.scalars(db.select(User).where(User.activo.is_(True), User.cliente_id == ticket.cliente_id)).all()
    con_acceso = [u for u in candidatos if u.es_cliente and u.puede("soporte.ver")]
    siguen = [u for u in con_acceso if u.id in ids]
    return siguen or con_acceso


def _lado_notas(ticket):
    """Nota interna: a quien lleva el ticket y a quien de Yikon haya escrito en él (también
    el FAS), si sigue activo y puede ver el ticket y sus notas."""
    ids = {m.autor_id for m in ticket.mensajes if not m.de_cliente}
    if ticket.asignado_a_id:
        ids.add(ticket.asignado_a_id)
    usuarios = db.session.scalars(db.select(User).where(User.activo.is_(True), User.id.in_(ids or [0]))).all()
    return [u for u in usuarios if ve_notas(u) and db.session.scalar(
        filtrar_tickets(db.select(Ticket.id).filter_by(id=ticket.id), u)) is not None]


def _lado_equipo(ticket):
    """Quien lleva el ticket; si no lo lleva nadie, todo Soporte ChromGo (o los admin si no hay)."""
    if ticket.asignado_a and ticket.asignado_a.activo and es_equipo(ticket.asignado_a):
        return [ticket.asignado_a]
    soporte = db.session.scalars(db.select(User).filter_by(rol="soporte", activo=True)).all()
    return soporte or db.session.scalars(db.select(User).filter_by(rol="admin", activo=True)).all()


def _avisar(mensaje, nuevo=False):
    ticket = mensaje.ticket
    if mensaje.interno:
        destinatarios = _lado_notas(ticket)
    elif mensaje.de_cliente:
        destinatarios = _lado_equipo(ticket)
    else:
        destinatarios = _lado_cliente(ticket)
    por_idioma = {}
    for u in destinatarios:
        if u.id == mensaje.autor_id:
            continue
        lectura = _lectura(u.id, ticket.id)
        campo = "avisado_interno" if mensaje.interno else "avisado"
        if getattr(lectura, campo):
            continue
        setattr(lectura, campo, True)
        por_idioma.setdefault(u.idioma or "es", []).append(u.email)
    enlace = url_for("soporte.detalle", id=ticket.id, _external=True) + ("#interno" if mensaje.interno else "#conversacion")
    for idioma, emails in por_idioma.items():
        with force_locale(idioma):
            if nuevo:
                asunto = _("[%(n)s] Nuevo ticket de ChromGo: %(asunto)s", n=ticket.numero, asunto=ticket.asunto)
            elif mensaje.interno:
                asunto = _("[%(n)s] Nota interna: %(asunto)s", n=ticket.numero, asunto=ticket.asunto)
            else:
                asunto = _("[%(n)s] Novedades en su ticket: %(asunto)s", n=ticket.numero, asunto=ticket.asunto)
            quien = f"{mensaje.autor.nombre} ({ticket.cliente.nombre if mensaje.de_cliente else 'Yikon Genomics'})"
            enviar_tras_guardar(emails, asunto, "ticket", meta={"tipo": "ticket", "cliente_id": ticket.cliente_id}, ticket=ticket, quien=quien, texto=mensaje.texto,
                                nuevo=nuevo, interno=mensaje.interno, enlace=enlace,
                                estado=ticket.estado_nombre, adjuntos=[a.nombre_original for a in mensaje.adjuntos])
