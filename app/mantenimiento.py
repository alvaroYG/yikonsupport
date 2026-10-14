"""
Modo mantenimiento (Administración → Ajustes → General): mientras está activado solo entra admin.
Los demás ven "Estamos actualizando la plataforma" (con el mensaje que escriba admin), también
si ya tenían la sesión abierta. La página de entrar sigue funcionando, para que admin pueda entrar.
Se guarda en la tabla "ajustes": mantenimiento = "1" y mantenimiento.mensaje.
"""
from flask import render_template, request
from flask_login import current_user

from app.extensions import db
from app.models import Ajuste

# Lo que sigue funcionando para todos: entrar/salir, archivos estáticos y el cambio de idioma
LIBRES = {"auth.login", "auth.logout", "static", "main.cambiar_idioma", "auth.dejar_de_ver_como"}


def estado():
    """(activado, mensaje)"""
    filas = {a.clave: a.valor for a in db.session.scalars(
        db.select(Ajuste).where(Ajuste.clave.in_(["mantenimiento", "mantenimiento.mensaje"])))}
    return filas.get("mantenimiento") == "1", filas.get("mantenimiento.mensaje", "")


def guardar(activado, mensaje):
    """Sin commit. Devuelve el texto para la auditoría (o "" si no cambia nada)."""
    antes, mensaje_antes = estado()
    mensaje = (mensaje or "").strip()[:500]
    for clave, valor in (("mantenimiento", "1" if activado else ""), ("mantenimiento.mensaje", mensaje)):
        fila = db.session.get(Ajuste, clave)
        if not valor:
            if fila is not None:
                db.session.delete(fila)
        elif fila is None:
            db.session.add(Ajuste(clave=clave, valor=valor))
        else:
            fila.valor = valor
    if antes != activado:
        return "modo mantenimiento " + ("activado" if activado else "desactivado")
    return "mensaje de mantenimiento" if mensaje != mensaje_antes else ""


def registrar(app):
    @app.before_request
    def _solo_admin_en_mantenimiento():
        if request.endpoint in LIBRES or request.endpoint is None:
            return None
        try:
            activado, mensaje = estado()
        except Exception:               # (la tabla aún no existe: p. ej. durante "flask db upgrade")
            db.session.rollback()
            return None
        if not activado or (current_user.is_authenticated and current_user.rol == "admin"):
            return None
        if not current_user.is_authenticated:
            return None                 # → irá a la página de entrar, que ya avisa
        return render_template("main/mantenimiento.html", mensaje=mensaje), 503

    @app.context_processor
    def _aviso_mantenimiento():
        try:
            activado, mensaje = estado()
        except Exception:
            db.session.rollback()
            return {}
        return {"mantenimiento_activo": activado, "mantenimiento_mensaje": mensaje}
