"""
Inicio del equipo de Yikon (admin, logística y Soporte de cliente): lo que rodea a "Pendientes"
en el mosaico (ese bloque sale de app/pedidos/pendientes.py).

  - fases(): la tira de arriba, un botón por fase con cuántos pedidos tiene;
  - anotar_pendientes(): añade a cada línea qué lleva el pedido, cuánto espera y si va con retraso
    (los plazos los fija admin en Administración → Ajustes: app/ajustes.py);
  - actividad_reciente(): quién ha hecho qué en los pedidos (sale de la auditoría); la lista
    completa, con filtros, es la página "Actividad" (consulta_actividad + eventos).

Todo pasa por los filtros de alcance: Soporte de cliente solo ve lo de sus clientes.
La plantilla es app/templates/main/_inicio_yikon.html.
"""
from flask import url_for
from markupsafe import Markup, escape
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy.orm import selectinload

from app.alcance import filtrar_pedidos
from app.extensions import db
from app.models import Factura, Pedido, RegistroAuditoria, ahora
from app.pedidos.novedades import _CAMBIO_ESTADO

MAXIMO_ACTIVIDAD = 6
_MARCA_QUIEN, _MARCA_REF = "\x00quien\x00", "\x00ref\x00"


def _desde_cuando(pedidos) -> dict:
    """{pedido_id: momento en que entró en su estado actual}. Sale de la auditoría (el último
    "… → estado"); si el pedido nació en ese estado, de cuando se creó."""
    if not pedidos:
        return {}
    registros = db.session.scalars(
        db.select(RegistroAuditoria)
        .where(RegistroAuditoria.entidad == "Pedido", RegistroAuditoria.entidad_id.in_([p.id for p in pedidos]))
        .order_by(RegistroAuditoria.id.desc())).all()
    estado = {p.id: p.estado for p in pedidos}
    desde, creado = {}, {}
    for r in registros:
        if r.accion == "crear":
            creado[r.entidad_id] = r.fecha
        cambio = _CAMBIO_ESTADO.match(r.detalle or "")
        if cambio and cambio.group(2) == estado[r.entidad_id]:
            desde.setdefault(r.entidad_id, r.fecha)        # el más reciente (van de nuevo a viejo)
    return {id_: desde.get(id_) or creado.get(id_) for id_ in estado}


def fases(resumen) -> list:
    """La tira de fases: [{"estado" (para el color), "icono", "nombre", "n", "url"}]. Los números
    vienen de `resumen` (ya filtrados por alcance en la vista)."""
    lista = []
    if "proformas_pendientes" in resumen:
        lista.append({"estado": "proforma_solicitada", "icono": "fa-file-signature", "nombre": _("Proformas"),
                      "n": resumen["proformas_pendientes"], "url": url_for("pedidos.lista", estado="proforma_pendiente")})
    lista += [
        {"estado": "aceptado", "icono": "fa-check", "nombre": _("Aceptados"), "n": resumen["pedidos_aceptados"],
         "url": url_for("pedidos.lista", estado="aceptado")},
        {"estado": "en_preparacion", "icono": "fa-box-open", "nombre": _("En preparación"),
         "n": resumen["pedidos_preparacion"], "url": url_for("pedidos.lista", estado="preparacion")},
        {"estado": "enviado", "icono": "fa-truck", "nombre": _("Enviados"), "n": resumen["pedidos_enviados"],
         "url": url_for("pedidos.lista", estado="enviado")},
        {"estado": "entregado", "icono": "fa-flag-checkered", "nombre": _("Recibidos"), "n": resumen["pedidos_entregados"],
         "url": url_for("pedidos.lista", estado="entregado")},
    ]
    if "vencidas" in resumen:
        lista.append({"estado": "cambios_solicitados", "icono": "fa-exclamation-triangle", "nombre": _("Fact. vencidas"),
                      "n": len(resumen["vencidas"]), "url": url_for("facturas.lista", estado="vencida")})
    return lista


def anotar_pendientes(grupos, ahora_=None) -> list:
    """A cada línea de "Pendientes" que es de un pedido le añade:
      - "contenido": qué lleva;  - "espera": días desde que entró en su estado actual;
      - "lento": True si ha pasado el plazo de ese estado (Administración → Ajustes).
    Dentro de cada grupo suben arriba los que más llevan esperando, y el grupo se queda con cuántos
    van con retraso ("lentos"). Devuelve los mismos grupos.
    Además, la marca "nuevo" de la lista de pedidos: "novedad" en cada línea cuyo pedido ha cambiado
    desde tu última visita ({"ancla", "texto"}) y "con_novedades" en el grupo. Esas líneas van primero,
    para que no se queden fuera de las que caben."""
    from app.ajustes import plazos
    from app.main.inicio_cliente import contenido_corto
    from app.pedidos.pendientes import MAXIMO_POR_GRUPO
    ahora_ = ahora_ or ahora()
    pedidos = {f["pedido"].id: f["pedido"] for g in grupos for f in g["todas"] if f.get("pedido")}
    desde, plazo = _desde_cuando(list(pedidos.values())), plazos()
    from flask_login import current_user
    from app.pedidos.novedades import resumen_novedades
    con_marca = {p.id: p for g in grupos for f in g["todas"]
                 for p in [f.get("pedido") or f.get("pedido_novedades")] if p is not None}
    novedades = resumen_novedades(current_user, list(con_marca.values()))
    for g in grupos:
        for f in g["todas"]:
            de_quien = f.get("pedido") or f.get("pedido_novedades")
            f["novedad"] = novedades.get(de_quien.id) if de_quien is not None else None
            pedido = f.get("pedido")
            if pedido is None:
                continue
            f["contenido"] = contenido_corto(pedido)
            momento = desde.get(pedido.id)
            if momento is None:
                continue
            if momento.tzinfo is None:                      # SQLite devuelve las fechas sin zona
                momento = momento.replace(tzinfo=ahora_.tzinfo)
            f["espera"] = (ahora_ - momento).days
            dias = plazo.get(pedido.estado, 0)
            # "Por facturar" no tiene plazo propio: el del estado (enviado/recibido) no le aplica
            f["lento"] = g["clave"] != "facturar" and bool(dias) and f["espera"] >= dias
        g["lentos"] = sum(1 for f in g["todas"] if f.get("lento"))
        g["con_novedades"] = any(f["novedad"] for f in g["todas"])
        g["filas"] = sorted(g["todas"], key=lambda f: (not f["novedad"], -f.get("espera", -1)))[:MAXIMO_POR_GRUPO]
    return grupos


def _frase(registro, quien, ref):
    """(icono, texto) de una entrada de auditoría, o None si no merece salir (precios, lotes...)."""
    detalle = registro.detalle or ""
    if registro.entidad == "Factura":
        return ("fa-file-invoice-dollar", _("%(quien)s ha registrado una factura en %(ref)s", quien=quien, ref=ref)) \
            if registro.accion == "crear" else None
    if registro.accion == "crear":
        return "fa-plus", _("%(quien)s ha creado el pedido %(ref)s", quien=quien, ref=ref)
    if detalle.startswith("documento adjuntado"):
        return "fa-paperclip", _("%(quien)s ha subido un documento a %(ref)s", quien=quien, ref=ref)
    cambio = _CAMBIO_ESTADO.match(detalle)
    if not cambio:
        return None
    origen, destino = cambio.groups()
    frases = {
        "proforma_enviada": ("fa-file-signature", _("%(quien)s ha enviado la proforma de %(ref)s", quien=quien, ref=ref)),
        "cambios_solicitados": ("fa-pen", _("%(quien)s pide cambios en la proforma de %(ref)s", quien=quien, ref=ref)),
        "aceptado": ("fa-check", _("%(quien)s ha aceptado %(ref)s", quien=quien, ref=ref)),
        "en_validacion": ("fa-camera", _("%(quien)s ha enviado %(ref)s a validación", quien=quien, ref=ref)),
        "validado": ("fa-check-double", _("%(quien)s ha validado %(ref)s", quien=quien, ref=ref)),
        "enviado": ("fa-truck", _("%(quien)s ha enviado %(ref)s", quien=quien, ref=ref)),
        "entregado": ("fa-flag-checkered", _("%(quien)s ha confirmado la recepción de %(ref)s", quien=quien, ref=ref)),
        "cancelado": ("fa-times", _("%(quien)s ha cancelado %(ref)s", quien=quien, ref=ref)),
    }
    if destino == "en_preparacion":
        if origen == "en_validacion":
            return "fa-undo", _("%(quien)s ha devuelto %(ref)s a preparación", quien=quien, ref=ref)
        return "fa-box-open", _("%(quien)s ha empezado a preparar %(ref)s", quien=quien, ref=ref)
    # Cualquier otro cambio de estado (raro: uno forzado por admin) también se cuenta, en general
    return frases.get(destino) or ("fa-exchange-alt", _("%(quien)s ha cambiado el estado de %(ref)s", quien=quien, ref=ref))


def consulta_actividad(cliente_id=None, desde=None, hasta=None, sin_lo_mio=False):
    """SELECT de las entradas de auditoría que se cuentan como actividad, lo más reciente primero:
    de los pedidos que esta persona ve (y sus facturas), solo los hechos que tienen frase (_frase):
    crear, cambiar de estado, adjuntar un documento y registrar una factura.
    Filtros opcionales: un cliente, entre dos fechas, y sin lo que ha hecho uno mismo."""
    from datetime import datetime, time, timedelta

    from app.models import ESTADOS_PEDIDO
    pedidos = filtrar_pedidos(db.select(Pedido.id))
    if cliente_id:
        pedidos = pedidos.where(Pedido.cliente_id == cliente_id)
    R = RegistroAuditoria
    de_pedido = db.and_(R.entidad == "Pedido", R.entidad_id.in_(pedidos), db.or_(
        R.accion == "crear", R.detalle.like("documento adjuntado%"),
        *[R.detalle.like(f"{estado} → %") for estado in ESTADOS_PEDIDO]))
    de_factura = db.and_(R.entidad == "Factura", R.accion == "crear",
                         R.entidad_id.in_(db.select(Factura.id).where(Factura.pedido_id.in_(pedidos))))
    select = (db.select(R).where(R.usuario_id.isnot(None), db.or_(de_pedido, de_factura))
              .options(selectinload(R.usuario)).order_by(R.id.desc()))
    if sin_lo_mio:
        select = select.where(R.usuario_id != current_user.id)
    if desde:
        select = select.where(R.fecha >= datetime.combine(desde, time.min))
    if hasta:
        select = select.where(R.fecha < datetime.combine(hasta + timedelta(days=1), time.min))
    return select


def eventos(registros) -> list:
    """De entradas de auditoría a lo que se pinta: [{"icono", "html", "fecha", "url"}].
    "html": la frase con quién en negrita y la referencia del pedido como enlace."""
    registros = list(registros)
    de_factura = [r.entidad_id for r in registros if r.entidad == "Factura"]
    pedido_de_factura = dict(db.session.execute(
        db.select(Factura.id, Factura.pedido_id).where(Factura.id.in_(de_factura))).all()) if de_factura else {}
    resultado = []
    for registro in registros:
        pedido_id = pedido_de_factura.get(registro.entidad_id) if registro.entidad == "Factura" else registro.entidad_id
        pedido, autor = db.session.get(Pedido, pedido_id), registro.usuario
        # La frase se traduce con dos marcas en el sitio de "quién" y de la referencia; después se
        # cambian por el nombre en negrita y la referencia como enlace (todo escapado antes).
        frase = _frase(registro, _MARCA_QUIEN, _MARCA_REF)
        if pedido is None or frase is None:
            continue
        # Del cliente se dice su empresa; de la gente de Yikon, su nombre
        quien = autor.empresa.nombre if autor.es_cliente and autor.empresa else autor.nombre
        ref, url = pedido.referencia_interna or f"#{pedido.id}", url_for("pedidos.detalle", id=pedido.id)
        html = (escape(frase[1])
                .replace(_MARCA_QUIEN, Markup("<strong>%s</strong>") % quien)
                .replace(_MARCA_REF, Markup('<a class="fw-semibold" href="%s">%s</a>') % (url, ref)))
        resultado.append({"icono": frase[0], "html": html, "fecha": registro.fecha, "url": url, "cliente": pedido.cliente})
    return resultado


def actividad_reciente() -> list:
    """La casilla del inicio: lo último que han hecho OTROS en los pedidos que ves (lo propio no
    es novedad). Todo, también lo de uno mismo, está en la página "Actividad" (/actividad)."""
    return eventos(db.session.scalars(consulta_actividad(sin_lo_mio=True).limit(MAXIMO_ACTIVIDAD)))
