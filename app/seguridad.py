"""
Administración → Ajustes → Seguridad: plazos y límites del acceso a la plataforma. Solo admin.

  - cuánto vale el enlace de una INVITACIÓN (días) y el de «he olvidado mi contraseña» (horas);
  - cuántos intentos fallidos de entrar con un mismo email bloquean ese email, y durante cuánto;
  - cierre de sesión por INACTIVIDAD: pasadas esas horas sin usar la plataforma hay que volver a
    entrar (0 = no se cierra nunca). Con «Recordarme» la cookie dura eso mismo.

Se guardan en la tabla "ajustes" (seguridad.<clave>); lo que no se ha tocado usa el valor de
fábrica (config.py: INVITACION_DIAS, PASSWORD_RESET_HORAS, LOGIN_MAX_FALLOS_EMAIL,
LOGIN_VENTANA_MINUTOS, SESION_INACTIVIDAD_HORAS). El límite por IP sigue en config.py.
"""
from dataclasses import dataclass
from datetime import timedelta

from flask import current_app, flash, redirect, request, session, url_for
from flask_babel import gettext as _, lazy_gettext as _l
from flask_login import current_user, logout_user, user_loaded_from_cookie

from app.extensions import db
from app.models import Ajuste, ahora


@dataclass
class Campo:
    config: str          # de dónde sale el valor de fábrica (config.py)
    texto: str
    unidad: str
    minimo: int
    maximo: int
    ayuda: str = ""


CAMPOS = {
    "invitacion_dias": Campo("INVITACION_DIAS", _l("Caducidad de la invitación"), _l("días"), 1, 60,
                             _l("Lo que vale el enlace para elegir contraseña que recibe un usuario nuevo.")),
    "reset_horas": Campo("PASSWORD_RESET_HORAS", _l("Caducidad del enlace para cambiar la contraseña"), _l("horas"), 1, 72,
                         _l("El de «¿Has olvidado tu contraseña?».")),
    "fallos": Campo("LOGIN_MAX_FALLOS_EMAIL", _l("Bloquear tras intentos fallidos"), _l("intentos"), 3, 50,
                    _l("Seguidos y con el mismo email.")),
    "ventana_minutos": Campo("LOGIN_VENTANA_MINUTOS", _l("…dentro de"), _l("minutos"), 1, 1440,
                             _l("Y el bloqueo dura eso mismo.")),
    "inactividad_horas": Campo("SESION_INACTIVIDAD_HORAS", _l("Cerrar la sesión por inactividad"), _l("horas"), 0, 720,
                               _l("Sin usar la plataforma ese tiempo, hay que volver a entrar. 0 = no se cierra.")),
}


def _clave(campo):
    return f"seguridad.{campo}"


def de_fabrica(campo) -> int:
    return int(current_app.config[CAMPOS[campo].config])


def valores() -> dict:
    """{campo: número} con lo guardado por admin y, para lo demás, el valor de fábrica."""
    guardados = {a.clave: a.valor for a in db.session.scalars(
        db.select(Ajuste).where(Ajuste.clave.like("seguridad.%")))}
    resultado = {}
    for campo in CAMPOS:
        valor = guardados.get(_clave(campo))
        resultado[campo] = int(valor) if valor is not None and valor.isdigit() else de_fabrica(campo)
    return resultado


def valor(campo) -> int:
    fila = db.session.get(Ajuste, _clave(campo))
    return int(fila.valor) if fila is not None and fila.valor.isdigit() else de_fabrica(campo)


def errores(nuevos: dict) -> dict:
    """{campo: mensaje} de lo que no vale (vacío = todo bien). nuevos: {campo: int o None}."""
    resultado = {}
    for campo, c in CAMPOS.items():
        n = nuevos.get(campo)
        if n is None or not c.minimo <= n <= c.maximo:
            resultado[campo] = _("Escribe un número entre %(min)s y %(max)s.", min=c.minimo, max=c.maximo)
    return resultado


def guardar(nuevos: dict) -> list:
    """Guarda (sin commit) y devuelve los cambios para la auditoría: ["fallos 5→8", ...]. Lo que
    queda igual que el de fábrica no se guarda (así le llegan los cambios de fábrica)."""
    actuales, cambios = valores(), []
    for campo in CAMPOS:
        n = nuevos[campo]
        if n == actuales[campo]:
            continue
        fila = db.session.get(Ajuste, _clave(campo))
        if n == de_fabrica(campo):
            if fila is not None:
                db.session.delete(fila)
        elif fila is None:
            db.session.add(Ajuste(clave=_clave(campo), valor=str(n)))
        else:
            fila.valor = str(n)
        cambios.append(f"{campo} {actuales[campo]}→{n}")
    return cambios


# --------------------------------------------------------------------------- #
# Cierre de sesión por inactividad
# --------------------------------------------------------------------------- #
# En la sesión (cookie firmada) se apunta la hora de la última petición. Si ha pasado más del plazo,
# se cierra la sesión. Con «Recordarme», la cookie de Flask-Login dura también ese plazo y se renueva
# con cada petición: quien vuelve al día siguiente con el navegador cerrado tampoco entra solo.
LIBRES = {"static", "salud", "robots", "auth.login", "auth.logout"}
AUTOMATICAS = {"mensajes.flotante_cuenta", "mensajes.nuevos_cliente", "mensajes.nuevos_pedido",
               "mensajes.nuevos_interno"}


def duracion_recordarme():
    horas = valor("inactividad_horas")
    return timedelta(hours=horas) if horas else None


def registrar(app):
    @app.before_request
    def _cerrar_por_inactividad():
        if request.endpoint in LIBRES or request.endpoint is None or not current_user.is_authenticated:
            return None
        try:
            horas = valor("inactividad_horas")
        except Exception:               # (la tabla aún no existe: p. ej. durante "flask db upgrade")
            db.session.rollback()
            return None
        momento = ahora().timestamp()
        ultima = session.get("ultima_actividad")
        if horas and ultima is not None and momento - ultima > horas * 3600:
            logout_user()
            session.clear()
            flash(_("Has estado un rato sin usar la plataforma y hemos cerrado tu sesión. Vuelve a entrar."), "info")
            return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
        # Las consultas automáticas de la página (contador de mensajes cada minuto, mensajes nuevos de
        # un chat abierto) no cuentan como actividad: una pestaña olvidada no mantiene la sesión abierta
        if request.endpoint in AUTOMATICAS and not request.args.get("abierto"):
            return None
        session["ultima_actividad"] = momento
        if horas and session.get("recordar") and not session.get("ver_como"):
            session["_remember"] = "set"                      # Flask-Login renueva la cookie...
            session["_remember_seconds"] = horas * 3600       # ...con la duración del plazo
        return None

    @user_loaded_from_cookie.connect_via(app)
    def _entro_con_recordarme(sender, user):
        # Volvió con la cookie de «Recordarme»: sigue contando como recordado (para renovarla)
        session["recordar"] = True
