"""
Proforma antes del pedido:

  cliente pide ──► "proforma solicitada" ──(Yikon envía)──► "proforma enviada" ──(acepta)──► "aceptado"
                                                             │   ▲      │
                   "cambios solicitados" ◄─(pide cambios)────┘   │      └─(Yikon la retira)─► "proforma solicitada"
                          └──────────(Yikon envía otra)──────────┘

Todos los cambios de estado pasan por pedidos.routes._cambiar_estado (permisos, auditoría,
email al cliente). La proforma guarda una foto fija de lo que se envió.
"""
import unicodedata
from datetime import date, timedelta
from urllib.parse import quote

from flask import Blueprint, Response, abort, flash, redirect, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app import archivos, avisos_internos
from app.alcance import pedido_o_404
from app.extensions import db
from app.mensajes import servicio as servicio_mensajes
from app.models import Proforma, ahora
from app.pedidos.routes import _cambiar_estado, _sigue_en
from app.permisos import requiere_permiso
from app.proformas.forms import DIAS_VALIDEZ, ProformaForm, RespuestaProformaForm, RetirarProformaForm
from app.proformas.pdf import generar_pdf_proforma
from app.proformas.servicio import crear_proforma, modelo_previo

bp = Blueprint("proformas", __name__)


def _volver(pedido):
    return redirect(url_for("pedidos.detalle", id=pedido.id) + "#proforma")


@bp.route("/<int:id>/proforma/enviar", methods=["POST"])
@requiere_permiso("pedidos.proforma.enviar")
def enviar(id):
    """Yikon ha revisado el pedido: se crea la proforma (foto fija) con el PDF que ha hecho
    Yikon (obligatorio) y se envía al cliente."""
    pedido = pedido_o_404(id)
    if not _sigue_en(pedido, "proforma_solicitada", "cambios_solicitados"):
        return _volver(pedido)
    if not pedido.lineas:
        flash(_("La proforma no puede ir vacía: añade al menos un kit o un producto."), "warning")
        return _volver(pedido)
    form = ProformaForm()
    if not form.validate_on_submit():
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
        return _volver(pedido)
    proforma = crear_proforma(pedido, current_user, form.valida_hasta.data,
                              (form.plazo_entrega.data or "").strip(), (form.notas.data or "").strip(),
                              pdf=form.pdf_leido)
    db.session.flush()
    if error := _cambiar_estado(pedido, "proforma_enviada", f"proforma {proforma.numero}"):
        flash(error, "danger")
        return _volver(pedido)
    db.session.commit()
    flash(_("Proforma %(numero)s enviada al cliente. El aviso por email está pendiente de revisar y enviar.", numero=proforma.numero), "success")
    return _volver(pedido)


@bp.route("/<int:id>/proforma/responder", methods=["POST"])
@requiere_permiso("pedidos.proforma.responder")
def responder(id):
    """El cliente acepta la proforma (→ pedido "aceptado") o pide cambios (→ "cambios solicitados")."""
    pedido = pedido_o_404(id)
    if not _sigue_en(pedido, "proforma_enviada"):
        return _volver(pedido)
    proforma = pedido.proforma_actual
    if proforma is None or proforma.estado != "enviada":
        flash(_("Esta proforma ya no está pendiente. Revisa el estado del pedido."), "warning")
        return _volver(pedido)
    form = RespuestaProformaForm()
    if not form.validate_on_submit():
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
        return _volver(pedido)
    if form.aceptar.data:
        if proforma.caducada:
            flash(_("La proforma caducó el %(fecha)s. Pida cambios para que le enviemos una nueva.",
                    fecha=proforma.valida_hasta.strftime("%d/%m/%Y")), "warning")
            return _volver(pedido)
        proforma.estado, proforma.respondida_por, proforma.respondida_fecha = "aceptada", current_user, ahora()
        if error := _cambiar_estado(pedido, "aceptado", f"proforma {proforma.numero} aceptada",
                                    motivo="proforma_aceptada"):
            flash(error, "danger")
            return _volver(pedido)
        avisos_internos.proforma_aceptada(pedido, proforma.numero_y_version, current_user.nombre)
        db.session.commit()
        flash(_("Proforma aceptada: ya es un pedido. Le avisaremos cuando empecemos a prepararlo."), "success")
        return _volver(pedido)
    if not form.cambios.data:           # ni "Aceptar" ni "Pedir cambios": no hacemos nada
        flash(_("Elija «Aceptar» o «Pedir cambios»."), "warning")
        return _volver(pedido)
    # Pedir cambios: pasa a "cambios solicitados" y el motivo queda en los mensajes del pedido
    # (la conversación sigue en un solo sitio). El email a Yikon es el aviso "cambios_proforma"
    # (Ajustes → Avisos internos), no el de "mensaje nuevo", para no mandar dos.
    comentario = (form.comentario.data or "").strip()
    proforma.estado, proforma.respondida_por, proforma.respondida_fecha = "cambios", current_user, ahora()
    proforma.comentario_cambios = comentario
    if error := _cambiar_estado(pedido, "cambios_solicitados", f"cambios pedidos a la proforma {proforma.numero}",
                                avisar=False):
        flash(error, "danger")
        return _volver(pedido)
    servicio_mensajes.enviar(current_user, pedido.cliente,
                             _("Cambios a la proforma %(numero)s:", numero=proforma.numero) + "\n" + comentario,
                             pedido=pedido, avisar=False)
    avisos_internos.cambios_proforma(pedido, proforma.numero_y_version, comentario, current_user.nombre)
    db.session.commit()
    flash(_("Hemos recibido su petición de cambios. Le enviaremos una proforma nueva."), "success")
    return _volver(pedido)


@bp.route("/<int:id>/proforma/retirar", methods=["POST"])
@requiere_permiso("pedidos.proforma.enviar")
def retirar(id):
    """Yikon retira la proforma enviada para corregirla (vuelve a "proforma solicitada")."""
    pedido = pedido_o_404(id)
    form = RetirarProformaForm()
    if not form.validate_on_submit() or not _sigue_en(pedido, "proforma_enviada"):
        return _volver(pedido)
    proforma = pedido.proforma_actual
    if proforma is not None and proforma.estado == "enviada":
        proforma.estado = "retirada"
    detalle = f"proforma {proforma.numero} retirada" if proforma else "proforma retirada"
    if error := _cambiar_estado(pedido, "proforma_solicitada", detalle, avisar=False):
        flash(error, "danger")
        return _volver(pedido)
    db.session.commit()
    flash(_("Proforma retirada. Ajusta el pedido y envía una nueva."), "success")
    return _volver(pedido)


@bp.route("/<int:id>/proforma/<int:proforma_id>.pdf")
@requiere_permiso("pedidos.ver")
def descargar(id, proforma_id):
    """PDF de una proforma (cualquiera de sus versiones) de un pedido que puedes ver: el que
    adjuntó Yikon al enviarla. Las antiguas, sin PDF adjunto, con el modelo de la plataforma."""
    pedido = pedido_o_404(id)
    proforma = db.get_or_404(Proforma, proforma_id)
    if proforma.pedido_id != pedido.id:
        abort(404)
    if proforma.pdf_archivo:
        # (con el nº de la proforma, no con el nombre que tenía el archivo en el ordenador de Yikon)
        return archivos.descargar(proforma.pdf_archivo, f"{proforma.numero}.pdf")
    return _pdf(generar_pdf_proforma(proforma), f"Proforma_{proforma.numero}.pdf")


@bp.route("/<int:id>/proforma/modelo.pdf")
@requiere_permiso("pedidos.proforma.enviar")
def modelo(id):
    """Solo Yikon: el modelo de la proforma que se enviaría ahora (productos, lotes reservados o
    sugeridos y su caducidad), para hacer la proforma de verdad a partir de él."""
    pedido = pedido_o_404(id)
    from app import ajustes
    defecto, idioma = ajustes.proformas(), ajustes.idioma_del_cliente(pedido.cliente)
    previa = modelo_previo(pedido, date.today() + timedelta(days=defecto["validez"]),
                           defecto["plazo"][idioma] or None, defecto["notas"][idioma] or None)
    return _pdf(generar_pdf_proforma(previa), f"Modelo_{previa.numero}.pdf")


def _pdf(datos, nombre):
    # (el nombre lleva la referencia del pedido, que puede tener tildes: va también en UTF-8)
    sencillo = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().replace('"', "")
    return Response(datos, mimetype="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"{sencillo}\"; filename*=UTF-8''{quote(nombre)}",
        "Cache-Control": "private, no-store"})
