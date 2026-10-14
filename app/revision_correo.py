"""Revisión privada de correos. Nunca envía al consultar o guardar un borrador."""
from datetime import timedelta
from email import policy
from email.parser import BytesParser

from flask import Blueprint, abort, g, has_request_context, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import Cliente, CorreoBorrador, User, ahora

bp = Blueprint("revision_correo", __name__)
EQUIPO = {"admin", "logistica", "fas", "soporte"}


def autor_revision(msg):
    if has_request_context() and g.get("solo_lectura"):
        return None
    if (getattr(msg, "meta", None) or {}).get("tipo") == "restablecer":
        return None
    # El aviso aplazado de un mensaje conserva al autor, no al visitante de la página.
    autor_id = (getattr(msg, "meta", None) or {}).get("revision_autor_id")
    if autor_id:
        usuario = db.session.get(User, autor_id)
        if (getattr(msg, "meta", None) or {}).get("revision_equipo"):
            if usuario is None:
                raise ValueError("El autor del correo pendiente ya no existe; no se envía automáticamente.")
            return usuario.id
        return usuario.id if usuario and usuario.rol in EQUIPO else None
    if has_request_context() and current_user.is_authenticated and current_user.rol in EQUIPO:
        return current_user.id
    return None


def guardar_borrador(msg, autor_id, reenvio_de=None, independiente=False):
    datos = dict(autor_id=autor_id, fecha=ahora(), caduca=ahora() + timedelta(hours=24),
                 estado="pendiente", mensaje=bytes(msg), meta=getattr(msg, "meta", None) or {},
                 reenvio_de_id=reenvio_de, version=1)
    if independiente:
        with Session(db.engine) as sesion:
            sesion.add(CorreoBorrador(**datos))
            sesion.commit()
    else:
        db.session.add(CorreoBorrador(**datos))
    if has_request_context():
        g.correo_para_revision = True


@bp.before_request
@login_required
def comprobar_equipo():
    if current_user.rol not in EQUIPO or not current_user.activo or g.get("solo_lectura"):
        abort(403)


@bp.after_request
def privado(respuesta):
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


def mensaje_de(borrador):
    return BytesParser(policy=policy.default).parsebytes(borrador.mensaje)


def permitido(borrador):
    if current_user.rol == "fas" and borrador.meta.get("cliente_id"):
        from app.alcance import filtrar_clientes
        return db.session.scalar(filtrar_clientes(db.select(Cliente.id)).where(
            Cliente.id == borrador.meta["cliente_id"])) is not None
    return True


def datos_de(borrador):
    msg = mensaje_de(borrador)
    parte = msg.get_body(preferencelist=("plain",)) if msg.is_multipart() else msg
    return dict(id=borrador.id, version=borrador.version, para=str(msg["To"]),
                asunto=str(msg["Subject"]), texto=parte.get_content() if parte else "",
                estado=borrador.estado)


@bp.get("/pendientes")
def pendientes():
    # Los enlaces privados de invitación no se conservan indefinidamente.
    db.session.execute(db.update(CorreoBorrador).where(
        CorreoBorrador.autor_id == current_user.id, CorreoBorrador.caduca < ahora(),
        CorreoBorrador.estado.in_(["pendiente", "fallido"])
    ).values(estado="caducado", mensaje=None))
    db.session.commit()
    filas = db.session.scalars(db.select(CorreoBorrador).where(
        CorreoBorrador.autor_id == current_user.id,
        CorreoBorrador.estado.in_(["pendiente", "fallido"]),
        CorreoBorrador.caduca >= ahora()).order_by(CorreoBorrador.id).limit(50)).all()
    return jsonify(correos=[datos_de(f) for f in filas if permitido(f)])


@bp.post("/<int:id>")
def resolver(id):
    b = db.session.scalar(db.select(CorreoBorrador).where(
        CorreoBorrador.id == id, CorreoBorrador.autor_id == current_user.id))
    if b is None or not permitido(b):
        abort(404)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        return jsonify(error="Petición no válida."), 400
    accion = data.get("accion")
    if accion not in {"guardar", "enviar", "descartar"}:
        return jsonify(error="Acción no válida."), 400
    if b.estado not in {"pendiente", "fallido"} or b.caduca.replace(tzinfo=None) < ahora().replace(tzinfo=None):
        return jsonify(error="Este correo ya no está pendiente o ha caducado. Actualiza la lista."), 409
    msg = mensaje_de(b)
    if accion != "descartar":
        asunto, texto = data.get("asunto"), data.get("texto")
        if not isinstance(asunto, str) or not asunto.strip() or len(asunto) > 300 or any(c in asunto for c in "\r\n"):
            return jsonify(error="Escribe un asunto de hasta 300 caracteres y sin saltos de línea."), 400
        if not isinstance(texto, str) or not texto.strip() or len(texto) > 100000:
            return jsonify(error="Escribe un mensaje de hasta 100.000 caracteres."), 400
        msg.replace_header("Subject", asunto.strip())
        parte = msg.get_body(preferencelist=("plain",)) if msg.is_multipart() else msg
        if parte is None:
            return jsonify(error="Este correo no tiene una versión de texto editable."), 400
        if parte.get_content() != texto:
            parte.set_content(texto)
            html = msg.get_body(preferencelist=("html",)) if msg.is_multipart() else None
            if html:
                from app.correos_cliente import html as componer_html, CID_LOGO
                tiene_logo = any(p.get("Content-ID") == f"<{CID_LOGO}>" for p in msg.walk())
                html.set_content(componer_html(texto, "", src_logo=f"cid:{CID_LOGO}" if tiene_logo else None), subtype="html")
    estado = {"guardar": "pendiente", "enviar": "enviando", "descartar": "descartado"}[accion]
    resultado = db.session.execute(db.update(CorreoBorrador).where(
        CorreoBorrador.id == id, CorreoBorrador.autor_id == current_user.id,
        CorreoBorrador.version == data.get("version"),
        CorreoBorrador.estado.in_(["pendiente", "fallido"])
    ).values(estado=estado, version=CorreoBorrador.version + 1,
             mensaje=None if accion == "descartar" else bytes(msg)), execution_options={"synchronize_session": False})
    if resultado.rowcount != 1:
        db.session.rollback()
        return jsonify(error="El correo ha cambiado en otra pestaña. Actualiza antes de enviarlo."), 409
    meta, reenvio = dict(b.meta), b.reenvio_de_id
    from app.auditoria import registrar
    registrar("editar", None, f"correo {id}: {accion}", entidad="CorreoBorrador")
    db.session.commit()
    if accion == "enviar":
        from app.correo import Correo, _entregar
        # Mantener el tipo que espera el backend de pruebas y el registro.
        msg = BytesParser(policy=policy.default, _class=Correo).parsebytes(bytes(msg))
        msg.meta = meta
        error = _entregar(msg, reenvio_de=reenvio, revisado=True)
        db.session.execute(db.update(CorreoBorrador).where(CorreoBorrador.id == id).values(
            estado="fallido" if error else "enviado", mensaje=bytes(msg) if error else None))
        db.session.commit()
        if error:
            return jsonify(error="No se ha podido confirmar la entrega. Revisa el registro antes de volver a enviar.", version=data.get("version") + 1), 502
    db.session.expire_all()
    return jsonify(ok=True)
