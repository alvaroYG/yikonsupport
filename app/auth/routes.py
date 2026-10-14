from datetime import timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import seguridad
from app.auditoria import registrar
from app.auth.forms import CambiarPasswordForm, LoginForm, OlvideForm, RestablecerForm
from app.notificaciones import enviar_restablecer_password
from app.extensions import db
from app.models import IntentoLogin, User, ahora
from app.utils import es_url_segura

bp = Blueprint("auth", __name__)

# Nota: NO hay ruta de registro. Los usuarios los crea un administrador.


def _ip():
    # En producción, detrás de nginx, es la IP real del visitante gracias a app/produccion.py
    return (request.remote_addr or "?")[:45]


def _demasiados_fallos(email):
    """¿Hay demasiados fallos recientes con este email o desde esta IP? (el límite por email y la
    ventana los decide admin en Ajustes → Seguridad; el de la IP está en config.py)"""
    cfg = current_app.config
    desde = ahora() - timedelta(minutes=seguridad.valor("ventana_minutos"))
    fallos = db.select(db.func.count(IntentoLogin.id)).where(
        IntentoLogin.exito.is_(False), IntentoLogin.fecha >= desde)
    por_email = db.session.scalar(fallos.where(IntentoLogin.email == email))
    por_ip = db.session.scalar(fallos.where(IntentoLogin.ip == _ip()))
    return por_email >= seguridad.valor("fallos") or por_ip >= cfg["LOGIN_MAX_FALLOS_IP"]


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if _demasiados_fallos(email):
            # Ni siquiera comprobamos la contraseña: así no sirve seguir probando
            current_app.logger.warning("Login bloqueado temporalmente: %s desde %s", email, _ip())
            flash(_("Demasiados intentos fallidos. Espera %(minutos)s "
                    "minutos o usa «¿Has olvidado tu contraseña?».",
                    minutos=seguridad.valor("ventana_minutos")), "danger")
            return render_template("auth/login.html", title=_("Entrar"), form=form), 429
        user = db.session.scalar(db.select(User).filter_by(email=email))
        if user and user.activo and user.check_password(form.password.data):
            # «Recordarme»: con cierre por inactividad (Ajustes → Seguridad), la cookie dura ese plazo
            login_user(user, remember=form.recordar.data,
                       duration=seguridad.duracion_recordarme() if form.recordar.data else None)
            session["recordar"] = bool(form.recordar.data)
            user.ultimo_acceso = ahora()
            db.session.add(IntentoLogin(email=email, ip=_ip(), exito=True))
            # un login correcto "perdona" los fallos anteriores de ese email
            db.session.execute(db.delete(IntentoLogin).where(
                IntentoLogin.email == email, IntentoLogin.exito.is_(False)))
            registrar("login", user)
            db.session.commit()
            destino = request.args.get("next")
            return redirect(destino if es_url_segura(destino) else url_for("main.inicio"))
        db.session.add(IntentoLogin(email=email, ip=_ip(), exito=False))
        db.session.commit()
        # Mismo mensaje exista o no el usuario: no damos pistas a un atacante.
        flash(_("Email o contraseña incorrectos."), "danger")
    return render_template("auth/login.html", title=_("Entrar"), form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()  # borra también mensajes pendientes u otros restos del usuario anterior
    flash(_("Has cerrado sesión."), "info")
    return redirect(url_for("auth.login"))


@bp.route("/dejar-de-ver-como", methods=["POST"])
@login_required
def dejar_de_ver_como():
    """Fin de "ver como un usuario": vuelve a la sesión del admin (app/ver_como.py)."""
    from app import ver_como
    if not ver_como.activo():
        return redirect(url_for("main.inicio"))
    if not ver_como.terminar():
        flash(_("Tu usuario ya no es administrador: vuelve a entrar."), "warning")
        return redirect(url_for("auth.login"))
    flash(_("Has vuelto a tu usuario."), "success")
    return redirect(url_for("admin.usuarios"))


@bp.route("/cuenta", methods=["GET", "POST"])
@login_required
def cuenta():
    form = CambiarPasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.actual.data):
            flash(_("La contraseña actual no es correcta."), "danger")
        else:
            current_user.set_password(form.nueva.data)
            registrar("editar", current_user, "cambio de contraseña")
            db.session.commit()
            flash(_("Contraseña actualizada."), "success")
            return redirect(url_for("auth.cuenta"))
    return render_template("auth/cuenta.html", title=_("Mi cuenta"), form=form)


# --------------------------------------------------------------------------- #
# "¿Has olvidado tu contraseña?"
# --------------------------------------------------------------------------- #
# El enlace lleva un token FIRMADO con la SECRET_KEY (nadie puede fabricarlo) que caduca.
# Incluye un trozo del hash de la contraseña actual: en cuanto se cambia la contraseña,
# el hash cambia y el enlace deja de servir. Así cada enlace solo se puede usar una vez.
# El "salt" separa los usos: un token de recuperar contraseña no sirve como invitación
# (ni al revés), aunque los dos estén firmados con la misma SECRET_KEY.
def _serializador(proposito="restablecer-password"):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=proposito)


def _crear_token(user, proposito="restablecer-password"):
    return _serializador(proposito).dumps({"id": user.id, "h": user.password_hash[-16:]})


def crear_token_invitacion(user):
    return _crear_token(user, "invitacion")


def _usuario_del_token(token, proposito="restablecer-password", max_age=None):
    try:
        datos = _serializador(proposito).loads(
            token, max_age=max_age or seguridad.valor("reset_horas") * 3600)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, datos.get("id"))
    if not user or not user.activo or user.password_hash[-16:] != datos.get("h"):
        return None
    return user


@bp.route("/olvide", methods=["GET", "POST"])
def olvide():
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))
    form = OlvideForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(db.select(User).filter_by(email=email, activo=True))
        if user:
            enlace = url_for("auth.restablecer", token=_crear_token(user), _external=True)
            enviar_restablecer_password(user, enlace, seguridad.valor("reset_horas"))
            registrar("editar", user, "solicitó restablecer contraseña")
            db.session.commit()
        # MISMO mensaje exista o no la cuenta: no revelamos qué emails están registrados
        flash(_("Si ese email tiene cuenta, te hemos enviado un enlace para elegir una contraseña nueva."),
              "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/olvide.html", title=_("Recuperar contraseña"), form=form)


@bp.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer(token):
    if current_user.is_authenticated:
        return redirect(url_for("main.inicio"))
    user = _usuario_del_token(token)
    if user is None:
        flash(_("El enlace no es válido o ha caducado. Pide uno nuevo."), "danger")
        return redirect(url_for("auth.olvide"))
    form = RestablecerForm()
    if form.validate_on_submit():
        user.set_password(form.nueva.data)
        # los fallos de login anteriores ya no deben bloquearle
        db.session.execute(db.delete(IntentoLogin).where(
            IntentoLogin.email == user.email, IntentoLogin.exito.is_(False)))
        registrar("editar", user, "contraseña restablecida por email")
        db.session.commit()
        flash(_("Contraseña cambiada. Ya puedes entrar."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/restablecer.html", title=_("Nueva contraseña"), form=form)



# --------------------------------------------------------------------------- #
# Invitación: el usuario nuevo elige su propia contraseña
# --------------------------------------------------------------------------- #
# Mismo mecanismo que "restablecer": token firmado, caduca (Ajustes → Seguridad) y deja
# de valer en cuanto el usuario pone su contraseña (cambia el hash).
@bp.route("/invitacion/<token>", methods=["GET", "POST"])
def invitacion(token):
    user = _usuario_del_token(token, "invitacion",
                              max_age=seguridad.valor("invitacion_dias") * 86400)
    # Una invitación es para ENTRAR POR PRIMERA VEZ: si ya ha entrado (p. ej. con una
    # contraseña que le dio el admin), el enlace ya no sirve
    if user is None or user.ultimo_acceso is not None:
        flash(_("La invitación no es válida o ha caducado. Pide a un administrador que te la reenvíe."), "danger")
        return redirect(url_for("auth.login"))
    form = RestablecerForm()
    if form.validate_on_submit():
        user.set_password(form.nueva.data)
        user.ultimo_acceso = ahora()
        registrar("editar", user, "aceptó la invitación y eligió su contraseña")
        db.session.commit()
        if current_user.is_authenticated:
            logout_user()                  # p. ej. el admin probando el enlace en su navegador
        login_user(user)
        flash(_("¡Bienvenido/a, %(nombre)s! Tu cuenta ya está lista.", nombre=user.nombre), "success")
        return redirect(url_for("main.inicio"))
    return render_template("auth/restablecer.html", title=_("Activa tu cuenta"), form=form,
                           titulo=_("Hola, %(nombre)s: elige tu contraseña", nombre=user.nombre),
                           texto=_("Te han dado de alta en la plataforma de pedidos de Yikon Genomics. Elige una contraseña para entrar."))
