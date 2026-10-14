"""
Lógica del inventario de la oficina.

Regla principal: el stock baja cuando un pedido pasa a "enviado" (la mercancía sale
de la oficina) y vuelve a subir si ese envío se anula (el pedido vuelve a un estado
anterior o se cancela). "Entregado" no toca el stock: ya había salido al enviarse.

Todo cambio de stock es un MovimientoInventario; nunca se edita un número a mano.

Qué tiene stock ("artículos"):
  - Los KITS CERRADOS: llegan del fabricante como un paquete con una sola etiqueta de
    lote y caducidad. Al enviar un pedido sale el kit entero, de su lote.
  - Los PRODUCTOS con "controlar stock": los que se venden sueltos y los que forman
    los kits montados en la oficina (Kit.cerrado = False). Los servicios no llevan stock.
  Cada artículo se identifica con una "clave": ("kit", id) o ("producto", id).

Lotes y caducidad:
  - Cada entrada de mercancía es de un lote (código + caducidad, obligatorios).
  - El lote de cada pedido se decide ANTES de enviar: al preparar la proforma (el cliente
    aprueba esa caducidad) o al crear el pedido si lo crea Yikon. Quedan RESERVADOS para ese
    pedido (inventario/reservas.py) y al enviar salen exactamente esos. Por defecto se
    propone el que caduca antes: FEFO ("first expired, first out"). Los caducados no se
    reservan ni se envían nunca.
  - El movimiento de salida guarda el lote: así queda registrado qué lote se envió
    en cada pedido (lo ve Yikon (admin, logística, FAS), el cliente no).
  - Al anular un envío, cada unidad vuelve a SU lote.
"""
from collections import defaultdict
from datetime import date, timedelta

from flask import current_app
from flask_babel import gettext as _
from flask_login import current_user

from app.extensions import db
from app.models import Kit, Lote, MovimientoInventario, Pedido, Producto

# Estados en los que la mercancía YA ha salido de la oficina
ESTADOS_FUERA_DE_OFICINA = {"enviado", "entregado"}


# --------------------------------------------------------------------------- #
# Artículos: productos o kits cerrados
# --------------------------------------------------------------------------- #
def _clave_de_fila(producto_id, kit_id):
    return ("kit", kit_id) if kit_id is not None else ("producto", producto_id)


def articulo_de(clave):
    """("kit", 3) → Kit 3; ("producto", 5) → Producto 5."""
    tipo, id_ = clave
    return db.session.get(Kit if tipo == "kit" else Producto, id_)


def filtro_articulo(modelo, articulo):
    """Condición SQL "de este artículo" para Lote o MovimientoInventario."""
    if articulo.tipo_articulo == "kit":
        return modelo.kit_id == articulo.id
    return modelo.producto_id == articulo.id


# --------------------------------------------------------------------------- #
# Consultas de stock
# --------------------------------------------------------------------------- #
def stock_por_articulo() -> dict:
    """{clave: unidades} TOTALES (incluidos lotes caducados), en una sola consulta."""
    filas = db.session.execute(
        db.select(MovimientoInventario.producto_id, MovimientoInventario.kit_id,
                  db.func.sum(MovimientoInventario.cantidad))
        .group_by(MovimientoInventario.producto_id, MovimientoInventario.kit_id))
    return defaultdict(int, {_clave_de_fila(p, k): total for p, k, total in filas})


def lotes_con_stock(articulo=None, hoy=None) -> list:
    """
    [(lote, unidades), ...] de los lotes que tienen unidades, ordenados FEFO:
    primero el que caduca antes; los que no tienen fecha ("SIN LOTE"), al final.
    Incluye los caducados (quien llama decide qué hacer con ellos).
    """
    select = (db.select(Lote, db.func.sum(MovimientoInventario.cantidad))
              .join(MovimientoInventario, MovimientoInventario.lote_id == Lote.id)
              .group_by(Lote.id)
              .having(db.func.sum(MovimientoInventario.cantidad) > 0))
    if articulo is not None:
        select = select.where(filtro_articulo(Lote, articulo))
    filas = db.session.execute(select).all()
    # Ordenamos en Python: "sin fecha al final" no se escribe igual en SQLite y PostgreSQL
    return sorted(((lote, n) for lote, n in filas),
                  key=lambda f: (f[0].caducidad is None, f[0].caducidad or date.max, f[0].id))


def disponible_por_articulo(hoy=None) -> dict:
    """{clave: unidades que se pueden enviar} = stock menos lotes caducados."""
    hoy = hoy or date.today()
    total = stock_por_articulo()
    for lote, unidades in lotes_con_stock(hoy=hoy):
        if lote.caducado(hoy):
            total[_clave_de_fila(lote.producto_id, lote.kit_id)] -= unidades
    return total


def disponible(articulo, hoy=None) -> int:
    return disponible_por_articulo(hoy)[articulo.clave]


def caducado_por_articulo(hoy=None) -> dict:
    hoy = hoy or date.today()
    total = defaultdict(int)
    for lote, unidades in lotes_con_stock(hoy=hoy):
        if lote.caducado(hoy):
            total[_clave_de_fila(lote.producto_id, lote.kit_id)] += unidades
    return total


def productos_en_kits_cerrados(hoy=None) -> dict:
    """Unidades de cada producto que hay DENTRO de los kits cerrados en stock (sin caducados).
    Es un cálculo, no un stock aparte: el kit se sigue contando como kit (y sale entero al
    enviarlo); esto solo sirve para ver cuántas unidades de cada producto hay en total.
    {producto_id: [(kit, lote_del_kit, unidades_del_producto), ...]}"""
    hoy = hoy or date.today()
    resultado = defaultdict(list)
    for lote, kits in lotes_con_stock(hoy=hoy):
        if lote.kit_id is None or lote.caducado(hoy):
            continue
        kit = lote.kit
        if not (kit.activo and kit.cerrado):
            continue
        for c in kit.componentes:
            if c.producto.controlar_stock:
                resultado[c.producto_id].append((kit, lote, c.cantidad * kits))
    return resultado


def productos_solo_en_kits_cerrados() -> set:
    """Productos que solo se usan dentro de kits cerrados (ningún kit montado los usa).
    No avisan de "stock bajo" por estar a 0 (su stock es el del kit), salvo que se les
    haya puesto un mínimo."""
    en_cerrados, en_montados = set(), set()
    for kit in db.session.scalars(db.select(Kit).filter_by(activo=True)):
        for c in kit.componentes:
            (en_cerrados if kit.cerrado else en_montados).add(c.producto_id)
    return en_cerrados - en_montados


def articulos_con_stock_bajo(hoy=None) -> list:
    """[(artículo, libre), ...]: kits cerrados y productos por debajo de su mínimo.
    Se mira lo LIBRE (sin caducar y sin reservar para pedidos): lo reservado ya tiene dueño."""
    from app.inventario.reservas import reservado_por_articulo
    disp = disponible_por_articulo(hoy)
    for clave, n in reservado_por_articulo().items():
        disp[clave] -= n
    solo_en_kits = productos_solo_en_kits_cerrados()
    bajos = [(k, disp[k.clave]) for k in db.session.scalars(
        db.select(Kit).filter_by(activo=True, cerrado=True).order_by(Kit.nombre))
        if disp[k.clave] <= k.stock_minimo]
    # Productos: cuentan los sueltos + los que hay dentro de kits cerrados
    en_kits = {pid: sum(n for _k, _l, n in filas) for pid, filas in productos_en_kits_cerrados(hoy).items()}
    for p in db.session.scalars(
            db.select(Producto).filter_by(activo=True, controlar_stock=True).order_by(Producto.nombre)):
        total = disp[p.clave] + en_kits.get(p.id, 0)
        if total <= p.stock_minimo and (p.id not in solo_en_kits or p.stock_minimo > 0):
            bajos.append((p, total))
    return bajos


def avisos_caducidad(hoy=None) -> list:
    """Lotes con stock caducados o que caducan en los próximos DIAS_AVISO_CADUCIDAD días.
    [{lote, unidades, dias}, ...] (dias < 0 = ya caducado), los más urgentes primero."""
    hoy = hoy or date.today()
    limite = hoy + timedelta(days=current_app.config.get("DIAS_AVISO_CADUCIDAD", 7))
    return [{"lote": lote, "unidades": n, "dias": lote.dias_para_caducar(hoy)}
            for lote, n in lotes_con_stock(hoy=hoy)
            if lote.caducidad is not None and lote.caducidad <= limite
            and lote.articulo.activo and lote.articulo.lleva_stock]


def registrar_movimiento(articulo, cantidad, tipo, nota=None, pedido=None, lote=None):
    datos = {"kit": articulo} if articulo.tipo_articulo == "kit" else {"producto": articulo}
    mov = MovimientoInventario(
        **datos, cantidad=cantidad, tipo=tipo, nota=nota, pedido=pedido, lote=lote,
        usuario_id=current_user.id if current_user and current_user.is_authenticated else None,
    )
    db.session.add(mov)
    return mov


def buscar_lote(articulo, codigo):
    return db.session.scalar(db.select(Lote).where(filtro_articulo(Lote, articulo), Lote.codigo == codigo))


def buscar_o_crear_lote(articulo, codigo, caducidad):
    """Para una entrada: si el lote ya existe (mismo artículo y código) se reutiliza."""
    lote = buscar_lote(articulo, codigo)
    if lote is None:
        datos = {"kit": articulo} if articulo.tipo_articulo == "kit" else {"producto": articulo}
        lote = Lote(**datos, codigo=codigo, caducidad=caducidad)
        db.session.add(lote)
    return lote


# --------------------------------------------------------------------------- #
# Envío de pedidos
# --------------------------------------------------------------------------- #
def unidades_por_articulo(pedido) -> dict:
    """Qué sale del almacén con este pedido: {clave: unidades}.
    - Un kit CERRADO sale entero (tantos kits como pida); sus productos no se tocan.
    - Los productos de un kit montado y los sueltos salen de su propio stock.
    - Los servicios no mueven inventario. Dos líneas del mismo artículo se suman."""
    total = defaultdict(int)
    for kp in pedido.kits:
        if kp.kit.cerrado:
            total[kp.kit.clave] += kp.cantidad
    for linea in pedido.lineas:
        kp = linea.kit_pedido
        if kp is not None and kp.kit.cerrado:
            continue
        if linea.producto.controlar_stock:
            total[linea.producto.clave] += linea.cantidad
    return total


def plan_de_salida(pedido, hoy=None, bloquear=False):
    """
    De qué lotes saldría cada artículo del pedido (FEFO, sin caducados).
    Devuelve (plan, faltan):
      plan  = {clave: [(lote, unidades), ...]}
      faltan = textos con lo que no alcanza, p. ej. ['PGT-A completo: hay 2, se necesitan 5']
    """
    hoy = hoy or date.today()
    plan, faltan = {}, []
    necesidades = unidades_por_articulo(pedido)
    if bloquear and necesidades:
        # Bloquea las filas de estos artículos hasta el commit (en PostgreSQL; SQLite ya
        # hace las escrituras de una en una): dos pedidos que se envían A LA VEZ no
        # pueden sacar las mismas unidades del mismo lote.
        for tipo, modelo in (("producto", Producto), ("kit", Kit)):
            ids = [i for t, i in necesidades if t == tipo]
            if ids:
                db.session.execute(db.select(modelo.id).where(modelo.id.in_(ids)).with_for_update())
    disp = disponible_por_articulo(hoy)
    for clave, necesarias in necesidades.items():
        articulo = articulo_de(clave)
        lotes = lotes_con_stock(articulo, hoy)
        validos = [(l, n) for l, n in lotes if not l.caducado(hoy)]
        caducadas = sum(n for l, n in lotes if l.caducado(hoy))
        # Nunca más de lo que hay en total sin caducar: si algún lote quedó en negativo
        # (ajustes antiguos), no aparece en `validos` pero sí resta aquí
        hay = min(sum(n for _l, n in validos), max(disp[clave], 0))
        if hay < necesarias:
            if caducadas:
                faltan.append(_("%(producto)s: hay %(hay)s sin caducar (y %(caducadas)s caducadas), se necesitan %(necesarias)s",
                                producto=articulo.nombre, hay=hay, caducadas=caducadas, necesarias=necesarias))
            else:
                faltan.append(_("%(producto)s: hay %(hay)s, se necesitan %(necesarias)s",
                                producto=articulo.nombre, hay=hay, necesarias=necesarias))
            continue
        reparto, pendiente = [], necesarias
        for lote, n in validos:              # FEFO: el que caduca antes, primero
            toma = min(n, pendiente)
            reparto.append((lote, toma))
            pendiente -= toma
            if pendiente == 0:
                break
        plan[clave] = reparto
    return plan, faltan


def sale_de_oficina(estado_anterior, estado_nuevo) -> bool:
    """¿Este cambio de estado hace que la mercancía salga (y se reste del stock)?"""
    return (estado_anterior not in ESTADOS_FUERA_DE_OFICINA
            and estado_nuevo in ESTADOS_FUERA_DE_OFICINA)


def resumen_salida(pedido) -> list:
    """
    Lo que se restaría del stock si se envía este pedido, para enseñarlo antes de confirmar:
    [{articulo, unidades, stock, restante, lotes, reservadas, suficiente}], donde `stock` es
    lo que hay sin caducar y `lotes` = [(lote, unidades)] RESERVADOS para este pedido (son
    los que salen). `suficiente` = está reservado entero. Lista vacía si el pedido no lleva
    nada con control de stock (solo servicios).
    """
    from app.inventario.reservas import reservas_de
    disp = disponible_por_articulo()
    reservado = reservas_de(pedido)
    filas = []
    for clave, unidades in unidades_por_articulo(pedido).items():
        lotes = reservado.get(clave, [])
        reservadas = sum(n for _l, n in lotes)
        filas.append({"articulo": articulo_de(clave), "clave": f"{clave[0]}-{clave[1]}", "unidades": unidades,
                      "stock": disp[clave], "restante": disp[clave] - unidades, "lotes": lotes,
                      "reservadas": reservadas, "suficiente": reservadas == unidades})
    return filas


def lotes_enviados(pedido) -> list:
    """Qué lotes salieron con este pedido (neto: si se anuló y reenvió, cuenta lo último).
    [{articulo, lote, unidades}, ...]. Solo para uso interno (el cliente no lo ve)."""
    filas = db.session.execute(
        db.select(MovimientoInventario.producto_id, MovimientoInventario.kit_id, MovimientoInventario.lote_id,
                  db.func.sum(MovimientoInventario.cantidad))
        .where(MovimientoInventario.pedido_id == pedido.id)
        .group_by(MovimientoInventario.producto_id, MovimientoInventario.kit_id, MovimientoInventario.lote_id))
    return [{"articulo": articulo_de(_clave_de_fila(pid, kid)),
             "lote": db.session.get(Lote, lid) if lid else None, "unidades": -neto}
            for pid, kid, lid, neto in filas if neto < 0]


def aplicar_cambio_de_estado(pedido, estado_anterior, estado_nuevo):
    """
    Llamar ANTES de cambiar pedido.estado. Crea los movimientos que tocan, ajusta las
    reservas de lote y devuelve la lista de problemas (vacía si todo bien). Si hay
    problemas, no se crea nada y quien llama no debe cambiar el estado.

      - Sale de la oficina (→ enviado): salen los lotes RESERVADOS del pedido, ni uno más ni
        uno distinto. La reserva desaparece: se ha convertido en la salida de stock.
      - Se anula el envío: cada unidad vuelve a su lote y queda reservada otra vez.
      - Se cancela: se devuelve lo enviado (si había salido) y se liberan las reservas.
      - Se reabre un pedido cancelado creado por Yikon: se vuelve a reservar solo (FEFO).
    """
    from app.inventario import reservas
    sale = sale_de_oficina(estado_anterior, estado_nuevo)
    vuelve = (estado_anterior in ESTADOS_FUERA_DE_OFICINA
              and estado_nuevo not in ESTADOS_FUERA_DE_OFICINA)

    if sale:
        reservas.bloquear(pedido)
        plan, problemas = reservas.plan_reservado(pedido, proforma=True)
        if problemas:
            return problemas
        for clave, lotes in plan.items():
            articulo = articulo_de(clave)
            for lote, unidades in lotes:
                registrar_movimiento(articulo, -unidades, "salida_pedido", pedido=pedido, lote=lote,
                                     nota=f"Envío {pedido.referencia_interna}")
        reservas.liberar(pedido)
    elif vuelve:
        # Se devuelve lo que REALMENTE salió con este pedido, a su mismo lote (según
        # sus movimientos), no lo que dirían hoy sus líneas: si entretanto se cambió
        # "controlar stock" o "kit cerrado", recalcularlo descuadraría el inventario.
        enviados = lotes_enviados(pedido)
        for fila in enviados:
            registrar_movimiento(fila["articulo"], fila["unidades"], "devolucion_pedido",
                                 pedido=pedido, lote=fila["lote"],
                                 nota=f"{pedido.referencia_interna}: {estado_anterior} → {estado_nuevo}")
        if estado_nuevo != "cancelado":
            reservas.reservar_lo_enviado(pedido, enviados)
    if estado_nuevo == "cancelado":
        reservas.liberar(pedido)
    elif estado_anterior == "cancelado" and not sale and not pedido.con_proforma:
        reservas.reservar_automatico(pedido)
    return []


def pedidos_con_kit_fuera(kit) -> list:
    """Referencias de los pedidos que tienen unidades de este kit cerrado enviadas y sin
    anular. Si el envío se anulara, esas unidades volverían al lote del kit: por eso un
    kit así no puede pasar a "montado" (ese stock quedaría escondido)."""
    filas = db.session.execute(
        db.select(MovimientoInventario.pedido_id)
        .where(MovimientoInventario.kit_id == kit.id, MovimientoInventario.pedido_id.is_not(None))
        .group_by(MovimientoInventario.pedido_id)
        .having(db.func.sum(MovimientoInventario.cantidad) < 0)).scalars().all()
    return [db.session.get(Pedido, pid).referencia_interna or f"#{pid}" for pid in filas]


# --------------------------------------------------------------------------- #
# Abrir un kit cerrado (sacar sus productos para venderlos o reponer sueltos)
# --------------------------------------------------------------------------- #
def abrir_kit(kit, lote, cantidad=1, motivo=None):
    """
    Resta `cantidad` kits del lote y suma sus productos como stock suelto, con el
    MISMO código de lote y caducidad (es lo que pone la etiqueta del kit).
    Solo los productos con "controlar stock" (los servicios no son mercancía).
    Devuelve un texto de error, o None si ha ido bien (sin commit).
    """
    if not kit.cerrado or lote.kit_id != kit.id:
        return _("Ese lote no es de este kit.")
    if cantidad < 1:
        return _("Indica cuántos kits abres.")
    # Bloquea el kit hasta el commit (PostgreSQL): dos aperturas a la vez no pueden
    # sacar el mismo kit del mismo lote (igual que en los envíos)
    db.session.execute(db.select(Kit.id).where(Kit.id == kit.id).with_for_update())
    if lote.stock < cantidad:
        return _("El lote %(lote)s solo tiene %(n)s kits.", lote=lote.codigo, n=lote.stock)
    from app.inventario.reservas import error_si_toca_reservas
    if error := error_si_toca_reservas(lote, lote.stock - cantidad):   # kits apartados para un pedido
        return error
    componentes = [c for c in kit.componentes if c.producto.controlar_stock]
    if not componentes:
        return _("Este kit no tiene productos con control de stock.")
    for c in componentes:
        existente = buscar_lote(c.producto, lote.codigo)
        if existente is not None and existente.caducidad != lote.caducidad:
            return _("%(producto)s ya tiene un lote %(lote)s con otra caducidad. Revísalo en Corregir.",
                     producto=c.producto.nombre, lote=lote.codigo)
    nota = f"Apertura de {cantidad} × {kit.referencia} (lote {lote.codigo})" + (f": {motivo}" if motivo else "")
    nota = nota[:250]
    registrar_movimiento(kit, -cantidad, "apertura_kit", lote=lote, nota=nota)
    for c in componentes:
        lote_producto = buscar_o_crear_lote(c.producto, lote.codigo, lote.caducidad)
        registrar_movimiento(c.producto, c.cantidad * cantidad, "apertura_kit", lote=lote_producto, nota=nota)
    return None
