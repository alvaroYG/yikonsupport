from collections import defaultdict
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import force_locale, gettext as _

from app.auditoria import registrar
from app.extensions import db
from app.inventario import reservas
from app.inventario.forms import AbrirKitForm, LoteEditForm, MovimientoEditForm, MovimientoForm
from app.inventario.stock import (abrir_kit, avisos_caducidad, buscar_o_crear_lote, caducado_por_articulo,
                                  disponible, disponible_por_articulo, filtro_articulo, lotes_con_stock,
                                  productos_en_kits_cerrados, productos_solo_en_kits_cerrados, registrar_movimiento)
from app.models import TIPOS_MOVIMIENTO, Kit, Lote, MovimientoInventario, Pedido, Producto
from app.permisos import requiere_permiso
from app.utils import limpiar_busqueda, ordenar, ordenar_lista, paginar, patron_like

bp = Blueprint("inventario", __name__)


@bp.route("/")
@requiere_permiso("inventario.ver")
def lista():
    disp = disponible_por_articulo()
    caducado = caducado_por_articulo()
    lotes = defaultdict(list)                      # {clave: [(lote, unidades), ...]} en orden FEFO
    for lote, unidades in lotes_con_stock():
        lotes[lote.articulo.clave].append((lote, unidades))
    solo_en_kits = productos_solo_en_kits_cerrados()
    # Lo reservado para pedidos sigue en la oficina (cuenta como stock) pero ya tiene dueño
    reservado, reservado_lote = reservas.reservado_por_articulo(), reservas.reservado_por_lote()
    libre = defaultdict(int, {clave: n - reservado[clave] for clave, n in disp.items()})

    def fila(a, avisa=True):
        # "Stock bajo" se mira con lo LIBRE: sin caducar y sin reservar para ningún pedido
        return {"articulo": a, "producto": a, "stock": disp[a.clave], "caducado": caducado[a.clave],
                "reservado": reservado[a.clave], "libre": libre[a.clave],
                "lotes": lotes[a.clave], "bajo": avisa and libre[a.clave] <= a.stock_minimo}

    kits_activos = db.session.scalars(db.select(Kit).filter_by(activo=True).order_by(Kit.nombre)).all()
    cerrados = [fila(k) for k in kits_activos if k.cerrado]
    montados = [_disponibilidad_kit(k, libre) for k in kits_activos if not k.cerrado]
    productos = db.session.scalars(
        db.select(Producto).filter_by(activo=True, controlar_stock=True).order_by(Producto.categoria, Producto.nombre)
    ).all()
    # Unidades de cada producto dentro de los kits cerrados (calculado a partir del stock de kits)
    en_kits = productos_en_kits_cerrados()

    def fila_producto(p):
        f = fila(p, avisa=False)
        f["en_kits"] = en_kits.get(p.id, [])
        f["en_kits_total"] = sum(n for _k, _l, n in f["en_kits"])
        f["total"] = f["stock"] + f["en_kits_total"]
        f["solo_en_kits"] = p.id in solo_en_kits
        f["bajo"] = (not f["solo_en_kits"] or p.stock_minimo > 0) and f["total"] - f["reservado"] <= p.stock_minimo
        return f
    filas = [fila_producto(p) for p in productos]
    if request.args.get("solo_bajo"):
        filas = [f for f in filas if f["bajo"]]
        cerrados = [f for f in cerrados if f["bajo"]]
    # Buscador: referencia, nombre o marca; un kit, también por los productos que lleva
    q = limpiar_busqueda(request.args.get("q"), 100)
    if q:
        filas = [f for f in filas if _coincide(f["articulo"], q)]
        cerrados = [f for f in cerrados if _coincide(f["articulo"], q)]
        montados = [k for k in montados if _coincide(k["kit"], q)]
    # Cabeceras que ordenan (las tres tablas a la vez, cada una con lo suyo). Sin orden: como siempre.
    articulo = lambda f: f["articulo"]                                         # noqa: E731
    claves = {"referencia": lambda f: articulo(f).referencia, "nombre": lambda f: articulo(f).nombre,
              "disponible": lambda f: f.get("total", f["stock"]), "minimo": lambda f: articulo(f).stock_minimo}
    filas, orden = ordenar_lista(filas, claves)
    cerrados, _o = ordenar_lista(cerrados, claves)
    montados, _o = ordenar_lista(montados, {"referencia": lambda k: k["kit"].referencia, "nombre": lambda k: k["kit"].nombre,
                                            "disponible": lambda k: k["montables"]})
    form = MovimientoForm()
    abrir_form = AbrirKitForm(formdata=None)
    # Para el formulario: lotes existentes de cada artículo (el navegador los sugiere al escribir)
    lotes_por_articulo = {f"{a.tipo_articulo}-{a.id}": [
        {"codigo": l.codigo, "caducidad": l.caducidad.isoformat() if l.caducidad else ""} for l in a.lotes]
        for a in form.kits + form.productos}
    return render_template("inventario/lista.html", title=_("Inventario"), filas=filas, cerrados=cerrados, q=q, orden=orden,
                           kits=montados, form=form, abrir_form=abrir_form, lotes_por_articulo=lotes_por_articulo,
                           reservado_lote=reservado_lote, pedidos_con_reserva=len(reservas.pedidos_con_reserva()),
                           hoy=date.today(), dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


def _coincide(articulo, q):
    """¿El kit o producto tiene «q» en la referencia, el nombre o la marca? Un kit, también si lo
    lleva alguno de sus productos (como en la página de Kits)."""
    q = q.lower()
    textos = [articulo.referencia, articulo.nombre, getattr(articulo, "categoria", None)]
    if isinstance(articulo, Kit):
        textos += [t for c in articulo.componentes for t in (c.producto.referencia, c.producto.nombre)]
    return any(q in t.lower() for t in textos if t)


def _disponibilidad_kit(kit, disp):
    """
    Kits MONTADOS: cuántos kits COMPLETOS se pueden montar ahora con el stock de sus
    productos (sin lotes caducados ni unidades reservadas para pedidos). Sale del producto que menos da de sí
    (p. ej. 10 tubos y el kit lleva 2 → 5 kits). Los productos sin control de stock
    (servicios) no limitan.
    """
    componentes = []
    for c in kit.componentes_activos:
        controla = c.producto.controlar_stock
        hay = disp[c.producto.clave] if controla else None
        componentes.append({"c": c, "hay": hay,
                            "alcanza": (max(hay, 0) // c.cantidad) if controla and c.cantidad else None})
    limites = [x["alcanza"] for x in componentes if x["alcanza"] is not None]
    montables = min(limites) if limites else None
    return {"kit": kit, "componentes": componentes, "montables": montables,
            "limita": [x["c"].producto for x in componentes if x["alcanza"] is not None and x["alcanza"] == montables]
            if montables is not None else []}


@bp.route("/movimiento", methods=["POST"])
@requiere_permiso("inventario.editar")
def nuevo_movimiento():
    form = MovimientoForm()
    articulo = form.articulo_elegido
    if form.validate_on_submit() and articulo is not None:
        if form.tipo.data == "entrada":
            lote = buscar_o_crear_lote(articulo, form.lote.data, form.caducidad.data)
        else:
            lote = form.lote_encontrado          # en un ajuste el lote ya existe (lo comprueba el formulario)
        mov = registrar_movimiento(articulo, form.cantidad.data, form.tipo.data,
                                   nota=form.nota.data or None, lote=lote)
        db.session.flush()
        with force_locale("es"):   # la auditoría se guarda siempre en español
            detalle = f"{mov.cantidad:+d} × {articulo.referencia} lote {lote.codigo} ({mov.tipo_nombre})"
        registrar("crear", mov, detalle)
        db.session.commit()
        flash(_("%(producto)s: %(cantidad)s unidades. Stock actual: %(stock)s.",
                producto=articulo.nombre, cantidad=f"{mov.cantidad:+d}", stock=disponible(articulo)),
              "success")
    else:
        for errores in form.errors.values():
            for e in errores:
                flash(e, "danger")
    return redirect(url_for("inventario.lista"))


# --------------------------------------------------------------------------- #
# Reservas: qué pedidos tienen lotes apartados, y liberarlos a mano
# --------------------------------------------------------------------------- #
@bp.route("/reservas")
@requiere_permiso("inventario.ver")
def lista_reservas():
    return render_template("inventario/reservas.html", title=_("Lotes reservados"),
                           filas=reservas.pedidos_con_reserva(), hoy=date.today(),
                           dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


@bp.route("/reservas/<int:pedido_id>/liberar", methods=["POST"])
@requiere_permiso("inventario.editar")
def liberar_reserva(pedido_id):
    """Suelta los lotes de un pedido para que los pueda usar otro. Pensado para proformas que
    el cliente no contesta. Si la proforma estaba enviada se RETIRA: las fechas que vio el
    cliente ya no están garantizadas, así que no debe poder aceptarla."""
    from app.pedidos.routes import _cambiar_estado      # (import aquí: pedidos importa inventario)
    pedido = db.get_or_404(Pedido, pedido_id)
    volver = redirect(url_for("inventario.lista_reservas"))
    if not pedido.reservas:
        flash(_("Ese pedido ya no tiene lotes reservados."), "info")
        return volver
    if not reservas.se_puede_liberar(pedido):
        flash(_("El cliente ya aceptó la proforma de %(ref)s con esas caducidades: no se puede liberar. "
                "Cancela el pedido o vuelve a «Proforma solicitada» para enviarle otra.",
                ref=pedido.referencia_interna), "danger")
        return volver
    lotes = ", ".join(f"{r.lote.codigo}×{r.cantidad}" for r in pedido.reservas)
    retirada = None
    if pedido.estado == "proforma_enviada":
        retirada = pedido.proforma_actual
        if retirada is not None and retirada.estado == "enviada":
            retirada.estado = "retirada"
        if error := _cambiar_estado(pedido, "proforma_solicitada", "proforma retirada al liberar la reserva", avisar=False):
            flash(error, "danger")
            return volver
    reservas.liberar(pedido)
    registrar("editar", pedido, f"{pedido.referencia_interna} · reserva de lotes liberada: {lotes}")
    db.session.commit()
    if retirada is not None:
        flash(_("Reserva de %(ref)s liberada y proforma %(numero)s retirada: el cliente ya no puede aceptarla.",
                ref=pedido.referencia_interna, numero=retirada.numero), "success")
    else:
        flash(_("Reserva de %(ref)s liberada: esas unidades vuelven a estar libres.", ref=pedido.referencia_interna), "success")
    return volver


def _articulo_de_la_url():
    """?kit_id=3 o ?producto_id=5 (para filtrar el historial)."""
    if kit_id := request.args.get("kit_id", type=int):
        return db.session.get(Kit, kit_id)
    if producto_id := request.args.get("producto_id", type=int):
        return db.session.get(Producto, producto_id)
    return None


@bp.route("/movimientos")
@requiere_permiso("inventario.ver")
def movimientos():
    M = MovimientoInventario
    select = db.select(M).order_by(M.fecha.desc(), M.id.desc())
    articulo = _articulo_de_la_url()
    if articulo:
        select = select.where(filtro_articulo(M, articulo))
    # Buscador: artículo (referencia o nombre), lote, nota o referencia del pedido
    q = limpiar_busqueda(request.args.get("q"), 100)
    if q:
        patron = patron_like(q)
        like = lambda col: col.ilike(patron, escape="\\")                  # noqa: E731
        select = select.where(
            M.producto.has(like(Producto.referencia) | like(Producto.nombre)) | M.kit.has(like(Kit.referencia) | like(Kit.nombre))
            | M.lote.has(like(Lote.codigo)) | like(M.nota) | M.pedido.has(like(Pedido.referencia_interna)))
    nombre_articulo = db.func.lower(db.func.coalesce(
        db.select(Producto.nombre).where(Producto.id == M.producto_id).scalar_subquery(),
        db.select(Kit.nombre).where(Kit.id == M.kit_id).scalar_subquery()))
    select, orden = ordenar(select, {
        "fecha": M.fecha, "articulo": nombre_articulo, "tipo": M.tipo, "cantidad": M.cantidad,
        "lote": db.select(db.func.lower(Lote.codigo)).where(Lote.id == M.lote_id).scalar_subquery(),
    }, desempate=M.id)
    return render_template("inventario/movimientos.html", title=_("Movimientos de inventario"),
                           pagina=paginar(select), producto=articulo, tipos=TIPOS_MOVIMIENTO, q=q, orden=orden)


# --------------------------------------------------------------------------- #
# Trazabilidad: ¿dónde está este lote? (ver inventario/rastreo.py)
# --------------------------------------------------------------------------- #
@bp.route("/rastrear-lote")
@requiere_permiso("pedidos.ver_lotes")
def rastrear_lote():
    from app.inventario.rastreo import rastrear
    q = limpiar_busqueda(request.args.get("q"), 60)
    rastros, clientes, hay_mas = rastrear(q)
    return render_template("inventario/rastreo.html", title=_("¿Dónde está este lote?"), q=q, rastros=rastros,
                           clientes=clientes, hay_mas=hay_mas, hoy=date.today(),
                           dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


@bp.route("/rastrear-lote.xlsx")
@requiere_permiso("pedidos.ver_lotes")
def rastrear_lote_excel():
    """El mismo resultado en Excel: una fila por envío, con el contacto del cliente (para avisar)."""
    from flask import Response
    from app.excel import MIMETYPE_XLSX, Columna, generar_excel
    from app.inventario.rastreo import rastrear
    q = limpiar_busqueda(request.args.get("q"), 60)
    rastros, _clientes, _hay_mas = rastrear(q)
    columnas = [Columna(_("Lote"), 16), Columna(_("Artículo"), 34), Columna(_("Caducidad"), 12, "fecha"),
                Columna(_("Cliente"), 30), Columna(_("Pedido"), 14), Columna(_("Estado"), 16),
                Columna(_("Fecha de envío"), 14, "fecha"), Columna(_("Unidades"), 10, "numero"),
                Columna(_("Persona de contacto"), 24), Columna(_("Email"), 28), Columna(_("Teléfono"), 16)]
    filas = [[r["lote"].codigo, r["lote"].articulo.nombre, r["lote"].caducidad, e["pedido"].cliente.nombre,
              e["pedido"].referencia_interna or f"#{e['pedido'].id}", str(e["pedido"].estado_nombre),
              e["fecha"].date() if e["fecha"] else None, e["unidades"], e["pedido"].cliente.persona_contacto or "",
              e["pedido"].cliente.email or "", e["pedido"].cliente.telefono or ""]
             for r in rastros for e in r["envios"]]
    datos = generar_excel(_("Rastreo de lote"), columnas, filas, subtitulo=_("Lote buscado: %(q)s", q=q))
    nombre = "".join(c if c.isalnum() or c in "-_" else "_" for c in q) or "lote"
    return Response(datos, mimetype=MIMETYPE_XLSX, headers={
        "Content-Disposition": f'attachment; filename="rastreo_{nombre}_{date.today():%Y%m%d}.xlsx"'})


@bp.route("/caducidades")
@requiere_permiso("inventario.ver")
def caducidades():
    """Lotes con stock caducados o a punto de caducar."""
    return render_template("inventario/caducidades.html", title=_("Caducidades"),
                           lotes_aviso=avisos_caducidad(), dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


# --------------------------------------------------------------------------- #
# Corregir lo que ya está registrado (errores al meter una entrada, un lote mal escrito…)
# Solo lotes, entradas y ajustes manuales: las salidas por envío son la trazabilidad
# de los pedidos y no se tocan aquí (se deshacen anulando el envío).
# Todo cambio queda en la auditoría con el valor de antes y el de después.
# --------------------------------------------------------------------------- #
TIPOS_CORREGIBLES = ("entrada", "ajuste")


def _corregible(mov):
    return mov.tipo in TIPOS_CORREGIBLES and mov.pedido_id is None


def _articulo_o_404(tipo, id):
    return db.get_or_404(Kit if tipo == "kit" else Producto, id)


def _volver_a_corregir(articulo):
    return redirect(url_for("inventario.corregir", tipo=articulo.tipo_articulo, id=articulo.id))


@bp.route("/<any(producto, kit):tipo>/<int:id>/corregir")
@requiere_permiso("inventario.editar")
def corregir(tipo, id):
    articulo = _articulo_o_404(tipo, id)
    lotes = db.session.scalars(db.select(Lote).where(filtro_articulo(Lote, articulo))
                               .order_by(Lote.caducidad.is_(None), Lote.caducidad, Lote.id)).all()
    movimientos = db.session.scalars(
        db.select(MovimientoInventario).where(filtro_articulo(MovimientoInventario, articulo))
        .where(MovimientoInventario.tipo.in_(TIPOS_CORREGIBLES), MovimientoInventario.pedido_id.is_(None))
        .order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.id.desc()).limit(100)).all()
    return render_template("inventario/corregir.html", title=_("Corregir inventario · %(producto)s", producto=articulo.nombre),
                           producto=articulo, lotes=lotes, movimientos=movimientos,
                           hoy=date.today(), dias_aviso=current_app.config["DIAS_AVISO_CADUCIDAD"])


def _errores(form):
    for errores in form.errors.values():
        for e in errores:
            flash(e, "danger")


@bp.route("/lote/<int:id>/editar", methods=["POST"])
@requiere_permiso("inventario.editar")
def editar_lote(id):
    lote = db.get_or_404(Lote, id)
    form = LoteEditForm(lote=lote)
    if form.validate_on_submit():
        antes = f"{lote.codigo} cad. {lote.caducidad or '—'}"
        lote.codigo = form.codigo.data
        # Cambiar la caducidad, o ponérsela si no tenía (vacía = se queda sin ella)
        if form.caducidad.data:
            lote.caducidad = form.caducidad.data
        despues = f"{lote.codigo} cad. {lote.caducidad or '—'}"
        if antes != despues:
            registrar("editar", lote, f"{lote.articulo.referencia} · lote {antes} → {despues}")
            db.session.commit()
            flash(_("Lote corregido."), "success")
            if afectados := reservas.pedidos_que_reservan(lote):
                flash(_("Ojo: este lote está reservado para %(pedidos)s. Si has cambiado la caducidad y el cliente "
                        "ya aprobó otra en la proforma, ese pedido no se podrá enviar hasta rehacer la proforma.",
                        pedidos=", ".join(afectados)), "warning")
    else:
        _errores(form)
    return _volver_a_corregir(lote.articulo)


def _comprobar_lote(mov, nueva):
    """Error si, con la cantidad nueva, el lote quedaría en negativo (ya salió parte)."""
    if mov.lote is not None and mov.lote.stock - mov.cantidad + nueva < 0:
        return _("No se puede: el lote %(lote)s quedaría con %(n)s unidades (parte ya ha salido en envíos).",
                 lote=mov.lote.codigo, n=mov.lote.stock - mov.cantidad + nueva)
    if mov.lote is not None and nueva < mov.cantidad:      # resta: no puede comerse lo reservado
        return reservas.error_si_toca_reservas(mov.lote, mov.lote.stock - mov.cantidad + nueva)
    return None


@bp.route("/movimiento/<int:id>/editar", methods=["POST"])
@requiere_permiso("inventario.editar")
def editar_movimiento(id):
    mov = db.get_or_404(MovimientoInventario, id)
    if not _corregible(mov):
        abort(403)
    form = MovimientoEditForm()
    if not form.validate_on_submit():
        _errores(form)
    elif mov.tipo == "entrada" and form.cantidad.data <= 0:
        flash(_("Una entrada debe ser positiva. Para restar usa «Ajuste»."), "danger")
    elif error := _comprobar_lote(mov, form.cantidad.data):
        flash(error, "danger")
    else:
        nota = (form.nota.data or "").strip() or None
        if (form.cantidad.data, nota) != (mov.cantidad, mov.nota):
            with force_locale("es"):
                detalle = (f"{mov.articulo.referencia} lote {mov.lote.codigo if mov.lote else '—'} ({mov.tipo_nombre}): "
                           f"{mov.cantidad:+d} → {form.cantidad.data:+d}")
            if nota != mov.nota:
                detalle += f" · nota: {mov.nota or '—'} → {nota or '—'}"
            mov.cantidad, mov.nota = form.cantidad.data, nota
            registrar("editar", mov, detalle)
            db.session.commit()
            flash(_("Movimiento corregido. Stock actual de %(producto)s: %(stock)s.",
                    producto=mov.articulo.nombre, stock=disponible(mov.articulo)), "success")
    return _volver_a_corregir(mov.articulo)


@bp.route("/movimiento/<int:id>/borrar", methods=["POST"])
@requiere_permiso("inventario.editar")
def borrar_movimiento(id):
    """Para una entrada o un ajuste metido por error (duplicado, producto equivocado…)."""
    mov = db.get_or_404(MovimientoInventario, id)
    if not _corregible(mov):
        abort(403)
    articulo = mov.articulo
    if error := _comprobar_lote(mov, 0):
        flash(error, "danger")
        return _volver_a_corregir(articulo)
    with force_locale("es"):
        detalle = (f"borrado: {mov.cantidad:+d} × {articulo.referencia} lote "
                   f"{mov.lote.codigo if mov.lote else '—'} ({mov.tipo_nombre}, {mov.fecha:%d/%m/%Y})")
    registrar("borrar", mov, detalle)
    db.session.delete(mov)
    db.session.commit()
    flash(_("Movimiento borrado."), "success")
    return _volver_a_corregir(articulo)


# --------------------------------------------------------------------------- #
# Abrir un kit cerrado: pasa a ser sus productos sueltos (mismo lote y caducidad)
# --------------------------------------------------------------------------- #
@bp.route("/kit/<int:id>/abrir", methods=["POST"])
@requiere_permiso("inventario.editar")
def abrir(id):
    kit = db.get_or_404(Kit, id)
    if not kit.cerrado:
        abort(400)
    form = AbrirKitForm()
    form.lote_id.choices = [(l.id, l.codigo) for l in kit.lotes]
    if not form.validate_on_submit():
        _errores(form)
        return redirect(url_for("inventario.lista"))
    lote = db.session.get(Lote, form.lote_id.data)
    if error := abrir_kit(kit, lote, form.cantidad.data, motivo=(form.nota.data or "").strip() or None):
        flash(error, "danger")
        return redirect(url_for("inventario.lista"))
    with force_locale("es"):
        detalle = (f"apertura: {form.cantidad.data} × {kit.referencia} lote {lote.codigo} → "
                   + ", ".join(f"{c.cantidad * form.cantidad.data} × {c.producto.referencia}"
                               for c in kit.componentes if c.producto.controlar_stock))
    registrar("editar", kit, detalle)
    db.session.commit()
    flash(_("%(n)s × %(kit)s abierto(s): sus productos ya están como stock suelto (lote %(lote)s).",
            n=form.cantidad.data, kit=kit.nombre, lote=lote.codigo), "success")
    return redirect(url_for("inventario.lista"))
