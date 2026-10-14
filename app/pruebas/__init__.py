"""
"Entrar como…": cambiar de usuario de un clic para probar la plataforma con cada rol.

SOLO EN DESARROLLO: el blueprint se registra únicamente si la configuración es "dev"
(app/__init__.py). En producción ni existe la dirección ni sale la barra.
"""
from flask import Blueprint, abort, current_app, redirect, request, url_for
from flask_login import login_user, logout_user

from app.extensions import db
from app.models import User

bp = Blueprint("pruebas", __name__)


@bp.before_request
def solo_desarrollo():
    if current_app.config.get("ENTORNO") != "dev":      # por si acaso: nunca fuera de desarrollo
        abort(404)


@bp.route("/entrar-como", methods=["POST"])
def entrar_como():
    usuario = db.get_or_404(User, request.form.get("usuario_id", type=int))
    if not usuario.activo:
        abort(404)
    logout_user()
    login_user(usuario)
    return redirect(request.form.get("volver") or url_for("main.inicio"))


def usuarios_para_probar():
    """Los usuarios activos, agrupados por rol, para la barra."""
    return db.session.scalars(db.select(User).filter_by(activo=True).order_by(User.rol, User.nombre)).all()
