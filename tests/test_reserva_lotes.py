"""
Reserva de lotes por pedido (app/inventario/reservas.py).

El lote se decide ANTES de enviar: al preparar la proforma (el cliente aprueba esa caducidad)
o al crear el pedido si lo crea Yikon. Queda reservado para ese pedido y al enviar salen
exactamente esos lotes. Escenario: P1 con dos lotes de 5 uds., PRONTO (caduca antes) y LEJANO.
"""
from datetime import date, timedelta

from app.extensions import db
from app.inventario import reservas
from app.inventario.stock import articulos_con_stock_bajo
from app.models import Lote, MovimientoInventario, Pedido, Producto, RegistroAuditoria, ReservaLote
from tests.conftest import doc_pedido, contenido, llevar_a_validado, login, pedido_cliente, pdf_proforma

F_PRONTO = date.today() + timedelta(days=30)
F_LEJANO = date.today() + timedelta(days=400)


def _salir(client):
    client.post("/auth/logout")


def _entrada(client, cantidad, lote, caducidad, articulo="producto-1"):
    client.post("/inventario/movimiento", data={"articulo": articulo, "tipo": "entrada", "cantidad": cantidad,
                                                "lote": lote, "caducidad": caducidad.isoformat()})


def _dos_lotes(client):
    login(client, "admin")
    _entrada(client, 5, "PRONTO", F_PRONTO); _entrada(client, 5, "LEJANO", F_LEJANO)
    _salir(client)


def _lote(codigo):
    return db.session.scalar(db.select(Lote).filter_by(codigo=codigo))


def _reservado(p):
    """{código de lote: unidades} reservadas para el pedido (leído de la base de datos)."""
    return {r.lote.codigo: r.cantidad for r in db.session.scalars(db.select(ReservaLote).filter_by(pedido_id=p.id))}


def _ultimo():
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _pedido_yikon(client, cantidad=3, usuario="admin"):
    """Pedido creado por Yikon (sin proforma): nace "aceptado"."""
    login(client, usuario)
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25", "referencia": f"OC-{cantidad}-{usuario}",
                                        "contenido": contenido(sueltos={1: cantidad})})
    return _ultimo()


def _proforma_pedida(client, cantidad=3):
    """Pedido del cliente en "proforma solicitada"."""
    login(client, "cliA"); pedido_cliente(client, cantidad=cantidad, con_proforma=True); _salir(client)
    return _ultimo()


def _enviar_proforma(client, p):
    return client.post(f"/pedidos/{p.id}/proforma/enviar", follow_redirects=True, data={
        "valida_hasta": (date.today() + timedelta(days=30)).isoformat(), "plazo_entrega": "5 días",
        "pdf": pdf_proforma()})


def _lotes(client, p, **unidades):
    return client.post(f"/pedidos/{p.id}/lotes", data={f"lote-{_lote(c).id}": n for c, n in unidades.items()},
                       follow_redirects=True)


def _enviar(client, p, **extra):
    datos = {"estado": "enviado", "confirmar_stock": "1", "transportista": "SEUR", "numero_seguimiento": "T1"}
    datos.update(extra)
    return client.post(f"/pedidos/{p.id}/estado", data=datos, follow_redirects=True)


def _hasta_validado(client, p):
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); _salir(client)
    llevar_a_validado(client, p.id)
    login(client, "admin")


def _salidas(p):
    return {m.lote.codigo: m.cantidad for m in db.session.scalars(
        db.select(MovimientoInventario).filter_by(pedido_id=p.id, tipo="salida_pedido"))}


# --------------------------------------------------------------------------- #
# Pedido creado por Yikon: se reserva al crearlo
# --------------------------------------------------------------------------- #
def test_pedido_de_yikon_reserva_al_crearlo_el_lote_que_caduca_antes(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3)
    assert p.estado == "aceptado" and _reservado(p) == {"PRONTO": 3}
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Lotes de este pedido" in html and "Todo reservado" in html
    assert f'name="lote-{_lote("PRONTO").id}"' in html and f'name="lote-{_lote("LEJANO").id}"' in html


def test_lo_reservado_no_esta_libre_para_otro_pedido(app, client):
    _dos_lotes(client)
    a = _pedido_yikon(client, 4)                       # se lleva 4 de PRONTO
    b = _pedido_yikon(client, 3, usuario="fac")        # solo queda 1 libre de PRONTO: el resto, de LEJANO
    assert _reservado(a) == {"PRONTO": 4} and _reservado(b) == {"PRONTO": 1, "LEJANO": 2}
    # y a mano tampoco se puede coger lo de otro pedido
    r = _lotes(client, b, PRONTO=3)
    assert "del lote PRONTO solo quedan 1 libres y has puesto 3" in r.get_data(as_text=True)
    assert _reservado(b) == {"PRONTO": 1, "LEJANO": 2}


def test_en_un_pedido_de_yikon_se_puede_cambiar_el_lote_hasta_enviarlo(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3)
    _lotes(client, p, PRONTO=1, LEJANO=2)
    assert _reservado(p) == {"PRONTO": 1, "LEJANO": 2}
    assert db.session.scalar(db.select(db.func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.detalle.like("%lotes reservados: PRONTO×1, LEJANO×2%"))) == 1
    _salir(client)
    _hasta_validado(client, p)
    _enviar(client, p)
    assert db.session.get(Pedido, p.id).estado == "enviado" and _salidas(p) == {"PRONTO": -1, "LEJANO": -2}
    assert _reservado(p) == {}                         # la reserva se ha convertido en la salida


def test_al_cambiar_lo_que_lleva_el_pedido_se_ajusta_la_reserva(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 7)
    assert _reservado(p) == {"PRONTO": 5, "LEJANO": 2}
    linea = p.lineas[0]
    client.post(f"/pedidos/{p.id}/guardar", data={f"cantidad_linea_{linea.id}": "4"})
    assert _reservado(p) == {"PRONTO": 4}              # se suelta primero lo que caduca más tarde
    client.post(f"/pedidos/{p.id}/guardar", data={f"cantidad_linea_{linea.id}": "6"})
    assert _reservado(p) == {"PRONTO": 5, "LEJANO": 1}
    client.post(f"/pedidos/{p.id}/lineas/{linea.id}/borrar")
    assert _reservado(p) == {}


# --------------------------------------------------------------------------- #
# Pedido del cliente: el lote se elige al preparar la proforma
# --------------------------------------------------------------------------- #
def test_la_proforma_lleva_la_caducidad_del_lote_elegido_y_lo_reserva(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    assert _reservado(p) == {}                         # al pedirla todavía no se reserva nada
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Propuesta sin guardar" in html and F_PRONTO.strftime("%d/%m/%Y") in html     # vista previa: FEFO
    _lotes(client, p, PRONTO=0, LEJANO=3)              # Yikon decide que saldrá el otro lote
    assert _reservado(p) == {"LEJANO": 3}
    _enviar_proforma(client, p)
    db.session.refresh(p)
    assert p.estado == "proforma_enviada" and [l.caducidad for l in p.proforma_actual.lineas] == [F_LEJANO]
    assert _reservado(p) == {"LEJANO": 3}


def test_si_no_se_elige_nada_la_proforma_reserva_el_que_caduca_antes(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _enviar_proforma(client, p)
    db.session.refresh(p)
    assert _reservado(p) == {"PRONTO": 3} and p.proforma_actual.lineas[0].caducidad == F_PRONTO


def test_lo_aprobado_en_la_proforma_no_se_puede_cambiar_sin_rehacerla(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _enviar_proforma(client, p); _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    login(client, "admin")
    assert db.session.get(Pedido, p.id).estado == "aceptado"
    r = _lotes(client, p, PRONTO=0, LEJANO=3)
    assert "El lote PRONTO ya está aprobado en la proforma" in r.get_data(as_text=True)
    assert _reservado(p) == {"PRONTO": 3}
    # rehaciendo la proforma (Aceptado → Proforma solicitada) sí se puede elegir otro
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "proforma_solicitada"})
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"
    _lotes(client, p, PRONTO=0, LEJANO=3)
    assert _reservado(p) == {"LEJANO": 3}


def test_sin_stock_la_proforma_va_a_confirmar_y_el_lote_se_asigna_despues(app, client):
    login(client, "admin"); _entrada(client, 1, "PRONTO", F_PRONTO); _salir(client)
    p = _proforma_pedida(client, cantidad=3)           # pide 3 y solo hay 1
    login(client, "loga")
    assert "a confirmar (sin stock libre)" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    _enviar_proforma(client, p)
    db.session.refresh(p)
    linea = p.proforma_actual.lineas[0]
    assert linea.sin_stock and linea.caducidad is None            # el cliente ve "a confirmar"
    assert _reservado(p) == {"PRONTO": 1}                         # lo que había queda reservado igualmente
    _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    _hasta_validado(client, p)
    r = _enviar(client, p)
    assert "No se puede enviar: Kit 1: faltan 2 por asignar a un lote" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "validado"
    # llega la mercancía: se asigna lo que faltaba (lo ya aprobado no se toca) y ya se puede enviar
    _entrada(client, 5, "LEJANO", F_LEJANO)
    r = _lotes(client, p, PRONTO=1, LEJANO=2)
    assert "comunica al cliente la fecha definitiva" in r.get_data(as_text=True)
    assert _reservado(p) == {"PRONTO": 1, "LEJANO": 2}
    _enviar(client, p)
    assert db.session.get(Pedido, p.id).estado == "enviado" and _salidas(p) == {"PRONTO": -1, "LEJANO": -2}


# --------------------------------------------------------------------------- #
# Envío estricto
# --------------------------------------------------------------------------- #
def test_al_enviar_salen_los_reservados_aunque_el_formulario_pida_otro_lote(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3); _salir(client)
    _hasta_validado(client, p)
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    ventana = html.split('id="modal-stock"')[1].split('class="modal-footer"')[0]
    assert "PRONTO" in ventana and "LEJANO" not in ventana and "<input" not in ventana    # solo lectura
    _enviar(client, p, **{f"lote-{_lote('LEJANO').id}": "3", f"lote-{_lote('PRONTO').id}": "0"})
    assert _salidas(p) == {"PRONTO": -3}
    assert _lote("PRONTO").stock == 2 and _lote("LEJANO").stock == 5


def test_si_el_lote_reservado_caduca_no_se_envia(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3); _salir(client)
    _hasta_validado(client, p)
    _lote("PRONTO").caducidad = date.today() - timedelta(days=1); db.session.commit()
    r = _enviar(client, p)
    assert "Kit 1: el lote PRONTO ha caducado" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "validado" and _salidas(p) == {}


def test_anular_el_envio_vuelve_a_reservar_y_cancelar_libera(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3); _lotes(client, p, PRONTO=0, LEJANO=3); _salir(client)
    _hasta_validado(client, p)
    _enviar(client, p)
    assert _lote("LEJANO").stock == 2 and _reservado(p) == {}
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "validado"})          # anular el envío
    assert _lote("LEJANO").stock == 5 and _reservado(p) == {"LEJANO": 3}
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "cancelado"})
    assert db.session.get(Pedido, p.id).estado == "cancelado" and _reservado(p) == {}
    # reabierto (pedido sin proforma): se vuelve a reservar solo, el que caduca antes
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "aceptado"})
    assert _reservado(p) == {"PRONTO": 3}


# --------------------------------------------------------------------------- #
# Inventario: reservado / libre y liberar a mano
# --------------------------------------------------------------------------- #
def test_inventario_muestra_lo_reservado_y_el_stock_bajo_mira_lo_libre(app, client):
    _dos_lotes(client)
    db.session.get(Producto, 1).stock_minimo = 4; db.session.commit()
    assert articulos_con_stock_bajo() == []                       # 10 libres
    p = _pedido_yikon(client, 7)
    assert [(a.referencia, libre) for a, libre in articulos_con_stock_bajo()] == [("P1", 3)]   # hay 10, libres 3
    html = client.get("/inventario/").get_data(as_text=True)
    assert "7 reservadas · 3 libres" in html
    html = client.get("/inventario/reservas").get_data(as_text=True)
    assert p.referencia_interna in html and "PRONTO" in html and "LEJANO" in html


def test_no_se_puede_ajustar_a_la_baja_lo_reservado(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 4)
    r = client.post("/inventario/movimiento", follow_redirects=True, data={
        "articulo": "producto-1", "tipo": "ajuste", "cantidad": -2, "lote": "PRONTO", "nota": "rotura"})
    assert "el lote PRONTO tiene 4 unidades reservadas para pedidos y quedarían 3" in r.get_data(as_text=True)
    assert _lote("PRONTO").stock == 5
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "ajuste", "cantidad": -1,
                                                "lote": "PRONTO", "nota": "rotura"})
    assert _lote("PRONTO").stock == 4 and _reservado(p) == {"PRONTO": 4}      # la unidad libre sí


def test_liberar_una_proforma_sin_contestar_la_retira(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _enviar_proforma(client, p); _salir(client)
    login(client, "fac")
    r = client.post(f"/inventario/reservas/{p.id}/liberar", follow_redirects=True)
    db.session.refresh(p)
    assert "liberada y proforma" in r.get_data(as_text=True)
    assert _reservado(p) == {} and p.estado == "proforma_solicitada" and p.proformas[0].estado == "retirada"
    _salir(client)
    # el cliente ya no puede aceptar esa proforma
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"})
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"


def test_una_proforma_aceptada_no_se_libera_desde_inventario(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _enviar_proforma(client, p); _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    login(client, "fac")
    r = client.post(f"/inventario/reservas/{p.id}/liberar", follow_redirects=True)
    assert "no se puede liberar" in r.get_data(as_text=True)
    assert _reservado(p) == {"PRONTO": 3} and db.session.get(Pedido, p.id).estado == "aceptado"


# --------------------------------------------------------------------------- #
# Permisos
# --------------------------------------------------------------------------- #
def test_el_cliente_ni_ve_ni_toca_los_lotes(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "cliA")
    assert "Lotes de este pedido" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert client.post(f"/pedidos/{p.id}/lotes", data={"accion": "automatico"}).status_code == 403
    assert client.get("/inventario/reservas").status_code == 403
    assert _reservado(p) == {}


def test_el_fas_solo_toca_los_lotes_de_sus_clientes_y_no_libera(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)                       # pedido de la Clínica A
    login(client, "logb")                              # FAS de la Clínica B
    assert client.post(f"/pedidos/{p.id}/lotes", data={"accion": "automatico"}).status_code == 404
    _salir(client)
    login(client, "loga")                              # el suyo sí
    client.post(f"/pedidos/{p.id}/lotes", data={"accion": "automatico"})
    assert _reservado(p) == {"PRONTO": 3}
    assert client.post(f"/inventario/reservas/{p.id}/liberar").status_code == 403    # liberar es de admin y Facturación
    assert _reservado(p) == {"PRONTO": 3}


# --------------------------------------------------------------------------- #
# Puesta en marcha: pedidos que ya estaban abiertos
# --------------------------------------------------------------------------- #
def test_comando_reservar_pendientes(app, client):
    p = _pedido_yikon(client, 3)                       # creado sin stock: nada reservado
    assert _reservado(p) == {}
    _entrada(client, 5, "PRONTO", F_PRONTO)
    assert _reservado(p) == {}                         # lo que entra después no se asigna solo
    salida = app.test_cli_runner().invoke(args=["reservar-pendientes"]).output
    assert f"{p.referencia_interna} (aceptado): PRONTO×3" in salida
    assert _reservado(p) == {"PRONTO": 3}
    assert reservas.plan_reservado(db.session.get(Pedido, p.id))[1] == []


# --------------------------------------------------------------------------- #
# Lo que aprobó el cliente manda, pase lo que pase por el camino
# --------------------------------------------------------------------------- #
def _proforma_aceptada_con(client, **lotes):
    """Proforma enviada (con esos lotes, o FEFO si no se indica) y aceptada por el cliente."""
    p = _proforma_pedida(client)
    login(client, "loga")
    if lotes:
        _lotes(client, p, **lotes)
    _enviar_proforma(client, p); _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    return p


def test_el_cliente_no_ve_los_lotes_tampoco_con_la_proforma_enviada(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _enviar_proforma(client, p); _salir(client)
    assert _reservado(p) == {"PRONTO": 3}
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "PRONTO" not in html and "Lotes de este pedido" not in html
    assert F_PRONTO.strftime("%d/%m/%Y") in html                     # la caducidad sí: es lo que aprueba


def test_si_se_corrige_la_caducidad_de_un_lote_aprobado_no_se_envia(app, client):
    _dos_lotes(client)
    p = _proforma_aceptada_con(client)
    login(client, "admin")
    nueva = F_PRONTO - timedelta(days=10)
    r = client.post(f"/inventario/lote/{_lote('PRONTO').id}/editar", follow_redirects=True,
                    data={"codigo": "PRONTO", "caducidad": nueva.isoformat()})
    assert f"este lote está reservado para {p.referencia_interna}" in r.get_data(as_text=True)
    _salir(client)
    _hasta_validado(client, p)
    r = _enviar(client, p)
    assert (f"el cliente aprobó caducidad {F_PRONTO:%d/%m/%Y} y el lote reservado caduca el {nueva:%d/%m/%Y}"
            in r.get_data(as_text=True))
    assert db.session.get(Pedido, p.id).estado == "validado" and _salidas(p) == {}


def test_forzar_el_estado_no_se_salta_la_proforma_aceptada(app, client):
    _dos_lotes(client)
    p = _proforma_aceptada_con(client)                               # aprobado: PRONTO
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "proforma_solicitada"})   # para rehacerla…
    _lotes(client, p, PRONTO=0, LEJANO=3)
    assert _reservado(p) == {"LEJANO": 3}
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "validado"})              # …pero admin fuerza sin enviarla
    assert db.session.get(Pedido, p.id).estado == "validado"
    r = _enviar(client, p)
    assert "el cliente aprobó caducidad" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "validado" and _salidas(p) == {}


def test_un_lote_elegido_que_caduca_antes_de_enviar_la_proforma_se_sustituye(app, client):
    _dos_lotes(client)
    p = _proforma_pedida(client)
    login(client, "loga"); _lotes(client, p, PRONTO=3)
    _lote("PRONTO").caducidad = date.today() - timedelta(days=1); db.session.commit()
    _enviar_proforma(client, p)
    db.session.refresh(p)
    assert _reservado(p) == {"LEJANO": 3} and p.proforma_actual.lineas[0].caducidad == F_LEJANO


def test_lo_reservado_en_un_lote_caducado_no_quita_stock_libre(app, client):
    _dos_lotes(client)
    a = _pedido_yikon(client, 3)                                     # PRONTO×3
    _lote("PRONTO").caducidad = date.today() - timedelta(days=1); db.session.commit()
    b = _pedido_yikon(client, 5, usuario="fac")
    assert _reservado(a) == {"PRONTO": 3} and _reservado(b) == {"LEJANO": 5}
    assert "3 reservadas" in client.get("/inventario/").get_data(as_text=True)       # (la etiqueta del lote caducado)


def test_cambiar_un_precio_no_vuelve_a_reservar_lo_liberado(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3)
    client.post(f"/inventario/reservas/{p.id}/liberar")
    assert _reservado(p) == {}
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_linea_{p.lineas[0].id}": "90,00"})
    assert _reservado(p) == {} and p.lineas[0].precio_unitario == 90


def test_no_se_puede_quitar_controlar_stock_con_lotes_reservados(app, client):
    _dos_lotes(client)
    p = _pedido_yikon(client, 3)
    r = client.post("/productos/1/editar", follow_redirects=True, data={
        "referencia": "P1", "nombre": "Kit 1", "precio": "100", "iva_pct": "21", "stock_minimo": 0, "activo": "y"})
    assert f"Hay pedidos con lotes de este producto reservados ({p.referencia_interna})" in r.get_data(as_text=True)
    assert db.session.get(Producto, 1).controlar_stock is True


def test_reservar_pendientes_busca_la_caducidad_que_aprobo_el_cliente(app, client):
    """Puesta en marcha: una proforma aceptada ANTES de que existieran las reservas."""
    _dos_lotes(client)
    p = _proforma_aceptada_con(client, PRONTO=0, LEJANO=3)           # aprobó la fecha de LEJANO
    for r in list(p.reservas):                                       # como estaba antes: sin nada reservado
        db.session.delete(r)
    db.session.commit()
    salida = app.test_cli_runner().invoke(args=["reservar-pendientes"]).output
    assert _reservado(p) == {"LEJANO": 3}                            # no el que caduca antes: el aprobado
    assert f"{p.referencia_interna} (aceptado): LEJANO×3" in salida and "⚠" not in salida
