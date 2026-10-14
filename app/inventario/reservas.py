"""
Reserva de lotes por pedido.

POR QUÉ: en la proforma el cliente aprueba la CADUCIDAD de lo que va a recibir. Esa fecha es
la del lote, así que el lote se decide ANTES de enviarle la proforma y queda reservado para
ese pedido: nadie más puede llevárselo y, al enviar, salen exactamente esos lotes.

CUÁNDO se reserva:
  - Pedido del cliente: al preparar la proforma (tarjeta "Lotes de este pedido"); al enviarla
    quedan reservados. Lo que no tenga stock libre va "a confirmar" y se asigna cuando llegue.
  - Pedido creado por Yikon (sin proforma): al crearlo, automáticamente (los que caducan
    antes: FEFO), y se puede cambiar en su ficha hasta que salga.
CUÁNDO se puede cambiar (modo_edicion):
  - "libre": mientras se prepara la proforma, y en los pedidos sin proforma hasta enviarlos.
  - "completar": proforma ya enviada/aceptada → lo reservado NO se toca (el cliente aprobó esas
    fechas); solo se puede asignar lo que quedó "a confirmar". Para cambiar un lote hay que
    rehacer la proforma (Aceptado → Proforma solicitada).
CUÁNDO se libera: al cancelar el pedido, al liberar la reserva a mano desde Inventario, o al
enviar (se convierte en la salida de stock). Si se anula un envío, vuelve a reservarse.

"Libre" de un lote = lo que hay − lo reservado para OTROS pedidos.
"""
from collections import defaultdict
from datetime import date

from flask_babel import gettext as _
from flask_login import current_user

from app.extensions import db
from app.inventario.stock import articulo_de, disponible, lotes_con_stock, unidades_por_articulo
from app.models import Kit, Lote, Pedido, Producto, ReservaLote

# Estados en los que un pedido puede tener lotes reservados (aún no ha salido ni está cancelado)
ESTADOS_CON_RESERVA = ("proforma_solicitada", "proforma_enviada", "cambios_solicitados", "aceptado",
                       "en_preparacion", "en_validacion", "validado")


def _orden_fefo(lote):
    return (lote.caducidad is None, lote.caducidad or date.max, lote.id)


def _clave(lote):
    return ("kit", lote.kit_id) if lote.kit_id is not None else ("producto", lote.producto_id)


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def reservado_por_lote(excluir_pedido_id=None) -> dict:
    """{lote_id: unidades reservadas} (sin contar las del pedido indicado)."""
    select = db.select(ReservaLote.lote_id, db.func.sum(ReservaLote.cantidad)).group_by(ReservaLote.lote_id)
    if excluir_pedido_id is not None:
        select = select.where(ReservaLote.pedido_id != excluir_pedido_id)
    return defaultdict(int, dict(db.session.execute(select).all()))


def reservado_en(lote) -> int:
    """Unidades de este lote apartadas para pedidos (no se pueden ajustar a la baja ni abrir)."""
    return db.session.scalar(db.select(db.func.coalesce(db.func.sum(ReservaLote.cantidad), 0))
                             .where(ReservaLote.lote_id == lote.id))


def error_si_toca_reservas(lote, quedarian):
    """Texto de error si, tras restar, en el lote quedarían menos unidades que las reservadas."""
    reservadas = reservado_en(lote)
    if reservadas and quedarian < reservadas:
        return _("No se puede: el lote %(lote)s tiene %(n)s unidades reservadas para pedidos y quedarían %(q)s. "
                 "Libera antes la reserva (Inventario → Reservas) o cambia el lote en el pedido.",
                 lote=lote.codigo, n=reservadas, q=quedarian)
    return None


def pedidos_que_reservan(lote) -> list:
    """Referencias de los pedidos que tienen reservado este lote."""
    return [r.pedido.referencia_interna or f"#{r.pedido_id}"
            for r in db.session.scalars(db.select(ReservaLote).where(ReservaLote.lote_id == lote.id))]


def reservado_por_articulo(hoy=None) -> dict:
    """{clave: unidades reservadas en lotes SIN CADUCAR} (para el inventario y el aviso de stock
    bajo). Lo reservado en un lote caducado no cuenta: ese lote ya no está en "disponible"."""
    hoy = hoy or date.today()
    total = defaultdict(int)
    for r in db.session.scalars(db.select(ReservaLote)):
        if not r.lote.caducado(hoy):
            total[_clave(r.lote)] += r.cantidad
    return total


def pedidos_abiertos_con_reservas(kit=None, producto=None) -> list:
    """Referencias de los pedidos con lotes reservados que llevan este kit, o que tienen
    reservado un lote de este producto. Mientras existan no se puede cambiar "kit cerrado" ni
    "controlar stock": la reserva se quedaría colgada de un artículo que el pedido ya no saca."""
    if kit is not None:
        from app.models import KitPedido
        select = db.select(Pedido).where(Pedido.id.in_(db.select(ReservaLote.pedido_id)),
                                         Pedido.id.in_(db.select(KitPedido.pedido_id).where(KitPedido.kit_id == kit.id)))
    else:
        select = db.select(Pedido).where(Pedido.id.in_(
            db.select(ReservaLote.pedido_id).join(Lote).where(Lote.producto_id == producto.id)))
    return [p.referencia_interna or f"#{p.id}" for p in db.session.scalars(select.order_by(Pedido.id))]


def reservas_de(pedido) -> dict:
    """{clave: [(lote, unidades), ...]} de este pedido, el que caduca antes primero."""
    por_clave = defaultdict(list)
    for r in sorted(pedido.reservas, key=lambda r: _orden_fefo(r.lote)):
        por_clave[_clave(r.lote)].append((r.lote, r.cantidad))
    return por_clave


def lotes_libres(articulo, pedido, hoy=None) -> list:
    """[(lote, hay, libre)] de los lotes SIN CADUCAR de un artículo, FEFO.
    libre = lo que hay − lo reservado para otros pedidos (nunca negativo).
    Además, entre todos no pueden dar más de lo que el artículo tiene DE VERDAD: si un lote
    antiguo quedó en negativo (ajustes de antes de los lotes), no sale aquí pero sí resta."""
    hoy = hoy or date.today()
    otros = reservado_por_lote(excluir_pedido_id=pedido.id if pedido is not None else None)
    # (lo reservado en lotes caducados no resta: "disponible" ya no cuenta esos lotes)
    tope = max(disponible(articulo, hoy) - sum(otros[l.id] for l in articulo.lotes if not l.caducado(hoy)), 0)
    filas = []
    for lote, hay in lotes_con_stock(articulo, hoy):
        if lote.caducado(hoy):
            continue
        libre = min(max(hay - otros[lote.id], 0), tope)
        tope -= libre
        filas.append((lote, hay, libre))
    return filas


def reparto_sugerido(pedido, hoy=None, sin_caducados=False) -> dict:
    """{lote_id: unidades}: lo ya reservado y, para lo que falta, los lotes libres que caducan
    antes (FEFO). Es lo que se propone en la ficha y lo que se reserva si no se elige otra cosa.
    sin_caducados: no cuenta lo que el pedido tenía reservado en lotes que YA han caducado o
    que se han quedado sin unidades (se sustituye por otro lote). Solo cuando el lote se puede
    cambiar libremente; con la proforma aprobada no se sustituye nada por su cuenta."""
    hoy = hoy or date.today()
    vale = (lambda r: not r.lote.caducado(hoy) and r.lote.stock >= r.cantidad) if sin_caducados else (lambda r: True)
    reparto = {r.lote_id: r.cantidad for r in pedido.reservas if vale(r)}
    actuales = defaultdict(list)
    for r in pedido.reservas:
        if vale(r):
            actuales[_clave(r.lote)].append((r.lote, r.cantidad))
    for clave, necesarias in unidades_por_articulo(pedido).items():
        pendiente = necesarias - sum(n for _l, n in actuales.get(clave, []))
        if pendiente <= 0:
            continue
        for lote, _hay, libre in lotes_libres(articulo_de(clave), pedido, hoy):
            toma = min(libre - reparto.get(lote.id, 0), pendiente)
            if toma > 0:
                reparto[lote.id] = reparto.get(lote.id, 0) + toma
                pendiente -= toma
            if pendiente == 0:
                break
    return reparto


def modo_edicion(pedido, usuario=None):
    """"libre", "completar" o None (ver la cabecera del módulo)."""
    usuario = usuario or current_user
    if not usuario.puede("pedidos.editar") or pedido.estado not in ESTADOS_CON_RESERVA:
        return None
    if pedido.estado in ("proforma_solicitada", "cambios_solicitados") or not pedido.con_proforma:
        return "libre"
    return "completar"      # proforma enviada o aceptada: lo aprobado no se cambia


def resumen(pedido, hoy=None, sin_caducados=False) -> list:
    """Lo que enseña la tarjeta "Lotes de este pedido":
    [{articulo, clave, necesarias, reservadas, completo, lotes: [{lote, hay, libre, reservadas, propuesta}]}]
    `propuesta` = lo que se reservaría con el reparto sugerido (lo que viene escrito en la casilla)."""
    hoy = hoy or date.today()
    actuales, sugerido = reservas_de(pedido), reparto_sugerido(pedido, hoy, sin_caducados)
    filas = []
    for clave, necesarias in unidades_por_articulo(pedido).items():
        articulo = articulo_de(clave)
        mias = {lote.id: n for lote, n in actuales.get(clave, [])}
        lotes = [{"lote": lote, "hay": hay, "libre": libre, "reservadas": mias.get(lote.id, 0),
                  "propuesta": sugerido.get(lote.id, 0), "caducado": False}
                 for lote, hay, libre in lotes_libres(articulo, pedido, hoy) if libre > 0 or lote.id in mias]
        vistos = {f["lote"].id for f in lotes}
        # Un lote reservado que ha caducado o se ha quedado sin unidades: se enseña para que se vea el problema
        for lote, n in actuales.get(clave, []):
            if lote.id not in vistos:
                lotes.append({"lote": lote, "hay": lote.stock, "libre": 0, "reservadas": n,
                              "propuesta": sugerido.get(lote.id, 0),
                              "caducado": lote.caducado(hoy)})
        reservadas = sum(mias.values())
        filas.append({"articulo": articulo, "clave": f"{clave[0]}-{clave[1]}", "necesarias": necesarias,
                      "reservadas": reservadas, "completo": reservadas == necesarias, "lotes": lotes,
                      "propuestas": sum(f["propuesta"] for f in lotes),
                      "cubierto": sum(f["propuesta"] for f in lotes) >= necesarias})
    return filas


def plan_reservado(pedido, hoy=None, faltan=True, proforma=None):
    """De qué lotes sale el pedido: SUS RESERVAS. Devuelve (plan, problemas):
      plan = {clave: [(lote, unidades)]} · problemas = textos (vacío si se puede enviar).
    Para enviar, cada artículo tiene que estar reservado entero, en lotes sin caducar, con
    unidades suficientes en la oficina y con la caducidad que el cliente aprobó en la proforma.
      faltan=False   → no cuenta como problema lo que falta por asignar (la tarjeta de la
                       ficha ya lo enseña de otra forma).
      proforma=None  → se compara con la proforma aceptada salvo mientras se está preparando
                       otra (entonces es normal que no coincida); True → siempre (al enviar)."""
    hoy = hoy or date.today()
    plan, problemas = {}, []
    actuales = reservas_de(pedido)
    necesidades = unidades_por_articulo(pedido)
    for clave, necesarias in necesidades.items():
        articulo, lotes = articulo_de(clave), actuales.get(clave, [])
        reservadas = sum(n for _l, n in lotes)
        if reservadas < necesarias and not faltan:
            pass
        elif reservadas < necesarias:
            problemas.append(_("%(producto)s: faltan %(n)s por asignar a un lote", producto=articulo.nombre,
                               n=necesarias - reservadas))
        elif reservadas > necesarias:
            problemas.append(_("%(producto)s: hay %(n)s reservadas de más", producto=articulo.nombre,
                               n=reservadas - necesarias))
        for lote, n in lotes:
            if lote.caducado(hoy):
                problemas.append(_("%(producto)s: el lote %(lote)s ha caducado", producto=articulo.nombre, lote=lote.codigo))
            elif lote.stock < n:
                problemas.append(_("%(producto)s: del lote %(lote)s solo hay %(hay)s y tiene %(n)s reservadas",
                                   producto=articulo.nombre, lote=lote.codigo, hay=lote.stock, n=n))
        hay = max(disponible(articulo, hoy), 0)     # (un lote antiguo en negativo resta del total)
        if reservadas > hay and not any(l.caducado(hoy) or l.stock < n for l, n in lotes):
            problemas.append(_("%(producto)s: hay %(hay)s, se necesitan %(necesarias)s",
                               producto=articulo.nombre, hay=hay, necesarias=reservadas))
        plan[clave] = lotes
    if set(actuales) - set(necesidades):
        problemas.append(_("Hay lotes reservados de artículos que el pedido ya no lleva"))
    # Y lo más importante: que lo reservado tenga la caducidad que el cliente aprobó
    if proforma is None:
        proforma = pedido.estado not in ("proforma_solicitada", "cambios_solicitados", "proforma_enviada")
    if proforma:
        from app.proformas.servicio import diferencias_con_la_aceptada
        problemas += diferencias_con_la_aceptada(pedido)
    return plan, problemas


def caducidades_reservadas(pedido, reparto=None):
    """Para la proforma: ({clave: caducidad más temprana de sus lotes}, {claves "a confirmar"}).
    reparto: {lote_id: unidades} a usar en vez de las reservas guardadas (la vista previa usa el
    sugerido). Un artículo sin todas sus unidades asignadas va "a confirmar"."""
    if reparto is None:
        reparto = {r.lote_id: r.cantidad for r in pedido.reservas}
    lotes = {l.id: l for l in db.session.scalars(db.select(Lote).where(Lote.id.in_(list(reparto))))} if reparto else {}
    por_clave = defaultdict(list)
    for lote_id, n in reparto.items():
        if n > 0 and lote_id in lotes:
            por_clave[_clave(lotes[lote_id])].append((lotes[lote_id], n))
    caducidad, a_confirmar = {}, set()
    for clave, necesarias in unidades_por_articulo(pedido).items():
        asignadas = por_clave.get(clave, [])
        if sum(n for _l, n in asignadas) < necesarias:
            a_confirmar.add(clave)
            continue
        fechas = [l.caducidad for l, _n in asignadas if l.caducidad]
        caducidad[clave] = min(fechas) if fechas else None
    return caducidad, a_confirmar


# --------------------------------------------------------------------------- #
# Cambios (sin commit: lo hace quien llama)
# --------------------------------------------------------------------------- #
def bloquear(pedido):
    _bloquear(unidades_por_articulo(pedido))


def _bloquear(necesidades):
    """Bloquea los artículos hasta el commit (PostgreSQL): dos personas reservando a la vez no
    pueden apartar las mismas unidades del mismo lote."""
    for tipo, modelo in (("producto", Producto), ("kit", Kit)):     # siempre en el mismo orden: sin interbloqueos
        ids = sorted(i for t, i in necesidades if t == tipo)
        if ids:
            db.session.execute(db.select(modelo.id).where(modelo.id.in_(ids)).order_by(modelo.id).with_for_update())


def guardar(pedido, reparto, solo_completar=False, hoy=None) -> list:
    """Deja las reservas del pedido como dice `reparto` ({lote_id: unidades}). Devuelve los
    errores (lista vacía = guardado). Reglas: lotes de artículos del pedido, sin caducar, sin
    pasarse de lo libre ni de lo que lleva el pedido. Se puede reservar MENOS de lo necesario
    (lo que falta queda "a confirmar"). solo_completar: lo ya reservado no se puede bajar ni
    quitar (el cliente aprobó esas caducidades); solo añadir.
    Un lote que el pedido YA tenía reservado se puede mantener aunque haya caducado o falten
    unidades (no se puede subir): eso se avisa al enviar, no impide guardar lo demás."""
    hoy = hoy or date.today()
    reparto = {int(k): int(v) for k, v in reparto.items() if int(v) > 0}
    necesidades = unidades_por_articulo(pedido)
    _bloquear(necesidades)
    actuales = {r.lote_id: r for r in pedido.reservas}
    errores, usados = [], set()
    if solo_completar:
        for lote_id, r in actuales.items():
            if reparto.get(lote_id, 0) < r.cantidad:
                errores.append(_("El lote %(lote)s ya está aprobado en la proforma: para cambiarlo hay que rehacer la proforma",
                                 lote=r.lote.codigo))
    for clave, necesarias in necesidades.items():
        articulo = articulo_de(clave)
        libres = {lote.id: (lote, libre) for lote, _hay, libre in lotes_libres(articulo, pedido, hoy)}
        total = 0
        for lote_id, n in reparto.items():
            ya = actuales.get(lote_id)
            if lote_id in libres:
                lote, libre = libres[lote_id]
            elif ya is not None and _clave(ya.lote) == clave:
                lote, libre = ya.lote, 0               # reservado de antes y ya caducado o sin unidades
            else:
                continue
            usados.add(lote_id)
            if n > max(libre, ya.cantidad if ya is not None else 0):
                errores.append(_("%(producto)s: del lote %(lote)s solo quedan %(libre)s libres y has puesto %(n)s",
                                 producto=articulo.nombre, lote=lote.codigo, libre=libre, n=n))
            total += n
        if total > necesarias:
            errores.append(_("%(producto)s: has repartido %(total)s entre los lotes y el pedido lleva %(necesarias)s",
                             producto=articulo.nombre, total=total, necesarias=necesarias))
    if set(reparto) - usados:
        errores.append(_("Has elegido un lote caducado o que no es de este pedido. Revisa el reparto."))
    if errores:
        return errores
    for lote_id, r in list(actuales.items()):
        if lote_id not in reparto:
            pedido.reservas.remove(r)
    quien = current_user.id if current_user and current_user.is_authenticated else None
    for lote_id, n in reparto.items():
        if lote_id in actuales:
            actuales[lote_id].cantidad = n
        else:
            pedido.reservas.append(ReservaLote(lote_id=lote_id, cantidad=n, usuario_id=quien))
    db.session.flush()
    return []


def normalizar(pedido, hoy=None):
    """Tras cambiar lo que lleva el pedido: quita las reservas de artículos que ya no lleva y,
    si sobran unidades, recorta empezando por el lote que caduca más tarde."""
    necesidades = unidades_por_articulo(pedido)
    por_clave = defaultdict(list)
    for r in list(pedido.reservas):
        por_clave[_clave(r.lote)].append(r)
    for clave, reservas in por_clave.items():
        sobra = sum(r.cantidad for r in reservas) - necesidades.get(clave, 0)
        for r in sorted(reservas, key=lambda r: _orden_fefo(r.lote), reverse=True):
            if sobra <= 0:
                break
            quita = min(r.cantidad, sobra)
            sobra -= quita
            if quita == r.cantidad:
                pedido.reservas.remove(r)
            else:
                r.cantidad -= quita
    db.session.flush()


def reservar_automatico(pedido, hoy=None, sin_caducados=False) -> list:
    """Completa la reserva con los lotes libres que caducan antes (lo ya reservado no se toca).
    sin_caducados=True: además sustituye lo reservado en lotes que han caducado entretanto."""
    normalizar(pedido, hoy)
    return guardar(pedido, reparto_sugerido(pedido, hoy, sin_caducados), hoy=hoy)


def tras_editar(pedido):
    """Llamar cuando cambian los kits/productos de un pedido: ajusta sus reservas. Un pedido
    sin proforma (creado por Yikon) se vuelve a completar solo; uno en proforma se completa al
    enviarla (así se ve antes en la ficha lo que se va a reservar)."""
    if pedido.estado not in ESTADOS_CON_RESERVA:
        return
    normalizar(pedido)
    if not pedido.con_proforma:
        guardar(pedido, reparto_sugerido(pedido, sin_caducados=True))


def liberar(pedido):
    """Suelta todos los lotes reservados del pedido."""
    for r in list(pedido.reservas):
        pedido.reservas.remove(r)
    db.session.flush()


def reservar_lo_enviado(pedido, enviados):
    """Al ANULAR un envío: las unidades vuelven a la oficina y quedan reservadas otra vez en
    los mismos lotes (siguen siendo los que aprobó el cliente). enviados = stock.lotes_enviados()."""
    liberar(pedido)
    for fila in enviados:
        if fila["lote"] is not None and fila["unidades"] > 0:
            pedido.reservas.append(ReservaLote(lote_id=fila["lote"].id, cantidad=fila["unidades"],
                                               usuario_id=current_user.id if current_user and current_user.is_authenticated else None))
    db.session.flush()


def pedidos_con_reserva():
    """Para Inventario → Reservas: qué pedidos retienen stock, el más antiguo primero.
    [{"pedido", "desde", "lineas": [(lote, unidades)], "unidades", "liberable"}]"""
    pedidos = db.session.scalars(db.select(Pedido).where(Pedido.id.in_(db.select(ReservaLote.pedido_id)))).all()
    filas = []
    for p in pedidos:
        reservas = sorted(p.reservas, key=lambda r: _orden_fefo(r.lote))
        desde = min(r.fecha for r in reservas)
        filas.append({"pedido": p, "desde": desde, "dias": (date.today() - desde.date()).days,
                      "lineas": [(r.lote, r.cantidad) for r in reservas],
                      "unidades": sum(r.cantidad for r in reservas), "liberable": se_puede_liberar(p)})
    return sorted(filas, key=lambda f: f["desde"])


def se_puede_liberar(pedido) -> bool:
    """A mano desde Inventario: proformas (aún sin aceptar) y pedidos sin proforma. Una proforma
    ACEPTADA no: el cliente ya aprobó esas fechas (se cancela el pedido o se rehace la proforma)."""
    return pedido.estado in ("proforma_solicitada", "proforma_enviada", "cambios_solicitados") or not pedido.con_proforma
