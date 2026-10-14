"""
Qué APARTADOS de la web ve cada rol. Admin lo cambia con casillas en Administración → Ajustes →
Qué ve cada rol, sin tocar código.

Cómo encaja con los permisos (permisos.py):
  - PERMISOS dice lo MÁS que puede llegar a hacer cada rol (el "techo"). Un apartado agrupa
    permisos ("facturas.ver", "facturas.revisar"…) y, si está quitado para un rol, ese rol pierde
    todos ellos: desaparece del menú, del buscador, de la campana y de las fichas, y sus páginas
    dan "sin permiso". Lo comprueba tiene_permiso() en cada pregunta.
  - En cada apartado, cada rol está:
      · fijo      → lo ve siempre (sin él no funciona el día a día; sale con candado)
      · cambiable → admin decide (casilla); de_fabrica dice cómo viene
      · nada      → ese rol no puede tenerlo (en la tabla sale "—")
  - Tickets ChromGo y Documentos internos están hechos pero en pausa: vienen quitados para todos
    (salvo que el .env diga lo contrario: SOPORTE_CHROMGO=1 / DOCUMENTOS_INTERNOS=1, que es su
    valor de fábrica). Al marcar la casilla de algún rol, vuelven con todo lo que tenían.

Se guarda en la tabla "ajustes" como apartado.<clave>.<rol> = "1"/"0", solo lo que no está como
de fábrica (así, si un día cambia el valor de fábrica, llega a quien no lo había tocado).
"""
from dataclasses import dataclass, field

from flask import current_app, g, has_app_context
from flask_babel import lazy_gettext as _l

ROLES_EN_ORDEN = ["admin", "facturacion", "logistica", "fas", "soporte", "cliente", "cliente_chromgo"]


@dataclass
class Apartado:
    nombre: str
    icono: str
    descripcion: str
    permisos: tuple = ()              # permisos que se pierden al quitarlo
    prefijo: str = ""                 # ...o todos los que empiezan así ("soporte.")
    fijos: set = field(default_factory=set)
    cambiables: set = field(default_factory=set)
    de_fabrica: set = field(default_factory=set)
    interruptor: str = ""             # si lo hay, el valor de fábrica es esa opción de config (para todos)
    aviso: str = ""                   # qué pasa si se quita (sale en la tabla)


APARTADOS = {
    "pedidos": Apartado(
        _l("Pedidos"), "fa-clipboard-list",
        _l("Lista y ficha de los pedidos, proformas, documentos y el chat con el cliente (Almacén: desde que el cliente acepta)."),
        fijos={"admin", "facturacion", "logistica", "fas", "cliente"}),
    "preparar": Apartado(
        _l("Preparar y fotos"), "fa-camera", _l("Preparar los pedidos, hacer las fotos y enviarlos."),
        fijos={"admin", "logistica"}),
    "inventario": Apartado(
        _l("Inventario"), "fa-warehouse", _l("Stock, entradas y salidas, reservas de lotes (Facturación: solo consulta)."),
        permisos=("inventario.ver",), fijos={"admin", "logistica"}, cambiables={"facturacion"}, de_fabrica={"facturacion"}),
    "catalogo": Apartado(
        _l("Kits y productos"), "fa-boxes",
        _l("El catálogo. Al cliente: los productos activos con su ficha de seguridad, sin precios."),
        permisos=("productos.ver", "productos.catalogo"),
        fijos={"admin", "facturacion"}, cambiables={"logistica", "fas", "cliente"}, de_fabrica={"logistica", "fas", "cliente"}),
    "lotes": Apartado(
        _l("Lotes y trazabilidad"), "fa-search-location",
        _l("La sección «Lotes» de cada pedido (qué lote sale y cuál salió) y «Rastrear lote»."),
        permisos=("pedidos.ver_lotes",),
        fijos={"admin", "logistica"}, cambiables={"fas", "facturacion"}, de_fabrica={"fas", "facturacion"}),
    "clientes": Apartado(
        _l("Clientes"), "fa-building",
        _l("La ficha de cada cliente: datos, usuarios, facturación (Soporte de cliente: solo los suyos)."),
        permisos=("clientes.ver", "clientes.precios_visibles", "clientes.avisos", "clientes.catalogo"),
        fijos={"admin", "facturacion"}, cambiables={"fas"}, de_fabrica={"fas"}),
    "facturas": Apartado(
        _l("Facturas"), "fa-file-invoice-dollar",
        _l("Las facturas (al cliente, solo las suyas ya enviadas). Soporte de cliente, además, las revisa."),
        permisos=("facturas.ver", "facturas.revisar", "facturas.ver_propias", "facturas.descargar"),
        fijos={"admin", "facturacion"}, cambiables={"fas", "cliente"}, de_fabrica={"fas", "cliente"},
        aviso=_l("Sin él, Soporte de cliente no revisa facturas: las que lo pidan las revisará admin.")),
    "estadisticas": Apartado(
        _l("Estadísticas"), "fa-chart-bar", _l("Pedidos por mes, productos más pedidos y facturación por cliente."),
        permisos=("estadisticas.ver",), fijos={"admin"}, cambiables={"facturacion"}, de_fabrica={"facturacion"}),
    "tickets": Apartado(
        _l("Tickets ChromGo"), "fa-life-ring",
        _l("Soporte de ChromGo. Al cliente, solo a los usuarios con «Acceso a Soporte ChromGo» en su ficha."),
        prefijo="soporte.", cambiables={"admin", "soporte", "fas", "cliente", "cliente_chromgo"},
        interruptor="SOPORTE_CHROMGO",
        aviso=_l("En pausa: actívalo cuando se empiece a usar. Los roles Soporte ChromGo y Cliente ChromGo "
                 "solo se ofrecen al crear usuarios si lo tienen activado.")),
    "documentos": Apartado(
        _l("Documentos internos"), "fa-folder-open",
        _l("Logos, plantillas y protocolos del equipo (no son los documentos de los pedidos). Subir y borrar: solo admin."),
        prefijo="documentos.", cambiables={"admin", "facturacion", "logistica", "fas", "soporte"},
        interruptor="DOCUMENTOS_INTERNOS", aviso=_l("En pausa: actívalo cuando se empiece a usar.")),
    "administracion": Apartado(
        _l("Administración"), "fa-cogs", _l("Usuarios, auditoría y estos ajustes."), fijos={"admin"}),
}


def apartado_de(permiso):
    """La clave del apartado al que pertenece un permiso (None si no es de ninguno cambiable)."""
    for clave, ap in APARTADOS.items():
        if permiso in ap.permisos or (ap.prefijo and permiso.startswith(ap.prefijo)):
            return clave
    return None


def _clave(apartado, rol):
    return f"apartado.{apartado}.{rol}"


def _guardados():
    """{clave del ajuste: "1"/"0"} — una sola consulta por petición (se pregunta muchas veces)."""
    if not has_app_context():
        return {}
    if "_apartados" not in g:
        from app.extensions import db
        from app.models import Ajuste
        try:
            g._apartados = {a.clave: a.valor for a in db.session.scalars(
                db.select(Ajuste).where(Ajuste.clave.like("apartado.%")))}
        except Exception:                 # (la tabla aún no existe: p. ej. durante "flask db upgrade")
            db.session.rollback()
            g._apartados = {}
    return g._apartados


def olvidar():
    """Tras guardar: que la próxima pregunta vuelva a leerlos."""
    if has_app_context():
        g.pop("_apartados", None)


def de_fabrica(clave, rol) -> bool:
    ap = APARTADOS[clave]
    if rol in ap.fijos:
        return True
    if rol not in ap.cambiables:
        return False
    if ap.interruptor:
        return bool(current_app.config.get(ap.interruptor)) if has_app_context() else False
    return rol in ap.de_fabrica


def visible(clave, rol) -> bool:
    """¿Este rol ve este apartado?"""
    ap = APARTADOS[clave]
    if rol in ap.fijos:
        return True
    if rol not in ap.cambiables:
        return False
    guardado = _guardados().get(_clave(clave, rol))
    return guardado == "1" if guardado is not None else de_fabrica(clave, rol)


def permite(rol, permiso) -> bool:
    """¿El apartado de este permiso está activado para este rol? (True si no es de ningún apartado)"""
    clave = apartado_de(permiso)
    return clave is None or visible(clave, rol)


def activo_para_alguien(clave) -> bool:
    ap = APARTADOS[clave]
    return any(visible(clave, rol) for rol in ap.fijos | ap.cambiables)


def tabla():
    """Para la página de ajustes: [(clave, apartado, {rol: "fijo"/"si"/"no"/None})]."""
    filas = []
    for clave, ap in APARTADOS.items():
        celdas = {}
        for rol in ROLES_EN_ORDEN:
            if rol in ap.fijos:
                celdas[rol] = "fijo"
            elif rol in ap.cambiables:
                celdas[rol] = "si" if visible(clave, rol) else "no"
            else:
                celdas[rol] = None
        filas.append((clave, ap, celdas))
    return filas


def guardar(marcados) -> list:
    """marcados: {(clave, rol)} con las casillas marcadas. Guarda (sin commit) y devuelve los
    cambios como texto para la auditoría: ["facturas·cliente sí→no", …]."""
    from app.extensions import db
    from app.models import Ajuste
    cambios = []
    for clave, ap in APARTADOS.items():
        for rol in ap.cambiables:
            nuevo, antes = (clave, rol) in marcados, visible(clave, rol)
            fila = db.session.get(Ajuste, _clave(clave, rol))
            if nuevo == de_fabrica(clave, rol):
                if fila is not None:
                    db.session.delete(fila)
            elif fila is None:
                db.session.add(Ajuste(clave=_clave(clave, rol), valor="1" if nuevo else "0"))
            else:
                fila.valor = "1" if nuevo else "0"
            if nuevo != antes:
                cambios.append(f"{clave}·{rol} {'no→sí' if nuevo else 'sí→no'}")
    olvidar()
    return cambios
