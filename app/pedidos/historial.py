"""
Historial (línea de tiempo) de un pedido.

No guarda nada nuevo: lo reconstruye a partir de la auditoría, que ya registra
cada cosa que pasa con el pedido ("crear", "en_preparacion → en_validacion", fotos...).

- Yikon (admin, logística, FAS) ve todos los pasos, con quién los hizo.
- El cliente solo ve los cambios de estado que le afectan, con los nombres
  simplificados ("En preparación" agrupa todos los pasos internos) y sin nombres
  de personas de Yikon.
"""
import re

from flask_babel import gettext as _, lazy_gettext as _l

from app.extensions import db
from app.models import (ESTADOS_PEDIDO, ESTADOS_PEDIDO_CLIENTE, ESTADOS_PREPARACION,
                        RegistroAuditoria)
from app.permisos import NOMBRE_FAS

# Los cambios de estado se registran como "origen → destino ..." (ver _cambiar_estado)
_CAMBIO_ESTADO = re.compile(r"^(\w+) → (\w+)")

# Estados de antes del flujo actual (29/09/2026) que siguen en la auditoría de pedidos
# antiguos: se enseñan con su nombre de entonces y el color/icono del estado equivalente.
_ANTIGUOS = {"solicitado": ("aceptado", _l("Solicitado")),
             "confirmado": ("aceptado", _l("Confirmado")),
             "revisar": ("en_preparacion", _l("Devuelto por %(rol)s", rol=NOMBRE_FAS))}


def _estado_y_nombre(destino):
    if destino in _ANTIGUOS:
        return _ANTIGUOS[destino]
    return destino, ESTADOS_PEDIDO.get(destino, destino)


def _clave_cliente(estado):
    return "preparacion" if estado in ESTADOS_PREPARACION else estado


def _empezo_con_proforma(pedido):
    """¿El pedido empezó pidiendo proforma? (tiene alguna o sigue en esa fase)"""
    return bool(pedido.proformas) or pedido.estado.startswith("proforma")


def historial_pedido(pedido, usuario):
    """[{fecha, titulo, detalle, quien, estado, forzado}, ...] en orden cronológico.
    `estado` es la clave del estado alcanzado (para el icono), o None si no es un cambio de estado."""
    registros = db.session.scalars(
        db.select(RegistroAuditoria).filter_by(entidad="Pedido", entidad_id=pedido.id)
        .order_by(RegistroAuditoria.fecha, RegistroAuditoria.id)).all()
    es_cliente = usuario.rol == "cliente"
    eventos = []
    for r in registros:
        quien = None if es_cliente else (r.usuario.nombre if r.usuario else None)
        m = _CAMBIO_ESTADO.match(r.detalle or "")
        if r.accion == "crear":
            # Los del cliente empiezan pidiendo proforma; los de Yikon, como pedido directamente
            inicial = "proforma_solicitada" if _empezo_con_proforma(pedido) else "aceptado"
            eventos.append({"fecha": r.fecha, "titulo": _("Proforma solicitada") if inicial == "proforma_solicitada" else _("Pedido creado"), "detalle": None,
                            "quien": quien, "estado": inicial, "forzado": False})
        elif m:
            destino, nombre = _estado_y_nombre(m.group(2))
            if es_cliente:
                clave = _clave_cliente(destino)
                if eventos and eventos[-1]["estado"] == clave:
                    continue                    # pasos internos: para el cliente, sigue "En preparación"
                titulo = ESTADOS_PEDIDO_CLIENTE.get(clave, nombre)
                eventos.append({"fecha": r.fecha, "titulo": titulo, "detalle": None, "quien": None,
                                "estado": clave, "forzado": False})
            else:
                resto = (r.detalle or "")[m.end():].lstrip(" ·")
                eventos.append({"fecha": r.fecha, "titulo": nombre,
                                "detalle": resto.replace("CAMBIO FORZADO (fuera del flujo normal)", "").strip(" ·") or None,
                                "quien": quien, "estado": destino,
                                "forzado": "CAMBIO FORZADO" in (r.detalle or "")})
        elif not es_cliente:
            # Otros pasos internos (fotos, documentos, líneas, datos de envío): tal cual
            # se registraron en la auditoría (en español, igual que la auditoría).
            eventos.append({"fecha": r.fecha, "titulo": r.detalle or r.accion, "detalle": None,
                            "quien": quien, "estado": None, "forzado": False})
    return eventos
