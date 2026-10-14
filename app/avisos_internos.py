"""
Quién de Yikon recibe cada aviso por email (Administración → Ajustes → Avisos internos).

Una casilla por aviso y rol (admin, Logística, Soporte de cliente). Soporte de cliente solo
recibe los de SUS clientes. Además, cada persona solo recibe lo que puede ver (si a su rol le
han quitado Facturas en "Qué ve cada rol", no le llegan avisos de facturas). Lo decide solo admin.

Se guarda en la tabla "ajustes" como aviso.<clave>.<rol> = "1"/"0", solo lo que no está como de
fábrica (igual que apartados.py). Los avisos que ya existían vienen marcados como antes.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from flask import url_for
from flask_babel import force_locale, gettext as _, lazy_gettext as _l

from app.correo import enviar_tras_guardar
from app.extensions import db
from app.models import Ajuste, User

COLUMNAS = ["admin", "logistica", "fas"]


@dataclass
class Aviso:
    nombre: str
    explicacion: str
    permiso: str                       # quien lo recibe tiene que poder verlo
    posibles: set = field(default_factory=lambda: set(COLUMNAS))
    de_fabrica: set = field(default_factory=set)
    existia: bool = False              # (para la página: "Ya existe" / "Nuevo")


AVISOS = {
    "proforma_pedida": Aviso(
        _l("Un cliente pide una proforma"), _l("Hasta ahora solo salía en la campana."),
        "pedidos.proforma.enviar", de_fabrica={"logistica", "fas"}),
    "cambios_proforma": Aviso(
        _l("Un cliente pide cambios a la proforma"), _l("Con lo que pide cambiar (también queda en el chat)."),
        "pedidos.proforma.enviar", de_fabrica={"fas"}, existia=True),
    "proforma_aceptada": Aviso(
        _l("Un cliente acepta la proforma"), _l("Para empezar a prepararlo."),
        "pedidos.ver", de_fabrica={"logistica"}),
    "listo_validar": Aviso(
        _l("Pedido listo para validar las fotos"), _l("Logística lo ha preparado y ha subido las fotos."),
        "pedidos.validar", de_fabrica={"fas"}),
    "devuelto": Aviso(
        _l("Pedido devuelto a preparación"), _l("Soporte de cliente rechaza las fotos, con su comentario."),
        "pedidos.ver", posibles={"admin", "logistica"}, de_fabrica={"admin", "logistica"}, existia=True),
    "recibido": Aviso(
        _l("El cliente marca un pedido como recibido"), "",
        "pedidos.ver", de_fabrica={"admin", "fas"}, existia=True),
    "mensaje_cliente": Aviso(
        _l("Mensaje nuevo de un cliente"),
        _l("A admin, solo si el cliente no tiene Soporte de cliente asignado (o ninguno lo recibe)."),
        "mensajes.ver", de_fabrica={"admin", "fas"}, existia=True),
    "nota_interna": Aviso(
        _l("Nota en el chat interno de un pedido"), "",
        "mensajes.internos", de_fabrica={"admin", "fas"}, existia=True),
    "mensaje_compartido": Aviso(
        _l("Soporte de cliente comparte con Logística un mensaje del cliente"),
        _l("Desde la conversación general, que es privada entre el cliente y su Soporte."),
        "mensajes.ver", posibles={"logistica"}, de_fabrica={"logistica"}),
    "incidencia": Aviso(
        _l("Un cliente avisa de un problema con un pedido"),
        _l("«Hay un problema con este pedido»: llegó dañado, falta algo, temperatura… Se contesta en el chat del pedido."),
        "pedidos.ver", de_fabrica={"fas", "logistica"}),
    "factura_revisar": Aviso(
        _l("Factura para revisar"), _l("Se registra (o se corrige) una factura que pide revisión."),
        "facturas.revisar", posibles={"admin", "fas"}, de_fabrica={"fas"}),
    "factura_devuelta": Aviso(
        _l("Factura devuelta por Soporte de cliente"), _l("Con lo que hay que corregir."),
        "facturas.editar", posibles={"admin", "logistica"}, de_fabrica={"logistica"}),
}


# --------------------------------------------------------------------------- #
# Las casillas
# --------------------------------------------------------------------------- #
def _clave(aviso, rol):
    return f"aviso.{aviso}.{rol}"


def _guardados():
    return {a.clave: a.valor for a in db.session.scalars(db.select(Ajuste).where(Ajuste.clave.like("aviso.%")))}


def activo(aviso, rol, guardados=None) -> bool:
    a = AVISOS[aviso]
    if rol not in a.posibles:
        return False
    valor = (guardados if guardados is not None else _guardados()).get(_clave(aviso, rol))
    return valor == "1" if valor is not None else rol in a.de_fabrica


def tabla():
    """[(clave, aviso, {rol: True/False/None})] (None = ese rol no puede recibirlo)."""
    guardados = _guardados()
    return [(clave, a, {rol: (activo(clave, rol, guardados) if rol in a.posibles else None) for rol in COLUMNAS})
            for clave, a in AVISOS.items()]


def guardar(marcados) -> list:
    """marcados: {(aviso, rol)}. Guarda (sin commit) y devuelve los cambios para la auditoría."""
    guardados, cambios = _guardados(), []
    for clave, a in AVISOS.items():
        for rol in a.posibles:
            nuevo, antes = (clave, rol) in marcados, activo(clave, rol, guardados)
            fila = db.session.get(Ajuste, _clave(clave, rol))
            if nuevo == (rol in a.de_fabrica):
                if fila is not None:
                    db.session.delete(fila)
            elif fila is None:
                db.session.add(Ajuste(clave=_clave(clave, rol), valor="1" if nuevo else "0"))
            else:
                fila.valor = "1" if nuevo else "0"
            if nuevo != antes:
                cambios.append(f"{clave}·{rol} {'no→sí' if nuevo else 'sí→no'}")
    return cambios


# --------------------------------------------------------------------------- #
# A quién le llega
# --------------------------------------------------------------------------- #
def destinatarios(aviso, cliente, excluir_id=None) -> list:
    """Los usuarios de Yikon que reciben este aviso sobre este cliente."""
    guardados = _guardados()
    roles = {rol for rol in COLUMNAS if activo(aviso, rol, guardados)}
    usuarios = []
    soporte = [u for u in cliente.logisticos if u.activo] if cliente is not None else []
    if "fas" in roles:
        usuarios += soporte
    if "logistica" in roles:
        usuarios += db.session.scalars(db.select(User).filter_by(rol="logistica", activo=True)).all()
    if "admin" in roles and not (aviso == "mensaje_cliente" and soporte and "fas" in roles):
        usuarios += db.session.scalars(db.select(User).filter_by(rol="admin", activo=True)).all()
    vistos, resultado = set(), []
    for u in usuarios:
        if u.id in vistos or u.id == excluir_id or not u.puede(AVISOS[aviso].permiso):
            continue
        vistos.add(u.id)
        resultado.append(u)
    return resultado


def avisar(aviso, cliente, contenido, excluir_id=None, plantilla="aviso_interno", pedido_id=None):
    """Manda el aviso (tras el commit) a quien le toque, cada uno en su idioma.
    contenido(): devuelve {"asunto", y lo que use la plantilla} — se llama ya en el idioma de cada grupo."""
    por_idioma = defaultdict(list)
    for u in destinatarios(aviso, cliente, excluir_id):
        por_idioma[u.idioma or "es"].append(u.email)
    for idioma, emails in por_idioma.items():
        with force_locale(idioma):
            datos = contenido()
            enviar_tras_guardar(emails, datos.pop("asunto"), plantilla, **datos,
                                meta={"tipo": f"interno.{aviso}", "cliente_id": cliente.id if cliente else None,
                                      "pedido_id": pedido_id})


# --------------------------------------------------------------------------- #
# Los avisos nuevos (los que ya existían siguen en notificaciones.py y mensajes/servicio.py)
# --------------------------------------------------------------------------- #
def _ref(pedido):
    return pedido.referencia_interna or f"#{pedido.id}"


def _enlace(pedido, ancla=""):
    return url_for("pedidos.detalle", id=pedido.id, _external=True) + ancla


def proforma_pedida(pedido, quien):
    avisar("proforma_pedida", pedido.cliente, lambda: {
        "asunto": _("Proforma pedida: %(ref)s (%(cliente)s)", ref=_ref(pedido), cliente=pedido.cliente.nombre),
        "texto": _("%(quien)s (%(cliente)s) ha pedido una proforma: pedido %(ref)s.", quien=quien,
                   cliente=pedido.cliente.nombre, ref=_ref(pedido)),
        "lineas": pedido.resumen_contenido("\n").split("\n") if pedido.lineas else [],
        "enlace": _enlace(pedido, "#proforma")}, pedido_id=pedido.id)


def cambios_proforma(pedido, numero, comentario, quien, excluir_id=None):
    avisar("cambios_proforma", pedido.cliente, lambda: {
        "asunto": _("Cambios a la proforma %(numero)s (%(cliente)s)", numero=numero, cliente=pedido.cliente.nombre),
        "texto": _("%(quien)s (%(cliente)s) pide cambios a la proforma %(numero)s del pedido %(ref)s.", quien=quien,
                   cliente=pedido.cliente.nombre, numero=numero, ref=_ref(pedido)),
        "comentario": comentario, "enlace": _enlace(pedido, "#proforma")}, excluir_id, pedido_id=pedido.id)


def proforma_aceptada(pedido, numero, quien):
    avisar("proforma_aceptada", pedido.cliente, lambda: {
        "asunto": _("✓ Proforma aceptada: %(ref)s (%(cliente)s)", ref=_ref(pedido), cliente=pedido.cliente.nombre),
        "texto": _("%(quien)s (%(cliente)s) ha aceptado la proforma %(numero)s: el pedido %(ref)s ya se puede preparar.",
                   quien=quien, cliente=pedido.cliente.nombre, numero=numero, ref=_ref(pedido)),
        "lineas": pedido.resumen_contenido("\n").split("\n") if pedido.lineas else [],
        "enlace": _enlace(pedido)}, pedido_id=pedido.id)


def listo_validar(pedido, quien, excluir_id=None):
    avisar("listo_validar", pedido.cliente, lambda: {
        "asunto": _("Fotos por validar: %(ref)s (%(cliente)s)", ref=_ref(pedido), cliente=pedido.cliente.nombre),
        "texto": _("%(quien)s ha preparado el pedido %(ref)s y ha subido %(n)s foto(s). Falta validarlas.",
                   quien=quien, ref=_ref(pedido), n=len(pedido.fotos)),
        "enlace": _enlace(pedido)}, excluir_id, pedido_id=pedido.id)


def mensaje_compartido(mensaje, quien, excluir_id=None):
    cliente = mensaje.cliente
    avisar("mensaje_compartido", cliente, lambda: {
        "asunto": _("%(quien)s te comparte un mensaje de %(cliente)s", quien=quien, cliente=cliente.nombre),
        "texto": _("%(quien)s ha compartido con Logística este mensaje de la conversación con %(cliente)s:",
                   quien=quien, cliente=cliente.nombre) + "\n\n" + (mensaje.texto or "")
                 + ("\n\n" + _("Nota de %(quien)s: %(nota)s", quien=quien, nota=mensaje.compartido_nota)
                    if mensaje.compartido_nota else ""),
        "enlace": url_for("mensajes.conversacion", cliente_id=cliente.id, _external=True)}, excluir_id)


def _enlace_factura(factura):
    if factura.pedido_id:
        return url_for("pedidos.detalle", id=factura.pedido_id, _external=True) + "#facturas"
    return url_for("facturas.lista", _external=True)


def factura_revisar(factura, quien, excluir_id=None):
    avisar("factura_revisar", factura.cliente, lambda: {
        "asunto": _("Factura para revisar: %(numero)s (%(cliente)s)", numero=factura.numero, cliente=factura.cliente.nombre),
        "texto": _("%(quien)s ha registrado la factura %(numero)s y pide que la revises antes de enviarla al cliente.",
                   quien=quien, numero=factura.numero),
        "enlace": _enlace_factura(factura)}, excluir_id, pedido_id=factura.pedido_id)


def factura_devuelta(factura, comentario, quien, excluir_id=None):
    avisar("factura_devuelta", factura.cliente, lambda: {
        "asunto": _("↩ Factura devuelta: %(numero)s (%(cliente)s)", numero=factura.numero, cliente=factura.cliente.nombre),
        "texto": _("%(quien)s ha devuelto la factura %(numero)s. Corrígela y sube el PDF nuevo.",
                   quien=quien, numero=factura.numero),
        "comentario": comentario, "enlace": _enlace_factura(factura)}, excluir_id, pedido_id=factura.pedido_id)


def incidencia(incidencia, quien, excluir_id=None):
    pedido = incidencia.pedido
    avisar("incidencia", pedido.cliente, lambda: {
        "asunto": _("⚠ Problema con el pedido %(ref)s (%(cliente)s): %(motivo)s", ref=_ref(pedido),
                    cliente=pedido.cliente.nombre, motivo=incidencia.motivo_nombre),
        "texto": _("%(quien)s (%(cliente)s) avisa de un problema con el pedido %(ref)s: %(motivo)s.", quien=quien,
                   cliente=pedido.cliente.nombre, ref=_ref(pedido), motivo=incidencia.motivo_nombre)
                 + ("\n" + _("Ha adjuntado %(n)s foto(s).", n=len(incidencia.fotos)) if incidencia.fotos else ""),
        "comentario": incidencia.texto,
        "enlace": _enlace(pedido, "#incidencias")}, excluir_id, pedido_id=pedido.id)
