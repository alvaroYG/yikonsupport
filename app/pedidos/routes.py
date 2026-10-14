import json
from datetime import date
from decimal import Decimal

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from flask_babel import force_locale, gettext as _
from flask_login import current_user
from sqlalchemy.orm import selectinload

from app import avisos_internos
from app.alcance import cliente_o_404, filtrar_clientes, filtrar_pedidos, pedido_o_404
from app.auditoria import registrar
from app.extensions import db
from app.notificaciones import (avisar_cambio_estado_cliente, avisar_datos_envio, avisar_recibido,
                                avisar_revisar_urgente)
from app.inventario import reservas
from app.inventario.stock import aplicar_cambio_de_estado, lotes_enviados, resumen_salida, sale_de_oficina
from app.utils import es_entero, limpiar_busqueda, ordenar
from app.models import (ESTADOS_PEDIDO, ESTADOS_PEDIDO_CLIENTE, ESTADOS_PREPARACION, TRANSICIONES, puede_alguno,
                        Cliente, DocumentoPedido, FotoPedido, Kit, KitPedido, LineaPedido, Pedido, Producto,
                        RevisionPedido, hilo_de)
from app.pedidos.forms import (TRANSPORTISTAS_HABITUALES, AnadirKitForm, DatosEnvioForm, DocumentoForm, EstadoPedidoForm,
                               FotosForm, LineaForm, PedidoClienteForm, PedidoInternoForm, ValidacionForm,
                               con_ids_propios)
from app.mensajes import servicio as servicio_mensajes
from app.mensajes.forms import MensajeForm
from app.pedidos import documentos as docs
from app.pedidos.historial import historial_pedido
from app.mensajes.routes import mensaje_para_deshacer
from app.pedidos.novedades import marcar_visto, novedades_de, resumen_novedades
from app.pedidos.fotos import FotoNoValida, borrar_archivo, carpeta, guardar_foto
from app.pedidos.pdf import generar_pdf_pedidos
from app.permisos import requiere_permiso
from app.utils import leer_precio, paginar
from app.permisos import NOMBRE_FAS

bp = Blueprint("pedidos", __name__)


def _puede_modificar_lineas(pedido):
    """
    Lo que lleva el pedido (kits, productos, cantidades) solo se toca mientras Yikon
    prepara la proforma (ver Pedido.editable), y solo Yikon (admin, logística, FAS). (El cliente no:
    ahí se ven y cambian precios.)
    """
    return pedido.editable and current_user.puede("pedidos.editar")


# Hasta que sale de la oficina, Yikon (admin, logística, FAS) pueden ajustar los precios a mano
ESTADOS_CON_PRECIO_EDITABLE = {"proforma_solicitada", "proforma_enviada", "cambios_solicitados", "aceptado",
                               "en_preparacion", "en_validacion", "validado"}


def _puede_cambiar_precios(pedido):
    # Con una factura ya registrada, cambiar precios descuadraría pedido y factura
    return (pedido.estado in ESTADOS_CON_PRECIO_EDITABLE and not pedido.facturas
            and current_user.puede("pedidos.editar"))


def _fecha(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None  # fecha mal escrita en la URL: se ignora el filtro


def _estados_filtro():
    return ESTADOS_PEDIDO_CLIENTE if current_user.rol == "cliente" else ESTADOS_PEDIDO


def _pedidos_filtrados():
    """
    Lee los filtros de la URL (?estado=...&cliente_id=...) y construye la consulta.
    La usan tanto la lista como el PDF, así ambos muestran exactamente lo mismo.
    Devuelve (consulta, filtros, descripción legible de los filtros).
    """
    a = request.args
    # "proforma_pendiente" (Yikon (admin, logística, FAS)): nuevas o con cambios pedidos, las dos por preparar
    # y "preparacion" (todos): preparación + validación + listo para enviar (tarjeta del inicio)
    # y "en_curso" (todos): los que no están recibidos ni cancelados ("Ver los N" del inicio del cliente)
    especial = a.get("estado") in ("proforma_pendiente", "preparacion", "en_curso") and (
        current_user.rol != "cliente" or a.get("estado") != "proforma_pendiente")
    f = {
        "q": a.get("q", "").strip(),
        "contiene": limpiar_busqueda(a.get("contiene")),     # texto de un kit o producto que lleva (buscador global)
        "estado": a.get("estado") if especial or a.get("estado") in _estados_filtro() else None,
        "cliente_id": a.get("cliente_id", type=int),
        "kit_id": a.get("kit_id", type=int),
        "producto_id": a.get("producto_id", type=int),
        "desde": _fecha(a.get("desde")),
        "hasta": _fecha(a.get("hasta")),
    }
    # SIEMPRE se parte de filtrar_pedidos(): los filtros de columna se suman al alcance
    select = filtrar_pedidos(db.select(Pedido))
    descripcion = []
    if f["q"]:
        select = select.where(Pedido.referencia_interna.ilike(f"%{f['q']}%")
                              | Pedido.referencia.ilike(f"%{f['q']}%"))
        descripcion.append(_("referencia contiene «%(texto)s»", texto=f["q"]))
    if f["contiene"]:
        from app.buscador import pedidos_que_contienen
        select = select.where(pedidos_que_contienen(f["contiene"]))
        descripcion.append(_("lleva un kit o producto con «%(texto)s»", texto=f["contiene"]))
    if f["estado"] == "proforma_pendiente":
        select = select.where(Pedido.estado.in_(["proforma_solicitada", "cambios_solicitados"]))
        descripcion.append(_("proformas por preparar"))
    elif f["estado"] == "en_curso":
        select = select.where(Pedido.estado.notin_(["entregado", "cancelado"]))
        descripcion.append(_("pedidos en curso"))
    elif f["estado"] == "preparacion":
        select = select.where(Pedido.estado.in_(ESTADOS_PREPARACION))
        descripcion.append(_("estado %(estado)s", estado=ESTADOS_PEDIDO_CLIENTE["preparacion"]))
    elif f["estado"]:
        select = select.filter_by(estado=f["estado"])
        descripcion.append(_("estado %(estado)s", estado=_estados_filtro()[f["estado"]]))
    if f["cliente_id"]:
        select = select.filter_by(cliente_id=f["cliente_id"])
        cliente = db.session.scalar(filtrar_clientes(db.select(Cliente).filter_by(id=f["cliente_id"])))
        descripcion.append(_("cliente %(cliente)s", cliente=cliente.nombre if cliente else f["cliente_id"]))
    if f["kit_id"]:
        select = select.where(Pedido.kits.any(KitPedido.kit_id == f["kit_id"]))
        kit = db.session.get(Kit, f["kit_id"])
        descripcion.append(_("kit %(kit)s", kit=kit.nombre if kit else f["kit_id"]))
    if f["producto_id"]:
        # "pedidos que tienen alguna línea con ese producto"
        select = select.where(Pedido.lineas.any(LineaPedido.producto_id == f["producto_id"]))
        producto = db.session.get(Producto, f["producto_id"])
        descripcion.append(_("producto %(producto)s", producto=producto.nombre if producto else f["producto_id"]))
    if f["desde"]:
        select = select.where(Pedido.fecha >= f["desde"])
        descripcion.append(_("desde %(fecha)s", fecha=f"{f['desde']:%d/%m/%Y}"))
    if f["hasta"]:
        select = select.where(Pedido.fecha <= f["hasta"])
        descripcion.append(_("hasta %(fecha)s", fecha=f"{f['hasta']:%d/%m/%Y}"))
    select = select.order_by(Pedido.fecha.desc(), Pedido.id.desc())
    # Cabeceras que ordenan (utils.ordenar): la lista, el PDF y el Excel salen en el mismo orden.
    # El estado se ordena por el flujo (proforma → … → recibido), no por orden alfabético.
    select, f["orden"] = ordenar(select, {
        "referencia": db.func.lower(Pedido.referencia_interna), "fecha": Pedido.fecha,
        "cliente": db.select(db.func.lower(Cliente.nombre)).where(Cliente.id == Pedido.cliente_id).scalar_subquery(),
        "ref_empresa": db.func.lower(Pedido.referencia),
        "estado": db.case({e: i for i, e in enumerate(ESTADOS_PEDIDO)}, value=Pedido.estado, else_=len(ESTADOS_PEDIDO)),
        "entrega": Pedido.fecha_entrega_estimada,
    }, desempate=Pedido.id)
    return select, f, ", ".join(descripcion)


@bp.route("/")
@requiere_permiso("pedidos.ver")
def lista():
    select, filtros, _descripcion = _pedidos_filtrados()
    clientes = []
    if current_user.rol != "cliente":
        clientes = db.session.scalars(
            filtrar_clientes(db.select(Cliente)).order_by(Cliente.nombre)).all()
    productos = db.session.scalars(db.select(Producto).order_by(Producto.nombre)).all()
    kits = db.session.scalars(db.select(Kit).order_by(Kit.nombre)).all()
    pagina = paginar(select)
    # Mensajes sin leer de los pedidos de esta página (el 💬 de cada fila)
    sin_leer = servicio_mensajes.no_leidos_por_hilo(
        current_user, [hilo_de(pedido_id=p.id) for p in pagina.items]) if current_user.puede("mensajes.ver") else {}
    return render_template("pedidos/lista.html", title=_("Pedidos"), pagina=pagina,
                           estados=_estados_filtro(), f=filtros, clientes=clientes,
                           productos=productos, kits=kits, orden=filtros["orden"],
                           hay_filtros=any(v for k, v in filtros.items() if k != "orden"),
                           sin_leer={int(h.split("-")[1]): n for h, n in sin_leer.items()},
                           novedades=resumen_novedades(current_user, pagina.items))


@bp.route("/exportar.pdf")
@requiere_permiso("pedidos.exportar")
def exportar_pdf():
    select, _filtros, descripcion = _pedidos_filtrados()
    pedidos = db.session.scalars(select.limit(5000)).all()
    pdf = generar_pdf_pedidos(pedidos, descripcion,
                              ver_importes=current_user.puede("pedidos.ver_importes"),
                              nombre_estado=lambda p: p.estado_nombre_para(current_user))
    nombre = f"pedidos_{date.today():%Y%m%d}.pdf"
    # inline: el navegador lo abre en una pestaña (desde ahí se puede descargar o imprimir)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"'})


@bp.route("/exportar.xlsx")
@requiere_permiso("pedidos.exportar")
def exportar_excel():
    """Los pedidos que estás viendo (mismos filtros que la lista), en Excel.
    El cliente lo recibe sin importes, igual que en la web y en el PDF."""
    from app.excel import MIMETYPE_XLSX, Columna, generar_excel
    select, _filtros, descripcion = _pedidos_filtrados()
    pedidos = db.session.scalars(select.limit(20000)).all()
    ver_importes = current_user.puede("pedidos.ver_importes")
    columnas = [Columna(_("Ref. interna"), 14), Columna(_("Fecha"), 12, "fecha"),
                Columna(_("Cliente"), 30), Columna(_("Ref. empresa"), 16), Columna(_("Productos"), 50),
                Columna(_("Estado"), 18), Columna(_("Entrega estimada"), 14, "fecha"),
                Columna(_("Transportista"), 16), Columna(_("Nº de seguimiento"), 20)]
    if ver_importes:
        columnas += [Columna(_("Base imponible"), 14, "euros"), Columna(_("IVA"), 12, "euros"),
                     Columna(_("Total"), 14, "euros")]
    filas = []
    for p in pedidos:
        fila = [p.referencia_interna or f"#{p.id}", p.fecha, p.cliente.nombre, p.referencia or "",
                p.resumen_contenido("\n"),
                str(p.estado_nombre_para(current_user)),
                p.fecha_entrega_estimada if p.estado == "enviado" else None,
                p.transportista or "", p.numero_seguimiento or ""]
        if ver_importes:
            fila += [p.base_imponible, p.total_iva, p.total]
        filas.append(fila)
    datos = generar_excel(_("Pedidos"), columnas, filas,
                          subtitulo=_("Filtros: %(filtros)s  ·  %(n)s pedidos",
                                      filtros=descripcion or _("ninguno"), n=len(pedidos)))
    return Response(datos, mimetype=MIMETYPE_XLSX, headers={
        "Content-Disposition": f'attachment; filename="pedidos_{date.today():%Y%m%d}.xlsx"'})


@bp.route("/nuevo", methods=["GET", "POST"])
@requiere_permiso("pedidos.crear")
def nuevo():
    if current_user.rol == "cliente":
        return _nuevo_pedido_cliente()

    form = PedidoInternoForm()
    if request.method == "GET" and request.args.get("cliente_id", type=int):
        form.cliente_id.data = request.args.get("cliente_id", type=int)
    if request.method == "GET":
        _rellenar_para_repetir(form)
    if form.validate_on_submit():
        cliente = cliente_o_404(form.cliente_id.data)  # FAS: solo sus clientes
        pedido = Pedido(cliente=cliente, fecha=form.fecha.data,
                        referencia=form.referencia.data, notas=form.notas.data or None,
                        estado="aceptado", creado_por=current_user,   # sin proforma: ya es un pedido
                        referencia_interna=cliente.siguiente_referencia_interna())
        _crear_pedido(pedido, form)
        flash(_("Pedido %(ref)s creado. Revisa las líneas; cuando esté listo, admin empezará a prepararlo.",
                ref=pedido.referencia_interna), "success")
        return redirect(url_for("pedidos.detalle", id=pedido.id))
    return render_template("pedidos/form.html", title=_("Nuevo pedido"), form=form)


def _rellenar_para_repetir(form):
    """/pedidos/nuevo?repetir=ID: el formulario sale con el contenido de ese pedido."""
    id_repetir = request.args.get("repetir", type=int)
    if id_repetir:
        original = pedido_o_404(id_repetir)        # solo pedidos que este usuario puede ver
        form.contenido.data = _contenido_para_repetir(original, sueltos=form.admite_sueltos,
                                                      productos_permitidos=form.productos_permitidos)


def _productos_del_cliente(pedido):
    """Productos sueltos que puede pedir quien mira el pedido: Yikon, todos (None); el cliente,
    los de su catálogo si tiene uno propio (app/catalogo_cliente.py)."""
    if current_user.rol != "cliente" or not pedido.cliente.catalogo_propio:
        return None
    from app.catalogo_cliente import productos_para
    return {p.id for p in productos_para(pedido.cliente)}


def _contenido_para_repetir(pedido, sueltos, productos_permitidos=None):
    """El contenido del pedido en el mismo JSON que usa el formulario (ver
    _PedidoConLineasForm), para "Repetir pedido". Solo kits y productos que siguen
    activos; los sueltos, si quien repite puede pedirlos (el cliente, solo los de su catálogo:
    productos_permitidos)."""
    kits = []
    for kp in pedido.kits:
        if not kp.kit.activo:
            continue
        # Todos los productos del kit, con 0 los que el pedido no llevaba: así "Repetir"
        # los deja desmarcados en vez de volver a meterlos con la cantidad estándar
        tiene = {}
        for l in kp.lineas:
            tiene[l.producto_id] = tiene.get(l.producto_id, 0) + l.cantidad
        productos = [{"producto_id": c.producto_id, "cantidad": tiene.get(c.producto_id, 0)}
                     for c in kp.kit.componentes if c.producto.activo]
        if any(p["cantidad"] for p in productos):
            kits.append({"kit_id": kp.kit_id, "cantidad": kp.cantidad, "productos": productos})
    lista_sueltos = [{"producto_id": l.producto_id, "cantidad": l.cantidad}
                     for l in pedido.lineas_sueltas if l.producto.activo
                     and (productos_permitidos is None or l.producto_id in productos_permitidos)] if sueltos else []
    if not kits and not lista_sueltos:
        return None
    return json.dumps({"kits": kits[:20], "sueltos": lista_sueltos[:40]})


def _crear_pedido(pedido, form):
    """
    Lo común a los pedidos del cliente y a los de Yikon (admin, logística, FAS):
      - por cada kit: un KitPedido con el precio automático para este cliente (su precio
        especial o el estándar) y una línea por producto (a 0 €: el precio lo lleva el kit);
      - por cada producto suelto: una línea con el precio del catálogo;
    guarda el documento si lo hay, registra la auditoría y hace commit.
    Los precios se COPIAN: si mañana cambia el catálogo, este pedido no cambia.
    """
    # Añadirlo a la sesión YA: las consultas de abajo hacen "autoflush" y SQLAlchemy
    # avisaría de un pedido enganchado al cliente pero fuera de la sesión.
    db.session.add(pedido)
    for bloque in form.kits_validos:
        kit = bloque["kit"]
        kp = KitPedido(kit=kit, cantidad=bloque["cantidad"], precio_unitario=kit.precio_para(pedido.cliente),
                       iva_pct=kit.iva_pct)
        pedido.kits.append(kp)
        # Los productos del kit, en el orden del kit (el que se eligió en su ficha)
        posicion = {c.producto_id: i for i, c in enumerate(kit.componentes)}
        for producto_id, cantidad in sorted(bloque["productos"].items(), key=lambda x: posicion.get(x[0], 999)):
            producto = db.session.get(Producto, producto_id)
            pedido.lineas.append(LineaPedido(producto=producto, cantidad=cantidad, kit_pedido=kp,
                                             precio_unitario=0, iva_pct=producto.iva_pct))
        # ¿Quitó productos o cambió cantidades respecto al kit del catálogo × nº de kits?
        estandar = {c.producto_id: c.cantidad * bloque["cantidad"] for c in kit.componentes_activos}
        kp.modificado = bloque["productos"] != estandar
    for producto_id, cantidad in form.sueltos_validos.items():
        producto = db.session.get(Producto, producto_id)
        pedido.lineas.append(LineaPedido(producto=producto, cantidad=cantidad,
                                         precio_unitario=producto.precio_para(pedido.cliente), iva_pct=producto.iva_pct))
    db.session.flush()
    if not pedido.con_proforma:
        # Pedido creado por Yikon: no hay proforma en la que elegir lote, así que se reservan
        # ya los que caducan antes (se pueden cambiar en la ficha, tarjeta "Lotes de este pedido")
        reservas.reservar_automatico(pedido)
    if form.documento.data and form.documento.data.filename:
        db.session.add(docs.guardar_documento(form.documento.data, pedido))
    registrar("crear", pedido,
              f"{pedido.referencia_interna} · {pedido.cliente.nombre} · {pedido.resumen_contenido(' · ')}"
              + (" · con documento" if pedido.documentos else ""))
    if pedido.estado == "proforma_solicitada" and current_user.es_cliente:
        avisos_internos.proforma_pedida(pedido, current_user.nombre)      # (Ajustes → Avisos internos)
    db.session.commit()


def _nuevo_pedido_cliente():
    """Pedido hecho por el propio cliente: uno o varios kits. Empieza como "proforma
    solicitada": Yikon la revisa y le envía la proforma; al aceptarla pasa a "aceptado"
    y admin lo prepara."""
    empresa = current_user.empresa
    if empresa is None or not empresa.activo:
        abort(403)
    form = PedidoClienteForm(cliente_id=empresa.id)
    if request.method == "GET":
        _rellenar_para_repetir(form)
    if form.validate_on_submit():
        pedido = Pedido(cliente=empresa, fecha=form.fecha.data, referencia=form.referencia.data,
                        estado="proforma_solicitada", con_proforma=True, creado_por=current_user,
                        referencia_interna=empresa.siguiente_referencia_interna())
        _crear_pedido(pedido, form)
        flash(_("Proforma solicitada (referencia %(ref)s). La revisaremos y se la enviaremos; "
                "cuando la acepte, pasará a ser un pedido.", ref=pedido.referencia_interna), "success")
        return redirect(url_for("pedidos.detalle", id=pedido.id))
    return render_template("pedidos/form_cliente.html", title=_("Nuevo pedido"), form=form,
                           empresa=empresa)


# Transiciones (origen, destino) que tienen su propio botón en la ficha: no salen en el desplegable
CON_BOTON_PROPIO = {
    ("proforma_solicitada", "proforma_enviada"), ("cambios_solicitados", "proforma_enviada"),  # "Enviar proforma"
    ("proforma_enviada", "aceptado"), ("proforma_enviada", "cambios_solicitados"),  # el cliente: aceptar / cambios
    ("proforma_enviada", "proforma_solicitada"),                   # Yikon: "Retirar proforma"
    ("aceptado", "en_preparacion"),                                # "Empezar preparación"
    ("en_preparacion", "en_validacion"),                           # "Enviar a validación" (exige fotos)
    ("en_validacion", "validado"), ("en_validacion", "en_preparacion"),   # formulario de validación
    ("enviado", "entregado"),                                      # "Marcar como recibido"
}


def _opciones_desplegable(pedido):
    return [e for e in pedido.transiciones_para(current_user)
            if (pedido.estado, e) not in CON_BOTON_PROPIO]


def _sigue_en(pedido, *estados):
    """Para los botones con acción propia (Confirmar, Enviar a validación, Validar):
    solo tienen sentido desde su estado. Si el pedido ya cambió (pestaña antigua,
    doble clic...), avisamos en vez de forzar el cambio."""
    if pedido.estado in estados:
        return True
    flash(_("El pedido ha cambiado de estado mientras tanto. Revisa su estado actual."), "warning")
    return False


def _cambiar_estado(pedido, destino, detalle="", avisar=True, motivo=None):
    """
    ÚNICO punto por el que cambia el estado de un pedido.
    Comprueba que la transición existe y que el usuario tiene permiso para ella,
    ajusta el inventario y deja rastro en auditoría. Devuelve un mensaje de error
    o None si todo fue bien (sin hacer commit: lo hace quien llama).
    """
    permiso = TRANSICIONES.get(pedido.estado, {}).get(destino)
    valida = pedido.transicion_valida(destino)
    if destino == "proforma_enviada" and not valida:
        abort(400)          # sin proforma pendiente no hay nada que enviar (ni forzando)
    forzado = False
    if permiso is None or not puede_alguno(current_user, permiso) or not valida:
        # Fuera del flujo normal: solo quien puede forzar (admin), y queda marcado
        if destino not in ESTADOS_PEDIDO or not current_user.puede("pedidos.forzar_estado"):
            abort(403)
        forzado = True
    origen = pedido.estado
    # Al enviar salen los lotes RESERVADOS del pedido (los de la proforma): si falta alguno
    # por asignar, ha caducado o no está en la oficina, no se envía.
    problemas = aplicar_cambio_de_estado(pedido, origen, destino)
    if problemas:
        return _("No se puede enviar: %(problemas)s. Revisa la tarjeta «Lotes de este pedido».",
                 problemas="; ".join(problemas))
    # Cambio "condicional": solo si en la base de datos sigue en el estado de origen.
    # Si dos peticiones llegan a la vez (doble clic en "Enviar", dos personas...), la
    # segunda no encuentra el pedido en su estado de origen y se deshace entera,
    # también sus movimientos de stock: así nunca se resta dos veces.
    cambiadas = db.session.execute(
        db.update(Pedido).where(Pedido.id == pedido.id, Pedido.estado == origen)
        .values(estado=destino).execution_options(synchronize_session=False)).rowcount
    if cambiadas != 1:
        db.session.rollback()
        return _("El pedido ha cambiado de estado mientras tanto. Revisa su estado actual.")
    partes = [detalle] if detalle else []
    if forzado:
        partes.append("CAMBIO FORZADO (fuera del flujo normal)")
    registrar("editar", pedido, f"{origen} → {destino}" + "".join(f" · {x}" for x in partes))
    estado_cliente_antes = pedido.estado_cliente
    pedido.estado = destino
    if destino == "cancelado":
        # Una proforma pendiente de un pedido cancelado ya no se puede aceptar
        for proforma in pedido.proformas:
            if proforma.estado == "enviada":
                proforma.estado = "retirada"
    if avisar:   # (no se avisa al cliente de lo que acaba de hacer él mismo)
        avisar_cambio_estado_cliente(pedido, estado_cliente_antes, motivo)   # se envía tras el commit
    return None


@bp.route("/<int:id>")
@requiere_permiso("pedidos.ver")
def detalle(id):
    pedido = pedido_o_404(id)
    opciones = [(e, ESTADOS_PEDIDO[e]) for e in _opciones_desplegable(pedido)]
    estado_form = None
    if opciones:
        estado_form = EstadoPedidoForm()
        estado_form.estado.choices = opciones
    # Para la ventana de confirmación: qué se restaría del stock y con qué estados
    salida_stock = resumen_salida(pedido)
    # Tarjeta "Lotes de este pedido" (solo Yikon): qué lotes tiene reservados y, si toca, elegirlos
    ve_lotes = current_user.puede("pedidos.ver_lotes") and pedido.estado in reservas.ESTADOS_CON_RESERVA
    modo_lotes = reservas.modo_edicion(pedido) if ve_lotes else None
    destinos_con_salida = [e for e, _nombre in opciones if sale_de_oficina(pedido.estado, e)] \
        if salida_stock else []
    # Conversación del pedido con el cliente. Los chats van detrás de los botones de la cabecera: los
    # mensajes cuentan como leídos al ABRIR el chat (mensajes.nuevos_* con ?abierto=1), no al abrir la ficha.
    hilo = hilo_de(pedido_id=pedido.id)
    mensajes = servicio_mensajes.mensajes_de(hilo) if current_user.puede("mensajes.ver") else []
    # Conversación interna (Yikon: admin, logística y FAS): el cliente ni la carga
    ver_internos = current_user.puede("mensajes.internos")
    hilo_interno = hilo_de(pedido_id=pedido.id, interno=True)
    internos = servicio_mensajes.mensajes_de(hilo_interno) if ver_internos else []
    internos_sin_leer = (servicio_mensajes.no_leidos_por_hilo(current_user, [hilo_interno]).get(hilo_interno, 0)
                         if internos else 0)
    # (igual con los del cliente: la cabecera de la sección "Mensajes" enseña cuántos son nuevos)
    mensajes_sin_leer = servicio_mensajes.no_leidos_por_hilo(current_user, [hilo]).get(hilo, 0) if mensajes else 0
    # Qué secciones tienen algo nuevo desde la última vez que esta persona abrió el pedido; y se
    # apunta esta visita (la próxima vez ya no saldrán)
    novedades = novedades_de(current_user, [pedido]).get(pedido.id, set())
    marcar_visto(current_user, pedido)
    db.session.commit()
    return render_template(
        "pedidos/detalle.html", title=_("Pedido %(ref)s", ref=pedido.referencia_interna or pedido.id),
        pedido=pedido,
        linea_form=con_ids_propios(LineaForm(), "suelto") if _puede_modificar_lineas(pedido) else None,
        kit_form=con_ids_propios(AnadirKitForm(), "kit") if _puede_modificar_lineas(pedido) else None,
        puede_cambiar_precios=_puede_cambiar_precios(pedido),
        estado_form=estado_form,
        salida_stock=salida_stock, destinos_con_salida=destinos_con_salida,
        lotes_pedido=reservas.resumen(pedido, sin_caducados=modo_lotes == "libre") if ve_lotes else [],
        modo_lotes=modo_lotes,
        problemas_lotes=reservas.plan_reservado(pedido, faltan=False)[1] if ve_lotes else [],
        hoy=date.today(), dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"],
        lotes_enviados=lotes_enviados(pedido) if current_user.puede("pedidos.ver_lotes") else [],
        historial=historial_pedido(pedido, current_user),
        repetir_json=(_contenido_para_repetir(pedido, sueltos=True, productos_permitidos=_productos_del_cliente(pedido))
                      if current_user.puede("pedidos.crear") else None),
        puede_modificar=_puede_modificar_lineas(pedido),
        puede_subir_fotos=_puede_gestionar_fotos(pedido),
        fotos_form=FotosForm() if _puede_gestionar_fotos(pedido) else None,
        documento_form=DocumentoForm() if _puede_subir_documentos(pedido) else None,
        transportistas=TRANSPORTISTAS_HABITUALES,
        envio_form=(DatosEnvioForm(obj=pedido, formdata=None, prefix="envio")
                    if pedido.estado == "enviado" and current_user.puede("pedidos.enviar") else None),
        puede_borrar_documento=lambda d: _puede_borrar_documento(pedido, d),
        validacion_form=ValidacionForm() if (pedido.estado == "en_validacion"
                                             and current_user.puede("pedidos.validar")) else None,
        mensajes=mensajes,
        internos=internos, internos_sin_leer=internos_sin_leer,
        mensajes_sin_leer=mensajes_sin_leer, novedades=novedades, deshacer=mensaje_para_deshacer(),
        interno_form=con_ids_propios(MensajeForm(), "interno") if ver_internos else None,
        mensaje_form=(con_ids_propios(MensajeForm(), "mensaje")
                      if current_user.puede("mensajes.pedido_cliente") else None),
        **_contexto_proforma(pedido),
        **_contexto_facturas(pedido),
        **_contexto_incidencias(pedido),
    )


def _contexto_incidencias(pedido):
    """Sección "Incidencias" de la ficha: las del pedido, si el cliente puede avisar de un problema
    y si quien mira puede resolverlas."""
    from app import incidencias
    from app.models import ICONOS_MOTIVO_INCIDENCIA, MOTIVOS_INCIDENCIA
    return {"incidencias": pedido.incidencias,
            "puede_abrir_incidencia": incidencias.puede_abrir(current_user, pedido),
            "puede_resolver_incidencia": current_user.puede("pedidos.incidencias.resolver"),
            "motivos_incidencia": MOTIVOS_INCIDENCIA, "iconos_motivo": ICONOS_MOTIVO_INCIDENCIA,
            "max_fotos_incidencia": incidencias.MAX_FOTOS}


def _contexto_facturas(pedido):
    """Formularios de la tarjeta "Facturas de este pedido" (solo quien registra facturas: admin)."""
    if not current_user.puede("facturas.editar"):
        return {"factura_form": None, "factura_pdf_form": None}
    from app.facturas.forms import FacturaPdfForm, FacturaPedidoForm
    from app.facturas.routes import ESTADOS_SIN_FACTURA
    factura_form = None
    if pedido.estado not in ESTADOS_SIN_FACTURA:
        factura_form = con_ids_propios(FacturaPedidoForm(formdata=None), "factura")
        factura_form.numero.data = pedido.referencia_interna      # el nº de factura es la referencia del pedido
        factura_form.revisar.data = pedido.cliente.revisar_facturas
    return {"factura_form": factura_form,
            "factura_pdf_form": FacturaPdfForm(formdata=None)}


def _contexto_proforma(pedido):
    """Lo que necesita la tarjeta "Proforma" de la ficha según el estado y quién mira."""
    from app.proformas.forms import ProformaForm, RespuestaProformaForm, RetirarProformaForm
    from app.proformas.servicio import lineas_previstas
    preparar = (pedido.estado in ("proforma_solicitada", "cambios_solicitados")
                and current_user.puede("pedidos.proforma.enviar"))
    enviada = pedido.estado == "proforma_enviada"
    return {
        "proforma_form": con_ids_propios(_proforma_con_valores_por_defecto(pedido), "proforma") if preparar else None,
        # vista previa: con los lotes ya elegidos + los libres que caducan antes para lo que falte
        "proforma_prevista": lineas_previstas(pedido) if preparar else None,
        "respuesta_form": (RespuestaProformaForm() if enviada and current_user.puede("pedidos.proforma.responder")
                           else None),
        "retirar_form": (RetirarProformaForm() if enviada and current_user.puede("pedidos.proforma.enviar")
                         else None),
    }


def _proforma_con_valores_por_defecto(pedido):
    """El formulario de enviar la proforma, ya relleno con lo de Ajustes → Proformas (validez,
    plazo y notas en el idioma del cliente). Se puede cambiar antes de enviarla."""
    from datetime import timedelta
    from app import ajustes
    from app.proformas.forms import ProformaForm
    form = ProformaForm()
    if not form.is_submitted():
        defecto, idioma = ajustes.proformas(), ajustes.idioma_del_cliente(pedido.cliente)
        form.valida_hasta.data = date.today() + timedelta(days=defecto["validez"])
        form.plazo_entrega.data = defecto["plazo"][idioma]
        form.notas.data = defecto["notas"][idioma]
    return form


def _ajustar_reservas(pedido):
    """Tras cambiar lo que lleva el pedido (antes del commit): sus lotes reservados se ajustan
    a lo que lleva ahora. Se recarga el pedido para que cuente lo recién añadido o borrado."""
    db.session.flush()
    db.session.expire(pedido, ["kits", "lineas"])
    reservas.tras_editar(pedido)


@bp.route("/<int:id>/lotes", methods=["POST"])
@requiere_permiso("pedidos.lotes")
def guardar_lotes(id):
    """
    Tarjeta "Lotes de este pedido": reserva para el pedido las unidades de cada lote.
    Campos "lote-<id del lote>" = unidades. accion=automatico: los que caducan antes.
    Qué se puede cambiar lo decide reservas.modo_edicion():
      - "libre" (preparando la proforma, o pedido creado por Yikon): cualquier reparto;
      - "completar" (proforma enviada o aceptada): solo asignar lo que quedó "a confirmar".
    """
    pedido = pedido_o_404(id)
    # Bloquea el pedido hasta el commit (PostgreSQL) y lo relee: si a la vez alguien envía la
    # proforma o el cliente la acepta, aquí ya se ve el estado nuevo y manda su modo.
    db.session.execute(db.select(Pedido.id).where(Pedido.id == pedido.id).with_for_update())
    db.session.refresh(pedido)
    modo = reservas.modo_edicion(pedido)
    if modo is None:
        abort(403)
    volver = redirect(url_for("pedidos.detalle", id=id) + "#lotes")
    reservas.normalizar(pedido)      # (por si quedó algo reservado de un artículo que ya no lleva)
    antes = {r.lote_id: r.cantidad for r in pedido.reservas}
    if request.form.get("accion") == "automatico":
        if modo == "libre":
            reservas.liberar(pedido)       # se rehace entero; en "completar" lo aprobado no se toca
        errores = reservas.reservar_automatico(pedido, sin_caducados=modo == "libre")
    else:
        reparto = {}
        for nombre, valor in request.form.items():
            if nombre.startswith("lote-") and es_entero(nombre[5:]) and valor.strip():
                if not es_entero(valor.strip()):
                    flash(_("Las unidades de cada lote deben ser un número entero."), "danger")
                    return volver
                reparto[int(nombre[5:])] = min(int(valor), 10**6)
        errores = reservas.guardar(pedido, reparto, solo_completar=modo == "completar")
    if errores:
        db.session.rollback()
        flash(_("No se han guardado los lotes: %(errores)s", errores="; ".join(errores)), "danger")
        return volver
    despues = {r.lote_id: r.cantidad for r in pedido.reservas}
    if despues != antes:
        lotes = ", ".join(f"{r.lote.codigo}×{r.cantidad}" for r in pedido.reservas) or "ninguno"
        registrar("editar", pedido, f"{pedido.referencia_interna} · lotes reservados: {lotes}")
        db.session.commit()
        _plan, problemas = reservas.plan_reservado(pedido)
        if problemas:
            flash(_("Lotes guardados. Queda pendiente: %(problemas)s.", problemas="; ".join(problemas)), "warning")
        elif modo == "completar":
            flash(_("Lotes guardados. Como la proforma salió con caducidad «a confirmar», "
                    "comunica al cliente la fecha definitiva."), "success")
        else:
            flash(_("Lotes guardados: quedan reservados para este pedido."), "success")
    else:
        db.session.rollback()
        flash(_("Los lotes ya estaban así: no había nada que cambiar."), "info")
    return volver


def _cantidad(texto, maximo):
    try:
        n = int(texto)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= maximo else None


@bp.route("/<int:id>/guardar", methods=["POST"])
@requiere_permiso("pedidos.editar")
def guardar_cambios(id):
    """
    El botón "Guardar cambios" de la tabla del pedido. Recoge los campos que haya:
      precio_kit_<id>      precio de UN kit          (hasta que el pedido sale)
      precio_linea_<id>    precio de un producto suelto (ídem)
      cantidad_kit_<id>    nº de kits (solo si Pedido.editable; si el kit es estándar, sus
                           productos se recalculan)
      cantidad_linea_<id>  cantidad de un producto, de kit o suelto (solo si Pedido.editable)
    Si el contenido de un kit cambia, se vuelve a comparar con el estándar ("modificado").
    """
    pedido = pedido_o_404(id)
    precios_ok, lineas_ok = _puede_cambiar_precios(pedido), _puede_modificar_lineas(pedido)
    if not (precios_ok or lineas_ok):
        abort(403)
    cambios, errores = [], []
    if precios_ok:
        for kp in pedido.kits:
            if f"precio_kit_{kp.id}" in request.form:
                nuevo = leer_precio(request.form[f"precio_kit_{kp.id}"])
                if nuevo is None:
                    errores.append(kp.kit.nombre)
                elif nuevo != kp.precio_unitario:
                    cambios.append(f"precio {kp.kit.referencia}: {kp.precio_unitario} → {nuevo}")
                    kp.precio_unitario = nuevo
        for l in pedido.lineas_sueltas:
            if f"precio_linea_{l.id}" in request.form:
                nuevo = leer_precio(request.form[f"precio_linea_{l.id}"])
                if nuevo is None:
                    errores.append(l.producto.nombre)
                elif nuevo != l.precio_unitario:          # guardar sin tocarlo no cambia nada
                    cambios.append(f"precio {l.producto.referencia}: {l.precio_unitario} → {nuevo}")
                    # el precio escrito a mano ya es el final: el descuento antiguo deja de aplicarse
                    l.precio_unitario, l.descuento_pct = nuevo, Decimal("0")
    n_precios = len(cambios)                         # lo que venga después son cambios de contenido
    if lineas_ok:
        tocados = set()                              # kits cuyo contenido ha cambiado
        escaladas = set()                            # líneas ya recalculadas por el nº de kits
        for kp in pedido.kits:
            campo = f"cantidad_kit_{kp.id}"
            if campo in request.form:
                nueva = _cantidad(request.form[campo], 1000)
                if nueva is None:
                    errores.append(kp.kit.nombre)
                elif nueva != kp.cantidad:
                    cambios.append(f"nº de kits {kp.kit.referencia}: {kp.cantidad} → {nueva}")
                    if not kp.modificado:
                        # kit estándar: sus productos siguen al nº de kits
                        for l in kp.lineas:
                            por_kit = l.cantidad // kp.cantidad if kp.cantidad else l.cantidad
                            if f"cantidad_linea_{l.id}" not in request.form or \
                                    request.form[f"cantidad_linea_{l.id}"] == str(l.cantidad):
                                l.cantidad = por_kit * nueva
                                escaladas.add(l.id)
                    kp.cantidad = nueva
                    tocados.add(kp.id)
        for l in pedido.lineas:
            campo = f"cantidad_linea_{l.id}"
            if campo in request.form and l.id not in escaladas:
                nueva = _cantidad(request.form[campo], 100000)
                if nueva is None:
                    errores.append(l.producto.nombre)
                elif nueva != l.cantidad:
                    cambios.append(f"cantidad {l.producto.referencia}: {l.cantidad} → {nueva}")
                    l.cantidad = nueva
                    if l.kit_pedido_id:
                        tocados.add(l.kit_pedido_id)
        # Solo se revisa la marca "modificado" de los kits que han cambiado aquí: si luego se
        # editó el kit en el catálogo, los pedidos antiguos no deben cambiar de marca solos.
        for kp in pedido.kits:
            if kp.id in tocados:
                kp.modificado = not kp.es_estandar()
    if errores:
        db.session.rollback()
        flash(_("Revisa estos valores (precio o cantidad no válidos): %(lista)s. No se ha guardado nada.",
                lista=", ".join(errores)), "danger")
    elif cambios:
        registrar("editar", pedido, " · ".join(cambios))
        if len(cambios) > n_precios:                 # (cambiar un precio no toca los lotes)
            _ajustar_reservas(pedido)
        db.session.commit()
        flash(_("Cambios guardados."), "success")
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/kits", methods=["POST"])
@requiere_permiso("pedidos.editar")
def anadir_kit(id):
    """Añade un kit con su composición estándar y el precio automático del cliente."""
    pedido = pedido_o_404(id)
    if not _puede_modificar_lineas(pedido):
        abort(403)
    form = AnadirKitForm()
    if form.validate_on_submit():
        kit = db.get_or_404(Kit, form.kit_id.data)
        n = form.cantidad.data
        kp = KitPedido(pedido=pedido, kit=kit, cantidad=n, precio_unitario=kit.precio_para(pedido.cliente),
                       iva_pct=kit.iva_pct)
        db.session.add(kp)
        for c in kit.componentes_activos:
            db.session.add(LineaPedido(pedido=pedido, kit_pedido=kp, producto=c.producto,
                                       cantidad=c.cantidad * n, precio_unitario=0, iva_pct=c.producto.iva_pct))
        registrar("editar", pedido, f"+ {n} x kit {kit.referencia}")
        _ajustar_reservas(pedido)
        db.session.commit()
    else:
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/kits/<int:kit_pedido_id>/borrar", methods=["POST"])
@requiere_permiso("pedidos.editar")
def borrar_kit(id, kit_pedido_id):
    pedido = pedido_o_404(id)
    kp = db.get_or_404(KitPedido, kit_pedido_id)
    if kp.pedido_id != pedido.id or not _puede_modificar_lineas(pedido):
        abort(403)
    registrar("editar", pedido, f"- {kp.cantidad} x kit {kp.kit.referencia}")
    db.session.delete(kp)                  # borra también sus productos (cascade)
    _ajustar_reservas(pedido)
    db.session.commit()
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/lineas", methods=["POST"])
@requiere_permiso("pedidos.editar")
def anadir_linea(id):
    """Añade un producto suelto (fuera de kit)."""
    pedido = pedido_o_404(id)
    if not _puede_modificar_lineas(pedido):
        abort(403)
    form = LineaForm()
    if form.validate_on_submit():
        producto = db.get_or_404(Producto, form.producto_id.data)
        precio = form.precio.data if form.precio.data is not None else producto.precio_para(pedido.cliente)
        linea = LineaPedido(pedido=pedido, producto=producto, cantidad=form.cantidad.data,
                            precio_unitario=precio, iva_pct=producto.iva_pct)
        db.session.add(linea)
        registrar("editar", pedido, f"+ {linea.cantidad} x {producto.referencia} ({precio} €)")
        _ajustar_reservas(pedido)
        db.session.commit()
    else:
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/lineas/<int:linea_id>/borrar", methods=["POST"])
@requiere_permiso("pedidos.editar")
def borrar_linea(id, linea_id):
    """Quita un producto (suelto o de un kit). Si era el último de su kit, se quita el kit."""
    pedido = pedido_o_404(id)
    linea = db.get_or_404(LineaPedido, linea_id)
    if linea.pedido_id != pedido.id or not _puede_modificar_lineas(pedido):
        abort(403)
    kp = linea.kit_pedido
    registrar("editar", pedido, f"- {linea.cantidad} x {linea.producto.referencia}"
              + (f" (de kit {kp.kit.referencia})" if kp else ""))
    if kp is not None:
        kp.lineas.remove(linea)
    pedido.lineas.remove(linea)
    db.session.delete(linea)
    if kp is not None:
        if not kp.lineas:
            db.session.delete(kp)
        else:
            kp.modificado = not kp.es_estandar()
    _ajustar_reservas(pedido)
    db.session.commit()
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/preparacion", methods=["POST"])
@requiere_permiso("pedidos.preparar")
def empezar_preparacion(id):
    """Aceptado → En preparación: admin empieza a prepararlo (a partir de aquí, las fotos)."""
    pedido = pedido_o_404(id)
    desde_movil = request.form.get("volver") == "preparar"
    if not _sigue_en(pedido, "aceptado"):
        pass
    elif not pedido.lineas:
        flash(_("No se puede preparar un pedido sin líneas."), "warning")
    elif error := _cambiar_estado(pedido, "en_preparacion"):
        flash(error, "danger")
    else:
        db.session.commit()
        flash(_("Pedido en preparación. Cuando esté listo, haz las fotos y envíalo a validación."), "success")
    return _volver_fotos(pedido) if desde_movil else redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/recibido", methods=["POST"])
@requiere_permiso("pedidos.ver")
def marcar_recibido(id):
    """Enviado → Recibido. Lo marca el cliente (o admin por él). Yikon
    reciben el aviso en los mensajes del pedido (campana) y por email."""
    pedido = pedido_o_404(id)
    if not (current_user.puede("pedidos.recibir") or current_user.puede("pedidos.enviar")):
        abort(403)
    if not _sigue_en(pedido, "enviado"):
        return redirect(url_for("pedidos.detalle", id=id))
    por_cliente = current_user.rol == "cliente"
    if error := _cambiar_estado(pedido, "entregado", "recibido por el cliente" if por_cliente else "",
                                avisar=not por_cliente):
        flash(error, "danger")
        return redirect(url_for("pedidos.detalle", id=id))
    if por_cliente:
        # Queda en la conversación del pedido: a admin, logística y FAS les sale en la campana
        servicio_mensajes.enviar(current_user, pedido.cliente,
                                 _("✓ Pedido %(ref)s recibido.", ref=pedido.referencia_interna or pedido.id),
                                 pedido=pedido, avisar=False)       # el email lo manda avisar_recibido
        avisar_recibido(pedido, current_user.nombre)
    db.session.commit()
    flash(_("Pedido marcado como recibido.") + (" " + _("¡Gracias!") if por_cliente else ""), "success")
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/estado", methods=["POST"])
@requiere_permiso("pedidos.ver")
def cambiar_estado(id):
    pedido = pedido_o_404(id)
    form = EstadoPedidoForm()
    form.estado.choices = [(e, e) for e in _opciones_desplegable(pedido)]
    if not form.validate_on_submit():
        if form.estado.data not in dict(form.estado.choices):
            abort(403)   # estado no permitido desde aquí para este usuario
        for errores in form.errors.values():     # p. ej. un enlace de seguimiento sin https://
            for e in errores:
                flash(e, "danger")
        return redirect(url_for("pedidos.detalle", id=id))
    # Si este cambio resta stock, tiene que venir confirmado desde la ventana emergente.
    # Lo comprobamos también aquí: nunca te fíes solo del navegador.
    if (sale_de_oficina(pedido.estado, form.estado.data) and resumen_salida(pedido)
            and request.form.get("confirmar_stock") != "1"):
        flash(_("Confirma la salida de stock en la ventana que aparece al cambiar el estado."), "warning")
        return redirect(url_for("pedidos.detalle", id=id))
    if form.estado.data == "enviado":
        if not (form.transportista.data or "").strip() or not (form.numero_seguimiento.data or "").strip():
            flash(_("Para enviar el pedido indica el transportista y el número de seguimiento."), "danger")
            return redirect(url_for("pedidos.detalle", id=id))
        fecha = form.fecha_entrega_estimada.data
        if fecha and fecha < pedido.fecha:
            flash(_("La fecha estimada de entrega no puede ser anterior a la fecha del pedido."), "danger")
            return redirect(url_for("pedidos.detalle", id=id))
        # se asignan ANTES de cambiar el estado para que salgan en el email al cliente
        for campo in CAMPOS_ENVIO:
            setattr(pedido, campo, getattr(form, campo).data or None)
    normal = pedido.es_transicion_normal(form.estado.data)
    error = _cambiar_estado(pedido, form.estado.data)
    if error:
        flash(error, "danger")
    else:
        db.session.commit()
        flash(_("Estado cambiado a «%(estado)s».", estado=pedido.estado_nombre)
              + ("" if normal else " " + _("(Fuera del flujo normal: queda registrado en auditoría.)")),
              "success" if normal else "warning")
    return redirect(url_for("pedidos.detalle", id=id))


# --------------------------------------------------------------------------- #
# Fotos de preparación y validación
# --------------------------------------------------------------------------- #
def _puede_gestionar_fotos(pedido):
    """Admin sube/borra fotos mientras el pedido está "En preparación" (también si el FAS lo devolvió)."""
    return pedido.estado == "en_preparacion" and current_user.puede("pedidos.fotos.subir")


def _volver_fotos(pedido):
    """Tras subir/quitar fotos se vuelve a la pantalla de la que venía: la ficha normal
    o la vista de móvil "Preparar" (formularios con volver=preparar)."""
    if request.form.get("volver") == "preparar":
        return redirect(url_for("pedidos.preparar_pedido", id=pedido.id))
    return redirect(url_for("pedidos.detalle", id=pedido.id))


# --------------------------------------------------------------------------- #
# Vista de móvil para preparar pedidos: la usa quien hace los paquetes.
# Lista de lo que hay por preparar y, en cada pedido, qué lleva, de qué lotes
# coger cada producto, hacer las fotos con la cámara y enviarlo a validación.
# Solo lo imprescindible (sin precios ni menú lateral) y con botones grandes.
# --------------------------------------------------------------------------- #
@bp.route("/preparar")
@requiere_permiso("pedidos.fotos.subir")
def preparar():
    pedidos = db.session.scalars(filtrar_pedidos(
        db.select(Pedido).where(Pedido.estado.in_(["en_preparacion", "aceptado"])))
        .options(selectinload(Pedido.cliente), selectinload(Pedido.fotos), selectinload(Pedido.revisiones),
                 selectinload(Pedido.kits).selectinload(KitPedido.kit), selectinload(Pedido.lineas))
        .order_by((Pedido.estado == "en_preparacion").desc(), Pedido.fecha, Pedido.id)).all()
    pedidos.sort(key=lambda p: not p.devuelto)      # los devueltos por el FAS, lo primero
    return render_template("pedidos/preparar_lista.html", title=_("Preparar pedidos"), pedidos=pedidos)


@bp.route("/<int:id>/preparar")
@requiere_permiso("pedidos.fotos.subir")
def preparar_pedido(id):
    from app.inventario.stock import articulo_de
    pedido = pedido_o_404(id)
    en_preparacion = pedido.estado in ("aceptado", "en_preparacion")
    # Lotes a coger: los RESERVADOS para este pedido (los que aprobó el cliente en la proforma).
    # De cada kit cerrado (el paquete entero) y de cada producto suelto o de kit montado.
    plan, faltan = reservas.plan_reservado(pedido) if en_preparacion else ({}, [])
    lotes = [(articulo_de(clave), reparto) for clave, reparto in plan.items() if reparto]
    lotes.sort(key=lambda x: (x[0].tipo_articulo != "kit", x[0].nombre.lower()))
    return render_template("pedidos/preparar.html", title=_("Preparar %(ref)s", ref=pedido.referencia_interna or pedido.id),
                           pedido=pedido, en_preparacion=en_preparacion, lotes=lotes, faltan=faltan,
                           fotos_form=FotosForm(formdata=None) if pedido.estado == "en_preparacion" else None,
                           hoy=date.today(), dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


@bp.route("/<int:id>/fotos", methods=["POST"])
@requiere_permiso("pedidos.fotos.subir")
def subir_fotos(id):
    pedido = pedido_o_404(id)
    if not _puede_gestionar_fotos(pedido):
        abort(403)
    form = FotosForm()
    archivos = [f for f in request.files.getlist(form.fotos.name) if f and f.filename]
    if not form.validate_on_submit() or not archivos:
        flash(_("Elige al menos una foto."), "warning")
        return _volver_fotos(pedido)
    subidas = 0
    for archivo in archivos:
        try:
            db.session.add(guardar_foto(archivo, pedido))
            subidas += 1
        except FotoNoValida as e:
            flash(str(e), "danger")
    if subidas:
        registrar("editar", pedido, f"{subidas} foto(s) subida(s)")
        db.session.commit()
        flash(_("%(n)s foto(s) subida(s).", n=subidas), "success")
    return _volver_fotos(pedido)


@bp.route("/<int:id>/fotos/<int:foto_id>")
@requiere_permiso("pedidos.fotos.ver")   # el cliente NO tiene este permiso: 403 siempre
def ver_foto(id, foto_id):
    pedido = pedido_o_404(id)            # y el FAS solo las de sus clientes
    foto = db.get_or_404(FotoPedido, foto_id)
    if foto.pedido_id != pedido.id:
        abort(404)
    respuesta = send_from_directory(carpeta(), foto.archivo)
    respuesta.headers["Cache-Control"] = "private, max-age=3600"
    return respuesta


@bp.route("/<int:id>/fotos/<int:foto_id>/borrar", methods=["POST"])
@requiere_permiso("pedidos.fotos.subir")
def borrar_foto(id, foto_id):
    pedido = pedido_o_404(id)
    foto = db.get_or_404(FotoPedido, foto_id)
    if foto.pedido_id != pedido.id or not _puede_gestionar_fotos(pedido):
        abort(403)
    registrar("editar", pedido, f"foto borrada ({foto.nombre_original})")
    borrar_archivo(foto)
    db.session.delete(foto)
    db.session.commit()
    return _volver_fotos(pedido)


@bp.route("/<int:id>/enviar-validacion", methods=["POST"])
@requiere_permiso("pedidos.fotos.subir")
def enviar_a_validacion(id):
    pedido = pedido_o_404(id)
    desde_movil = request.form.get("volver") == "preparar"
    if not _sigue_en(pedido, "en_preparacion"):
        return _volver_fotos(pedido)
    if not pedido.fotos:
        flash(_("Sube al menos una foto antes de enviarlo a validación."), "warning")
        return _volver_fotos(pedido)
    if error := _cambiar_estado(pedido, "en_validacion", f"{len(pedido.fotos)} foto(s)"):
        flash(error, "danger")
        return _volver_fotos(pedido)
    avisos_internos.listo_validar(pedido, current_user.nombre, excluir_id=current_user.id)
    db.session.commit()
    flash(_("Enviado a validación. %(rol)s revisará las fotos.", rol=NOMBRE_FAS), "success")
    # desde el móvil, de vuelta a la lista: a por el siguiente pedido
    return redirect(url_for("pedidos.preparar") if desde_movil else url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/validar", methods=["POST"])
@requiere_permiso("pedidos.validar")
def validar(id):
    pedido = pedido_o_404(id)
    if not _sigue_en(pedido, "en_validacion"):
        return redirect(url_for("pedidos.detalle", id=id))
    form = ValidacionForm()
    if not form.validate_on_submit():
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
        return redirect(url_for("pedidos.detalle", id=id))
    aprobado = bool(form.aprobar.data)
    comentario = (form.comentario.data or "").strip() or None
    if current_user.rol != "fas":
        with force_locale("es"):   # queda guardado en la base de datos: siempre en español
            comentario = f"[Revisado por {current_user.rol_nombre} en lugar de {NOMBRE_FAS}] {comentario or ''}".strip()
    if error := _cambiar_estado(pedido, "validado" if aprobado else "en_preparacion", comentario or ""):
        flash(error, "danger")
        return redirect(url_for("pedidos.detalle", id=id))
    db.session.add(RevisionPedido(pedido=pedido, usuario_id=current_user.id,
                                  aprobado=aprobado, comentario=comentario))
    if not aprobado:
        avisar_revisar_urgente(pedido, comentario, current_user.nombre)
    db.session.commit()
    if aprobado:
        flash(_("Pedido validado: listo para enviar."), "success")
    else:
        flash(_("Pedido devuelto a preparación. Almacén recibirá el aviso con tu comentario."), "warning")
    return redirect(url_for("pedidos.detalle", id=id))


# --------------------------------------------------------------------------- #
# Documentos del pedido (orden de compra del cliente, etc.)
# --------------------------------------------------------------------------- #
def _puede_subir_documentos(pedido):
    return pedido.estado != "cancelado" and current_user.puede("pedidos.documentos.subir")


def _puede_borrar_documento(pedido, documento):
    """Admin, Facturación, Almacén y el Soporte de cliente de ese cliente, siempre; los demás, lo
    que subieron ellos mismos mientras el pedido no haya salido."""
    if current_user.rol in ("admin", "facturacion", "logistica"):
        return True
    if current_user.rol == "fas" and pedido.cliente in current_user.clientes_asignados:
        return True
    return (documento.subido_por_id == current_user.id
            and pedido.estado not in ("enviado", "entregado", "cancelado"))


@bp.route("/<int:id>/documentos", methods=["POST"])
@requiere_permiso("pedidos.documentos.subir")
def subir_documento(id):
    pedido = pedido_o_404(id)                 # un cliente solo en pedidos de su empresa
    if not _puede_subir_documentos(pedido):
        abort(403)
    form = DocumentoForm()
    if form.validate_on_submit():
        try:
            doc = docs.guardar_documento(form.documento.data, pedido)
        except docs.DocumentoNoValido as e:       # red de seguridad: el formulario ya lo comprueba
            flash(str(e), "danger")
            return redirect(url_for("pedidos.detalle", id=id))
        db.session.add(doc)
        registrar("editar", pedido, f"documento adjuntado: {doc.nombre_original}")
        db.session.commit()
        flash(_("Documento «%(nombre)s» adjuntado.", nombre=doc.nombre_original), "success")
    else:
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
    return redirect(url_for("pedidos.detalle", id=id))


@bp.route("/<int:id>/documentos/<int:doc_id>")
@requiere_permiso("pedidos.documentos.ver")
def descargar_documento(id, doc_id):
    pedido = pedido_o_404(id)
    doc = db.get_or_404(DocumentoPedido, doc_id)
    if doc.pedido_id != pedido.id:
        abort(404)
    # as_attachment: se descarga, nunca se abre "dentro" de la web
    respuesta = send_from_directory(docs.carpeta(), doc.archivo, as_attachment=True,
                                    download_name=doc.nombre_original)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, no-store"
    return respuesta


@bp.route("/<int:id>/documentos/<int:doc_id>/borrar", methods=["POST"])
@requiere_permiso("pedidos.documentos.subir")
def borrar_documento(id, doc_id):
    pedido = pedido_o_404(id)
    doc = db.get_or_404(DocumentoPedido, doc_id)
    if doc.pedido_id != pedido.id or not _puede_borrar_documento(pedido, doc):
        abort(403)
    registrar("editar", pedido, f"documento borrado: {doc.nombre_original}")
    docs.borrar_archivo(doc)
    db.session.delete(doc)
    db.session.commit()
    flash(_("Documento quitado."), "info")
    return redirect(url_for("pedidos.detalle", id=id))



CAMPOS_ENVIO = ("fecha_entrega_estimada", "transportista", "numero_seguimiento", "enlace_seguimiento")


@bp.route("/<int:id>/datos-envio", methods=["POST"])
@requiere_permiso("pedidos.enviar")
def cambiar_datos_envio(id):
    """Corregir los datos de un pedido ya enviado: fecha estimada (p. ej. retraso del
    transporte), transportista o nº de seguimiento. Si cambia algo, se avisa al cliente."""
    pedido = pedido_o_404(id)
    if pedido.estado != "enviado":
        abort(403)
    # prefix: sus campos se llaman "envio-transportista"... para no repetir los id del
    # formulario de cambio de estado, que está en la misma página
    form = DatosEnvioForm(prefix="envio")
    if not form.validate_on_submit():
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
        return redirect(url_for("pedidos.detalle", id=id))
    nueva = form.fecha_entrega_estimada.data
    if nueva and nueva < pedido.fecha:
        flash(_("La fecha estimada de entrega no puede ser anterior a la fecha del pedido."), "danger")
        return redirect(url_for("pedidos.detalle", id=id))

    def txt(v):
        return v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else (v or "—")
    cambios = []
    for campo in CAMPOS_ENVIO:
        antes, despues = getattr(pedido, campo), getattr(form, campo).data or None
        if antes != despues:
            cambios.append(f"{campo}: {txt(antes)} → {txt(despues)}")
            setattr(pedido, campo, despues)
    if cambios:
        registrar("editar", pedido, "datos de envío · " + " · ".join(cambios))
        avisar_datos_envio(pedido)                # email al cliente, tras el commit
        db.session.commit()
        flash(_("Datos de envío actualizados. Revisa el correo pendiente antes de enviarlo."), "success")
    return redirect(url_for("pedidos.detalle", id=id))

# --------------------------------------------------------------------------- #
# Modelo de pedido de compra (Word, bilingüe) para los clientes que no tienen uno propio.
# El archivo está en app/recursos/ y se regenera con scripts/generar_modelo_pedido.js
# (cambiar ahí la dirección de Yikon, los campos...).
# --------------------------------------------------------------------------- #
MODELO_PEDIDO = "Pedido_de_compra_Yikon.docx"


@bp.route("/modelo-pedido-compra")
@requiere_permiso("pedidos.crear")
def modelo_pedido_compra():
    from flask import send_from_directory
    import os
    respuesta = send_from_directory(os.path.join(current_app.root_path, "recursos"), MODELO_PEDIDO,
                                    as_attachment=True, download_name=MODELO_PEDIDO)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    return respuesta


# --------------------------------------------------------------------------- #
# Incidencias: "Hay un problema con este pedido" (lógica en app/incidencias.py)
# --------------------------------------------------------------------------- #
@bp.route("/<int:id>/incidencias", methods=["POST"])
@requiere_permiso("pedidos.incidencias.abrir")
def abrir_incidencia(id):
    """El cliente avisa de un problema con un pedido enviado o recibido (motivo, texto y fotos)."""
    from flask_wtf import FlaskForm

    from app import archivos, incidencias
    from app.models import MOTIVOS_INCIDENCIA
    pedido = pedido_o_404(id)
    volver = redirect(url_for("pedidos.detalle", id=id) + "#incidencias")
    if not FlaskForm().validate_on_submit():
        return volver
    if not incidencias.puede_abrir(current_user, pedido):
        flash(_("Solo se puede avisar de un problema cuando el pedido ya se ha enviado."), "warning")
        return volver
    motivo, texto = request.form.get("motivo"), (request.form.get("texto") or "").strip()
    if motivo not in MOTIVOS_INCIDENCIA or not texto:
        flash(_("Elija qué ha pasado y cuéntenos el problema."), "danger")
        return volver
    try:
        fotos = incidencias.leer_fotos(request.files.getlist("fotos"))
    except archivos.ArchivoNoValido as e:
        flash(str(e), "danger")
        return volver
    incidencias.abrir(pedido, current_user, motivo, texto, fotos)
    db.session.commit()
    flash(_("Gracias: hemos recibido su aviso. Le contestaremos en los mensajes de este pedido."), "success")
    return volver


@bp.route("/<int:id>/incidencias/<int:incidencia_id>/resolver", methods=["POST"])
@requiere_permiso("pedidos.incidencias.resolver")
def resolver_incidencia(id, incidencia_id):
    """Yikon cierra la incidencia con «Resuelta» y una nota (le llega al cliente por el chat)."""
    from flask_wtf import FlaskForm

    from app import incidencias
    from app.models import Incidencia
    pedido = pedido_o_404(id)
    incidencia = db.get_or_404(Incidencia, incidencia_id)
    if incidencia.pedido_id != pedido.id:
        abort(404)
    volver = redirect(url_for("pedidos.detalle", id=id) + "#incidencias")
    if not FlaskForm().validate_on_submit() or not incidencia.abierta:
        return volver
    nota = (request.form.get("nota") or "").strip()
    if not nota:
        flash(_("Escribe una nota: qué se ha hecho (le llega al cliente)."), "danger")
        return volver
    incidencias.resolver(incidencia, current_user, nota)
    db.session.commit()
    flash(_("Incidencia resuelta. El cliente recibe tu nota en los mensajes del pedido."), "success")
    return volver
