"""
Roles y permisos de la plataforma.

Toda la lógica de "quién puede hacer qué" vive AQUÍ. PERMISOS dice lo MÁS que puede hacer
cada rol; encima, admin quita o pone APARTADOS enteros a cada rol desde Ajustes → Qué ve cada
rol (app/apartados.py). Las vistas y las plantillas preguntan por el permiso, nunca por el rol.
"""
from functools import wraps

from flask import abort
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required

from app import apartados

# El nombre VISIBLE del rol "fas" (FAS y business developers: quienes llevan clientes asignados).
# Está solo aquí: los textos lo reciben como %(rol)s y las plantillas como {{ rol_fas }}.
# Por dentro (base de datos, permisos, código) el rol sigue llamándose "fas".
NOMBRE_FAS = _l("Soporte de cliente")

ROLES = {
    "admin": _l("Administrador"),                # todo; da los accesos (usuarios y clientes)
    "facturacion": _l("Facturación"),            # proformas, facturas, clientes, precios y catálogo
    # Por dentro sigue llamándose "logistica" (así los usuarios que ya había no cambian); desde el
    # 14/10/2026 es solo el ALMACÉN: los pedidos desde que el cliente acepta, fotos, envío e inventario
    "logistica": _l("Almacén"),
    "fas": NOMBRE_FAS,                            # lleva sus clientes asignados: pedidos y ChromGo
    "soporte": _l("Soporte ChromGo"),            # Yikon: tickets de ChromGo
    "cliente": _l("Cliente"),                    # empresa cliente: sus pedidos (y tickets si se le da acceso)
    "cliente_chromgo": _l("Cliente ChromGo"),    # empresa cliente: solo sus tickets de ChromGo
}

# Qué registros ve cada uno (lo aplica alcance.py; aquí solo se agrupan los roles):
#   admin y Facturación → todos · Almacén → todos desde que el cliente acepta (no las proformas)
#   FAS → sus clientes asignados · clientes → su empresa
ROLES_CLIENTE = {"cliente", "cliente_chromgo"}      # tienen empresa y solo ven lo suyo
ROLES_YIKON = {"admin", "facturacion", "logistica", "fas", "soporte"}
ALMACEN = {"admin", "logistica"}                    # preparar, fotos, enviar, inventario
OFICINA = {"admin", "facturacion"}                  # proformas, facturas, clientes, precios, catálogo
GESTION = {"admin", "facturacion", "fas"}           # Yikon en lo comercial del pedido (FAS: sus clientes)
YIKON_PEDIDOS = GESTION | {"logistica"}             # Yikon en los pedidos (Almacén: desde «aceptado»)
PEDIDOS = YIKON_PEDIDOS | {"cliente"}               # los que trabajan con pedidos
# Con quién puede compartir el Soporte de cliente un mensaje de la conversación general (es privada)
COMPARTIR_CON = ("logistica", "facturacion")
TODOS = PEDIDOS   # (nombre antiguo; OJO: no es set(ROLES), un rol nuevo no hereda nada sin querer)

PERMISOS = {
    # Clientes (empresas/clínicas): admin y Facturación, todos; el FAS, los suyos. Almacén no.
    "clientes.ver": {"admin", "facturacion", "fas"},
    "clientes.editar": OFICINA,                        # datos, facturación, precios especiales
    "clientes.asignar_soporte": {"admin"},             # quién es su Soporte de cliente (decide quién ve qué)
    "clientes.precios_visibles": GESTION,              # decidir si un cliente ve precios
    "clientes.avisos": GESTION,                        # qué avisos por email recibe cada usuario del cliente
    "clientes.catalogo": GESTION,                      # su catálogo: qué kits puede pedir y qué productos ve
    "clientes.exportar": {"admin"},                    # descargar todo lo de un cliente en un ZIP
    # Catálogo de productos
    "productos.ver": YIKON_PEDIDOS,
    "productos.editar": OFICINA,                 # (Almacén cambia el stock mínimo desde Inventario)
    "productos.catalogo": {"cliente"},           # el cliente: catálogo activo con SDS, sin precios
    "productos.sds": PEDIDOS,                    # descargar la ficha de seguridad (SDS)
    # Pedidos (cada uno solo los que le tocan: alcance.py)
    "pedidos.ver": PEDIDOS,
    "pedidos.crear": GESTION | {"cliente"},      # Almacén no crea pedidos
    "pedidos.editar": GESTION,                   # líneas, precios, cancelar y reabrir
    "pedidos.lotes": YIKON_PEDIDOS,              # reservar lotes (Facturación/FAS en la proforma; Almacén, al llegar el stock)
    "pedidos.ver_importes": GESTION,             # precios, IVA y totales (Almacén no)
    "pedidos.ver_lotes": YIKON_PEDIDOS,          # trazabilidad: qué lote salió en cada envío
    "pedidos.documentos.ver": PEDIDOS,
    "pedidos.documentos.subir": PEDIDOS,
    # Preparación y validación con fotos (el cliente nunca ve las fotos)
    "pedidos.fotos.ver": YIKON_PEDIDOS,
    "pedidos.preparar": ALMACEN,                 # Almacén pasa un pedido aceptado a "En preparación"...
    "pedidos.fotos.subir": ALMACEN,              # ...lo prepara y hace las fotos
    "pedidos.validar": {"fas", "admin"},         # el FAS del cliente las valida (admin puede suplirle)
    "pedidos.enviar": ALMACEN,                   # Almacén lo envía (y puede marcarlo recibido por el cliente)
    "pedidos.recibir": {"cliente"},              # el cliente marca que ha recibido el pedido
    "pedidos.forzar_estado": {"admin"},          # admin puede saltarse el flujo (queda en auditoría)
    # Proforma antes del pedido
    "pedidos.proforma.enviar": GESTION,          # preparar y enviar la proforma (FAS: sus clientes)
    "pedidos.proforma.responder": {"cliente"},   # aceptarla (→ "aceptado") o pedir cambios
    "pedidos.proforma.cancelar": {"cliente"},    # el cliente cancela mientras es proforma
    "pedidos.exportar": PEDIDOS,                 # PDF del estado de pedidos
    # Incidencias: "Hay un problema con este pedido" (enviado o recibido). Se habla en el chat del pedido
    "pedidos.incidencias.abrir": {"cliente"},
    "pedidos.incidencias.resolver": YIKON_PEDIDOS,   # cerrarla con «Resuelta» y una nota
    # Mensajes con el cliente y chat interno de cada pedido (el cliente no ve el interno)
    "mensajes.ver": PEDIDOS,
    "mensajes.enviar": PEDIDOS,
    "mensajes.internos": YIKON_PEDIDOS,
    # QUIÉN HABLA CON LOS CLIENTES: admin lo decide en Ajustes → Qué ve cada rol (apartados.py,
    # filas «Conversación general» y «Mensajes en los pedidos»). Esto es el techo:
    #  · escribir al cliente en la conversación de un pedido (de fábrica: todo Yikon)
    "mensajes.pedido_cliente": PEDIDOS,
    #  · la conversación GENERAL de cada cliente (de fábrica: el cliente y su Soporte de cliente;
    #    admin también la ve, pero el cliente no lo sabe: admin es un perfil interno). Facturación y
    #    Almacén, si admin no se la da, solo ven lo que el Soporte les comparte (alcance.filtrar_mensajes).
    "mensajes.general": YIKON_PEDIDOS | {"cliente"},
    "mensajes.compartir": {"admin", "fas"},          # "Compartir con Almacén / Facturación"
    # Inventario de la oficina (Facturación: consulta, para ver stock y caducidades al hacer la proforma)
    "inventario.ver": ALMACEN | {"facturacion"},
    "inventario.editar": ALMACEN,
    # Facturas (FAS: solo consulta, de sus clientes)
    "facturas.ver": GESTION,
    "facturas.editar": OFICINA,
    "facturas.revisar": {"admin", "fas"},          # aprobar o devolver antes de enviarla (FAS: sus clientes)
    "facturas.ver_propias": {"cliente"},         # el cliente ve las de SU empresa (sin notas)
    "facturas.descargar": GESTION | {"cliente"},  # PDF oficial (cada uno las que ve)
    # Documentos internos de Yikon (logos, plantillas, protocolos...). El cliente nunca.
    "documentos.ver": ROLES_YIKON,
    "documentos.subir": {"admin"},               # subir documentos y versiones nuevas, editar datos
    "documentos.borrar": {"admin"},
    # Soporte ChromGo (tickets): soporte y admin, todos; el FAS, los de sus clientes
    "soporte.ver": {"admin", "soporte", "fas", "cliente_chromgo"},    # "cliente": si su USUARIO tiene acceso
    "soporte.crear": {"admin", "soporte", "cliente_chromgo"},
    "soporte.responder": {"admin", "soporte", "fas"},   # escribir al cliente en el ticket
    "soporte.gestionar": {"admin", "soporte"},    # estado, prioridad, asignar; todos los tickets
    "soporte.notas": {"admin", "soporte", "fas"},  # leer y escribir las notas internas de los tickets
    # Administración de la plataforma
    "usuarios.gestionar": {"admin"},
    "usuarios.ver_como": {"admin"},              # ver la plataforma como otro usuario (solo lectura)
    "auditoria.ver": {"admin"},
    "ajustes.editar": {"admin"},                 # plazos de aviso (Administración → Ajustes)
    "estadisticas.ver": OFICINA,
    "correos.ver": GESTION,                      # registro de correos enviados (Soporte: los de sus clientes)
    "correos.reenviar": {"admin"},
    "estado.ver": {"admin"},                     # Administración → Estado de la plataforma
}


# Permisos que el rol "cliente" NO tiene por defecto, pero sí si se le activa la opción indicada:
# a su EMPRESA (campo de Cliente) o a su propio USUARIO (campo de User). Lo mira User.puede().
PERMISOS_SEGUN_EMPRESA = {
    "pedidos.ver_importes": "ver_precios",   # precios de sus pedidos, catálogo y facturas
}
PERMISOS_SEGUN_USUARIO = {
    "soporte.ver": "acceso_chromgo",         # admin le da acceso a Soporte ChromGo en su ficha de usuario
    "soporte.crear": "acceso_chromgo",
}


# --------------------------------------------------------------------------- #
# Módulos en pausa: Soporte ChromGo (tickets) y Documentos internos
# --------------------------------------------------------------------------- #
# Están hechos pero de momento no se usan. Son dos apartados (app/apartados.py) que vienen
# quitados para todos; admin los activa por rol desde Ajustes → Qué ve cada rol. Sin activar:
#   - nadie tiene sus permisos → desaparecen del menú, del buscador y de la campana;
#   - sus páginas (/soporte/..., /documentos/...) responden "no encontrado";
#   - los roles Soporte ChromGo y Cliente ChromGo, y la casilla "Acceso a Soporte ChromGo",
#     no se ofrecen al crear usuarios (roles_disponibles).
# El código, las tablas y los datos siguen ahí: al activarlos vuelve todo tal cual estaba.
ROLES_SOLO_SOPORTE = {"soporte", "cliente_chromgo"}


def soporte_activo() -> bool:
    """¿Alguien ve los Tickets ChromGo?"""
    return apartados.activo_para_alguien("tickets")


def chromgo_para_clientes() -> bool:
    """¿Se puede dar a un usuario Cliente el "Acceso a Soporte ChromGo"?"""
    return apartados.visible("tickets", "cliente")


def documentos_activos() -> bool:
    """¿Alguien ve los Documentos internos?"""
    return apartados.activo_para_alguien("documentos")


def roles_disponibles(incluir=None) -> dict:
    """Los roles que se pueden asignar ahora: sin los de Soporte que no tengan los tickets activados.
    `incluir`: un rol que hay que ofrecer igualmente (el que ya tiene el usuario que se edita)."""
    return {clave: nombre for clave, nombre in ROLES.items()
            if clave not in ROLES_SOLO_SOPORTE or clave == incluir or apartados.visible("tickets", clave)}


def tiene_permiso(rol: str, permiso: str) -> bool:
    return rol in PERMISOS.get(permiso, set()) and apartados.permite(rol, permiso)


def requiere_permiso(permiso: str):
    """Decorador para vistas: @requiere_permiso('facturas.editar')."""
    if permiso not in PERMISOS:
        raise ValueError(f"Permiso desconocido: {permiso}")

    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(*args, **kwargs):
            if not current_user.puede(permiso):
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador
