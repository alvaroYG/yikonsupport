"""
Administración → Correos enviados (admin todos; Soporte de cliente, los enviados a sus clientes,
sin reenviar) y Administración → Estado de la plataforma (solo admin).
"""
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _, lazy_gettext as _l
from flask_login import current_user

from app import estado as estado_
from app.admin.routes import bp
from app.auditoria import registrar
from app.extensions import db
from app.models import Cliente, CorreoEnviado, User, ahora
from app.permisos import requiere_permiso
from app.utils import limpiar_busqueda, paginar

GRUPOS = {"cliente": _l("Al cliente"), "interno": _l("Internos"), "otros": _l("Invitaciones y contraseñas")}
ESTADOS = {"enviado": _l("Enviado"), "fallido": _l("Falló")}


def nombre_tipo(tipo):
    """"cliente.enviado" → "Al cliente · Enviado"; "interno.recibido" → "Interno · …"."""
    from app.avisos_internos import AVISOS
    from app.correos_cliente import CASOS
    if not tipo:
        return "—"
    grupo, _sep, clave = tipo.partition(".")
    if grupo == "cliente":
        return _("Al cliente") + (f" · {CASOS[clave].nombre}" if clave in CASOS else "")
    if grupo == "interno":
        return _("Interno") + (f" · {AVISOS[clave].nombre}" if clave in AVISOS else "")
    return {"invitacion": _("Invitación"), "restablecer": _("Cambio de contraseña"), "ticket": _("Ticket ChromGo"),
            "prueba": _("Prueba")}.get(tipo, tipo)


def _visibles(select):
    """Admin y Facturación: todos. Soporte de cliente: solo los enviados a sus clientes (no los internos)."""
    if current_user.rol != "fas":
        return select
    return select.where(CorreoEnviado.tipo.like("cliente.%"),
                        CorreoEnviado.cliente.has(Cliente.logisticos.any(User.id == current_user.id)))


@bp.route("/correos")
@requiere_permiso("correos.ver")
def correos():
    select = _visibles(db.select(CorreoEnviado)).order_by(CorreoEnviado.fecha.desc(), CorreoEnviado.id.desc())
    q = limpiar_busqueda(request.args.get("q"), 100)
    estado = request.args.get("estado") if request.args.get("estado") in ESTADOS else ""
    grupo = request.args.get("grupo") if request.args.get("grupo") in GRUPOS else ""
    dias = request.args.get("dias", 30, type=int)
    dias = dias if dias in (7, 30, 183) else 30
    if q:
        from app.models import Pedido
        patron = f"%{q}%"
        select = select.where(CorreoEnviado.para.ilike(patron) | CorreoEnviado.asunto.ilike(patron)
                              | CorreoEnviado.pedido.has(Pedido.referencia_interna.ilike(patron)))
    if estado:
        select = select.filter_by(estado=estado)
    if grupo == "otros":
        select = select.where(~CorreoEnviado.tipo.like("cliente.%"), ~CorreoEnviado.tipo.like("interno.%"))
    elif grupo:
        select = select.where(CorreoEnviado.tipo.like(f"{grupo}.%"))
    select = select.where(CorreoEnviado.fecha >= ahora() - timedelta(days=dias))
    return render_template("admin/correos.html", title=_("Correos enviados"), pagina=paginar(select), q=q,
                           estado=estado, grupo=grupo, dias=dias, grupos=GRUPOS if current_user.rol != "fas"
                           else {}, estados=ESTADOS, nombre_tipo=nombre_tipo,
                           hay_filtros=bool(q or estado or grupo or dias != 30))


def _correo_o_404(id):
    correo = db.session.scalar(_visibles(db.select(CorreoEnviado).filter_by(id=id)))
    if correo is None:
        abort(404)
    return correo


@bp.route("/correos/<int:id>")
@requiere_permiso("correos.ver")
def correo(id):
    c = _correo_o_404(id)
    reenvios = db.session.scalars(db.select(CorreoEnviado).filter_by(reenvio_de_id=c.id)
                                  .order_by(CorreoEnviado.id)).all()
    return render_template("admin/correo.html", title=c.asunto, c=c, nombre_tipo=nombre_tipo, reenvios=reenvios)


@bp.route("/correos/<int:id>/reenviar", methods=["POST"])
@requiere_permiso("correos.reenviar")
def correo_reenviar(id):
    from flask_wtf import FlaskForm

    from app.correo import reenviar
    if not FlaskForm().validate_on_submit():
        abort(400)
    c = _correo_o_404(id)
    if c.tipo in ("restablecer", "invitacion"):
        flash(_("Este correo lleva un enlace privado que no se guarda: para mandarlo otra vez, usa «Reenviar "
                "invitación» o «¿Has olvidado tu contraseña?»."), "warning")
        return redirect(url_for("admin.correo", id=c.id))
    reenviar(c)
    registrar("editar", None, f"reenvío preparado: «{c.asunto}» → {c.para}", entidad="Correo")
    db.session.commit()
    flash(_("Correo preparado. Revísalo antes de confirmar el reenvío."), "info")
    return redirect(url_for("admin.correo", id=c.id))


@bp.route("/estado")
@requiere_permiso("estado.ver")
def estado():
    return render_template("admin/estado.html", title=_("Estado de la plataforma"), e=estado_.todo(),
                           legible=estado_.legible)
