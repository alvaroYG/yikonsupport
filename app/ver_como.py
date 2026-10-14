"""
"Ver como un usuario" (solo admin): ver la plataforma exactamente como la ve otra persona, para
entender lo que le pasa ("no me sale el botón", "no veo el pedido") sin pedirle su contraseña.

Reglas:
  - Solo admin, y no sirve para ver como otro admin (ni como un usuario desactivado).
  - SOLO LECTURA: mientras dura, nada se guarda ni se envía. Dos capas:
      1. Cualquier envío de formulario (POST…) se rechaza, salvo volver a tu usuario, salir y
         cambiar el idioma (que solo cambia la sesión).
      2. Además, toda la petición va dentro de una transacción de la base de datos que se deshace
         al terminar (aunque el código haga commit): así tampoco queda lo que se apunta solo al
         abrir páginas (mensajes leídos, "visto" de un pedido, último acceso...). Y no sale ningún
         correo (app/correo.py mira g.solo_lectura).
  - Arriba de todas las páginas sale una franja con a quién estás viendo y el botón para volver.
  - Queda en la auditoría (acción "Ver como", sobre el usuario).

En la sesión se guarda {"admin_id", "usuario_id"}: quién es de verdad y a quién está viendo.
"""
from flask import abort, flash, g, jsonify, redirect, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_user, logout_user
from sqlalchemy.orm import Session

from app.extensions import db

CLAVE = "ver_como"
# Lo único que se puede enviar mientras se ve como otro
PERMITIDOS = {"auth.dejar_de_ver_como", "auth.logout", "main.cambiar_idioma"}
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}


def activo() -> bool:
    return bool(session.get(CLAVE))


def se_puede_ver_como(admin, usuario) -> bool:
    return (admin.rol == "admin" and admin.activo and usuario.id != admin.id
            and usuario.activo and usuario.rol != "admin")


def empezar(admin, usuario):
    """Apunta en la auditoría (y la guarda) y cambia la sesión al usuario. Quien llama ya ha
    comprobado se_puede_ver_como()."""
    from app.auditoria import registrar
    registrar("ver_como", usuario, "solo lectura")
    db.session.commit()
    recordar = session.get("recordar")
    login_user(usuario)                     # (sin «Recordarme»: la cookie del admin, si tenía, sigue siendo suya)
    # Nunca se renueva la cookie de «Recordarme» mientras se ve como otro (app/seguridad.py): si no,
    # al volver a abrir el navegador se entraría como ese usuario, y ya sin solo lectura
    session["recordar"] = False
    session.pop("_remember", None)
    session[CLAVE] = {"admin_id": admin.id, "usuario_id": usuario.id, "recordar": bool(recordar)}


def terminar():
    """Vuelve al admin. Devuelve False si el admin ya no existe o ya no es admin (entonces se sale)."""
    from app.models import User
    datos = session.pop(CLAVE, None) or {}
    admin = db.session.get(User, datos.get("admin_id") or 0)
    if admin is None or not admin.activo or admin.rol != "admin":
        logout_user()
        session.clear()
        return False
    login_user(admin)
    session["recordar"] = datos.get("recordar", False)
    return True


# --------------------------------------------------------------------------- #
# Solo lectura
# --------------------------------------------------------------------------- #
def _abrir_transaccion_que_se_deshace():
    """La sesión de base de datos de esta petición va dentro de una transacción que se deshace al
    final: los commit de las vistas solo "guardan" dentro de ella (savepoints)."""
    conexion = db.engine.connect()
    sqlite = conexion.dialect.name == "sqlite"
    crudo, antes = conexion.connection.driver_connection, None
    if sqlite:
        # El driver de SQLite no abre la transacción él solo de forma que se pueda deshacer con
        # savepoints dentro: se le pide que no lo gestione y se abre a mano (receta de SQLAlchemy).
        antes, crudo.isolation_level = crudo.isolation_level, None
    transaccion = conexion.begin()
    if sqlite:
        conexion.exec_driver_sql("BEGIN")
    previa = db.session.registry() if db.session.registry.has() else None
    db.session.registry.set(Session(bind=conexion, join_transaction_mode="create_savepoint"))
    g._solo_lectura_bd = (conexion, transaccion, sqlite, antes, previa)


def _deshacer_transaccion():
    datos = g.pop("_solo_lectura_bd", None)
    if not datos:
        return
    # (En producción `g` muere con la petición; en los tests se comparte entre peticiones: se limpia
    #  aquí lo de esta, también el usuario cargado, que era de la sesión de base de datos que se cierra)
    for clave in ("solo_lectura", "ver_como_admin", "_login_user"):
        g.pop(clave, None)
    conexion, transaccion, sqlite, antes, previa = datos
    try:
        db.session.close()
        transaccion.rollback()
        if sqlite:
            conexion.connection.driver_connection.isolation_level = antes
    finally:
        conexion.close()
        if previa is not None:
            db.session.registry.set(previa)
        else:
            db.session.registry.clear()


def _rechazar():
    mensaje = _("Estás viendo la plataforma como otra persona: no se puede guardar ni enviar nada.")
    if request.headers.get("X-Requested-With") or request.accept_mimetypes.best == "application/json" \
            or request.headers.get("Sec-Fetch-Mode") in ("cors", "same-origin"):
        return jsonify(error=mensaje), 403
    flash(mensaje, "warning")
    from app.utils import es_url_segura
    from urllib.parse import urlsplit
    anterior = request.referrer or ""
    partes = urlsplit(anterior)
    destino = partes.path + (f"?{partes.query}" if partes.query else "")
    if partes.netloc != request.host or not es_url_segura(destino):
        destino = url_for("main.inicio")
    return redirect(destino)


def registrar(app):
    """Se registra ANTES que los demás before_request: el resto de la petición (también cargar el
    usuario conectado) ya usa la sesión de base de datos que se deshace."""

    @app.before_request
    def _solo_lectura():
        if request.endpoint == "static" or not activo():
            return None
        g.solo_lectura = True
        _abrir_transaccion_que_se_deshace()
        datos = session.get(CLAVE) or {}
        from app.models import User
        admin = db.session.get(User, datos.get("admin_id") or 0)
        if admin is None or not admin.activo or admin.rol != "admin" or session.get("_user_id") != str(datos.get("usuario_id")):
            # Algo no cuadra (le han quitado el admin, la sesión es de otro…): fuera
            session.clear()
            logout_user()
            return redirect(url_for("auth.login"))
        g.ver_como_admin = admin.nombre
        if request.method not in METODOS_LECTURA and request.endpoint not in PERMITIDOS:
            return _rechazar()
        return None

    @app.teardown_request
    def _fin_solo_lectura(_error=None):
        _deshacer_transaccion()

    @app.context_processor
    def _franja_ver_como():
        if not activo() or not current_user.is_authenticated:
            return {}
        return {"ver_como": {"admin": g.get("ver_como_admin", ""), "usuario": current_user}}


def solo_lectura() -> bool:
    """¿Esta petición es de alguien que está viendo como otro? (nada se guarda ni se envía)"""
    from flask import has_request_context
    return has_request_context() and bool(g.get("solo_lectura"))


def comprobar_admin(usuario):
    """Para la vista que empieza: 404 si no se puede ver como este usuario."""
    if not se_puede_ver_como(current_user, usuario):
        abort(404)
