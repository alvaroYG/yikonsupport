"""
Envío de correos, con la librería estándar de Python (smtplib), sin dependencias.

Tres "backends" según la configuración:
  - smtp     → se envía de verdad (producción; hace falta MAIL_SERVER en el .env)
  - archivo  → se guarda como .eml en instance/correos/ (desarrollo, sin MAIL_SERVER).
               Los .eml se abren con Outlook/Thunderbird y ves el correo tal cual.
  - memoria  → se guarda en una lista (tests)

Un fallo al enviar NUNCA rompe la petición del usuario: se registra en el log y ya.

Además, los avisos se envían solo DESPUÉS de que el cambio se guarde en la base de
datos (commit). Si el guardado falla, no sale ningún correo anunciando algo que no pasó.
"""
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, g, has_request_context
from sqlalchemy import event
from sqlalchemy.orm import Session


def _backend():
    cfg = current_app.config
    return cfg.get("MAIL_BACKEND") or ("smtp" if cfg.get("MAIL_SERVER") else "archivo")


class Correo(EmailMessage):
    """Un EmailMessage que, si va en texto + HTML, devuelve el TEXTO con get_content() (lo que
    leen el log y los tests), en vez de dar error por ser de varias partes.
    meta: para el registro de correos enviados ({"tipo", "cliente_id", "pedido_id", "sin_cuerpo"})."""
    meta = None

    def get_content(self, *args, **kwargs):
        if self.is_multipart():
            return self.get_body(preferencelist=("plain",)).get_content(*args, **kwargs)
        return super().get_content(*args, **kwargs)


def _cabeceras(destinatarios, asunto):
    destinatarios = sorted({d for d in destinatarios if d})
    if not destinatarios:
        return None
    msg = Correo()
    msg["Subject"] = asunto
    msg["From"] = current_app.config["MAIL_FROM"]
    msg["To"] = ", ".join(destinatarios)
    msg["Message-ID"] = make_msgid(domain="plataforma")
    return msg


def _construir(destinatarios, asunto, plantilla, contexto):
    """Prepara el correo. Se usa jinja_env directamente (no render_template) para no
    ejecutar los context processors de la web, que hacen consultas a la base de datos."""
    msg = _cabeceras(destinatarios, asunto)
    if msg is None:
        return None
    cuerpo = current_app.jinja_env.get_template(f"correos/{plantilla}.txt").render(**contexto)
    msg.set_content(cuerpo)
    return msg


def construir_compuesto(destinatarios, compuesto):
    """Un correo al cliente ya compuesto (app/correos_cliente.componer): texto + HTML, con el logo
    dentro del propio correo (así se ve aunque el programa de correo bloquee las imágenes de internet)."""
    from app.correos_cliente import CID_LOGO
    msg = _cabeceras(destinatarios, compuesto["asunto"])
    if msg is None:
        return None
    msg.set_content(compuesto["texto"])
    msg.add_alternative(compuesto["html"], subtype="html")
    if compuesto.get("logo"):
        datos, tipo, subtipo = compuesto["logo"]
        msg.get_payload()[1].add_related(datos, maintype=tipo, subtype=subtipo, cid=f"<{CID_LOGO}>",
                                         filename=f"logo.{subtipo}", disposition="inline")
    return msg


def _entregar(msg, reenvio_de=None, *, revisado=False):
    """Envía (o guarda) un correo ya construido y lo apunta en el registro. Nunca lanza excepciones."""
    if has_request_context() and g.get("solo_lectura"):
        # Admin viendo la plataforma como otro usuario (app/ver_como.py): no sale nada
        current_app.logger.info("Correo no enviado (ver como, solo lectura): %s", msg["Subject"])
        return
    from app.revision_correo import autor_revision, guardar_borrador
    autor = None if revisado or getattr(msg, "revision_resuelta", False) else autor_revision(msg)
    if autor:
        guardar_borrador(msg, autor, reenvio_de, independiente=True)
        return None
    error = None
    try:
        backend = _backend()
        if backend == "memoria":
            current_app.extensions.setdefault("correos_enviados", []).append(msg)
        elif backend == "archivo":
            carpeta = os.path.join(current_app.instance_path, "correos")
            os.makedirs(carpeta, exist_ok=True)
            nombre = (f"{datetime.now():%Y%m%d_%H%M%S_%f}_"
                      f"{re.sub(r'[^A-Za-z0-9]+', '_', msg['Subject'])[:40]}.eml")
            with open(os.path.join(carpeta, nombre), "wb") as f:
                f.write(bytes(msg))
            current_app.logger.info("Correo guardado (no enviado, falta MAIL_SERVER): %s → %s",
                                    msg["Subject"], msg["To"])
        else:
            cfg = current_app.config
            with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as smtp:
                if cfg.get("MAIL_USE_TLS"):
                    smtp.starttls()
                if cfg.get("MAIL_USERNAME"):
                    smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                smtp.send_message(msg)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:1000]
        current_app.logger.exception("No se pudo enviar el correo «%s» a %s",
                                     msg["Subject"], msg["To"])
    _registrar(msg, error, reenvio_de)
    return error


def _partes(msg):
    """(texto, html) de un correo, para guardarlos en el registro."""
    if not msg.is_multipart():
        return msg.get_content(), None
    texto = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    return (texto.get_content() if texto else None), (html.get_content() if html else None)


def _registrar(msg, error, reenvio_de=None):
    """Apunta el correo en el registro (Administración → Correos enviados), en una transacción
    aparte: se llama justo después del commit, cuando la sesión de la petición ya ha terminado.
    Borra de paso lo que tenga más de CORREOS_REGISTRO_DIAS. Si algo falla, solo se anota en el log."""
    from datetime import timedelta

    from sqlalchemy.orm import Session as SesionAparte

    from app.extensions import db
    from app.models import CorreoEnviado, ahora
    meta = getattr(msg, "meta", None) or {}
    try:
        texto, html = _partes(msg)
        if meta.get("sin_cuerpo"):            # (p. ej. restablecer contraseña: lleva un enlace que no debe quedar)
            texto, html = "(" + "no se guarda el texto: lleva un enlace privado" + ")", None
        with SesionAparte(db.engine) as sesion:
            sesion.add(CorreoEnviado(
                fecha=ahora(), para=str(msg["To"]), asunto=str(msg["Subject"])[:300], tipo=meta.get("tipo"),
                cliente_id=meta.get("cliente_id"), pedido_id=meta.get("pedido_id"),
                estado="fallido" if error else "enviado", error=error, texto=texto, html=html,
                reenvio_de_id=reenvio_de))
            dias = current_app.config.get("CORREOS_REGISTRO_DIAS", 183)
            sesion.execute(db.delete(CorreoEnviado).where(CorreoEnviado.fecha < ahora() - timedelta(days=dias)))
            sesion.commit()
    except Exception:
        current_app.logger.exception("No se pudo apuntar en el registro el correo «%s»", msg["Subject"])


def reenviar(registro):
    """Vuelve a mandar un correo del registro (el logo, si llevaba, se vuelve a poner)."""
    from app.correos_cliente import CID_LOGO, logo
    msg = _cabeceras([d.strip() for d in registro.para.split(",")], registro.asunto)
    if msg is None:
        return
    msg.meta = {"tipo": registro.tipo, "cliente_id": registro.cliente_id, "pedido_id": registro.pedido_id}
    msg.set_content(registro.texto or "")
    if registro.html:
        msg.add_alternative(registro.html, subtype="html")
        imagen = logo() if f"cid:{CID_LOGO}" in registro.html else None
        if imagen:
            datos, tipo, subtipo = imagen
            msg.get_payload()[1].add_related(datos, maintype=tipo, subtype=subtipo, cid=f"<{CID_LOGO}>",
                                             filename=f"logo.{subtipo}", disposition="inline")
    _entregar(msg, reenvio_de=registro.id)


def enviar(destinatarios, asunto, plantilla, meta=None, **contexto):
    """Envía YA un correo usando la plantilla templates/correos/<plantilla>.txt"""
    msg = _construir(destinatarios, asunto, plantilla, contexto)
    if msg:
        msg.meta = meta
        _entregar(msg)


def enviar_tras_guardar(destinatarios, asunto, plantilla, meta=None, **contexto):
    """
    Construye el correo AHORA (todavía se puede consultar la base de datos) y lo deja
    en cola; se entrega cuando la base de datos confirme el cambio (commit).
    meta: lo que se apunta en el registro de correos ({"tipo", "cliente_id", "pedido_id"}).
    """
    _a_la_cola(_construir(destinatarios, asunto, plantilla, contexto), meta)


def enviar_al_cliente_tras_guardar(destinatarios, clave, idioma, valores, meta=None):
    """Igual, para los correos al cliente con texto editable (app/correos_cliente.py)."""
    from app.correos_cliente import componer
    _a_la_cola(construir_compuesto(destinatarios, componer(clave, idioma, valores)),
               {"tipo": f"cliente.{clave}", **(meta or {})})


def _a_la_cola(msg, meta=None):
    if msg is None:
        return
    if meta:
        msg.meta = meta
    from app.revision_correo import autor_revision, guardar_borrador
    autor = autor_revision(msg)
    if autor:
        guardar_borrador(msg, autor)
        return
    if not has_request_context():
        return _entregar(msg)
    msg.revision_resuelta = True
    g.setdefault("correos_pendientes", []).append(msg)


@event.listens_for(Session, "after_commit")
def _enviar_pendientes(session):
    from app.extensions import db
    if has_request_context() and session is db.session():
        for msg in g.pop("correos_pendientes", []):
            _entregar(msg)


@event.listens_for(Session, "after_rollback")
def _descartar_pendientes(session):
    from app.extensions import db
    if has_request_context() and session is db.session():
        g.pop("correos_pendientes", None)
