from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.alcance import filtrar_clientes, filtrar_facturas, filtrar_pedidos
from app.extensions import db
from app.permisos import ROLES_SOLO_SOPORTE, requiere_permiso
from app.models import ESTADOS_PREPARACION, ESTADOS_PROFORMA, Cliente, Factura, KitPedido, LineaPedido, Pedido

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def inicio():
    # Soporte ChromGo y Cliente ChromGo no trabajan con pedidos: su inicio es la lista de tickets
    if not current_user.puede("pedidos.ver") and current_user.puede("soporte.ver"):
        return redirect(url_for("soporte.lista"))
    # Tickets ChromGo quitados a su rol (Ajustes → Qué ve cada rol): a quien SOLO tiene ese rol no le
    # queda nada que ver. Se le explica, en vez de enseñarle un inicio de pedidos vacío.
    if current_user.rol in ROLES_SOLO_SOPORTE and not current_user.puede("soporte.ver"):
        return render_template("main/soporte_en_pausa.html")
    # Todas las cifras pasan por el filtro de alcance: cada uno ve SUS números
    def contar(estados):
        return db.session.scalar(filtrar_pedidos(
            db.select(func.count(Pedido.id)).where(Pedido.estado.in_(estados))))

    # Todas las cifras pasan por el filtro de alcance: cada uno ve SUS números
    resumen = {
        "pedidos_aceptados": contar(["aceptado"]),
        "pedidos_preparacion": contar(ESTADOS_PREPARACION),   # preparación + validación + listo para enviar
        "pedidos_enviados": contar(["enviado"]),
        "pedidos_entregados": contar(["entregado"]),
    }
    if current_user.puede("pedidos.proforma.enviar"):   # proformas que esperan que Yikon las prepare
        resumen["proformas_pendientes"] = contar(["proforma_solicitada", "cambios_solicitados"])
    elif current_user.puede("pedidos.proforma.responder"):   # el cliente: proformas por responder
        resumen["proformas_por_responder"] = contar(["proforma_enviada"])
    if current_user.puede("clientes.ver"):
        resumen["clientes"] = db.session.scalar(filtrar_clientes(
            db.select(func.count(Cliente.id)).filter_by(activo=True)))
    # (El stock bajo y las caducidades salen en sus iconos de la barra superior: ver
    #  el context processor "avisos" en app/__init__.py)
    if current_user.puede("facturas.ver"):
        # FAS: solo las de sus clientes (filtrar_facturas)
        pendientes = filtrar_facturas(db.select(Factura).filter_by(estado="pendiente")
                                      .where(Factura.enviada_el.isnot(None)))   # vencida: solo si el cliente la tiene
        resumen["vencidas"] = db.session.scalars(
            pendientes.where(Factura.fecha_vencimiento < date.today())
            .order_by(Factura.fecha_vencimiento)
        ).all()
    # "Pendientes": lo que esta persona tiene que hacer (no se va hasta que se hace).
    # La marca "nuevo" de la tabla de últimos pedidos es otra cosa: lo que ha cambiado desde su última visita.
    from app.pedidos.pendientes import pendientes_de
    # Yikon ve siempre todas sus pestañas de "Pendientes", también las vacías
    extra, pendientes = {}, pendientes_de(current_user, con_vacios=current_user.rol != "cliente")
    if current_user.rol == "cliente":      # su inicio es otro: app/main/inicio_cliente.py
        from app.main import inicio_cliente
        en_curso = inicio_cliente.pedidos_en_curso()
        extra = {"en_curso": en_curso[:inicio_cliente.MAXIMO_EN_CURSO], "total_en_curso": len(en_curso),
                 "te_tocan": sum(1 for f in en_curso if f["accion"]), "pasos": inicio_cliente.PASOS,
                 "proximo_envio": inicio_cliente.proximo_envio(en_curso),
                 "contactos": inicio_cliente.contactos(), "documentos": inicio_cliente.documentos_recientes(),
                 "actividad": inicio_cliente.actividad_reciente()}
        # Aviso de Ajustes → General (vacaciones, retrasos...): arriba del todo, en su idioma
        from flask_babel import get_locale

        from app import aviso_clientes
        extra["aviso_clientes"] = aviso_clientes.para(current_user, str(get_locale() or "es"))
        from app.control_admin import anuncios_para, bloqueo
        extra["anuncios_clientes"] = anuncios_para(current_user, str(get_locale() or "es"))
        extra["pedidos_pausados"] = bloqueo(current_user.cliente_id, str(get_locale() or "es"))
    if current_user.rol != "cliente":      # el mosaico de Yikon: app/main/inicio_yikon.py
        from app.main import inicio_yikon
        inicio_yikon.anotar_pendientes(pendientes)
        extra = {"fases": inicio_yikon.fases(resumen), "actividad": inicio_yikon.actividad_reciente()}
    return render_template("main/inicio.html", title=_("Inicio"), resumen=resumen,
                           pendientes=pendientes,
                           **extra)


@bp.route("/aviso-clientes/cerrar", methods=["POST"])
@login_required
def cerrar_aviso():
    """El cliente cierra el aviso de Ajustes → General: no le vuelve a salir hasta que cambie el texto."""
    from app.utils import es_url_segura
    huella = (request.form.get("huella") or "")[:20]
    if current_user.rol == "cliente" and huella:
        anuncio_id = request.form.get("anuncio_id")
        if anuncio_id:
            from app.control_admin import anuncios_para, anuncios
            from flask_babel import get_locale
            visibles = anuncios_para(current_user, str(get_locale() or "es"))
            if not any(a['id'] == anuncio_id and a['huella'] == huella for a in visibles):
                abort(404)
            ids = {a['id'] for a in anuncios()}
            cerrados = {k: v for k, v in (current_user.anuncios_cerrados or {}).items() if k in ids}
            current_user.anuncios_cerrados = dict(cerrados, **{anuncio_id: huella})
        else:
            current_user.aviso_cerrado = huella
        db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return "", 204
    destino = request.form.get("volver")
    return redirect(destino if es_url_segura(destino) else url_for("main.inicio"))


@bp.route("/idioma", methods=["POST"])
def cambiar_idioma():
    """
    Cambia el idioma de la interfaz. Se guarda en la sesión (sirve también en el login)
    y, si hay usuario, en su ficha: así la próxima vez entra ya en su idioma y sus
    correos le llegan en ese idioma. Es POST (con token CSRF) porque cambia datos.
    """
    from app.idioma import IDIOMAS
    codigo = request.form.get("idioma")
    if codigo in IDIOMAS:
        session["idioma"] = codigo
        if current_user.is_authenticated:
            current_user.idioma = codigo
            db.session.commit()
    # Volver a la página donde estaba, pero solo si es de esta misma web
    destino = request.referrer or ""
    if urlparse(destino).netloc != request.host:
        destino = url_for("main.inicio")
    return redirect(destino)


@bp.route("/estadisticas")
@requiere_permiso("estadisticas.ver")
def estadisticas():
    """Pedidos por mes, productos más pedidos y facturación por cliente.
    Cuenta los pedidos no cancelados del periodo elegido (?meses=6/12/24)."""
    from collections import defaultdict
    meses = request.args.get("meses", 12, type=int)
    if meses not in (6, 12, 24):
        meses = 12
    hoy = date.today()
    # primer día del mes de hace (meses - 1) meses
    anio, mes = hoy.year, hoy.month - (meses - 1)
    while mes <= 0:
        mes += 12
        anio -= 1
    desde = date(anio, mes, 1)
    hasta = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)   # primer día del mes que viene
    # selectinload: trae líneas, productos y clientes en pocas consultas (no una por pedido)
    pedidos = db.session.scalars(
        db.select(Pedido).where(Pedido.fecha >= desde, Pedido.fecha < hasta,
                                # las proformas todavía no son pedidos: no cuentan
                                Pedido.estado.notin_(["cancelado", *ESTADOS_PROFORMA]))
        .options(selectinload(Pedido.lineas).selectinload(LineaPedido.producto),
                 selectinload(Pedido.kits).selectinload(KitPedido.kit),
                 selectinload(Pedido.cliente))).all()

    # Una fila por mes, también los meses sin pedidos (si no, el gráfico engaña)
    claves, a, m = [], anio, mes
    for _i in range(meses):
        claves.append((a, m))
        m += 1
        if m > 12:
            m, a = 1, a + 1
    por_mes = {k: {"pedidos": 0, "importe": Decimal(0)} for k in claves}
    por_producto = defaultdict(int)
    por_kit = defaultdict(int)
    por_cliente = defaultdict(lambda: {"pedidos": 0, "importe": Decimal(0)})
    for p in pedidos:
        clave = (p.fecha.year, p.fecha.month)
        if clave in por_mes:
            por_mes[clave]["pedidos"] += 1
            por_mes[clave]["importe"] += p.total
        for linea in p.lineas:
            por_producto[linea.producto] += linea.cantidad
        for kp in p.kits:
            por_kit[kp.kit] += kp.cantidad
        por_cliente[p.cliente]["pedidos"] += 1
        por_cliente[p.cliente]["importe"] += p.total

    total = sum((p.total for p in pedidos), Decimal(0))
    resumen = {"pedidos": len(pedidos), "importe": total,
               "ticket_medio": (total / len(pedidos)) if pedidos else Decimal(0),
               "clientes": len(por_cliente)}
    return render_template(
        "main/estadisticas.html", title=_("Estadísticas"), meses=meses, desde=desde, resumen=resumen,
        por_mes=[{"fecha": date(a, m, 1), **v} for (a, m), v in por_mes.items()],
        productos=sorted(por_producto.items(), key=lambda x: -x[1])[:8],
        kits=sorted(por_kit.items(), key=lambda x: -x[1])[:8],
        clientes=sorted(por_cliente.items(), key=lambda x: -x[1]["importe"])[:10])


# --------------------------------------------------------------------------- #
# Buscador global (la caja de la barra superior): ver app/buscador.py
# --------------------------------------------------------------------------- #
@bp.route("/buscar")
@login_required
def buscar():
    from app.buscador import MIN_LETRAS, buscar as buscar_todo, limpiar
    q = limpiar(request.args.get("q"))
    grupos = buscar_todo(q, limite=8)
    # Un único resultado (p. ej. se escribió la referencia entera): directo a él
    if sum(g["total"] for g in grupos) == 1 and not request.args.get("lista"):
        return redirect(grupos[0]["resultados"][0]["url"])
    return render_template("main/buscar.html", title=_("Buscar"), q=q, grupos=grupos, corto=0 < len(q) < MIN_LETRAS)


@bp.route("/buscar/sugerencias")
@login_required
def buscar_sugerencias():
    """Trozo de HTML para el desplegable que aparece mientras se escribe (static/js/buscador.js)."""
    from flask import current_app, jsonify
    from app.buscador import buscar as buscar_todo, limpiar
    q = limpiar(request.args.get("q"))
    grupos = buscar_todo(q, limite=4)
    html = current_app.jinja_env.get_template("main/_sugerencias.html").render(q=q, grupos=grupos)
    return jsonify(html=html, q=q)


@bp.route("/actividad")
@login_required
def actividad():
    """Toda la actividad de los pedidos que ves (la casilla del inicio solo enseña la última),
    con filtro por cliente y por fechas. Solo Yikon; Soporte de cliente, lo de sus clientes."""
    from datetime import date as date_

    from flask import abort

    from app.main import inicio_yikon
    from app.utils import paginar
    if current_user.rol == "cliente":
        abort(403)

    def fecha(nombre):
        try:
            return date_.fromisoformat(request.args.get(nombre, ""))
        except ValueError:
            return None                      # vacía o mal escrita en la URL: se ignora el filtro
    clientes = db.session.scalars(filtrar_clientes(db.select(Cliente).order_by(Cliente.nombre))).all()
    cliente_id = request.args.get("cliente_id", type=int)
    if cliente_id not in {c.id for c in clientes}:
        cliente_id = None                    # uno que no existe o que no es suyo: como si no se filtrara
    desde, hasta = fecha("desde"), fecha("hasta")
    pagina = paginar(inicio_yikon.consulta_actividad(cliente_id, desde, hasta))
    return render_template("main/actividad.html", title=_("Actividad"), pagina=pagina,
                           eventos=inicio_yikon.eventos(pagina.items), clientes=clientes, cliente_id=cliente_id,
                           desde=desde, hasta=hasta)
