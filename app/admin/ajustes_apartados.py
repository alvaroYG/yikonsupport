"""
Administración → Ajustes → Qué ve cada rol: una casilla por apartado y rol (app/apartados.py).
Solo admin (permiso "ajustes.editar").
"""
from flask import flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm

from app import apartados
from app.admin.routes import bp
from app.extensions import db
from app.models import RegistroAuditoria, User
from app.permisos import ROLES, requiere_permiso


@bp.route("/ajustes/apartados", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_apartados():
    form = FlaskForm()                       # solo para el token CSRF: las casillas son "ver" = "apartado:rol"
    if form.validate_on_submit():
        if request.form.get("accion") == "fabrica":
            marcados = {(clave, rol) for clave, ap in apartados.APARTADOS.items() for rol in ap.cambiables
                        if apartados.de_fabrica(clave, rol)}
        else:
            marcados = {tuple(v.split(":", 1)) for v in request.form.getlist("ver") if ":" in v}
        cambios = apartados.guardar(marcados)
        if cambios:
            db.session.add(RegistroAuditoria(usuario_id=current_user.id, accion="editar", entidad="Ajuste",
                                             detalle="qué ve cada rol: " + ", ".join(cambios)))
            db.session.commit()
            flash(_("Guardado. Cada uno lo verá así desde su próxima página."), "success")
        else:
            db.session.commit()
            flash(_("No has cambiado nada."), "info")
        return redirect(url_for("admin.ajustes_apartados"))
    usuarios = dict(db.session.execute(db.select(User.rol, db.func.count(User.id))
                                       .where(User.activo.is_(True)).group_by(User.rol)).all())
    roles = [(rol, ROLES[rol], usuarios.get(rol, 0)) for rol in apartados.ROLES_EN_ORDEN]
    return render_template("admin/ajustes_apartados.html", title=_("Qué ve cada rol"), form=form,
                           filas=apartados.tabla(), roles=roles)
