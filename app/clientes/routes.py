
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app import paises
from app.alcance import cliente_o_404, filtrar_clientes
from app.auditoria import cambios, registrar
from app.clientes.forms import ClienteForm
from app.extensions import db
from app.models import Producto, PrecioProductoCliente
from app.models import FORMATOS_FACTURA, REGIMENES_IVA, Cliente, Factura, Kit, Pedido, PrecioCliente, User
from app.permisos import requiere_permiso
from app.utils import leer_precio, ordenar, paginar

bp = Blueprint("clientes", __name__)

CAMPOS = ["nombre", "razon_social", "cif", "prefijo", "email", "telefono", "persona_contacto",
          "direccion", "ciudad", "codigo_postal", "provincia", "pais", "eori", "notas", "activo",
          "envio_igual", "envio_destinatario", "envio_contacto", "envio_telefono", "envio_direccion",
          "envio_codigo_postal", "envio_ciudad", "envio_provincia", "envio_pais", "envio_instrucciones"]


def _situar(form, cliente, lugar_antes):
    """Dónde sale en el mapa. Si lo han puesto a mano en el mapita, eso; si no, cuando cambia la
    dirección (o aún no lo tenía), se busca su ciudad (app/geocodificar.py). Devuelve un aviso o None."""
    from app import geocodificar
    punto = form.punto()
    if form.ubicacion_manual.data == "quitar":
        cliente.latitud = cliente.longitud = None
        return None
    if form.ubicacion_manual.data == "1" and punto:
        cliente.latitud, cliente.longitud = punto
        return None
    lugar_ahora = tuple(getattr(cliente, c) for c in geocodificar.CAMPOS_LUGAR)
    if cliente.latitud is not None and lugar_ahora == lugar_antes:
        return None
    if not (cliente.ciudad or cliente.codigo_postal):
        cliente.latitud = cliente.longitud = None
        return None
    if geocodificar.situar(cliente):
        return None
    cliente.latitud = cliente.longitud = None
    return _("No he encontrado «%(lugar)s» en el mapa: sitúalo a mano en «Editar» (haz clic en el mapa).",
             lugar=", ".join(x for x in (cliente.ciudad, paises.nombre(cliente.pais)) if x))


def _guardar(form, cliente):
    for campo in CAMPOS:
        valor = getattr(form, campo).data
        setattr(cliente, campo, valor if valor != "" else None)
    # Relación muchos-a-muchos: se asigna una LISTA de usuarios y SQLAlchemy
    # se encarga de añadir/quitar filas en la tabla intermedia cliente_logistica.
    # (Solo si el formulario lo trae: quien no es admin no asigna el Soporte de cliente.)
    if "logisticos" not in form:
        return
    ids = form.logisticos.data or []
    cliente.logisticos = db.session.scalars(
        db.select(User).where(User.id.in_(ids), User.rol == "fas")
    ).all()


@bp.route("/")
@requiere_permiso("clientes.ver")
def lista():
    """Lista con buscador y filtros (?q=&estado=&fas=&precios=). Siempre dentro de lo que el
    usuario puede ver: el FAS, solo sus clientes."""
    q = request.args.get("q", "").strip()[:100]
    select = filtrar_clientes(db.select(Cliente)).order_by(Cliente.nombre)
    if q:
        patron = f"%{q}%"
        select = select.where(
            Cliente.nombre.ilike(patron) | Cliente.razon_social.ilike(patron)
            | Cliente.cif.ilike(patron) | Cliente.ciudad.ilike(patron)
            | Cliente.persona_contacto.ilike(patron) | Cliente.email.ilike(patron) | Cliente.prefijo.ilike(patron)
        )
    # Estado: activos (por defecto), inactivos o todos. (?inactivos=1 es el enlace antiguo: todos)
    estado = request.args.get("estado") or ("todos" if request.args.get("inactivos") else "activos")
    if estado == "inactivos":
        select = select.filter_by(activo=False)
    elif estado != "todos":
        estado = "activos"
        select = select.filter_by(activo=True)
    # FAS que lo lleva (solo tiene sentido para quien ve todos los clientes): un FAS o "sin FAS"
    fas, lista_fas = request.args.get("fas") or "", []
    if current_user.puede("clientes.editar"):
        lista_fas = db.session.scalars(db.select(User).filter_by(rol="fas").order_by(User.nombre)).all()
        if fas == "ninguno":
            select = select.where(~Cliente.logisticos.any())
        elif fas.isdigit():
            select = select.where(Cliente.logisticos.any(User.id == int(fas)))
        else:
            fas = ""
    precios = request.args.get("precios") or ""
    if precios in ("si", "no"):
        select = select.filter_by(ver_precios=(precios == "si"))
    else:
        precios = ""
    hay_filtros = bool(q or fas or precios or estado != "activos")
    # Cabeceras que ordenan (utils.ordenar). «Soporte de cliente»: por el primero (A→Z) que lo lleva.
    from app.models import cliente_logistica
    primer_fas = (db.select(db.func.min(db.func.lower(User.nombre)))
                  .join(cliente_logistica, cliente_logistica.c.usuario_id == User.id)
                  .where(cliente_logistica.c.cliente_id == Cliente.id).scalar_subquery())
    select, orden = ordenar(select, {
        "nombre": db.func.lower(Cliente.nombre), "cif": Cliente.cif, "ciudad": db.func.lower(Cliente.ciudad),
        "contacto": db.func.lower(Cliente.persona_contacto), "fas": primer_fas,
        "precios": db.case((Cliente.ver_precios.is_(True), 0), else_=1),        # los que ven precios primero
    }, desempate=Cliente.id)
    return render_template("clientes/lista.html", title=_("Clientes"), pagina=paginar(select), q=q, orden=orden,
                           estado=estado, fas=fas, lista_fas=lista_fas, precios=precios, hay_filtros=hay_filtros)


@bp.route("/mapa")
@requiere_permiso("clientes.ver")
def mapa():
    """Mapa de clientes (Europa y Latinoamérica): un punto por cliente, con su resumen al elegirlo.
    Cada uno ve los clientes que ve en la lista (Soporte de cliente: los suyos). El dibujo lo hace
    js/mapa_clientes.js con el mapa del mundo que va en static/vendor (sin servicios de fuera)."""
    from datetime import date

    hoy = date.today()
    clientes = db.session.scalars(filtrar_clientes(db.select(Cliente)).order_by(Cliente.nombre)).all()
    ids = [c.id for c in clientes]
    # Pedidos de los últimos 12 meses (sin los cancelados), para el resumen y la gráfica por meses
    desde = date(hoy.year - 1, hoy.month, 1)
    meses = [((hoy.year * 12 + hoy.month - 1 - i) // 12, (hoy.year * 12 + hoy.month - 1 - i) % 12 + 1)
             for i in range(11, -1, -1)]
    filas = db.session.execute(db.select(Pedido.cliente_id, Pedido.fecha).where(
        Pedido.cliente_id.in_(ids), Pedido.estado != "cancelado", Pedido.fecha >= desde)).all() if ids else []
    ultimos = dict(db.session.execute(db.select(Pedido.cliente_id, db.func.max(Pedido.fecha)).where(
        Pedido.cliente_id.in_(ids), Pedido.estado != "cancelado").group_by(Pedido.cliente_id)).all()) if ids else {}
    por_cliente = {}
    for cid, fecha in filas:
        por_cliente.setdefault(cid, []).append(fecha)
    datos, sin_situar = [], []
    for c in clientes:
        fechas = por_cliente.get(c.id, [])
        if c.latitud is None or c.longitud is None:
            sin_situar.append(c)
            continue
        ultimo = ultimos.get(c.id)
        datos.append({
            "id": c.id, "nombre": c.nombre, "ciudad": c.ciudad or "", "pais": paises.nombre(c.pais),
            "lat": c.latitud, "lon": c.longitud,
            "estado": "inactivo" if not c.activo else ("con_pedidos" if ultimo else "nuevo"),
            "pedidos_anio": sum(1 for f in fechas if f.year == hoy.year),
            "ultimo": ultimo.strftime("%d/%m/%Y") if ultimo else "",
            "soporte": ", ".join(u.nombre for u in c.logisticos),
            "serie": [sum(1 for f in fechas if (f.year, f.month) == m) for m in meses],
            "url": url_for("clientes.detalle", id=c.id),
        })
    soportes = sorted({u.nombre for c in clientes for u in c.logisticos}) if current_user.puede("clientes.editar") else []
    return render_template("clientes/mapa.html", title=_("Mapa de clientes"), clientes=datos, sin_situar=sin_situar,
                           soportes=soportes, anio=hoy.year, meses=meses)


@bp.route("/mi-empresa")
@requiere_permiso("clientes.mi_empresa")
def mi_empresa():
    """El usuario de una empresa cliente ve los datos de SU empresa (facturación y envío), sin poder
    cambiarlos: los cambia Yikon (si algo no está bien, nos escribe)."""
    cliente = current_user.empresa
    if cliente is None:
        abort(404)
    return render_template("clientes/mi_empresa.html", title=_("Mi empresa"), cliente=cliente)


@bp.route("/nuevo", methods=["GET", "POST"])
@requiere_permiso("clientes.crear")
def nuevo():
    form = ClienteForm()
    if form.validate_on_submit():
        cliente = Cliente()
        _guardar(form, cliente)
        aviso_mapa = _situar(form, cliente, None)
        # Soporte de cliente: el cliente que da de alta es suyo (si no, ni lo vería)
        if current_user.rol == "fas" and current_user not in cliente.logisticos:
            cliente.logisticos.append(current_user)
        db.session.add(cliente)
        db.session.flush()
        registrar("crear", cliente, cliente.nombre)
        from app import avisos_internos
        avisos_internos.alta_cliente(cliente, current_user)
        db.session.commit()
        if aviso_mapa and current_app.config.get("GEOCODIFICAR"):
            flash(aviso_mapa, "warning")
        if current_user.puede("clientes.usuarios"):
            flash(_("Cliente «%(nombre)s» creado. Ahora añade sus usuarios: les llegará la invitación.",
                    nombre=cliente.nombre), "success")
            return redirect(url_for("clientes.detalle", id=cliente.id) + "#usuarios")
        flash(_("Cliente «%(nombre)s» creado.", nombre=cliente.nombre), "success")
        return redirect(url_for("clientes.detalle", id=cliente.id))
    return render_template("clientes/form.html", title=_("Nuevo cliente"), form=form)


@bp.route("/<int:id>")
@requiere_permiso("clientes.ver")
def detalle(id):
    cliente = cliente_o_404(id)
    # Pedidos y facturas, paginados cada uno por su lado (10 por página, como todas las listas)
    pedidos = paginar(db.select(Pedido).filter_by(cliente_id=cliente.id).order_by(Pedido.fecha.desc(), Pedido.id.desc()),
                      "pagina_pedidos", "por_pagina_pedidos")
    facturas = None
    if current_user.puede("facturas.ver"):
        facturas = paginar(db.select(Factura).filter_by(cliente_id=cliente.id)
                           .order_by(Factura.fecha_emision.desc(), Factura.id.desc()),
                           "pagina_facturas", "por_pagina_facturas")
    precios, kits_sin_precio = [], []
    if current_user.puede("pedidos.ver_importes"):
        precios = db.session.scalars(db.select(PrecioCliente).filter_by(cliente_id=cliente.id)
                                     .join(Kit).order_by(Kit.nombre)).all()
        con_precio = {p.kit_id for p in precios}
        kits_sin_precio = [k for k in db.session.scalars(db.select(Kit).filter_by(activo=True).order_by(Kit.nombre))
                           if k.id not in con_precio]
    precios_productos, productos_sin_precio = [], []
    if current_user.puede("pedidos.ver_importes"):
        precios_productos = db.session.scalars(db.select(PrecioProductoCliente).filter_by(cliente_id=cliente.id)
            .join(Producto).order_by(Producto.nombre)).all()
        con_precio_producto = {p.producto_id for p in precios_productos}
        productos_sin_precio = [p for p in db.session.scalars(db.select(Producto).filter_by(activo=True).order_by(Producto.nombre))
                               if p.id not in con_precio_producto]
    catalogo = None
    if current_user.puede("clientes.catalogo"):
        from app import catalogo_cliente
        kits_cat, productos_cat = catalogo_cliente.tabla(cliente)
        otros = db.session.scalars(filtrar_clientes(db.select(Cliente)).where(
            Cliente.id != cliente.id, Cliente.catalogo_propio.is_(True)).order_by(Cliente.nombre)).all()
        catalogo = {"kits": kits_cat, "productos": productos_cat, "otros": otros}
    avisos = None
    if current_user.puede("clientes.avisos"):
        from app import avisos_cliente
        usuarios, copias = avisos_cliente.tabla(cliente)
        avisos = {"usuarios": usuarios, "copias": copias, "tipos": avisos_cliente.TIPOS,
                  "explicacion": avisos_cliente.EXPLICACION, "max_copias": avisos_cliente.MAX_COPIAS}
    # Pestaña «Usuarios» (su Soporte de cliente y admin): los de la empresa, activos primero
    usuarios = (sorted(cliente.usuarios, key=lambda u: (not u.activo, u.nombre.lower()))
                if current_user.puede("clientes.usuarios") else None)
    from app.admin.panel import pausa_form
    from markupsafe import Markup
    pausa_html = Markup(pausa_form(cliente.id)) if current_user.puede("ajustes.editar") else ""
    return render_template("clientes/detalle.html", pausa_html=pausa_html, title=cliente.nombre, cliente=cliente, avisos=avisos, catalogo=catalogo,
                           usuarios=usuarios,
                           pedidos=pedidos, facturas=facturas, precios=precios, precios_productos=precios_productos,
                           productos_sin_precio=productos_sin_precio,
                           kits_sin_precio=kits_sin_precio, formatos=FORMATOS_FACTURA, regimenes=REGIMENES_IVA)


# --------------------------------------------------------------------------- #
# Precios especiales de kits para este cliente
# --------------------------------------------------------------------------- #
@bp.route("/<int:id>/precios", methods=["POST"])
@requiere_permiso("clientes.editar")
def guardar_precio(id):
    """Crea o cambia el precio especial de un kit para este cliente. Los pedidos ya
    hechos no cambian: el precio se copia al pedido cuando se crea."""
    cliente = cliente_o_404(id)
    kit = db.get_or_404(Kit, request.form.get("kit_id", type=int))
    precio = leer_precio(request.form.get("precio"))
    if precio is None:
        flash(_("Escribe un precio válido (p. ej. 1850 o 1850,50)."), "danger")
        return redirect(url_for("clientes.detalle", id=id) + "#precios")
    existente = db.session.scalar(db.select(PrecioCliente).filter_by(cliente_id=cliente.id, kit_id=kit.id))
    antes = existente.precio if existente else None
    if existente:
        existente.precio = precio
    else:
        db.session.add(PrecioCliente(cliente=cliente, kit=kit, precio=precio))
    registrar("editar", cliente, f"precio especial {kit.referencia}: {antes or 'estándar'} → {precio}")
    db.session.commit()
    flash(_("Precio especial de %(kit)s guardado.", kit=kit.nombre), "success")
    return redirect(url_for("clientes.detalle", id=id) + "#precios")


@bp.route("/<int:id>/precios/<int:precio_id>/borrar", methods=["POST"])
@requiere_permiso("clientes.editar")
def borrar_precio(id, precio_id):
    cliente = cliente_o_404(id)
    precio = db.get_or_404(PrecioCliente, precio_id)
    if precio.cliente_id != cliente.id:
        abort(404)
    registrar("editar", cliente, f"precio especial {precio.kit.referencia} quitado ({precio.precio})")
    db.session.delete(precio)
    db.session.commit()
    flash(_("Ahora %(kit)s vuelve a su precio estándar para este cliente.", kit=precio.kit.nombre), "success")
    return redirect(url_for("clientes.detalle", id=id) + "#precios")


@bp.route("/<int:id>/precios-productos", methods=["POST"])
@requiere_permiso("clientes.editar")
def guardar_precio_producto(id):
    """Crea o cambia el precio especial de un producto para este cliente. Los pedidos ya
    hechos no cambian: el precio se copia al pedido cuando se crea."""
    cliente = cliente_o_404(id)
    producto = db.get_or_404(Producto, request.form.get("producto_id", type=int))
    precio = leer_precio(request.form.get("precio"))
    if precio is None:
        flash(_("Escribe un precio válido (p. ej. 1850 o 1850,50)."), "danger")
        return redirect(url_for("clientes.detalle", id=id) + "#precios-productos")
    existente = db.session.scalar(db.select(PrecioProductoCliente).filter_by(cliente_id=cliente.id, producto_id=producto.id))
    antes = existente.precio if existente else None
    if existente:
        existente.precio = precio
    else:
        db.session.add(PrecioProductoCliente(cliente=cliente, producto=producto, precio=precio))
    registrar("editar", cliente, f"precio especial {producto.referencia}: {antes or 'estándar'} → {precio}")
    db.session.commit()
    flash(_("Precio especial de %(producto)s guardado.", producto=producto.nombre), "success")
    return redirect(url_for("clientes.detalle", id=id) + "#precios-productos")


@bp.route("/<int:id>/precios-productos/<int:precio_id>/borrar", methods=["POST"])
@requiere_permiso("clientes.editar")
def borrar_precio_producto(id, precio_id):
    cliente = cliente_o_404(id)
    precio = db.get_or_404(PrecioProductoCliente, precio_id)
    if precio.cliente_id != cliente.id:
        abort(404)
    registrar("editar", cliente, f"precio especial {precio.producto.referencia} quitado ({precio.precio})")
    db.session.delete(precio)
    db.session.commit()
    flash(_("Ahora %(producto)s vuelve a su precio estándar para este cliente.", producto=precio.producto.nombre), "success")
    return redirect(url_for("clientes.detalle", id=id) + "#precios-productos")


@bp.route("/<int:id>/editar", methods=["GET", "POST"])
@requiere_permiso("clientes.datos")
def editar(id):
    cliente = cliente_o_404(id)                # Soporte de cliente: solo los suyos
    form = ClienteForm(obj=cliente, cliente=cliente)
    if request.method == "GET" and "logisticos" in form:
        form.logisticos.data = [u.id for u in cliente.logisticos]
    if form.validate_on_submit():
        detalle = cambios(cliente, form, CAMPOS)
        antes = sorted(u.nombre for u in cliente.logisticos)
        from app.geocodificar import CAMPOS_LUGAR
        lugar_antes = tuple(getattr(cliente, c) for c in CAMPOS_LUGAR)
        _guardar(form, cliente)
        aviso_mapa = _situar(form, cliente, lugar_antes)
        despues = sorted(u.nombre for u in cliente.logisticos)
        if antes != despues:
            detalle = "; ".join(filter(None, [detalle, f"asignados: {antes} → {despues}"]))
        registrar("editar", cliente, detalle)
        db.session.commit()
        flash(_("Cliente actualizado."), "success")
        if aviso_mapa and current_app.config.get("GEOCODIFICAR"):
            flash(aviso_mapa, "warning")
        return redirect(url_for("clientes.detalle", id=cliente.id))
    return render_template("clientes/form.html", title=_("Editar %(nombre)s", nombre=cliente.nombre), form=form)


# --------------------------------------------------------------------------- #
# Usuarios de la empresa (pestaña «Usuarios»): los da de alta su Soporte de cliente (o admin)
# --------------------------------------------------------------------------- #
def _usuario_de(cliente, uid):
    from app.permisos import ROLES_CLIENTE
    usuario = db.get_or_404(User, uid)
    if usuario.cliente_id != cliente.id or usuario.rol not in ROLES_CLIENTE:
        abort(404)
    return usuario


@bp.route("/<int:id>/usuarios/nuevo", methods=["GET", "POST"])
@requiere_permiso("clientes.usuarios")
def nuevo_usuario(id):
    """Alta de un usuario de esta empresa (rol Cliente). Se le prepara la invitación para que elija su
    contraseña (como todas las invitaciones, la revisa y envía quien la hace)."""
    import secrets

    from app.admin.routes import _invitar
    from app.clientes.forms import UsuarioClienteForm
    cliente = cliente_o_404(id)
    form = UsuarioClienteForm()
    if form.validate_on_submit():
        usuario = User(nombre=form.nombre.data, email=form.email.data, rol="cliente", cliente_id=cliente.id,
                       activo=form.activo.data, idioma=form.idioma.data or None)
        usuario.set_password(secrets.token_urlsafe(32))        # nadie la sabe: la elige él con la invitación
        db.session.add(usuario)
        db.session.flush()
        registrar("crear", usuario, f"rol=cliente · empresa={cliente.nombre}"
                  + (" · invitación preparada" if usuario.activo else ""))
        if usuario.activo:
            _invitar(usuario)
        from app import avisos_internos
        avisos_internos.alta_usuario(usuario, current_user)
        db.session.commit()
        flash(_("Usuario %(email)s creado. La invitación está pendiente de revisar y enviar.", email=usuario.email)
              if usuario.activo else _("Usuario %(email)s creado.", email=usuario.email), "success")
        return redirect(url_for("clientes.detalle", id=cliente.id) + "#usuarios")
    return render_template("clientes/usuario_form.html", title=_("Nuevo usuario de %(cliente)s", cliente=cliente.nombre),
                           form=form, cliente=cliente)


@bp.route("/<int:id>/usuarios/<int:uid>", methods=["GET", "POST"])
@requiere_permiso("clientes.usuarios")
def editar_usuario(id, uid):
    from app.clientes.forms import UsuarioClienteForm
    cliente = cliente_o_404(id)
    usuario = _usuario_de(cliente, uid)
    form = UsuarioClienteForm(obj=usuario, usuario=usuario)
    if request.method == "GET":
        form.idioma.data = usuario.idioma or ""
    if form.validate_on_submit():
        detalle = cambios(usuario, form, ["nombre", "email", "activo"])
        usuario.nombre, usuario.email, usuario.activo = form.nombre.data, form.email.data, form.activo.data
        usuario.idioma = form.idioma.data or None
        registrar("editar", usuario, detalle or "idioma")
        db.session.commit()
        flash(_("Usuario actualizado."), "success")
        return redirect(url_for("clientes.detalle", id=cliente.id) + "#usuarios")
    return render_template("clientes/usuario_form.html", title=_("Editar %(nombre)s", nombre=usuario.nombre),
                           form=form, cliente=cliente, usuario=usuario)


@bp.route("/<int:id>/usuarios/<int:uid>/invitar", methods=["POST"])
@requiere_permiso("clientes.usuarios")
def invitar_usuario(id, uid):
    """Volver a mandarle la invitación (perdió el email, caducó el enlace...). Solo si aún no ha entrado."""
    from flask_wtf import FlaskForm

    from app.admin.routes import _invitar
    cliente = cliente_o_404(id)
    usuario = _usuario_de(cliente, uid)
    volver = redirect(url_for("clientes.detalle", id=cliente.id) + "#usuarios")
    if not FlaskForm().validate_on_submit():
        return volver
    if usuario.activo and usuario.ultimo_acceso is None:
        _invitar(usuario)
        registrar("editar", usuario, "invitación reenviada")
        db.session.commit()
        flash(_("Invitación preparada para %(email)s. Revisa el correo antes de enviarlo.", email=usuario.email), "success")
    else:
        flash(_("No se envía: el usuario ya ha entrado alguna vez o está desactivado."), "warning")
    return volver


@bp.route("/<int:id>/ver-precios", methods=["POST"])
@requiere_permiso("clientes.precios_visibles")
def cambiar_ver_precios(id):
    """Activa o desactiva que los usuarios de este cliente vean precios (FAS: solo sus clientes)."""
    cliente = cliente_o_404(id)
    cliente.ver_precios = request.form.get("ver_precios") == "1"
    registrar("editar", cliente, f"ver precios: {'sí' if cliente.ver_precios else 'no'}")
    db.session.commit()
    flash(_("%(cliente)s ahora ve los precios.", cliente=cliente.nombre) if cliente.ver_precios
          else _("%(cliente)s ya no ve los precios.", cliente=cliente.nombre), "success")
    destino = request.form.get("volver")
    return redirect(url_for("clientes.lista") if destino == "lista" else url_for("clientes.detalle", id=cliente.id))


# --------------------------------------------------------------------------- #
# Avisos por email: qué recibe cada usuario del cliente y los emails en copia (app/avisos_cliente.py)
# --------------------------------------------------------------------------- #
@bp.route("/<int:id>/avisos", methods=["POST"])
@requiere_permiso("clientes.avisos")
def guardar_avisos(id):
    """Las casillas de «Avisos por email» de la ficha (admin y el Soporte de cliente de ese cliente)."""
    from email_validator import EmailNotValidError, validate_email
    from flask_wtf import FlaskForm

    from app import avisos_cliente
    cliente = cliente_o_404(id)
    volver = redirect(url_for("clientes.detalle", id=id) + "#avisos")
    if not FlaskForm().validate_on_submit():
        return volver
    marcados = {u.id: set(request.form.getlist(f"u{u.id}")) for u in avisos_cliente.usuarios_del_cliente(cliente)}
    de_usuarios = {u.email for u in cliente.usuarios}
    copias = []
    for i in range(avisos_cliente.MAX_COPIAS + 1):
        email = (request.form.get(f"copia_email_{i}") or "").strip().lower()
        if not email or request.form.get(f"copia_quitar_{i}"):
            continue
        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            flash(_("«%(email)s» no es un email válido.", email=email), "danger")
            return volver
        if email in de_usuarios:
            flash(_("%(email)s ya es un usuario de este cliente: marca sus avisos en su fila.", email=email), "danger")
            return volver
        copias.append((email, set(request.form.getlist(f"copia_tipos_{i}"))))
    if len(copias) > avisos_cliente.MAX_COPIAS:
        flash(_("Como mucho %(n)s emails en copia.", n=avisos_cliente.MAX_COPIAS), "danger")
        return volver
    cambios = avisos_cliente.guardar(cliente, marcados, copias)
    if cambios:
        registrar("editar", cliente, "avisos por email: " + "; ".join(cambios))
        db.session.commit()
        flash(_("Avisos guardados."), "success")
    else:
        flash(_("No has cambiado nada."), "info")
    return volver


@bp.route("/<int:id>/exportar", methods=["POST"])
@requiere_permiso("clientes.exportar")
def exportar(id):
    """«Exportar todo»: un ZIP con sus pedidos (Excel), facturas, proformas y documentos (solo admin).
    Queda en la auditoría. Lógica: app/clientes/exportar.py"""
    import os

    from flask import send_file
    from flask_wtf import FlaskForm

    from app.clientes import exportar as exp
    cliente = cliente_o_404(id)
    if not FlaskForm().validate_on_submit():
        return redirect(url_for("clientes.detalle", id=id))
    ruta, resumen = exp.generar_zip(cliente, current_user)
    registrar("exportar", cliente, resumen)
    db.session.commit()
    respuesta = send_file(ruta, mimetype="application/zip", as_attachment=True,
                          download_name=exp.nombre_del_zip(cliente), max_age=0)
    respuesta.headers["Cache-Control"] = "private, no-store"
    respuesta.call_on_close(lambda: os.path.exists(ruta) and os.remove(ruta))
    return respuesta


# --------------------------------------------------------------------------- #
# Su catálogo: qué kits puede pedir y qué productos ve (app/catalogo_cliente.py)
# --------------------------------------------------------------------------- #
@bp.route("/<int:id>/catalogo", methods=["POST"])
@requiere_permiso("clientes.catalogo")
def guardar_catalogo(id):
    """La tarjeta «Su catálogo» de la ficha (admin y su Soporte de cliente). Con accion=copiar, se
    guarda aquí la lista de otro cliente con catálogo propio (uno que quien lo hace también pueda ver)."""
    from flask_wtf import FlaskForm

    from app import catalogo_cliente
    cliente = cliente_o_404(id)
    volver = redirect(url_for("clientes.detalle", id=id) + "#catalogo")
    if not FlaskForm().validate_on_submit():
        return volver
    if request.form.get("accion") == "copiar":
        origen = cliente_o_404(request.form.get("copiar_de", type=int) or 0)
        kit_ids = [k.id for k in origen.kits_catalogo]
        producto_ids = [p.id for p in origen.productos_catalogo]
        propio = True
        aviso_copia = _("Copiado el catálogo de %(otro)s.", otro=origen.nombre)
    else:
        kit_ids = request.form.getlist("kit", type=int)
        producto_ids = request.form.getlist("producto", type=int)
        propio = request.form.get("modo") == "propio"
        aviso_copia = None
    cambio, afectados = catalogo_cliente.guardar(cliente, propio, kit_ids, producto_ids)
    if not cambio:
        db.session.rollback()
        flash(_("No has cambiado nada."), "info")
        return volver
    registrar("editar", cliente, cambio)
    db.session.commit()
    flash(aviso_copia or _("Catálogo guardado."), "success")
    if afectados:
        flash(_("Ojo: tiene proformas abiertas con kits que ya no están en su catálogo: %(refs)s. No se tocan; "
                "revísalas por si hay que cambiarlas.",
                refs=", ".join(p.referencia_interna or f"#{p.id}" for p in afectados)), "warning")
    return volver
