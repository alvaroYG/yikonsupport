"""
Qué avisos por email recibe cada usuario de un CLIENTE (ficha del cliente → «Avisos por email»).
Lo deciden admin y el Soporte de cliente de ese cliente.

  - Cuatro tipos (los correos de Ajustes → Correos al cliente se agrupan así, ver Caso.tipo):
      Proformas · Estado del pedido · Envío y seguimiento · Mensajes
  - Por usuario, una casilla por tipo. De fábrica, todo marcado (como hasta ahora). En el usuario
    se guardan los que NO quiere (User.avisos_desactivados): así un usuario nuevo los recibe todos.
  - Emails en copia SIN usuario en la plataforma (el almacén de la clínica, contabilidad…), cada
    uno con sus tipos (tabla copias_aviso). Les llega el mismo correo, en el idioma del cliente.
    Los correos llevan enlaces a la plataforma: sin usuario no los podrán abrir.

Los correos de acceso (invitación y cambiar contraseña) no son avisos: llegan siempre.
"""
from collections import defaultdict

from flask_babel import lazy_gettext as _l

from app.extensions import db
from app.models import CopiaAviso, User

TIPOS = {
    "proformas": _l("Proformas"),
    "estado": _l("Estado del pedido"),
    "envio": _l("Envío y seguimiento"),
    "mensajes": _l("Mensajes"),
}
EXPLICACION = {
    "proformas": _l("Proforma lista, en preparación, cambios y aceptada."),
    "estado": _l("Pedido registrado, en preparación, recibido y cancelado."),
    "envio": _l("Enviado (con el seguimiento) y cambios en los datos de envío."),
    "mensajes": _l("Mensajes nuevos de Yikon (a un usuario, uno hasta que entra a leerlos; a un email en copia, uno por mensaje)."),
}
MAX_COPIAS = 10


def _lista(texto) -> set:
    return {t for t in (texto or "").split(",") if t in TIPOS}


def recibe(usuario, tipo) -> bool:
    return tipo not in _lista(usuario.avisos_desactivados)


def usuarios_del_cliente(cliente):
    """Los usuarios que pueden recibir avisos de pedidos: los de rol Cliente, activos o no (para la tabla)."""
    return db.session.scalars(db.select(User).filter_by(cliente_id=cliente.id, rol="cliente")
                              .order_by(User.activo.desc(), User.nombre)).all()


def destinatarios(cliente_id, tipo) -> list:
    """Los usuarios activos del cliente que reciben este tipo de aviso."""
    usuarios = db.session.scalars(db.select(User).filter_by(rol="cliente", activo=True, cliente_id=cliente_id))
    return [u for u in usuarios if tipo is None or recibe(u, tipo)]


def copias(cliente_id, tipo) -> list:
    """Los emails en copia (sin usuario) de este cliente que reciben este tipo."""
    if tipo is None:
        return []
    filas = db.session.scalars(db.select(CopiaAviso).filter_by(cliente_id=cliente_id))
    return [c.email for c in filas if tipo in _lista(c.tipos)]


def por_idioma(cliente, tipo) -> dict:
    """{idioma: [emails]} de todos los que reciben este aviso: los usuarios en su idioma y las copias en
    el del cliente (el que más usan sus usuarios). Un email que esté como usuario y como copia, una vez."""
    from app.ajustes import idioma_del_cliente
    grupos, vistos = defaultdict(list), set()
    for u in destinatarios(cliente.id, tipo):
        grupos[u.idioma or "es"].append(u.email)
        vistos.add(u.email)
    extra = [e for e in copias(cliente.id, tipo) if e not in vistos]
    if extra:
        grupos[idioma_del_cliente(cliente)].extend(extra)
    return dict(grupos)


def guardar(cliente, marcados_usuarios: dict, copias_nuevas: list) -> list:
    """Sin commit. marcados_usuarios: {user_id: {tipos marcados}} (solo de usuarios de este cliente).
    copias_nuevas: [(email, {tipos})]. Devuelve los cambios para la auditoría."""
    cambios = []
    for u in usuarios_del_cliente(cliente):
        if u.id not in marcados_usuarios:
            continue
        quitados = ",".join(t for t in TIPOS if t not in marcados_usuarios[u.id])
        if quitados != ",".join(t for t in TIPOS if t in _lista(u.avisos_desactivados)):
            cambios.append(f"{u.email}: sin {quitados or 'nada'}")
            u.avisos_desactivados = quitados
    antes = {c.email: c for c in cliente.copias_aviso}
    nuevas = {}
    for email, tipos in copias_nuevas:
        email = (email or "").strip().lower()
        if email and email not in nuevas:
            nuevas[email] = ",".join(t for t in TIPOS if t in tipos)
    for email, fila in antes.items():
        if email not in nuevas:
            cliente.copias_aviso.remove(fila)
            cambios.append(f"copia quitada: {email}")
    for email, tipos in nuevas.items():
        fila = antes.get(email)
        if fila is None:
            cliente.copias_aviso.append(CopiaAviso(email=email, tipos=tipos))
            cambios.append(f"copia: {email} ({tipos or 'nada'})")
        elif fila.tipos != tipos:
            fila.tipos = tipos
            cambios.append(f"copia: {email} ({tipos or 'nada'})")
    return cambios


def tabla(cliente):
    """Para la ficha del cliente: [(usuario, {tipo: bool})] y [(email, {tipo: bool})]."""
    usuarios = [(u, {t: recibe(u, t) for t in TIPOS}) for u in usuarios_del_cliente(cliente)]
    filas_copias = [(c.email, {t: t in _lista(c.tipos) for t in TIPOS}) for c in cliente.copias_aviso]
    return usuarios, filas_copias
