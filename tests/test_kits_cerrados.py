"""
Kits CERRADOS: llegan del fabricante como un paquete (una bolsa con varias cajas) con una
sola etiqueta de lote y caducidad. Tienen stock propio; al enviar sale el kit entero de
su lote (FEFO) y sus productos no se tocan. Se pueden "abrir" para pasar a productos sueltos.
"""
from datetime import date, timedelta

from app.extensions import db
from app.inventario.stock import disponible
from app.models import ComponenteKit, Kit, Lote, MovimientoInventario, Pedido, Producto
from tests.conftest import contenido, llevar_a_validado, login, proforma_aceptada


def _kit_cerrado():
    """Kit "KX" cerrado = 2 × P1 + 1 × servicio (sin stock)."""
    serv = Producto(referencia="SERV", nombre="Análisis", precio=50, controlar_stock=False)
    kit = Kit(referencia="KX", nombre="Kit cerrado", precio=300, cerrado=True,
              componentes=[ComponenteKit(producto_id=1, cantidad=2), ComponenteKit(producto=serv, cantidad=1)])
    db.session.add(kit); db.session.commit()
    return kit, serv


def _entrada(client, articulo, cantidad, lote, caducidad="2099-12-31", tipo="entrada"):
    return client.post("/inventario/movimiento", data={"articulo": articulo, "tipo": tipo, "cantidad": cantidad,
                                                       "lote": lote, "caducidad": caducidad})


def _pedido_de_kits(client, kit, serv, n):
    """cliA pide n kits KX y logistics lo confirma."""
    login(client, "cliA")
    client.post("/pedidos/nuevo", data={"contenido": contenido([(kit.id, n, {1: 2 * n, serv.id: n})]),
                                        "fecha": "2026-09-25", "referencia": f"OC-KX-{n}"})
    proforma_aceptada(); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    return p


def _estado(client, pedido, estado):
    return client.post(f"/pedidos/{pedido.id}/estado", data={"estado": estado, "confirmar_stock": "1",
                                                            "transportista": "SEUR", "numero_seguimiento": "TRK1"},
                       follow_redirects=True)


def test_entrada_de_un_kit_cerrado_va_a_su_propio_lote(app, client):
    kit, _serv = _kit_cerrado()
    login(client, "admin")
    _entrada(client, f"kit-{kit.id}", 5, "YK-A", "2027-01-31")
    lote = db.session.scalar(db.select(Lote).filter_by(codigo="YK-A"))
    assert lote.kit_id == kit.id and lote.producto_id is None
    assert disponible(kit) == 5 and disponible(db.session.get(Producto, 1)) == 0
    # el inventario lo enseña en su sección de kits cerrados
    assert "YK-A" in client.get("/inventario/").get_data(as_text=True)


def test_al_enviar_sale_el_kit_entero_fefo_y_no_sus_productos(app, client):
    kit, serv = _kit_cerrado()
    login(client, "admin")
    _entrada(client, f"kit-{kit.id}", 2, "LEJANO", (date.today() + timedelta(days=400)).isoformat())
    _entrada(client, f"kit-{kit.id}", 2, "PRONTO", (date.today() + timedelta(days=30)).isoformat())
    _entrada(client, "producto-1", 10, "P1-SUELTO")
    client.post("/auth/logout")
    p = _pedido_de_kits(client, kit, serv, 3)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    _estado(client, p, "enviado")
    assert disponible(kit) == 1
    assert disponible(db.session.get(Producto, 1)) == 10          # los productos del kit no se tocan
    salidas = {m.lote.codigo: m.cantidad for m in db.session.scalars(
        db.select(MovimientoInventario).filter_by(tipo="salida_pedido"))}
    assert salidas == {"PRONTO": -2, "LEJANO": -1}               # primero el que caduca antes
    # anular el envío: cada kit vuelve a su lote
    _estado(client, p, "validado")
    assert disponible(kit) == 4


def test_sin_kits_no_se_puede_enviar(app, client):
    kit, serv = _kit_cerrado()
    login(client, "admin"); _entrada(client, "producto-1", 50, "P1"); client.post("/auth/logout")
    p = _pedido_de_kits(client, kit, serv, 1)                     # hay P1 de sobra, pero 0 kits
    llevar_a_validado(client, p.id)
    login(client, "admin")
    _estado(client, p, "enviado")
    assert db.session.get(Pedido, p.id).estado == "validado"


def test_abrir_kit_pasa_sus_productos_a_stock_suelto(app, client):
    kit, _serv = _kit_cerrado()
    login(client, "admin")
    _entrada(client, f"kit-{kit.id}", 3, "YK-B", "2027-06-30")
    lote = db.session.scalar(db.select(Lote).filter_by(codigo="YK-B"))
    client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": lote.id, "cantidad": 1, "nota": "reponer"})
    assert disponible(kit) == 2
    p1 = db.session.get(Producto, 1)
    assert disponible(p1) == 2                                   # 1 kit × 2 de P1
    lote_p1 = db.session.scalar(db.select(Lote).filter_by(producto_id=1, codigo="YK-B"))
    assert lote_p1 is not None and str(lote_p1.caducidad) == "2027-06-30"   # mismo lote y caducidad
    # el servicio no es mercancía: no se crea stock
    assert db.session.scalar(db.select(db.func.count(Lote.id)).filter_by(producto_id=_serv.id)) == 0
    # no se pueden abrir más de los que hay en el lote
    client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": lote.id, "cantidad": 5})
    assert disponible(kit) == 2


def test_abrir_solo_kits_cerrados_y_solo_admin(app, client):
    kit, _serv = _kit_cerrado()
    login(client, "admin")
    assert client.post("/inventario/kit/1/abrir", data={"lote_id": 1, "cantidad": 1}).status_code == 400  # K1 es montado
    client.post("/auth/logout")
    login(client, "loga")
    assert client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": 1, "cantidad": 1}).status_code == 403


def test_proforma_y_preparar_usan_la_caducidad_del_kit(app, client):
    from app.proformas.servicio import lineas_previstas
    kit, serv = _kit_cerrado()
    login(client, "admin")
    _entrada(client, f"kit-{kit.id}", 4, "YK-C", "2028-02-29")
    _entrada(client, "producto-1", 10, "P1-OTRO", "2030-01-01")
    client.post("/auth/logout")
    p = _pedido_de_kits(client, kit, serv, 1)
    filas = {f["producto"].referencia: f for f in lineas_previstas(db.session.get(Pedido, p.id))}
    assert str(filas["P1"]["caducidad"]) == "2028-02-29"           # la de la etiqueta del kit
    assert filas["SERV"]["sin_control"] and filas["SERV"]["caducidad"] is None
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert "YK-C" in html and "P1-OTRO" not in html                # se coge el kit, no P1 suelto
    assert "kit cerrado, tal como llega" in html


def test_formulario_de_kit_guarda_cerrado_y_minimo(app, client):
    login(client, "admin")
    client.post("/productos/kits/nuevo", data={
        "referencia": "KZ", "nombre": "Kit Z", "precio": "100", "iva_pct": "21.00", "activo": "y",
        "cerrado": "y", "stock_minimo": "3", "componentes-0-producto_id": 1, "componentes-0-cantidad": 1})
    kit = db.session.scalar(db.select(Kit).filter_by(referencia="KZ"))
    assert kit.cerrado and kit.stock_minimo == 3
    # con stock no se puede pasar a "montado" (descuadraría el inventario)
    _entrada(client, f"kit-{kit.id}", 1, "Z1")
    client.post(f"/productos/kits/{kit.id}/editar", data={
        "referencia": "KZ", "nombre": "Kit Z", "precio": "100", "iva_pct": "21.00", "activo": "y",
        "stock_minimo": "3", "componentes-0-producto_id": 1, "componentes-0-cantidad": 1})
    db.session.refresh(kit)
    assert kit.cerrado


def test_no_pasa_a_montado_con_envios_sin_anular(app, client):
    """Si pasara a montado y luego se anulara el envío, el kit volvería a un lote escondido."""
    kit, serv = _kit_cerrado()
    login(client, "admin"); _entrada(client, f"kit-{kit.id}", 1, "UNO"); client.post("/auth/logout")
    p = _pedido_de_kits(client, kit, serv, 1)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    _estado(client, p, "enviado")
    assert disponible(kit) == 0
    datos = {"referencia": "KX", "nombre": "Kit cerrado", "precio": "300", "iva_pct": "21.00", "activo": "y",
             "componentes-0-producto_id": 1, "componentes-0-cantidad": 2,
             "componentes-1-producto_id": serv.id, "componentes-1-cantidad": 1}      # sin "cerrado"
    r = client.post(f"/productos/kits/{kit.id}/editar", data=datos)
    assert "Hay pedidos enviados con este kit cerrado" in r.get_data(as_text=True)
    db.session.refresh(kit)
    assert kit.cerrado
    # anulado el envío (el kit vuelve a su lote) y abierto/ajustado a 0, ya se puede
    _estado(client, p, "validado")
    lote = db.session.scalar(db.select(Lote).filter_by(codigo="UNO"))
    # al anular, el kit queda otra vez reservado para el pedido: así no se puede abrir...
    r = client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": lote.id, "cantidad": 1}, follow_redirects=True)
    assert "tiene 1 unidades reservadas para pedidos" in r.get_data(as_text=True) and lote.stock == 1
    # ...hasta que se libera la reserva (Inventario → Reservas)
    client.post(f"/inventario/reservas/{p.id}/liberar")
    client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": lote.id, "cantidad": 1})
    client.post(f"/productos/kits/{kit.id}/editar", data=datos)
    db.session.refresh(kit)
    assert not kit.cerrado


def test_los_productos_de_los_kits_cuentan_en_el_inventario(app, client):
    """Al dar de alta kits cerrados, sus productos aparecen en la pestaña Productos
    (calculado: sueltos + dentro de kits), sin duplicar el stock."""
    from app.inventario.stock import productos_en_kits_cerrados
    kit, _serv = _kit_cerrado()                                   # KX = 2 × P1 + servicio
    login(client, "admin")
    _entrada(client, f"kit-{kit.id}", 3, "YK-D", "2027-05-31")
    _entrada(client, "producto-1", 4, "P1-SUELTO")
    [(k, lote, n)] = productos_en_kits_cerrados()[1]
    assert k.id == kit.id and lote.codigo == "YK-D" and n == 6       # 3 kits × 2
    html = client.get("/inventario/").get_data(as_text=True)
    assert "Dentro de kits cerrados" in html and "4 sueltos + 6 en kits" in html
    assert disponible(db.session.get(Producto, 1)) == 4           # el stock suelto no cambia
    # al abrir un kit: 1 kit menos, 2 P1 sueltos más → el total sigue siendo 10
    client.post(f"/inventario/kit/{kit.id}/abrir", data={"lote_id": lote.id, "cantidad": 1})
    assert "6 sueltos + 4 en kits" in client.get("/inventario/").get_data(as_text=True)
