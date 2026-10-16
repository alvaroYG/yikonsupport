"""
Administración → Ajustes → Datos de Yikon, Proformas y Avisos internos. Solo admin.
La lógica está en app/datos_empresa.py, app/ajustes.py (proformas) y app/avisos_internos.py.
"""
from flask import flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm

from app import ajustes, avisos_internos, datos_empresa
from app.admin.routes import bp
from app.extensions import db
from app.models import RegistroAuditoria
from app.permisos import ROLES, requiere_permiso


def _auditar(detalle):
    db.session.add(RegistroAuditoria(usuario_id=current_user.id, accion="editar", entidad="Ajuste",
                                     objeto=_("Ajustes"), detalle=detalle))


def _guardado(cambios, que):
    if cambios:
        _auditar(f"{que}: " + ", ".join(cambios))
        db.session.commit()
        flash(_("Guardado."), "success")
    else:
        db.session.commit()
        flash(_("No has cambiado nada."), "info")


@bp.route("/ajustes/datos-yikon", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_empresa():
    form = FlaskForm()
    if form.validate_on_submit():
        _guardado(datos_empresa.guardar({c: request.form.get(c, "") for c in datos_empresa.CAMPOS}), "datos de Yikon")
        return redirect(url_for("admin.ajustes_empresa"))
    return render_template("admin/ajustes_empresa.html", title=_("Datos de Yikon"), form=form,
                           campos=datos_empresa.CAMPOS, datos=datos_empresa.datos(),
                           vendedor=datos_empresa.lineas_vendedor(), cabecera=datos_empresa.lineas_cabecera())


@bp.route("/ajustes/proformas", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_proformas():
    form = FlaskForm()
    actuales, error = ajustes.proformas(), None
    if form.validate_on_submit():
        validez = request.form.get("validez", type=int)
        plazo = {i: request.form.get(f"plazo_{i}", "") for i in ajustes.IDIOMAS_PROFORMA}
        notas = {i: request.form.get(f"notas_{i}", "") for i in ajustes.IDIOMAS_PROFORMA}
        if validez is None or not 1 <= validez <= 365:
            error = _("Escribe un número de días entre 1 y 365.")
            actuales = {"validez": request.form.get("validez", ""), "plazo": plazo, "notas": notas}
        else:
            _guardado(ajustes.guardar_proformas(validez, plazo, notas), "proformas por defecto")
            return redirect(url_for("admin.ajustes_proformas"))
    return render_template("admin/ajustes_proformas.html", title=_("Proformas"), form=form, actuales=actuales,
                           error=error, idiomas={"es": _("Español"), "en": _("Inglés")})


@bp.route("/ajustes/avisos-internos", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_avisos():
    form = FlaskForm()
    if form.validate_on_submit():
        if request.form.get("accion") == "fabrica":
            marcados = {(clave, rol) for clave, a in avisos_internos.AVISOS.items() for rol in a.de_fabrica}
        else:
            marcados = {tuple(v.split(":", 1)) for v in request.form.getlist("recibe") if ":" in v}
        _guardado(avisos_internos.guardar(marcados), "avisos internos")
        return redirect(url_for("admin.ajustes_avisos"))
    return render_template("admin/ajustes_avisos.html", title=_("Avisos internos"), form=form,
                           filas=avisos_internos.tabla(),
                           roles=[(r, ROLES[r]) for r in avisos_internos.COLUMNAS])


@bp.route("/ajustes/aviso-clientes", methods=["POST"])
@requiere_permiso("ajustes.editar")
def ajustes_aviso_clientes():
    """Ajustes → General → Aviso para clientes: guardarlo o quitarlo (app/aviso_clientes.py)."""
    from datetime import date

    from app import aviso_clientes
    destino = redirect(url_for("admin.ajustes_panel", tema="comunicaciones", seccion="anuncios") + "#aviso-clientes")
    if not FlaskForm().validate_on_submit():
        return destino
    if request.form.get("accion") == "quitar":
        if cambio := aviso_clientes.quitar():
            _auditar(cambio)
        db.session.commit()
        flash(_("Aviso quitado."), "success")
        return destino

    def fecha(campo):
        try:
            return date.fromisoformat(request.form.get(campo) or "")
        except ValueError:
            return None
    textos = {i: request.form.get(f"aviso_{i}", "") for i in aviso_clientes.IDIOMAS}
    desde, hasta = fecha("desde"), fecha("hasta")
    for problema, maximo in aviso_clientes.errores(textos, desde, hasta):
        flash(_("El aviso es demasiado largo: como mucho %(n)s caracteres.", n=maximo) if problema == "texto"
              else _("La fecha «hasta» no puede ser anterior a «desde»."), "danger")
        return destino
    cambio = aviso_clientes.guardar(textos, desde, hasta)
    if cambio:
        _auditar(cambio)
        db.session.commit()
        flash(_("Aviso guardado.") if any(t.strip() for t in textos.values()) else _("Aviso quitado."), "success")
    else:
        flash(_("No has cambiado nada."), "info")
    return destino


@bp.route("/ajustes/seguridad", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_seguridad():
    """Ajustes → Seguridad: caducidad de los enlaces, bloqueo tras fallos y cierre por inactividad."""
    from app import seguridad
    form = FlaskForm()
    actuales, errores = seguridad.valores(), {}
    if form.validate_on_submit():
        if request.form.get("accion") == "fabrica":
            nuevos = {c: seguridad.de_fabrica(c) for c in seguridad.CAMPOS}
        else:
            nuevos = {c: request.form.get(c, type=int) for c in seguridad.CAMPOS}
        errores = seguridad.errores(nuevos)
        if not errores:
            _guardado(seguridad.guardar(nuevos), "seguridad")
            return redirect(url_for("admin.ajustes_seguridad"))
        actuales = {c: request.form.get(c, "") for c in seguridad.CAMPOS}
    return render_template("admin/ajustes_seguridad.html", title=_("Seguridad"), form=form, campos=seguridad.CAMPOS,
                           actuales=actuales, errores=errores,
                           fabrica={c: seguridad.de_fabrica(c) for c in seguridad.CAMPOS})
