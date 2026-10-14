"""Cabeceras de los correos que ayudan a no caer en spam: fecha, Message-ID con el dominio real del
remitente y, si se configura, Reply-To (a dónde van las respuestas)."""
from email.utils import parsedate_to_datetime

from app.correo import _cabeceras


def _envia(app):
    """Las cabeceras que lleva cualquier correo de la plataforma."""
    with app.test_request_context():
        return _cabeceras(["alguien@ejemplo.com"], "Asunto")


def test_fecha_y_message_id_con_el_dominio_del_remitente(app):
    app.config["MAIL_FROM"] = "Yikon Genomics PO <avisos@yikonsupport.com>"
    msg = _envia(app)
    assert parsedate_to_datetime(msg["Date"]) is not None
    assert msg["Message-ID"].endswith("@yikonsupport.com>")
    assert msg["Reply-To"] is None                                   # sin configurar, no se pone


def test_reply_to_si_se_configura(app):
    app.config.update(MAIL_FROM="avisos@yikonsupport.com", MAIL_REPLY_TO="Yikon España <info@yikon.es>")
    msg = _envia(app)
    assert msg["Reply-To"] == "Yikon España <info@yikon.es>"
