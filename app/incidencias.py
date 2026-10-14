"""
Incidencias: "Hay un problema con este pedido".

  - Las abre el CLIENTE en un pedido enviado o recibido: motivo (Llegó dañado / Falta algo /
    Temperatura / Otro), qué pasa y, si quiere, fotos.
  - Lo que escribe (y las fotos) va también al CHAT del pedido, como un mensaje suyo: la
    conversación sigue allí, en un solo sitio (las fotos son los adjuntos de ese mensaje).
  - Yikon lo ve en la ficha del pedido (aviso arriba), en la pestaña «Incidencias» de Pendientes
    y en la campana; le llega un email a quien diga Ajustes → Avisos internos (de fábrica: su
    Soporte de cliente y Logística).
  - Yikon la cierra con «Resuelta» y una nota, que le llega al cliente por el chat del pedido.

Todo pasa por el alcance de siempre (app/alcance.py): cada uno ve las de los pedidos que ve.
"""
from flask_babel import force_locale, gettext as _
from sqlalchemy.orm import selectinload

from app import avisos_internos
from app.alcance import filtrar_pedidos
from app.auditoria import registrar
from app.extensions import db
from app.mensajes import servicio as servicio_mensajes
from app.models import ESTADOS_CON_INCIDENCIAS, MOTIVOS_INCIDENCIA, Incidencia, Pedido, ahora

EXTENSIONES_FOTO = {"jpg", "jpeg", "png"}
MAX_FOTOS = servicio_mensajes.MAX_ADJUNTOS
MAX_TEXTO = 3000


def _motivo_es(motivo):
    """El motivo en español, para la auditoría (que se guarda siempre en español)."""
    with force_locale("es"):
        return str(MOTIVOS_INCIDENCIA.get(motivo, motivo)).lower()


def puede_abrir(usuario, pedido) -> bool:
    return usuario.puede("pedidos.incidencias.abrir") and pedido.estado in ESTADOS_CON_INCIDENCIAS


def leer_fotos(ficheros):
    """Comprueba las fotos antes de guardar nada: [(nombre, ext, bytes)] o ArchivoNoValido."""
    from app import archivos
    ficheros = [f for f in ficheros if f and getattr(f, "filename", "")]
    if len(ficheros) > MAX_FOTOS:
        raise archivos.ArchivoNoValido(_("Como máximo %(n)s fotos.", n=MAX_FOTOS))
    fotos = [archivos.leer_y_validar(f, EXTENSIONES_FOTO) for f in ficheros]
    for nombre, _ext, datos in fotos:
        if not (datos.startswith(b"\xff\xd8") or datos.startswith(b"\x89PNG")):
            raise archivos.ArchivoNoValido(_("«%(nombre)s» no parece una foto (JPG o PNG).", nombre=nombre))
    return fotos


def abrir(pedido, usuario, motivo, texto, fotos=()) -> Incidencia:
    """Guarda la incidencia y su mensaje en el chat del pedido (sin commit) y deja preparado el email
    a Yikon. fotos: lo que devuelve leer_fotos()."""
    motivo = motivo if motivo in MOTIVOS_INCIDENCIA else "otro"
    texto = (texto or "").strip()[:MAX_TEXTO]
    # En el chat, con su motivo delante. (El email de "mensaje nuevo" no se manda: ya va el de la incidencia.)
    mensaje = servicio_mensajes.enviar(
        usuario, pedido.cliente, "⚠ " + _("Problema con el pedido: %(motivo)s", motivo=MOTIVOS_INCIDENCIA[motivo])
        + "\n" + texto, pedido=pedido, adjuntos=fotos, avisar=False)
    incidencia = Incidencia(pedido=pedido, motivo=motivo, texto=texto, creada_por=usuario, mensaje=mensaje)
    db.session.add(incidencia)
    db.session.flush()
    registrar("editar", pedido, f"incidencia abierta: {_motivo_es(motivo)}" + (f" · {len(fotos)} foto(s)" if fotos else ""))
    avisos_internos.incidencia(incidencia, usuario.nombre, excluir_id=usuario.id)
    return incidencia


def resolver(incidencia, usuario, nota):
    """«Resuelta» con una nota (sin commit). La nota le llega al cliente por el chat del pedido, en su
    idioma, con el email de "mensaje nuevo" de siempre."""
    from app.ajustes import idioma_del_cliente
    pedido = incidencia.pedido
    nota = (nota or "").strip()[:MAX_TEXTO]
    incidencia.estado, incidencia.resuelta_el, incidencia.resuelta_por = "resuelta", ahora(), usuario
    incidencia.nota_resolucion = nota
    registrar("editar", pedido, f"incidencia resuelta: {_motivo_es(incidencia.motivo)}")
    with force_locale(idioma_del_cliente(pedido.cliente)):
        texto = "✓ " + _("Hemos resuelto el problema que nos indicó (%(motivo)s).", motivo=incidencia.motivo_nombre)
    servicio_mensajes.enviar(usuario, pedido.cliente, texto + ("\n" + nota if nota else ""), pedido=pedido)


def abiertas():
    """Las incidencias abiertas de los pedidos que ve el usuario conectado, la más antigua primero."""
    return db.session.scalars(
        db.select(Incidencia).join(Pedido).where(Incidencia.estado == "abierta",
                                                 Pedido.id.in_(filtrar_pedidos(db.select(Pedido.id))))
        .options(selectinload(Incidencia.pedido).selectinload(Pedido.cliente))
        .order_by(Incidencia.creada, Incidencia.id)).all()


def contar_abiertas() -> int:
    return db.session.scalar(
        db.select(db.func.count(Incidencia.id)).where(Incidencia.estado == "abierta",
                                                       Incidencia.pedido_id.in_(filtrar_pedidos(db.select(Pedido.id)))))
