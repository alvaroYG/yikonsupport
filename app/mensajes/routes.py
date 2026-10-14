"""
Mensajes entre el cliente y Yikon. Dos tipos de conversación:
  - general de cada cliente → /mensajes/cliente/<id>
  - la de cada pedido       → dentro de la ficha del pedido (aquí solo se reciben los envíos)

Quién ve qué: las mismas reglas que los pedidos (alcance.py). Un cliente solo ve las
conversaciones de su empresa; el FAS, las de sus clientes; admin y logística, todas.
"""
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app import archivos
from app.alcance import cliente_o_404, filtrar_clientes, filtrar_mensajes, pedido_o_404
from app.extensions import db
from app.mensajes import servicio
from app.mensajes.forms import MensajeForm, NuevoMensajeForm
from app.models import AdjuntoMensaje, Cliente, Mensaje, ahora, hilo_de
from app.pedidos.forms import con_ids_propios
from app.permisos import requiere_permiso

bp = Blueprint("mensajes", __name__)


def _clientes_visibles():
    return db.session.scalars(filtrar_clientes(
        db.select(Cliente).filter_by(activo=True).order_by(Cliente.nombre))).all()


def _nuevo_mensaje_form(clientes):
    form = con_ids_propios(NuevoMensajeForm(), "nuevo")
    form.cliente_id.choices = [(0, _("— Elige un cliente —"))] + [(c.id, c.nombre) for c in clientes]
    return form


@bp.route("/", methods=["GET", "POST"])
@requiere_permiso("mensajes.ver")
def lista():
    """Todas tus conversaciones, la más reciente primero, con las no leídas marcadas.
    Yikon (admin, logística, FAS): botón "Mensaje nuevo" (ventana para elegir cliente y escribir)."""
    cliente_id = request.args.get("cliente_id", type=int)
    if current_user.rol == "cliente":
        cliente_id = current_user.cliente_id
    solo_internas = bool(request.args.get("internas")) and current_user.puede("mensajes.internos")
    clientes, nuevo_form, abrir_ventana = [], None, False
    if current_user.rol != "cliente":
        clientes = _clientes_visibles()
        if current_user.puede("mensajes.enviar") and current_user.puede("mensajes.general"):
            nuevo_form = _nuevo_mensaje_form(clientes)
    if request.method == "POST":
        if nuevo_form is None:
            abort(403)
        if nuevo_form.validate_on_submit():
            cliente = cliente_o_404(nuevo_form.cliente_id.data)     # FAS: solo sus clientes
            try:
                adjuntos = servicio.leer_adjuntos(nuevo_form.adjuntos.data or [])
            except archivos.ArchivoNoValido as e:
                nuevo_form.adjuntos.errors = [str(e)]
            else:
                servicio.enviar(current_user, cliente, nuevo_form.texto.data, adjuntos=adjuntos)
                db.session.commit()
                flash(_("Mensaje enviado a %(cliente)s.", cliente=cliente.nombre), "success")
                return redirect(url_for("mensajes.conversacion", cliente_id=cliente.id))
        abrir_ventana = True        # algo no cuadra: se vuelve a abrir la ventana con lo escrito y el error
    return render_template("mensajes/lista.html", title=_("Mensajes"), clientes=clientes,
                           cliente_id=cliente_id, nuevo_form=nuevo_form, abrir_ventana=abrir_ventana,
                           solo_internas=solo_internas,
                           conversaciones=servicio.conversaciones(current_user, cliente_id,
                                                                  interno=True if solo_internas else None),
                           resumen=servicio.resumen_texto)


@bp.route("/cliente/<int:cliente_id>", methods=["GET", "POST"])
@requiere_permiso("mensajes.ver")
def conversacion(cliente_id):
    """Conversación general con un cliente (lo que no va de un pedido concreto)."""
    cliente = cliente_o_404(cliente_id)
    hilo = hilo_de(cliente_id=cliente.id)
    form = MensajeForm()
    if request.method == "POST":
        if not (current_user.puede("mensajes.enviar") and current_user.puede("mensajes.general")):
            return redirect(url_for("mensajes.conversacion", cliente_id=cliente.id))
        if form.validate_on_submit():
            try:
                adjuntos = servicio.leer_adjuntos(form.adjuntos.data or [])
            except archivos.ArchivoNoValido as e:
                form.adjuntos.errors = [str(e)]        # se queda en la página con el texto escrito
            else:
                mensaje = servicio.enviar(current_user, cliente, form.texto.data, adjuntos=adjuntos)
                db.session.commit()
                _ofrecer_deshacer(mensaje)
                return redirect(url_for("mensajes.conversacion", cliente_id=cliente.id))
    servicio.marcar_leido(current_user, hilo)
    db.session.commit()
    escribe = current_user.puede("mensajes.general")      # Facturación y Almacén: solo leen lo que les comparten
    return render_template("mensajes/conversacion.html", deshacer=mensaje_para_deshacer(),
                           title=_("Mensajes · %(cliente)s", cliente=cliente.nombre), cliente=cliente,
                           mensajes=servicio.mensajes_de(hilo), form=form if escribe else None,
                           soportes=[u for u in cliente.logisticos if u.activo],
                           accion=url_for("mensajes.conversacion", cliente_id=cliente.id),
                           url_nuevos=url_for("mensajes.nuevos_cliente", cliente_id=cliente.id))


def _enviar_en_pedido(pedido, interno):
    form = MensajeForm()
    if form.validate_on_submit():
        try:
            adjuntos = servicio.leer_adjuntos(form.adjuntos.data or [])
        except archivos.ArchivoNoValido as e:
            flash(str(e), "danger")
        else:
            mensaje = servicio.enviar(current_user, pedido.cliente, form.texto.data, pedido=pedido,
                                      adjuntos=adjuntos, interno=interno)
            db.session.commit()
            _ofrecer_deshacer(mensaje)
    else:
        for error in form.texto.errors + form.adjuntos.errors:
            flash(error, "danger")
    return redirect(url_for("pedidos.detalle", id=pedido.id) + ("#interno" if interno else "#mensajes"))


@bp.route("/pedido/<int:pedido_id>", methods=["POST"])
@requiere_permiso("mensajes.pedido_cliente")     # (Ajustes → Qué ve cada rol → Mensajes en los pedidos)
def enviar_pedido(pedido_id):
    """Mensaje en la conversación de un pedido con el cliente (formulario en la ficha del pedido)."""
    return _enviar_en_pedido(pedido_o_404(pedido_id), interno=False)


@bp.route("/pedido/<int:pedido_id>/interno", methods=["POST"])
@requiere_permiso("mensajes.internos")
def enviar_interno(pedido_id):
    """Mensaje en la conversación INTERNA del pedido: solo admin, logística y FAS, el cliente no la ve."""
    return _enviar_en_pedido(pedido_o_404(pedido_id), interno=True)


# --------------------------------------------------------------------------- #
# Deshacer un mensaje al cliente (unos segundos: config MENSAJES_DESHACER_SEGUNDOS)
# --------------------------------------------------------------------------- #
def _ofrecer_deshacer(mensaje):
    """Tras enviar: la página siguiente enseña el aviso "Enviado · Deshacer" con la cuenta atrás."""
    if mensaje.visible_desde is not None:
        session["deshacer_mensaje"] = mensaje.id


def mensaje_para_deshacer():
    """El mensaje recién enviado que aún se puede deshacer (o None). Lo usan las plantillas."""
    mensaje_id = session.pop("deshacer_mensaje", None)
    mensaje = db.session.get(Mensaje, mensaje_id) if mensaje_id else None
    if mensaje is None or not servicio.se_puede_deshacer(mensaje, current_user):
        return None
    restan = (servicio._con_zona(mensaje.visible_desde) - ahora()).total_seconds()
    return {"mensaje": mensaje, "segundos": max(1, int(restan))}


@bp.route("/<int:mensaje_id>/compartir", methods=["POST"])
@requiere_permiso("mensajes.compartir")
def compartir(mensaje_id):
    """Soporte de cliente (o admin) comparte con Almacén o con Facturación (campo «destino») un
    mensaje de la conversación general, que es privada: desde entonces ese equipo lo ve (solo ese)
    y le llega un aviso. Se puede compartir después también con el otro."""
    from app import avisos_internos
    from app.auditoria import registrar
    from app.permisos import COMPARTIR_CON, ROLES
    mensaje = db.session.scalar(filtrar_mensajes(db.select(Mensaje).filter_by(id=mensaje_id)))
    if mensaje is None or mensaje.pedido_id is not None or mensaje.interno:
        abort(404)
    destino = request.form.get("destino", "logistica")
    if destino not in COMPARTIR_CON:
        abort(400)
    ya = mensaje.compartido_roles
    if destino not in ya:
        nota = (request.form.get("nota") or "").strip()[:500] or None
        if mensaje.compartido_el is None:
            mensaje.compartido_el, mensaje.compartido_por = ahora(), current_user
        mensaje.compartido_con = ",".join(ya + [destino])
        if nota:
            mensaje.compartido_nota = (f"{mensaje.compartido_nota} · {nota}" if mensaje.compartido_nota else nota)[:500]
        from flask_babel import force_locale
        with force_locale("es"):          # la auditoría, siempre en español
            registrar("editar", mensaje.cliente, f"mensaje compartido con {ROLES[destino]}"
                      + (f" · «{nota}»" if nota else ""))
        avisos_internos.mensaje_compartido(mensaje, current_user.nombre, destino, nota, excluir_id=current_user.id)
        db.session.commit()
        flash(_("Compartido con %(equipo)s: ya lo ve y le hemos avisado.", equipo=ROLES[destino]), "success")
    destino = request.form.get("volver")
    if destino == "flotante":
        return redirect(url_for("mensajes.conversacion", cliente_id=mensaje.cliente_id))
    return redirect(url_for("mensajes.conversacion", cliente_id=mensaje.cliente_id) + f"#m{mensaje.id}")


@bp.route("/<int:mensaje_id>/deshacer", methods=["POST"])
@requiere_permiso("mensajes.enviar")
def deshacer(mensaje_id):
    mensaje = db.get_or_404(Mensaje, mensaje_id)
    destino = (url_for("pedidos.detalle", id=mensaje.pedido_id) + "#mensajes" if mensaje.pedido_id
               else url_for("mensajes.conversacion", cliente_id=mensaje.cliente_id))
    if not servicio.se_puede_deshacer(mensaje, current_user):
        flash(_("Ya no se puede deshacer: el cliente ya lo tiene."), "warning")
        return redirect(destino)
    ficheros = servicio.deshacer(mensaje)
    db.session.commit()
    for f in ficheros:
        archivos.borrar(f)
    flash(_("Mensaje retirado: el cliente no lo ha visto ni le ha llegado el email."), "success")
    return redirect(destino)


@bp.route("/adjunto/<int:adjunto_id>")
@requiere_permiso("mensajes.ver")
def descargar_adjunto(adjunto_id):
    """Un archivo de un mensaje: solo si puedes ver ese mensaje (mismo alcance que la conversación)."""
    adjunto = db.get_or_404(AdjuntoMensaje, adjunto_id)
    visible = db.session.scalar(filtrar_mensajes(db.select(Mensaje.id).filter_by(id=adjunto.mensaje_id)))
    if visible is None:
        abort(404)
    return archivos.descargar(adjunto.archivo, adjunto.nombre_original)


# --------------------------------------------------------------------------- #
# Mensajes nuevos sin recargar la página: el navegador pregunta cada 30 s
# (static/js/mensajes.js) y recibe solo los que han llegado desde el último que tiene.
# --------------------------------------------------------------------------- #
def _nuevos(hilo):
    despues = request.args.get("despues", 0, type=int)
    despues = max(0, min(despues, 2**31 - 1))         # un número absurdo no debe dar error
    mensajes = servicio.mensajes_de(hilo, despues=despues)
    # Los está viendo en pantalla. ?abierto=1: acaba de abrir el chat (ficha del pedido) y ya ha
    # visto los que había, aunque no haya ninguno nuevo
    if mensajes or request.args.get("abierto"):
        servicio.marcar_leido(current_user, hilo)
        db.session.commit()
    # jinja_env directamente (y no render_template): así no se ejecutan los context
    # processors de la página completa (contadores del menú...) en cada consulta de 30 s
    html = current_app.jinja_env.get_template("mensajes/_burbujas.html").render(mensajes=mensajes)
    return jsonify(html=html, ultimo=mensajes[-1].id if mensajes else despues)


@bp.route("/cliente/<int:cliente_id>/nuevos")
@requiere_permiso("mensajes.ver")
def nuevos_cliente(cliente_id):
    return _nuevos(hilo_de(cliente_id=cliente_o_404(cliente_id).id))


@bp.route("/pedido/<int:pedido_id>/nuevos")
@requiere_permiso("mensajes.ver")
def nuevos_pedido(pedido_id):
    return _nuevos(hilo_de(pedido_id=pedido_o_404(pedido_id).id))


@bp.route("/pedido/<int:pedido_id>/interno/nuevos")
@requiere_permiso("mensajes.internos")
def nuevos_interno(pedido_id):
    return _nuevos(hilo_de(pedido_id=pedido_o_404(pedido_id).id, interno=True))


# --------------------------------------------------------------------------- #
# Botón flotante de mensajes (solo Yikon): las mismas conversaciones, en un panel que acompaña
# en todas las páginas. NO es un chat en directo: carga al abrirlo y refresca el contador cada
# cierto tiempo (static/js/mensajes_flotante.js). Devuelve trozos de HTML, no páginas.
# --------------------------------------------------------------------------- #
MAX_FLOTANTE_CONVERSACIONES = 12
MAX_FLOTANTE_MENSAJES = 30


def _solo_yikon():
    if current_user.es_cliente:
        abort(403)


def _hilo_flotante(hilo):
    """De "pedido-12" / "interno-12" / "cliente-4" a (cliente, pedido, interno), comprobando que
    esta persona puede ver esa conversación (mismo alcance que el resto de la plataforma)."""
    tipo, _sep, id_ = hilo.partition("-")
    if tipo not in ("pedido", "interno", "cliente") or not id_.isdigit():
        abort(404)
    if tipo == "cliente":
        return cliente_o_404(int(id_)), None, False
    if tipo == "interno" and not current_user.puede("mensajes.internos"):
        abort(403)
    pedido = pedido_o_404(int(id_))
    return pedido.cliente, pedido, tipo == "interno"


def _cuenta_flotante():
    return servicio.no_leidos_total(current_user)


@bp.route("/flotante")
@requiere_permiso("mensajes.ver")
def flotante():
    """La lista del panel: conversaciones con clientes o, con ?internas=1, las internas."""
    _solo_yikon()
    internas = bool(request.args.get("internas")) and current_user.puede("mensajes.internos")
    todas = servicio.conversaciones(current_user, interno=internas)
    todas.sort(key=lambda c: (not c["no_leidos"], -c["ultimo"].id))          # primero las no leídas
    return render_template(
        "mensajes/_flotante_lista.html", internas=internas, conversaciones=todas[:MAX_FLOTANTE_CONVERSACIONES],
        sin_leer_clientes=servicio.no_leidos_total(current_user, interno=False),
        sin_leer_internas=servicio.no_leidos_total(current_user, interno=True)
        if current_user.puede("mensajes.internos") else None,
        resumen=servicio.resumen_texto, cuenta=_cuenta_flotante())


@bp.route("/flotante/cuenta")
@requiere_permiso("mensajes.ver")
def flotante_cuenta():
    _solo_yikon()
    return jsonify(sin_leer=_cuenta_flotante())


def _escribe_en(pedido, interno):
    """¿Puede escribir en este hilo? Al cliente, según Ajustes → Qué ve cada rol (Quién habla con
    los clientes): la general, «Conversación general»; la de un pedido, «Mensajes en los pedidos»."""
    if interno:
        return current_user.puede("mensajes.internos")
    return current_user.puede("mensajes.pedido_cliente" if pedido else "mensajes.general")


@bp.route("/flotante/hilo/<hilo>", methods=["GET", "POST"])
@requiere_permiso("mensajes.ver")
def flotante_hilo(hilo):
    """Una conversación dentro del panel: la enseña (y la da por leída) o añade una respuesta."""
    _solo_yikon()
    cliente, pedido, interno = _hilo_flotante(hilo)
    error = None
    if request.method == "POST":
        if not current_user.puede("mensajes.enviar") or not _escribe_en(pedido, interno):
            abort(403)
        texto = (request.form.get("texto") or "").strip()
        if not texto:
            error = _("Escribe algo antes de enviar.")
        elif len(texto) > servicio.MAX_TEXTO:
            error = _("Máximo %(max)d caracteres.", max=servicio.MAX_TEXTO)
        else:
            servicio.enviar(current_user, cliente, texto, pedido=pedido, interno=interno)
    servicio.marcar_leido(current_user, hilo)
    db.session.commit()
    return render_template("mensajes/_flotante_hilo.html", hilo=hilo, cliente=cliente, pedido=pedido, interno=interno,
                           escribe=current_user.puede("mensajes.enviar") and _escribe_en(pedido, interno),
                           mensajes=servicio.mensajes_de(hilo)[-MAX_FLOTANTE_MENSAJES:], error=error,
                           cuenta=_cuenta_flotante())
