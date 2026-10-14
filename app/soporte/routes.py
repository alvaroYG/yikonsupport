"""
Soporte ChromGo: tickets de incidencias de los clientes con la plataforma de análisis ChromGo.

  /soporte/                 lista (el equipo: todos, con filtros; el cliente: los de su empresa)
  /soporte/nuevo            abrir un ticket (el equipo puede abrirlo en nombre de un cliente)
  /soporte/<id>             el ticket: conversación con el cliente + notas internas del equipo
Quién ve qué: soporte/servicio.py (filtrar_tickets y mensajes_de).
"""
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy import or_

from app import archivos
from app.auditoria import registrar
from app.extensions import db
from app.models import (AYUDA_PRIORIDAD_TICKET, ESTADOS_TICKET, ESTADOS_TICKET_ACTIVOS, ICONOS_ESTADO_TICKET,
                        ICONOS_PRIORIDAD_TICKET, PRIORIDADES_TICKET, AdjuntoTicket, Cliente, Ticket, User)
from app.permisos import requiere_permiso
from app.soporte import servicio
from app.soporte.forms import GestionForm, RespuestaForm, TicketForm
from app.utils import paginar

bp = Blueprint("soporte", __name__)


@bp.before_request
def _solo_si_esta_activo():
    """Tickets ChromGo en pausa (nadie los tiene activados en Ajustes → Qué ve cada rol): sus páginas no existen."""
    from app.permisos import soporte_activo
    if not soporte_activo():
        abort(404)


@bp.record_once
def _ayudantes(estado):
    # Globales de Jinja (y no context processor): así las ven también las macros importadas
    # y las burbujas que se pintan sueltas cada 30 s
    estado.app.jinja_env.globals.update(iconos_estado_ticket=ICONOS_ESTADO_TICKET,
                                        iconos_prioridad_ticket=ICONOS_PRIORIDAD_TICKET)


# --------------------------------------------------------------------------- #
# Lista
# --------------------------------------------------------------------------- #
@bp.route("/")
@requiere_permiso("soporte.ver")
def lista():
    equipo = servicio.es_equipo(current_user)
    yikon = not current_user.es_cliente          # equipo de soporte o FAS: vista "interna"
    estado = request.args.get("estado", "activos")
    q = (request.args.get("q") or "").strip()[:100]
    select = servicio.filtrar_tickets(db.select(Ticket))
    if estado == "activos":
        select = select.where(Ticket.estado.in_(ESTADOS_TICKET_ACTIVOS))
    elif estado in ESTADOS_TICKET:
        select = select.filter_by(estado=estado)
    else:
        estado = "todos"
    filtros = {"estado": estado, "q": q}
    if yikon:
        prioridad = request.args.get("prioridad") or None
        if prioridad in PRIORIDADES_TICKET:
            select = select.filter_by(prioridad=prioridad)
            filtros["prioridad"] = prioridad
        elif prioridad == "altas":
            select = select.where(Ticket.prioridad.in_(["urgente", "alta"]))
            filtros["prioridad"] = prioridad
        asignado = request.args.get("asignado") or None
        if asignado == "mios":
            select = select.filter_by(asignado_a_id=current_user.id)
        elif asignado == "nadie":
            select = select.where(Ticket.asignado_a_id.is_(None))
        filtros["asignado"] = asignado
        cliente_id = request.args.get("cliente_id", type=int)
        if cliente_id:
            select = select.filter_by(cliente_id=cliente_id)
            filtros["cliente_id"] = cliente_id
    if q:
        patron = f"%{q}%"
        select = select.where(or_(Ticket.numero.ilike(patron), Ticket.asunto.ilike(patron),
                                  Ticket.referencia.ilike(patron)))
    pagina = paginar(servicio.ordenar(select))
    no_leidos = servicio.no_leidos_por_ticket(current_user, [t.id for t in pagina.items])

    resumen = {}
    if yikon:
        # (FAS: solo cuenta los de sus clientes)
        activos = servicio.filtrar_tickets(db.select(db.func.count(Ticket.id)).where(Ticket.estado.in_(ESTADOS_TICKET_ACTIVOS)))
        resumen = {
            "sin_asignar": db.session.scalar(activos.where(Ticket.asignado_a_id.is_(None))),
            "urgentes": db.session.scalar(activos.where(Ticket.prioridad.in_(["urgente", "alta"]))),
            "esperando": db.session.scalar(activos.filter_by(estado="esperando_cliente")),
        }
        if equipo:
            resumen["mios"] = db.session.scalar(activos.filter_by(asignado_a_id=current_user.id))
    clientes = db.session.scalars(db.select(Cliente).where(Cliente.id.in_(servicio.filtrar_tickets(db.select(Ticket.cliente_id))))
                                  .order_by(Cliente.nombre)).all() if yikon else []
    return render_template("soporte/lista.html", title=_("Soporte ChromGo"), pagina=pagina, no_leidos=no_leidos,
                           equipo=equipo, yikon=yikon, filtros=filtros, resumen=resumen, clientes=clientes,
                           estados=ESTADOS_TICKET, prioridades=PRIORIDADES_TICKET)


# --------------------------------------------------------------------------- #
# Nuevo ticket
# --------------------------------------------------------------------------- #
@bp.route("/nuevo", methods=["GET", "POST"])
@requiere_permiso("soporte.crear")
def nuevo():
    equipo = servicio.es_equipo(current_user)
    form = TicketForm()
    if equipo:
        form.cliente_id.choices = [(0, _("— Elige el cliente —"))] + [
            (c.id, c.nombre)
            for c in servicio.clientes_para_ticket()]
        if request.method == "GET" and request.args.get("cliente_id", type=int):
            form.cliente_id.data = request.args.get("cliente_id", type=int)
    else:
        del form.cliente_id                    # el cliente abre siempre para su propia empresa
    if form.validate_on_submit():
        cliente = db.get_or_404(Cliente, form.cliente_id.data) if equipo else current_user.empresa
        if cliente is None or not cliente.activo:
            abort(403)
        try:
            adjuntos = servicio.leer_adjuntos(form.adjuntos.data)
        except archivos.ArchivoNoValido as e:
            form.adjuntos.errors = [str(e)]
        else:
            ticket = servicio.crear(current_user, cliente, form.asunto.data, form.categoria.data,
                                    form.prioridad.data, form.texto.data, form.referencia.data, adjuntos)
            registrar("crear", ticket, f"{ticket.numero} · {cliente.nombre} · {ticket.asunto}")
            db.session.commit()
            flash(_("Ticket %(n)s enviado. Le avisaremos por email cuando le respondamos.", n=ticket.numero)
                  if not equipo else _("Ticket %(n)s creado.", n=ticket.numero), "success")
            return redirect(url_for("soporte.detalle", id=ticket.id))
    return render_template("soporte/nuevo.html", title=_("Nuevo ticket de ChromGo"), form=form, equipo=equipo,
                           ayuda_prioridad=AYUDA_PRIORIDAD_TICKET), 400 if form.errors else 200


# --------------------------------------------------------------------------- #
# Un ticket
# --------------------------------------------------------------------------- #
def _gestion_form(ticket, formdata=None):
    form = GestionForm(formdata=formdata, obj=None if formdata else ticket)
    equipo = servicio.usuarios_equipo()
    if ticket.asignado_a and ticket.asignado_a not in equipo:
        equipo.append(ticket.asignado_a)       # desactivado: que no se pierda sin querer al guardar
    form.asignado_a_id.choices = [(0, _("— Nadie —"))] + [(u.id, u.nombre + ("" if u.activo else " " + _("(desactivado)")))
                                                          for u in equipo]
    if formdata is None:
        form.asignado_a_id.data = ticket.asignado_a_id or 0
    return form


@bp.route("/<int:id>")
@requiere_permiso("soporte.ver")
def detalle(id, respuesta_form=None, nota_form=None, gestion_form=None):
    ticket = servicio.ticket_o_404(id)
    equipo = servicio.es_equipo(current_user)
    notas = servicio.ve_notas(current_user)
    mensajes = servicio.mensajes_de(ticket, current_user)
    internos = servicio.mensajes_de(ticket, current_user, interno=True) if notas else []
    internos_sin_leer = servicio.internos_sin_leer(current_user, ticket)
    # Escriben en la conversación: el equipo de soporte (también con el ticket cerrado), el FAS
    # del cliente y el propio cliente (estos dos, mientras no esté cerrado)
    puede_responder = equipo or (ticket.estado != "cerrado" and
                                 (current_user.es_cliente or current_user.puede("soporte.responder")))
    if puede_responder and respuesta_form is None:
        respuesta_form = RespuestaForm(formdata=None)
        if ticket.estado in ("en_curso", "esperando_cliente", "resuelto") and equipo:
            respuesta_form.dejar_en.data = "esperando_cliente"
    if respuesta_form is not None and not equipo:
        del respuesta_form.dejar_en
    if notas:
        nota_form = nota_form or RespuestaForm(formdata=None, prefix="nota")
        del nota_form.dejar_en
    if equipo:
        gestion_form = gestion_form or _gestion_form(ticket)
    servicio.marcar_leido(current_user, ticket)        # lo está viendo
    db.session.commit()
    return render_template("soporte/detalle.html", title=f"{ticket.numero} · {ticket.asunto}", ticket=ticket,
                           mensajes=mensajes, internos=internos, internos_sin_leer=internos_sin_leer, equipo=equipo,
                           yikon=not current_user.es_cliente,
                           respuesta_form=respuesta_form if puede_responder else None, nota_form=nota_form,
                           gestion_form=gestion_form)


def _responder(id, interno):
    ticket = servicio.ticket_o_404(id)
    equipo = servicio.es_equipo(current_user)
    if interno and not servicio.ve_notas(current_user):
        abort(403)
    if not interno and not (current_user.puede("soporte.responder") or current_user.es_cliente):
        abort(403)
    if ticket.estado == "cerrado" and not equipo:
        flash(_("Este ticket está cerrado. Si el problema continúa, abra uno nuevo."), "warning")
        return redirect(url_for("soporte.detalle", id=id))
    form = RespuestaForm(prefix="nota" if interno else "")
    if interno or not equipo:
        del form.dejar_en
    if form.validate_on_submit():
        try:
            adjuntos = servicio.leer_adjuntos(form.adjuntos.data)
        except archivos.ArchivoNoValido as e:
            form.adjuntos.errors = [str(e)]
        else:
            servicio.responder(current_user, ticket, form.texto.data, adjuntos, interno=interno,
                               dejar_en=form.dejar_en.data if "dejar_en" in form else None)
            db.session.commit()
            return redirect(url_for("soporte.detalle", id=id) + ("#interno" if interno else "#conversacion"))
    if interno:
        return detalle(id, nota_form=form), 400
    return detalle(id, respuesta_form=form), 400


@bp.route("/<int:id>/responder", methods=["POST"])
@requiere_permiso("soporte.ver")
def responder(id):
    return _responder(id, interno=False)


@bp.route("/<int:id>/nota", methods=["POST"])
@requiere_permiso("soporte.notas")
def nota(id):
    return _responder(id, interno=True)


@bp.route("/<int:id>/gestion", methods=["POST"])
@requiere_permiso("soporte.gestionar")
def gestion(id):
    ticket = servicio.ticket_o_404(id)
    form = _gestion_form(ticket, formdata=request.form)
    if not form.validate_on_submit():
        return detalle(id, gestion_form=form), 400
    asignado = None
    if form.asignado_a_id.data:
        asignado = db.session.get(User, form.asignado_a_id.data)
        if asignado is None or not (servicio.es_equipo(asignado) or asignado.id == ticket.asignado_a_id):
            abort(400)
    antes = (ticket.estado, ticket.prioridad, ticket.asignado_a_id)
    if servicio.cambiar(ticket, current_user, estado=form.estado.data, prioridad=form.prioridad.data,
                        asignado=asignado, categoria=form.categoria.data):
        registrar("editar", ticket, f"{ticket.numero}: {antes} → {(ticket.estado, ticket.prioridad, ticket.asignado_a_id)}")
        db.session.commit()
        flash(_("Ticket actualizado."), "success")
    return redirect(url_for("soporte.detalle", id=id))


@bp.route("/<int:id>/cerrar", methods=["POST"])
@requiere_permiso("soporte.ver")
def cerrar(id):
    """El cliente da la incidencia por solucionada."""
    ticket = servicio.ticket_o_404(id)
    if not current_user.es_cliente:
        abort(403)                          # Yikon lo cierra desde el panel de gestión
    if ticket.estado != "cerrado":
        servicio.cerrar_por_cliente(ticket, current_user)
        registrar("editar", ticket, f"{ticket.numero}: cerrado por {current_user.email}")
        db.session.commit()
        flash(_("Ticket cerrado. ¡Gracias! Si vuelve a pasar, abra uno nuevo."), "success")
    return redirect(url_for("soporte.detalle", id=id))


@bp.route("/adjunto/<int:adjunto_id>")
@requiere_permiso("soporte.ver")
def descargar_adjunto(adjunto_id):
    """Solo si ves el ticket; y si es de una nota interna, solo el equipo."""
    adjunto = db.get_or_404(AdjuntoTicket, adjunto_id)
    mensaje = adjunto.mensaje
    servicio.ticket_o_404(mensaje.ticket_id)
    if mensaje.interno and not servicio.ve_notas(current_user):
        abort(404)
    return archivos.descargar(adjunto.archivo, adjunto.nombre_original)


# Mensajes nuevos sin recargar (static/js/mensajes.js pregunta cada 30 s)
def _nuevos(id, interno):
    ticket = servicio.ticket_o_404(id)
    despues = max(0, min(request.args.get("despues", 0, type=int), 2**31 - 1))
    mensajes = servicio.mensajes_de(ticket, current_user, interno=interno, despues=despues)
    if mensajes:
        servicio.marcar_leido(current_user, ticket, interno=interno)   # solo la conversación que está viendo
        db.session.commit()
    html = current_app.jinja_env.get_template("soporte/_burbujas.html").render(mensajes=mensajes, ticket=ticket)
    return jsonify(html=html, ultimo=mensajes[-1].id if mensajes else despues)


@bp.route("/<int:id>/nuevos")
@requiere_permiso("soporte.ver")
def nuevos(id):
    return _nuevos(id, interno=False)


@bp.route("/<int:id>/nuevos-internos")
@requiere_permiso("soporte.notas")
def nuevos_internos(id):
    return _nuevos(id, interno=True)
