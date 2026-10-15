"""
Correos que reciben los CLIENTES con las novedades de sus pedidos.

Admin cambia sus textos desde Administración → Ajustes → Correos al cliente:
  - Cada caso (CASOS) tiene un texto de fábrica, traducido al idioma del cliente. Admin puede
    cambiarlo en español y en inglés por separado (tabla plantillas_correo). "Volver al original"
    borra el cambio y vuelve a salir el de fábrica.
  - Los textos llevan DATOS entre llaves: {referencia}, {enlace}… Si una línea lleva un dato que
    este pedido no tiene (p. ej. {seguimiento} sin nº de seguimiento), esa línea no sale; y si en
    un párrafo no queda ningún dato, no sale el párrafo entero.
  - No es Jinja a propósito: un texto que se edita desde la web no puede ejecutar nada.
  - Todos llevan al final la FIRMA (datos de contacto, editable) y, si está activado, el LOGO
    (el de la plataforma u otro que suba admin), metido dentro del correo (no se descarga de la web).

El correo sale en HTML (con el logo) y en texto (para quien no ve HTML).
"""
import mimetypes
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from flask import current_app, request
from flask_babel import force_locale, gettext as _, lazy_gettext as _l
from markupsafe import escape

from app.extensions import db
from app.models import ESTADOS_PEDIDO_CLIENTE, Ajuste, PlantillaCorreo, ahora

IDIOMAS = {"es": _l("Español"), "en": _l("Inglés")}
COLOR_MARCA = "#a61c92"
CID_LOGO = "logo-yikon"
PATRON = re.compile(r"\{([a-z_]+)\}")

# Qué significa cada dato (sale en la página de edición, para elegir)
DATOS = {
    "referencia": _l("Nº de pedido de Yikon (YK-2026-…)"),
    "su_referencia": _l("La referencia que puso el cliente (su nº de pedido)"),
    "cliente": _l("Nombre del cliente"),
    "estado": _l("Estado del pedido, tal como lo ve el cliente"),
    "contenido": _l("Lo que lleva el pedido (una línea por kit o producto)"),
    "enlace": _l("Enlace al pedido en la plataforma"),
    "entrega_estimada": _l("Fecha estimada de entrega"),
    "transportista": _l("Transportista"),
    "seguimiento": _l("Nº de seguimiento"),
    "enlace_seguimiento": _l("Enlace de seguimiento del transportista"),
    "quien": _l("Quién ha escrito el mensaje"),
    "sobre": _l("De qué conversación es (el pedido o la conversación general)"),
    "texto": _l("El mensaje"),
    "adjuntos": _l("Los archivos adjuntos (uno por línea)"),
    "nombre": _l("Nombre del usuario"),
    "email": _l("Su email (es su usuario para entrar)"),
    "invita": _l("Quién le ha dado de alta"),
    "enlace_acceso": _l("Enlace para elegir la contraseña"),
    "caducidad": _l("Cuánto vale el enlace («7 días», «2 horas»…: Ajustes → Seguridad)"),
}
DATOS_PEDIDO = ["referencia", "su_referencia", "cliente", "estado", "contenido", "enlace"]
DATOS_ENVIO = ["entrega_estimada", "transportista", "seguimiento", "enlace_seguimiento"]
DATOS_MENSAJE = ["quien", "sobre", "texto", "adjuntos", "enlace", "cliente"]
DATOS_INVITACION = ["nombre", "email", "invita", "enlace_acceso", "caducidad"]
DATOS_RESTABLECER = ["nombre", "email", "enlace_acceso", "caducidad"]


@dataclass
class Caso:
    nombre: str
    cuando: str
    asunto: object          # funciones que devuelven el texto de fábrica en el idioma activo
    cuerpo: object
    datos: list = field(default_factory=lambda: list(DATOS_PEDIDO))


def _cambio_de_estado(explicacion):
    """El texto de fábrica de un cambio de estado: igual en todos salvo el párrafo del medio."""
    return (_("Hola,") + "\n\n"
            + _("Su pedido {referencia} ha cambiado de estado: {estado}") + "\n"
            + _("Su referencia: {su_referencia}") + "\n\n"
            + explicacion + "\n\n"
            + _("Contenido:") + "\n{contenido}\n\n"
            + _("Puede consultarlo en:") + "\n{enlace}")


def _asunto_estado():
    return _("Su pedido {referencia}: {estado}")


def _datos_de_envio():
    return (_("Fecha estimada de entrega: {entrega_estimada}") + "\n"
            + _("Transportista: {transportista}") + "\n"
            + _("Nº de seguimiento: {seguimiento}") + "\n"
            + _("Seguimiento: {enlace_seguimiento}"))


# Los casos, en el orden en que le pasan al pedido. La clave de los cambios de estado es el estado
# que ve el cliente (ESTADOS_PEDIDO_CLIENTE); "aceptado_proforma" es "aceptado" cuando viene de
# aceptar la proforma.
CASOS = {
    "proforma_solicitada": Caso(
        _l("Proforma en preparación"), _l("Yikon retira una proforma ya enviada para cambiarla."), _asunto_estado,
        lambda: _cambio_de_estado(_("Estamos preparando su proforma. Le avisaremos cuando esté lista."))),
    "proforma_enviada": Caso(
        _l("Proforma lista"), _l("Yikon envía la proforma al cliente."), _asunto_estado,
        lambda: _cambio_de_estado(_("Hemos preparado la proforma de su pedido. Puede descargarla y aceptarla "
                                    "(o pedirnos cambios) en la plataforma."))),
    "cambios_solicitados": Caso(
        _l("Cambios solicitados"), _l("El pedido vuelve a «Cambios solicitados» (lo cambia Yikon)."), _asunto_estado,
        lambda: _cambio_de_estado(_("Hemos recibido su petición de cambios. Le enviaremos una proforma nueva."))),
    "aceptado_proforma": Caso(
        _l("Proforma aceptada"), _l("El cliente acepta la proforma: ya es un pedido."), _asunto_estado,
        lambda: _cambio_de_estado(_("Hemos recibido su aceptación de la proforma: ya es un pedido. Le avisaremos "
                                    "cuando empecemos a prepararlo."))),
    "aceptado": Caso(
        _l("Pedido registrado"), _l("Un pedido sin proforma queda aceptado."), _asunto_estado,
        lambda: _cambio_de_estado(_("Hemos registrado su pedido. Le avisaremos cuando empecemos a prepararlo."))),
    "preparacion": Caso(
        _l("En preparación"), _l("Almacén empieza a preparar el pedido."), _asunto_estado,
        lambda: _cambio_de_estado(_("Estamos preparando su pedido."))),
    "enviado": Caso(
        _l("Enviado"), _l("El pedido sale de la oficina."), _asunto_estado,
        lambda: _cambio_de_estado(_("Su pedido ha salido de nuestras instalaciones.") + "\n\n" + _datos_de_envio()
                                  + "\n\n" + _("Cuando lo reciba, márquelo como «Recibido» en la plataforma "
                                                "(botón en la ficha del pedido).")),
        DATOS_PEDIDO + DATOS_ENVIO),
    "entregado": Caso(
        _l("Recibido"), _l("El pedido consta como recibido."), _asunto_estado,
        lambda: _cambio_de_estado(_("Su pedido consta como recibido. Gracias por su confianza."))),
    "cancelado": Caso(
        _l("Cancelado"), _l("Se cancela el pedido."), _asunto_estado,
        lambda: _cambio_de_estado(_("Si no esperaba esta cancelación, póngase en contacto con nosotros."))),
    "datos_envio": Caso(
        _l("Datos de envío actualizados"), _l("Cambian la fecha estimada o el seguimiento de un pedido ya enviado."),
        lambda: _("Su pedido {referencia}: datos de envío actualizados"),
        lambda: (_("Hola,") + "\n\n" + _("Hemos actualizado los datos de envío de su pedido {referencia}:") + "\n\n"
                 + _datos_de_envio() + "\n\n" + _("Puede consultarlo en:") + "\n{enlace}"),
        DATOS_PEDIDO + DATOS_ENVIO),
    # Automático (cada día a las 9:00, `flask recordar-recepcion`): 24 h después de la fecha estimada de entrega,
    # si el pedido sigue «Enviado». Una vez por pedido (Pedido.recordatorio_recibido_el).
    "recordatorio_recibido": Caso(
        _l("¿Ha recibido el pedido? (recordatorio)"),
        _l("Automático: el día después de la fecha estimada de entrega, si el pedido sigue sin marcarse como recibido. Una vez por pedido."),
        lambda: _("¿Ha recibido su pedido {referencia}?"),
        lambda: (_("Hola,") + "\n\n"
                 + _("Según nuestras previsiones, su pedido {referencia} (su referencia: {su_referencia}) debía llegar el {entrega_estimada}.")
                 + "\n\n" + _("¿Lo ha recibido ya? Si es así, por favor márquelo como «Recibido» en la plataforma "
                               "(botón «Marcar como recibido» en la ficha del pedido):") + "\n{enlace}\n\n"
                 + _("Si todavía no ha llegado o ha habido algún problema, escríbanos desde los mensajes del pedido "
                     "o con «Hay un problema con este pedido».")),
        DATOS_PEDIDO + DATOS_ENVIO),
    "mensaje_nuevo": Caso(
        _l("Mensaje nuevo de Yikon"), _l("Alguien de Yikon escribe al cliente en el chat (de un pedido o el general)."),
        lambda: _("Nuevo mensaje sobre {sobre}"),
        lambda: (_("Hola,") + "\n\n" + _("{quien} ha escrito un mensaje sobre {sobre}:") + "\n\n{texto}\n\n"
                 + _("Archivos adjuntos (descárguelos desde la plataforma):") + "\n{adjuntos}\n\n"
                 + _("Para responder, entre en la plataforma:") + "\n{enlace}\n\n"
                 + _("Si escriben más mensajes en esta conversación antes de que la abra, no le enviaremos otro aviso.")),
        DATOS_MENSAJE),
    # Acceso a la plataforma: los reciben todos los usuarios nuevos (también los de Yikon) y quien
    # pide cambiar la contraseña. No son avisos de pedidos: llegan siempre (no salen en «Avisos por email»).
    "invitacion": Caso(
        _l("Invitación"), _l("Admin da de alta a un usuario (o le reenvía la invitación)."),
        lambda: _("Tu acceso a Yikon Genomics PO"),
        lambda: (_("Hola %(nombre)s,", nombre="{nombre}") + "\n\n"
                 + _("%(invita)s te ha dado de alta en la plataforma de pedidos de Yikon Genomics.", invita="{invita}")
                 + "\n\n" + _("Para activar tu cuenta y elegir tu contraseña, abre este enlace (caduca en {caducidad} "
                               "y solo sirve una vez):") + "\n{enlace_acceso}\n\n"
                 + _("Tu usuario para entrar es tu email: %(email)s", email="{email}")),
        DATOS_INVITACION),
    "restablecer": Caso(
        _l("Cambiar la contraseña"), _l("Alguien pide «¿Has olvidado tu contraseña?» en la página de entrar."),
        lambda: _("Restablecer tu contraseña · Yikon Genomics PO"),
        lambda: (_("Hola %(nombre)s,", nombre="{nombre}") + "\n\n"
                 + _("Alguien (seguramente tú) ha pedido restablecer la contraseña de tu cuenta en Yikon Genomics PO.")
                 + "\n\n" + _("Para elegir una contraseña nueva, abre este enlace (caduca en {caducidad} y solo sirve "
                               "una vez):") + "\n{enlace_acceso}\n\n"
                 + _("Si no has sido tú, ignora este correo: tu contraseña no cambiará.")),
        DATOS_RESTABLECER),
}
FIRMA = "firma"
# A qué tipo de «Avisos por email» (app/avisos_cliente.py) pertenece cada correo: así cada usuario del
# cliente recibe solo los que tiene marcados. Los de acceso no tienen tipo: llegan siempre.
TIPO_DE_CASO = {
    "proforma_solicitada": "proformas", "proforma_enviada": "proformas", "cambios_solicitados": "proformas",
    "aceptado_proforma": "proformas",
    "aceptado": "estado", "preparacion": "estado", "entregado": "estado", "cancelado": "estado",
    "enviado": "envio", "datos_envio": "envio", "recordatorio_recibido": "envio",
    "mensaje_nuevo": "mensajes",
}
CASOS_ACCESO = ("invitacion", "restablecer")


# --------------------------------------------------------------------------- #
# Textos: los guardados por admin o, si no, los de fábrica
# --------------------------------------------------------------------------- #
def _guardada(clave, idioma):
    return db.session.scalar(db.select(PlantillaCorreo).filter_by(clave=clave, idioma=idioma))


def firma_de_fabrica():
    """La firma mientras nadie la cambie a mano: sale de Ajustes → Datos de Yikon."""
    from app import datos_empresa
    return ("\n".join(datos_empresa.lineas_firma()) + "\n\n"
            + _("Este es un aviso automático, no responda a este correo."))


def texto(clave, idioma):
    """{"asunto", "cuerpo", "cambiado": bool, "por", "el"}: lo que va a salir en ese idioma."""
    fila = _guardada(clave, idioma)
    if fila is not None:
        return {"asunto": fila.asunto or "", "cuerpo": fila.cuerpo, "cambiado": True,
                "por": fila.actualizado_por, "el": fila.actualizado_el}
    with force_locale(idioma):
        if clave == FIRMA:
            return {"asunto": "", "cuerpo": firma_de_fabrica(), "cambiado": False, "por": None, "el": None}
        caso = CASOS[clave]
        return {"asunto": caso.asunto(), "cuerpo": caso.cuerpo(), "cambiado": False, "por": None, "el": None}


def de_fabrica(clave, idioma):
    with force_locale(idioma):
        if clave == FIRMA:
            return {"asunto": "", "cuerpo": firma_de_fabrica()}
        return {"asunto": CASOS[clave].asunto(), "cuerpo": CASOS[clave].cuerpo()}


def errores(clave, asunto, cuerpo):
    """Lo que impide guardar el texto (lista vacía = todo bien)."""
    lista = []
    permitidos = set() if clave == FIRMA else set(CASOS[clave].datos)
    if clave != FIRMA and not (asunto or "").strip():
        lista.append(_("El asunto no puede ir vacío."))
    if not (cuerpo or "").strip():
        lista.append(_("El texto no puede ir vacío."))
    for d in sorted(set(PATRON.findall(asunto or "")) | set(PATRON.findall(cuerpo or ""))):
        if d not in permitidos:
            lista.append(_("«{%(dato)s}» no es un dato de este correo: quítalo o elige uno de la lista.", dato=d)
                         if clave != FIRMA else _("La firma no lleva datos entre llaves: «{%(dato)s}».", dato=d))
    if "\n" in (asunto or "").strip():
        lista.append(_("El asunto tiene que ir en una sola línea."))
    if clave in CASOS_ACCESO and "{enlace_acceso}" not in (cuerpo or ""):
        lista.append(_("Este correo tiene que llevar {enlace_acceso}: sin él no se puede elegir la contraseña."))
    return lista


def guardar(clave, idioma, asunto, cuerpo, usuario):
    """Guarda el texto de admin (sin commit). Si queda igual que el de fábrica, no se guarda nada
    (así, si un día cambia el de fábrica, le llega)."""
    fabrica = de_fabrica(clave, idioma)
    asunto = (asunto or "").strip() if clave != FIRMA else None
    cuerpo = _normalizar(cuerpo)
    fila = _guardada(clave, idioma)
    if cuerpo == _normalizar(fabrica["cuerpo"]) and (asunto or "") == fabrica["asunto"]:
        if fila is not None:
            db.session.delete(fila)
        return
    if fila is None:
        fila = PlantillaCorreo(clave=clave, idioma=idioma)
        db.session.add(fila)
    fila.asunto, fila.cuerpo, fila.actualizado_por, fila.actualizado_el = asunto, cuerpo, usuario, ahora()


def volver_al_original(clave, idioma):
    fila = _guardada(clave, idioma)
    if fila is not None:
        db.session.delete(fila)


def _normalizar(t):
    return "\n".join(l.rstrip() for l in (t or "").replace("\r\n", "\n").strip().split("\n"))


# --------------------------------------------------------------------------- #
# Rellenar los datos
# --------------------------------------------------------------------------- #
def rellenar(plantilla, valores):
    """Pone los datos. Una línea con un dato vacío no sale; un párrafo sin ningún dato con valor
    (y que llevaba alguno), tampoco. Los datos de varias líneas (contenido, adjuntos) salen tal cual."""
    salida = []
    for parrafo in re.split(r"\n\s*\n", _normalizar(plantilla)):
        lineas = parrafo.split("\n")
        usados = [d for l in lineas for d in PATRON.findall(l)]
        if usados and not any(valores.get(d) for d in usados):
            continue
        quedan = [PATRON.sub(lambda m: str(valores.get(m.group(1)) or ""), l)
                  for l in lineas if all(valores.get(d) for d in PATRON.findall(l))]
        if quedan:
            salida.append("\n".join(quedan))
    return "\n\n".join(salida)


def rellenar_asunto(plantilla, valores):
    return " ".join(PATRON.sub(lambda m: str(valores.get(m.group(1)) or ""), plantilla or "").split())


# --------------------------------------------------------------------------- #
# Logo
# --------------------------------------------------------------------------- #
def _ajuste(clave, de_fabrica=""):
    a = db.session.get(Ajuste, clave)
    return a.valor if a is not None else de_fabrica


def _poner_ajuste(clave, valor):
    a = db.session.get(Ajuste, clave)
    if a is None:
        db.session.add(Ajuste(clave=clave, valor=valor))
    else:
        a.valor = valor


def con_logo() -> bool:
    return _ajuste("correo.logo", "1") == "1"


def logo_propio() -> str:
    """Nombre en disco del logo que subió admin ("" = el de la plataforma)."""
    return _ajuste("correo.logo_archivo", "")


def logo(aunque_este_desactivado=False):
    """(bytes, tipo, subtipo) del logo que va en los correos, o None si va sin logo."""
    if not con_logo() and not aunque_este_desactivado:
        return None
    propio = logo_propio()
    try:
        if propio:
            from app.archivos import carpeta
            ruta = os.path.join(carpeta(), propio)
        else:
            ruta = os.path.join(current_app.static_folder, "img", "yikon-logo.png")
        with open(ruta, "rb") as f:
            datos = f.read()
    except OSError:
        current_app.logger.warning("No se encuentra el logo de los correos: van sin logo")
        return None
    tipo = mimetypes.guess_type(ruta)[0] or "image/png"
    return datos, *tipo.split("/", 1)


def guardar_logo(activado, nuevo=None, quitar_propio=False):
    """Sin commit. nuevo: (nombre, ext, bytes) de un logo subido. Devuelve el archivo que ya no se usa."""
    _poner_ajuste("correo.logo", "1" if activado else "0")
    anterior = logo_propio()
    if nuevo:
        from app import archivos
        _nombre, ext, datos = nuevo
        _poner_ajuste("correo.logo_archivo", archivos.escribir(datos, "logo_correo", ext))
        return anterior or None
    if quitar_propio and anterior:
        _poner_ajuste("correo.logo_archivo", "")
        return anterior
    return None


# --------------------------------------------------------------------------- #
# El correo entero: asunto, texto y HTML
# --------------------------------------------------------------------------- #
_URL = re.compile(r"(https?://[^\s<]+)")


def _html_parrafos(texto_plano, estilo_enlace):
    trozos = []
    for parrafo in texto_plano.split("\n\n"):
        lineas = [_URL.sub(lambda m: f'<a href="{m.group(1)}" style="{estilo_enlace}">{m.group(1)}</a>', str(escape(l)))
                  for l in parrafo.split("\n")]
        trozos.append('<p style="margin:0 0 14px">' + "<br>".join(lineas) + "</p>")
    return "".join(trozos)


def html(cuerpo, firma, src_logo=None):
    """El correo en HTML: tarjeta blanca con la línea de color de la marca arriba, el texto y,
    separado por una raya, el logo y la firma. Estilos en línea (los programas de correo no leen CSS)."""
    enlace = f"color:{COLOR_MARCA};font-weight:bold"
    from app import datos_empresa
    nombre = escape(datos_empresa.nombre())
    img = (f'<img src="{src_logo}" alt="{nombre}" height="44" style="display:block;height:44px;width:auto;'
           f'border:0;margin:0 0 10px">' if src_logo else "")
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '</head><body style="margin:0;padding:0;background:#f6f2f7">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f2f7">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;'
        f'background:#ffffff;border-radius:12px;border-top:4px solid {COLOR_MARCA}">'
        '<tr><td style="padding:28px 32px 6px;font:15px/1.55 Arial,Helvetica,sans-serif;color:#2b2330">'
        + _html_parrafos(cuerpo, enlace) +
        '</td></tr><tr><td style="padding:0 32px 26px">'
        '<div style="border-top:1px solid #e3e6f0;padding-top:16px;font:13px/1.5 Arial,Helvetica,sans-serif;color:#6a5f70">'
        + img + _html_parrafos(firma, enlace) +
        '</div></td></tr></table></td></tr></table></body></html>')


def componer(clave, idioma, valores, src_logo=None):
    """{"asunto", "texto", "html", "logo"} del correo `clave` en `idioma` con esos datos. El logo va
    con src="cid:…" (dentro del correo) salvo que se pida otro src (vista previa en la web)."""
    t, f = texto(clave, idioma), texto(FIRMA, idioma)
    return montar(t["asunto"], t["cuerpo"], f["cuerpo"], valores, src_logo)


def montar(asunto, cuerpo, firma, valores, src_logo=None):
    imagen = logo()
    cuerpo_relleno = rellenar(cuerpo, valores)
    firma = _normalizar(firma)
    return {"asunto": rellenar_asunto(asunto, valores),
            "texto": cuerpo_relleno + "\n\n-- \n" + firma,
            "html": html(cuerpo_relleno, firma, (src_logo or f"cid:{CID_LOGO}") if imagen else None),
            "logo": imagen}


def valores_de_pedido(pedido, estado=None):
    """Los datos de un pedido para los correos (se calculan antes del commit: después ya no se
    puede consultar la base de datos)."""
    from flask import url_for
    return {
        "referencia": pedido.referencia_interna or f"#{pedido.id}",
        "su_referencia": pedido.referencia or "",
        "cliente": pedido.cliente.nombre,
        "estado": estado or str(ESTADOS_PEDIDO_CLIENTE.get(pedido.estado_cliente, pedido.estado_cliente)),
        "contenido": "\n".join(f"  - {k}" for k in (pedido.resumen_contenido("\n").split("\n") if pedido.lineas else [])),
        "enlace": url_for("pedidos.detalle", id=pedido.id, _external=True),
        "entrega_estimada": pedido.fecha_entrega_estimada.strftime("%d/%m/%Y") if pedido.fecha_entrega_estimada else "",
        "transportista": pedido.transportista or "",
        "seguimiento": pedido.numero_seguimiento or "",
        "enlace_seguimiento": pedido.enlace_seguimiento or "",
    }


def valores_de_ejemplo(clave):
    """Datos inventados para la vista previa y el correo de prueba (en el idioma activo)."""
    base = request.host_url.rstrip("/") if request else ""
    estado = ESTADOS_PEDIDO_CLIENTE.get("aceptado" if clave == "aceptado_proforma" else clave,
                                        ESTADOS_PEDIDO_CLIENTE["enviado"])
    return {
        "referencia": "YK-2026-Ejemplo-014", "su_referencia": "PO-2291", "cliente": _("Clínica de ejemplo"),
        "estado": str(estado), "contenido": "  - 2 × PGT-A\n  - 1 × " + _("Tubos PCR 0,2 ml (caja 1000)"),
        "enlace": f"{base}/pedidos/14", "entrega_estimada": (date.today() + timedelta(days=3)).strftime("%d/%m/%Y"),
        "transportista": "DHL Express", "seguimiento": "4471 2290 18", "enlace_seguimiento": "https://www.dhl.com/",
        "quien": "Laura Martín (Yikon Genomics)", "sobre": _("el pedido %(ref)s", ref="YK-2026-Ejemplo-014"),
        "texto": _("Os lo enviamos mañana a primera hora."), "adjuntos": "  - albaran.pdf",
        "nombre": "Laura Martín", "email": "laura.martin@clinica-ejemplo.com", "invita": "Álvaro (Yikon Genomics)",
        "enlace_acceso": f"{base}/auth/invitacion/…" if clave == "invitacion" else f"{base}/auth/restablecer/…",
        "caducidad": caducidad(clave),
    }


def caducidad(clave) -> str:
    """«7 días» / «2 horas» (en el idioma activo): lo que vale el enlace de una invitación o del cambio
    de contraseña, según Ajustes → Seguridad."""
    from flask_babel import ngettext

    from app import seguridad
    if clave == "restablecer":
        horas = seguridad.valor("reset_horas")
        return ngettext("%(num)s hora", "%(num)s horas", horas)
    dias = seguridad.valor("invitacion_dias")
    return ngettext("%(num)s día", "%(num)s días", dias)


def aviso_activado(clave):
    """¿Está activado este aviso al cliente? (Ajustes → Correos al cliente → «Qué correos recibe el
    cliente»). Es global: vale para todos los clientes e idiomas, además de lo que cada usuario tenga
    marcado en la ficha de su cliente. Los de acceso (invitación, contraseña) siempre lo están."""
    return clave in CASOS_ACCESO or _ajuste("correo.aviso." + clave, "1") == "1"


def configurar_avisos(activados):
    for clave in CASOS:
        if clave not in CASOS_ACCESO:
            _poner_ajuste("correo.aviso." + clave, "1" if clave in activados else "0")
