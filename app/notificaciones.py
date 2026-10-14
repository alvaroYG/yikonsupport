"""
Qué avisos se mandan por email y a quién. Las plantillas están en templates/correos/.

Ojo: a las plantillas les pasamos TEXTOS ya preparados (no objetos de la base de datos),
porque el correo se genera justo después del commit y ahí ya no se pueden hacer consultas.
"""
from collections import defaultdict

from flask import url_for
from flask_babel import force_locale, gettext as _

from app import avisos_cliente, avisos_internos, correos_cliente
from app.correo import enviar_al_cliente_tras_guardar, enviar_tras_guardar
from app.permisos import NOMBRE_FAS


def _por_idioma_de(usuarios):
    grupos = defaultdict(list)
    for u in usuarios:
        grupos[u.idioma or "es"].append(u.email)
    return grupos


def _datos_pedido(pedido):
    return {
        "referencia": pedido.referencia_interna or f"#{pedido.id}",
        "referencia_cliente": pedido.referencia,
        "cliente": pedido.cliente.nombre,
        "kits": pedido.resumen_contenido("\n").split("\n") if pedido.lineas else [],
        "enlace": url_for("pedidos.detalle", id=pedido.id, _external=True),
        "entrega_estimada": (pedido.fecha_entrega_estimada.strftime("%d/%m/%Y")
                             if pedido.fecha_entrega_estimada else None),
        "transportista": pedido.transportista,
        "numero_seguimiento": pedido.numero_seguimiento,
        "enlace_seguimiento": pedido.enlace_seguimiento,
    }


def avisar_revisar_urgente(pedido, comentario, quien):
    """El FAS ha devuelto el pedido a preparación (fotos rechazadas) → email a quien diga Ajustes →
    Avisos internos (de fábrica: Logística y admin)."""
    datos = _datos_pedido(pedido)
    for idioma, emails in _por_idioma_de(avisos_internos.destinatarios("devuelto", pedido.cliente)).items():
        with force_locale(idioma):         # asunto y plantilla se traducen a ese idioma
            enviar_tras_guardar(
                emails, _("⚠ Devuelto por %(rol)s: pedido %(ref)s (%(cliente)s)", rol=NOMBRE_FAS,
                          ref=datos["referencia"], cliente=datos["cliente"]),
                "revisar_urgente", meta={"tipo": "interno.devuelto", "cliente_id": pedido.cliente_id,
                                         "pedido_id": pedido.id}, comentario=comentario, quien=quien, **datos)


def avisar_recibido(pedido, quien):
    """El cliente ha marcado el pedido como recibido → email a quien diga Ajustes → Avisos internos
    (de fábrica: admin y el Soporte de cliente de ese cliente)."""
    datos = _datos_pedido(pedido)
    for idioma, emails in _por_idioma_de(avisos_internos.destinatarios("recibido", pedido.cliente)).items():
        with force_locale(idioma):
            enviar_tras_guardar(emails, _("✓ Recibido: pedido %(ref)s (%(cliente)s)",
                                          ref=datos["referencia"], cliente=datos["cliente"]),
                                "recibido", meta={"tipo": "interno.recibido", "cliente_id": pedido.cliente_id,
                                                  "pedido_id": pedido.id}, quien=quien, **datos)


def avisar_cambio_estado_cliente(pedido, estado_cliente_antes, motivo=None):
    """
    Email a los usuarios de la empresa cliente cuando cambia el estado QUE ELLOS VEN.
    Los pasos internos (fotos, validación...) son todos "En preparación": no generan correo.
    El texto lo puede cambiar admin (app/correos_cliente.py: un caso por estado).
    """
    if pedido.estado_cliente == estado_cliente_antes:
        return
    clave = pedido.estado_cliente
    if clave == "aceptado" and motivo == "proforma_aceptada":
        clave = "aceptado_proforma"
    if clave not in correos_cliente.CASOS:
        return
    # Solo a quien tiene marcado ese tipo de aviso, y a los emails en copia (ficha del cliente)
    grupos = avisos_cliente.por_idioma(pedido.cliente, correos_cliente.TIPO_DE_CASO.get(clave))
    for idioma, emails in grupos.items():
        with force_locale(idioma):
            enviar_al_cliente_tras_guardar(emails, clave, idioma, correos_cliente.valores_de_pedido(pedido),
                                           {"cliente_id": pedido.cliente_id, "pedido_id": pedido.id})


def avisar_datos_envio(pedido):
    """Han cambiado la fecha estimada o el seguimiento de un pedido ya enviado → email al cliente."""
    grupos = avisos_cliente.por_idioma(pedido.cliente, correos_cliente.TIPO_DE_CASO["datos_envio"])
    for idioma, emails in grupos.items():
        with force_locale(idioma):
            enviar_al_cliente_tras_guardar(emails, "datos_envio", idioma, correos_cliente.valores_de_pedido(pedido),
                                           {"cliente_id": pedido.cliente_id, "pedido_id": pedido.id})


def _correo_de_acceso(usuario, clave, enlace, caducidad, tipo, **mas):
    """Invitación o cambiar contraseña: con el texto, la firma y el logo de Ajustes → Correos al cliente,
    en el idioma del usuario. No se guarda el texto en el registro de correos: lleva un enlace privado."""
    idioma = usuario.idioma or "es"
    with force_locale(idioma):
        valores = {"nombre": usuario.nombre, "email": usuario.email, "enlace_acceso": enlace,
                   "caducidad": caducidad(), **mas}
        enviar_al_cliente_tras_guardar([usuario.email], clave, idioma, valores,
                                       {"tipo": tipo, "sin_cuerpo": True, "cliente_id": usuario.cliente_id})


def enviar_restablecer_password(usuario, enlace, horas):
    from flask_babel import ngettext
    _correo_de_acceso(usuario, "restablecer", enlace, lambda: ngettext("%(num)s hora", "%(num)s horas", horas),
                      "restablecer")


def enviar_invitacion(usuario, enlace, dias, invita):
    """Alta de un usuario: le llega un enlace para elegir su contraseña (en su idioma)."""
    from flask_babel import ngettext
    _correo_de_acceso(usuario, "invitacion", enlace, lambda: ngettext("%(num)s día", "%(num)s días", dias),
                      "invitacion", invita=invita)
