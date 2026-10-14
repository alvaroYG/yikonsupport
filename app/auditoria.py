import re

from flask import url_for
from flask_babel import lazy_gettext as _l
from flask_login import current_user

from app.extensions import db
from app.models import RegistroAuditoria


def registrar(accion: str, objeto=None, detalle: str = "", entidad: str = None):
    """
    Añade una entrada de auditoría a la sesión actual. Se guarda en el mismo
    commit que el cambio, así nunca hay un cambio sin su registro (ni al revés).
    """
    usuario_id = current_user.id if current_user and current_user.is_authenticated else None
    db.session.add(
        RegistroAuditoria(
            usuario_id=usuario_id,
            accion=accion,
            entidad=entidad or (type(objeto).__name__ if objeto is not None else "-"),
            entidad_id=getattr(objeto, "id", None),
            objeto=nombre_de(objeto)[:250] or None,
            detalle=detalle,
        )
    )


def nombre_de(objeto) -> str:
    """Cómo se reconoce un objeto a simple vista en la auditoría ("" si no se sabe)."""
    if objeto is None:
        return ""
    try:
        tipo = type(objeto).__name__
        if tipo == "Pedido":
            return f"{objeto.referencia_interna or f'#{objeto.id}'} · {objeto.cliente.nombre}"
        if tipo == "Cliente":
            return objeto.nombre
        if tipo == "User":
            return f"{objeto.nombre} ({objeto.email})"
        if tipo == "Factura":
            return f"{objeto.numero} · {objeto.cliente.nombre}"
        if tipo in ("Producto", "Kit"):
            return f"{objeto.referencia} · {objeto.nombre}"
        if tipo == "Lote":
            return f"{objeto.articulo.referencia} · lote {objeto.codigo}"
        if tipo == "MovimientoInventario":
            lote = f" · lote {objeto.lote.codigo}" if objeto.lote is not None else ""
            return f"{objeto.articulo.referencia}{lote} · {objeto.cantidad:+d}"
        if tipo == "DocumentoInterno":
            return objeto.titulo
        if tipo == "Ticket":
            return f"{objeto.numero} · {objeto.asunto}"
    except Exception:          # (un objeto a medio crear: mejor sin nombre que un error al guardar)
        return ""
    return ""


def cambios(objeto, form, campos):
    """Devuelve un texto 'campo: antes → después' con lo que cambia el formulario."""
    partes = []
    for campo in campos:
        antes = getattr(objeto, campo)
        despues = getattr(form, campo).data
        if despues == "":
            despues = None
        if antes != despues:
            partes.append(f"{campo}: {antes} → {despues}")
    return "; ".join(partes)


# --------------------------------------------------------------------------- #
# Para la página de Auditoría: qué es cada cosa y a dónde lleva
# --------------------------------------------------------------------------- #
TIPOS = {
    "Pedido": _l("Pedido"), "Cliente": _l("Cliente"), "Factura": _l("Factura"), "User": _l("Usuario"),
    "Producto": _l("Producto"), "Kit": _l("Kit"), "Lote": _l("Lote"),
    "MovimientoInventario": _l("Movimiento de inventario"), "DocumentoInterno": _l("Documento interno"),
    "Ticket": _l("Ticket"), "Ajuste": _l("Ajustes"),
}
ACCIONES = {"crear": _l("Crear"), "editar": _l("Cambiar"), "borrar": _l("Borrar"), "login": _l("Entrar"),
            "ver_como": _l("Ver como"), "exportar": _l("Exportar")}


def _modelos():
    from app import models
    return {nombre: getattr(models, nombre) for nombre in TIPOS if nombre != "Ajuste"}


def _enlace(entidad, obj):
    """La página donde se ve el objeto (None si no hay ninguna o el usuario no la puede abrir)."""
    from app.permisos import documentos_activos, soporte_activo
    rutas = {
        "Pedido": ("pedidos.detalle", "pedidos.ver"), "Cliente": ("clientes.detalle", "clientes.ver"),
        "Factura": ("facturas.editar", "facturas.editar"), "User": ("admin.editar_usuario", "usuarios.gestionar"),
        "Producto": ("productos.editar", "productos.editar"), "Kit": ("productos.editar_kit", "productos.editar"),
    }
    if entidad in rutas:
        endpoint, permiso = rutas[entidad]
        return url_for(endpoint, id=obj.id) if current_user.puede(permiso) else None
    if entidad == "Lote" and current_user.puede("pedidos.ver_lotes"):
        return url_for("inventario.rastrear_lote", q=obj.codigo)
    if entidad == "MovimientoInventario" and obj.lote is not None and current_user.puede("pedidos.ver_lotes"):
        return url_for("inventario.rastrear_lote", q=obj.lote.codigo)
    if entidad == "DocumentoInterno" and documentos_activos() and current_user.puede("documentos.ver"):
        return url_for("documentos.detalle", id=obj.id)
    if entidad == "Ticket" and soporte_activo() and current_user.puede("soporte.ver"):
        return url_for("soporte.detalle", id=obj.id)
    return None


def describir(registros):
    """{id del registro: {"tipo", "nombre", "enlace", "existe"}} para pintar la columna «Objeto».
    El nombre es el que se guardó al registrarlo; los registros antiguos sin nombre usan el de hoy.
    Una consulta por tipo de objeto, no una por fila."""
    from app.extensions import db
    modelos, ids = _modelos(), {}
    for r in registros:
        if r.entidad in modelos and r.entidad_id:
            ids.setdefault(r.entidad, set()).add(r.entidad_id)
    vivos = {(entidad, o.id): o for entidad, conjunto in ids.items()
             for o in db.session.scalars(db.select(modelos[entidad]).where(modelos[entidad].id.in_(conjunto)))}
    resultado = {}
    for r in registros:
        obj = vivos.get((r.entidad, r.entidad_id))
        if r.entidad == "Ajuste":
            resultado[r.id] = {"tipo": TIPOS["Ajuste"], "nombre": r.objeto or "", "existe": True,
                               "enlace": url_for("admin.ajustes") if current_user.puede("ajustes.editar") else None}
            continue
        resultado[r.id] = {
            "tipo": TIPOS.get(r.entidad, r.entidad),
            "nombre": r.objeto or (nombre_de(obj) if obj is not None else "") or (f"#{r.entidad_id}" if r.entidad_id else ""),
            "existe": obj is not None or not r.entidad_id,
            "enlace": _enlace(r.entidad, obj) if obj is not None else None,
        }
    return resultado


_CAMBIO_ESTADO = re.compile(r"^([a-z_]+) → ([a-z_]+)(?=$| ·)")


def detalle_legible(detalle):
    """En los cambios de estado de un pedido, los nombres que ve la gente en vez de los internos:
    "en_validacion → validado · 2 foto(s)" → "Pendiente de validación → Listo para enviar · 2 foto(s)"."""
    from app.models import ESTADOS_PEDIDO
    if not detalle:
        return ""

    def nombres(m):
        a, b = m.group(1), m.group(2)
        if a in ESTADOS_PEDIDO and b in ESTADOS_PEDIDO:
            return f"{ESTADOS_PEDIDO[a]} → {ESTADOS_PEDIDO[b]}"
        return m.group(0)
    return _CAMBIO_ESTADO.sub(nombres, detalle)
