"""
Menú lateral: qué secciones y enlaces ve cada usuario, cuál está abierta y qué contadores lleva.

La plantilla (layout.html) solo pinta lo que devuelve menu_lateral(). Para añadir una pantalla
al menú basta con añadir un Enlace en su sección (o una Seccion nueva).

Reglas de la experiencia de uso:
  - Cada sección se pliega; la de la página en la que estás llega ABIERTA (desde el servidor,
    así no "salta" al cargar). Las demás, cerradas.
  - Si una sección solo tiene un enlace para ese usuario, se pinta como enlace directo (sin
    cabecera): no tiene sentido abrir una sección para ver una sola cosa.
  - Los avisos no se esconden: con la sección cerrada, su cabecera muestra la suma de los
    contadores de sus enlaces.
"""
from dataclasses import dataclass, field
from typing import Callable

from flask_babel import lazy_gettext as _l

EN_PREPARAR = ("pedidos.preparar", "pedidos.preparar_pedido")


@dataclass
class Enlace:
    permiso: str
    endpoint: str
    texto: str
    icono: str
    # ¿Esta página pertenece a este enlace? (recibe endpoint y blueprint de la petición)
    activo_si: Callable[[str, str], bool]
    # Contador de avisos: función que recibe el diccionario "avisos" del context processor
    contador: Callable[[dict], int] = lambda avisos: 0
    titulo_contador: str = ""


@dataclass
class Seccion:
    clave: str
    titulo: str
    icono: str
    enlaces: list = field(default_factory=list)


def _blueprint(nombre):
    return lambda endpoint, bp: bp == nombre


def _suma(*claves):
    return lambda avisos: sum(avisos.get(c) or 0 for c in claves)


SECCIONES = [
    Seccion("pedidos", _l("Pedidos"), "fa-clipboard-list", [
        Enlace("pedidos.ver", "pedidos.lista", _l("Pedidos"), "fa-clipboard-list",
               lambda e, bp: bp in ("pedidos", "proformas") and e not in EN_PREPARAR,
               _suma("revisar", "validar", "proformas"), _l("Pedidos que requieren tu atención")),
        Enlace("pedidos.fotos.subir", "pedidos.preparar", _l("Preparar"), "fa-camera",
               lambda e, bp: e in EN_PREPARAR, _suma("preparar"), _l("Pedidos por preparar")),
        Enlace("mensajes.ver", "mensajes.lista", _l("Mensajes"), "fa-comments", _blueprint("mensajes"),
               _suma("mensajes", "internos"), _l("Mensajes sin leer")),
    ]),
    Seccion("catalogo", _l("Catálogo"), "fa-boxes", [
        Enlace("productos.ver", "productos.kits", _l("Kits"), "fa-cubes",
               lambda e, bp: bp == "productos" and "kit" in e),
        Enlace("productos.ver", "productos.lista", _l("Productos"), "fa-box",
               lambda e, bp: bp == "productos" and "kit" not in e and e != "productos.catalogo"),
        Enlace("productos.catalogo", "productos.catalogo", _l("Productos"), "fa-box",
               lambda e, bp: e == "productos.catalogo"),
        Enlace("inventario.ver", "inventario.lista", _l("Inventario"), "fa-warehouse",
               lambda e, bp: bp == "inventario" and not e.startswith("inventario.rastrear_lote")),
        Enlace("pedidos.ver_lotes", "inventario.rastrear_lote", _l("Rastrear lote"), "fa-search-location",
               lambda e, bp: e.startswith("inventario.rastrear_lote")),
    ]),
    Seccion("clientes", _l("Clientes y facturas"), "fa-building", [
        Enlace("clientes.ver", "clientes.lista", _l("Clientes"), "fa-building", _blueprint("clientes")),
        Enlace("facturas.ver", "facturas.lista", _l("Facturas"), "fa-file-invoice-dollar", _blueprint("facturas")),
        Enlace("facturas.ver_propias", "facturas.mias", _l("Facturas"), "fa-file-invoice-dollar", _blueprint("facturas")),
    ]),
    Seccion("soporte", _l("Soporte ChromGo"), "fa-life-ring", [
        Enlace("soporte.ver", "soporte.lista", _l("Tickets ChromGo"), "fa-life-ring", _blueprint("soporte"),
               _suma("soporte"), _l("Tickets con novedades")),
    ]),
    Seccion("equipo", _l("Equipo Yikon"), "fa-users", [
        Enlace("documentos.ver", "documentos.lista", _l("Documentos internos"), "fa-folder-open",
               _blueprint("documentos")),
    ]),
    Seccion("admin", _l("Administración"), "fa-cogs", [
        Enlace("usuarios.gestionar", "admin.usuarios", _l("Usuarios"), "fa-users-cog",
               lambda e, bp: bp == "admin" and "usuario" in e),
        Enlace("estadisticas.ver", "main.estadisticas", _l("Estadísticas"), "fa-chart-bar",
               lambda e, bp: e == "main.estadisticas"),
        Enlace("auditoria.ver", "admin.auditoria", _l("Auditoría"), "fa-history",
               lambda e, bp: e == "admin.auditoria"),
        Enlace("correos.ver", "admin.correos", _l("Correos enviados"), "fa-paper-plane",
               lambda e, bp: e.startswith("admin.correo")),
        Enlace("estado.ver", "admin.estado", _l("Estado"), "fa-heartbeat",
               lambda e, bp: e == "admin.estado"),
        Enlace("ajustes.editar", "admin.ajustes", _l("Ajustes"), "fa-sliders-h",
               lambda e, bp: e.startswith("admin.ajustes")),
    ]),
]


def menu_lateral(usuario, endpoint, blueprint, avisos=None):
    """Las secciones que ve este usuario, ya filtradas:
    [{"clave", "titulo", "icono", "enlaces": [{"endpoint", "texto", "icono", "activo", "contador",
      "titulo_contador"}], "abierta", "contador", "directo"}]"""
    avisos = avisos or {}
    endpoint = endpoint or ""
    resultado = []
    for seccion in SECCIONES:
        enlaces = [{"endpoint": e.endpoint, "texto": e.texto, "icono": e.icono,
                    "activo": bool(e.activo_si(endpoint, blueprint)),
                    "contador": e.contador(avisos), "titulo_contador": e.titulo_contador}
                   for e in seccion.enlaces if usuario.puede(e.permiso)]
        if not enlaces:
            continue
        resultado.append({
            "clave": seccion.clave, "titulo": seccion.titulo, "icono": seccion.icono, "enlaces": enlaces,
            "abierta": any(e["activo"] for e in enlaces),
            "contador": sum(e["contador"] for e in enlaces),
            "directo": len(enlaces) == 1,     # un solo enlace: sin cabecera ni desplegable
        })
    return resultado
