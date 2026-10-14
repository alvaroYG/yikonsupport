"""
Proformas: qué lleva cada una y cómo se numera.

La proforma es una foto fija del pedido al enviarla: productos (agrupados por kit),
cantidades y la CADUCIDAD de cada producto, que es la de los LOTES RESERVADOS para ese
pedido (inventario/reservas.py). Por eso el lote se decide antes de enviarla: lo que el
cliente aprueba es lo que va a recibir. Si no hay stock libre para algún producto, sale
"a confirmar". Si luego cambian el pedido o el stock, la proforma enviada no cambia.
"""
from datetime import date
from types import SimpleNamespace

from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError

from app import archivos
from app.extensions import db
from app.inventario import reservas
from app.models import Proforma, ProformaLinea


def caducidades_previstas(pedido, previa=True):
    """({clave: caducidad}, {claves "a confirmar"}) de cada artículo (kit cerrado o producto).
    previa=True (vista previa en la ficha): con lo que se reservaría si se enviara ahora =
    lo ya elegido + los lotes libres que caducan antes para lo que falte.
    previa=False (al guardar la proforma): solo con lo que YA está reservado."""
    return reservas.caducidades_reservadas(
        pedido, reservas.reparto_sugerido(pedido, sin_caducados=True) if previa else None)


def lineas_previstas(pedido, previa=True):
    """Lo que saldría en la proforma si se enviara ahora (también para la vista previa):
    [{"grupo", "producto", "cantidad", "caducidad", "sin_stock", "sin_control", "clave"}], primero
    los kits (cada uno con sus productos) y después los productos sueltos.

    En un kit CERRADO todos sus productos llevan la caducidad del kit (la de su etiqueta),
    salvo los servicios;
    en un kit montado y en los sueltos, la de cada producto."""
    caducidad, sin_stock = caducidades_previstas(pedido, previa)
    filas = []

    def fila(grupo, linea, clave, controla):
        filas.append({"grupo": grupo, "producto": linea.producto, "cantidad": linea.cantidad,
                      "caducidad": caducidad.get(clave), "sin_stock": clave in sin_stock,
                      "sin_control": not controla, "clave": clave})

    for kp in pedido.kits:
        grupo = f"{kp.cantidad} × {kp.kit.nombre}"
        for linea in kp.lineas:
            if kp.kit.cerrado and linea.producto.controlar_stock:   # (un servicio no caduca)
                fila(grupo, linea, kp.kit.clave, True)
            else:
                fila(grupo, linea, linea.producto.clave, linea.producto.controlar_stock)
    for linea in pedido.lineas_sueltas:
        fila(None, linea, linea.producto.clave, linea.producto.controlar_stock)
    return filas


def proforma_aceptada(pedido):
    """La última proforma que el cliente aceptó (None si no ha aceptado ninguna)."""
    return next((pf for pf in pedido.proformas if pf.estado == "aceptada"), None)


def _aprobado_por_clave(pedido):
    """{clave: caducidad aprobada} según la proforma aceptada, o None si el pedido ya no lleva
    lo mismo que esa proforma. Solo los artículos que salieron CON fecha (los "a confirmar" y
    los servicios no comprometen ninguna)."""
    aceptada = proforma_aceptada(pedido)
    if aceptada is None:
        return {}
    ahora_lleva = lineas_previstas(pedido, previa=False)
    if [(f["producto"].referencia, f["cantidad"]) for f in ahora_lleva] != [(l.referencia, l.cantidad) for l in aceptada.lineas]:
        return None
    return {f["clave"]: l.caducidad for f, l in zip(ahora_lleva, aceptada.lineas) if l.caducidad is not None}


def diferencias_con_la_aceptada(pedido) -> list:
    """Textos con lo que NO coincide entre los lotes reservados y la proforma que aceptó el
    cliente (lista vacía = todo coincide, o el pedido no tiene proforma aceptada). Es lo que
    impide enviar un lote con otra caducidad sin rehacer la proforma, pase lo que pase por el
    camino: lote corregido en Inventario, cambio de estado forzado, reserva liberada…"""
    if not pedido.con_proforma:
        return []
    aprobado = _aprobado_por_clave(pedido)
    if aprobado is None:
        return [_("El pedido ya no lleva lo mismo que la proforma que aceptó el cliente: rehaz la proforma")]
    reservado, _a_confirmar = reservas.caducidades_reservadas(pedido)
    difieren = []
    for clave, fecha in aprobado.items():
        if clave in reservado and reservado[clave] != fecha:
            difieren.append(_("%(producto)s: el cliente aprobó caducidad %(aprobada)s y el lote reservado caduca el "
                              "%(reservada)s (para enviar otro lote hay que rehacer la proforma)",
                              producto=reservas.articulo_de(clave).nombre, aprobada=fecha.strftime("%d/%m/%Y"),
                              reservada=reservado[clave].strftime("%d/%m/%Y") if reservado[clave] else "—"))
    return difieren


def reservar_como_la_proforma(pedido) -> list:
    """Para la puesta en marcha (flask reservar-pendientes): un pedido con la proforma ya
    aceptada y sin lotes reservados. Reserva, de cada artículo, primero los lotes libres que
    tienen LA CADUCIDAD QUE APROBÓ EL CLIENTE y, si no alcanzan, los que caducan antes."""
    aprobado = _aprobado_por_clave(pedido) or {}
    reservas.normalizar(pedido)
    reparto = {r.lote_id: r.cantidad for r in pedido.reservas}
    ya = reservas.reservas_de(pedido)
    for clave, necesarias in reservas.unidades_por_articulo(pedido).items():
        pendiente = necesarias - sum(n for _l, n in ya.get(clave, []))
        libres = reservas.lotes_libres(reservas.articulo_de(clave), pedido)
        libres.sort(key=lambda f: f[0].caducidad != aprobado.get(clave))      # (orden estable: después, FEFO)
        for lote, _hay, libre in libres:
            toma = min(libre - reparto.get(lote.id, 0), pendiente)
            if toma > 0:
                reparto[lote.id] = reparto.get(lote.id, 0) + toma
                pendiente -= toma
    return reservas.guardar(pedido, reparto)


def numero_para(pedido, version):
    """PF-{referencia interna del pedido}: PF-YK-2026-Nuuma-009. Las siguientes versiones
    llevan -v2, -v3… (PF-YK-2026-Nuuma-009-v2). Sin referencia (no debería pasar): PF-{id}."""
    numero = f"PF-{pedido.referencia_interna or pedido.id}"
    return numero if version == 1 else f"{numero}-v{version}"


def crear_proforma(pedido, usuario, valida_hasta, plazo_entrega=None, notas=None, pdf=None) -> Proforma:
    """Reserva los lotes y guarda la proforma con su foto fija (sin commit). La anterior, si
    seguía pendiente, queda como "retirada" (solo vale la última).

    Lotes: se respeta lo que se haya elegido en la ficha y lo que falte se completa con los
    lotes libres que caducan antes. Lo que no tenga stock libre va "a confirmar".

    pdf: (nombre, extensión, bytes) del PDF que ha hecho Yikon; es el que descargará el cliente.

    Numeración (numero_para): si dos personas envían a la vez una proforma del mismo pedido,
    las dos calculan la misma versión y la base de datos rechaza la segunda (número único).
    En ese caso se deshace solo ese intento (savepoint) y se prueba con la versión siguiente."""
    reservas.reservar_automatico(pedido, sin_caducados=True)   # (un lote elegido que haya caducado se sustituye)
    previstas = lineas_previstas(pedido, previa=False)   # con lo que ha quedado reservado de verdad
    version = len(pedido.proformas) + 1
    for anterior in pedido.proformas:
        if anterior.estado == "enviada":
            anterior.estado = "retirada"
    for intento in range(5):
        proforma = Proforma(numero=numero_para(pedido, version + intento), pedido_id=pedido.id,
                            version=version + intento, valida_hasta=valida_hasta,
                            plazo_entrega=plazo_entrega or None, notas=notas or None, creada_por=usuario)
        try:
            with db.session.begin_nested():
                db.session.add(proforma)
                db.session.flush()
            break
        except IntegrityError:
            continue
    else:
        raise RuntimeError("No se ha podido numerar la proforma")
    if pdf:
        nombre, ext, datos = pdf
        proforma.pdf_archivo = archivos.escribir(datos, "proforma", ext)
        proforma.pdf_nombre, proforma.pdf_tamano = nombre, len(datos)
    db.session.expire(pedido, ["proformas"])   # que pedido.proformas la incluya ya (la primera)
    for orden, f in enumerate(previstas):
        p = f["producto"]
        proforma.lineas.append(ProformaLinea(
            orden=orden, grupo=f["grupo"], referencia=p.referencia, nombre=p.nombre, marca=p.categoria,
            cantidad=f["cantidad"], caducidad=f["caducidad"], sin_stock=f["sin_stock"]))
    return proforma


def modelo_previo(pedido, valida_hasta, plazo_entrega=None, notas=None):
    """Una proforma "de mentira" (no se guarda) con lo que saldría si se enviara ahora, para
    descargar el modelo en PDF y hacer la de verdad a partir de él."""
    from app.models import ahora
    version = len(pedido.proformas) + 1
    lineas = [SimpleNamespace(grupo=f["grupo"], referencia=f["producto"].referencia, nombre=f["producto"].nombre,
                              marca=f["producto"].categoria, cantidad=f["cantidad"], caducidad=f["caducidad"],
                              sin_stock=f["sin_stock"])
              for f in lineas_previstas(pedido, previa=True)]
    return SimpleNamespace(pedido=pedido, numero=numero_para(pedido, version), version=version,
                           numero_y_version=numero_para(pedido, version), fecha=ahora(),
                           valida_hasta=valida_hasta, plazo_entrega=plazo_entrega, notas=notas, lineas=lineas)
