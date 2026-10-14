from app.extensions import db
from app.models import Cliente, MovimientoInventario, Pedido, Producto
from tests.conftest import contenido, llevar_a_validado, login, pedido_cliente


def _entrada(client, cantidad, producto_id=1, tipo="entrada", lote="L1", caducidad="2099-12-31"):
    return client.post("/inventario/movimiento",
                       data={"producto_id": producto_id, "tipo": tipo, "cantidad": cantidad,
                             "lote": lote, "caducidad": caducidad})


def _pedido_confirmado(client, cantidad):
    """cliA pide `cantidad` del Kit 1 y loga lo confirma. Devuelve el pedido."""
    login(client, "cliA"); pedido_cliente(client, cantidad=cantidad); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    return p


def _estado(client, pedido, estado, confirmar=True):
    datos = {"estado": estado, "confirmar_stock": "1" if confirmar else "0",
             "transportista": "SEUR", "numero_seguimiento": "TRK1"}
    return client.post(f"/pedidos/{pedido.id}/estado", data=datos, follow_redirects=True)


def test_solo_admin_ve_inventario(client):
    for usuario, esperado in [("admin", 200), ("loga", 403), ("cliA", 403)]:
        login(client, usuario)
        assert client.get("/inventario/").status_code == esperado
        client.post("/auth/logout")


def test_entradas_y_ajustes(app, client):
    login(client, "admin")
    _entrada(client, 10)
    _entrada(client, -2, tipo="ajuste")
    assert db.session.get(Producto, 1).stock == 8
    # una "entrada" negativa no se admite (para restar está el ajuste)
    _entrada(client, -5)
    assert db.session.get(Producto, 1).stock == 8


def test_enviar_resta_stock_y_anular_lo_devuelve(app, client):
    login(client, "admin"); _entrada(client, 10); client.post("/auth/logout")
    p = _pedido_confirmado(client, cantidad=3)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    _estado(client, p, "enviado")
    assert db.session.get(Producto, 1).stock == 7
    _estado(client, p, "entregado")                    # entregado no vuelve a restar
    assert db.session.get(Producto, 1).stock == 7
    _estado(client, p, "enviado")
    _estado(client, p, "validado")                     # se anula el envío: vuelve la mercancía
    assert db.session.get(Producto, 1).stock == 10
    tipos = db.session.scalars(db.select(MovimientoInventario.tipo)).all()
    assert tipos == ["entrada", "salida_pedido", "devolucion_pedido"]


def test_sin_stock_no_se_puede_enviar(app, client):
    login(client, "admin"); _entrada(client, 2); client.post("/auth/logout")
    p = _pedido_confirmado(client, cantidad=5)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    r = _estado(client, p, "enviado")
    html = r.get_data(as_text=True)              # solo se pudieron reservar 2 de las 5
    assert "No se puede enviar: Kit 1: faltan 3 por asignar a un lote" in html
    assert db.session.get(Pedido, p.id).estado == "validado"
    assert db.session.get(Producto, 1).stock == 2


def test_servicios_no_mueven_stock(app, client):
    servicio = Producto(referencia="SERV", nombre="Análisis", precio=150, controlar_stock=False)
    db.session.add(servicio); db.session.commit()
    login(client, "loga")
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    client.post("/pedidos/nuevo", data={"cliente_id": a.id, "fecha": "2026-09-25",
                                        "contenido": contenido(sueltos={servicio.id: 1})})
    p = db.session.scalar(db.select(Pedido))
    client.post("/auth/logout")
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    llevar_a_validado(client, p.id)
    login(client, "admin")
    r = _estado(client, p, "enviado")                   # sin stock, pero es un servicio: OK
    assert db.session.get(Pedido, p.id).estado == "enviado"
    assert db.session.scalar(db.select(db.func.count(MovimientoInventario.id))) == 0


def test_enviar_exige_confirmar_la_salida_de_stock(app, client):
    login(client, "admin"); _entrada(client, 10); client.post("/auth/logout")
    p = _pedido_confirmado(client, cantidad=3)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    # la ficha trae la ventana con lo que se va a restar
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Confirmar salida de stock" in html and "−3" in html
    # sin confirmar (p. ej. JavaScript desactivado o petición manual): no se envía ni se resta nada
    r = _estado(client, p, "enviado", confirmar=False)
    assert "Confirma la salida de stock" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "validado"
    assert db.session.get(Producto, 1).stock == 10
    # confirmando, sí
    _estado(client, p, "enviado", confirmar=True)
    assert db.session.get(Pedido, p.id).estado == "enviado"
    assert db.session.get(Producto, 1).stock == 7


def test_otros_cambios_no_piden_confirmacion(app, client):
    p = _pedido_confirmado(client, cantidad=1)
    login(client, "admin")
    _estado(client, p, "cancelado", confirmar=False)   # cancelar no resta stock: sin ventana
    assert db.session.get(Pedido, p.id).estado == "cancelado"


def test_inventario_muestra_los_kits_que_se_pueden_montar(app, client):
    """Kit K1 = 1 × P1. Con 7 unidades de P1 → 7 kits; un kit de 2 × P1 + un servicio → 3."""
    from app.models import ComponenteKit, Kit, Producto
    serv = Producto(referencia="SERV", nombre="Servicio análisis", precio=10, controlar_stock=False)
    db.session.add(Kit(referencia="K2", nombre="Kit doble", precio=1, cerrado=False,
                       componentes=[ComponenteKit(producto_id=1, cantidad=2), ComponenteKit(producto=serv, cantidad=1)]))
    db.session.commit()
    login(client, "admin")
    _entrada(client, 7)
    html = client.get("/inventario/").get_data(as_text=True)
    assert 'id="tab-kits"' in html and 'id="modal-movimiento"' in html
    import re
    fila = lambda nombre: re.search(nombre + r".*?</tr>", html, re.S).group(0)
    assert re.search(r'<td class="num fw-semibold">7', fila("Kit uno"))
    assert re.search(r'<td class="num fw-semibold">3', fila("Kit doble"))
    assert "sin control de stock" in fila("Kit doble")


def test_iconos_de_stock_bajo_y_caducidades_solo_para_admin(app, client):
    from app.models import Producto
    db.session.get(Producto, 1).stock_minimo = 5; db.session.commit()      # sin stock: queda "bajo"
    login(client, "admin")
    html = client.get("/").get_data(as_text=True)
    assert "fa-box-open" in html and "fa-hourglass-half" in html
    assert 'aria-label="Stock bajo (1)"' in html
    client.post("/auth/logout"); login(client, "loga")
    html = client.get("/").get_data(as_text=True)
    assert "Stock bajo (" not in html and "Caducidades (" not in html


# --- Corregir lo ya registrado ------------------------------------------------ #
def _mov(tipo="entrada"):
    return db.session.scalar(db.select(MovimientoInventario).filter_by(tipo=tipo)
                             .order_by(MovimientoInventario.id.desc()))


def test_corregir_lote(app, client):
    from app.models import Lote
    login(client, "admin"); _entrada(client, 5, lote="L1"); _entrada(client, 3, lote="L2")
    assert client.get("/inventario/producto/1/corregir").status_code == 200
    lote = db.session.scalar(db.select(Lote).filter_by(codigo="L1"))
    client.post(f"/inventario/lote/{lote.id}/editar", data={"codigo": "L1-BIEN", "caducidad": "2030-01-31"})
    db.session.refresh(lote)
    assert lote.codigo == "L1-BIEN" and str(lote.caducidad) == "2030-01-31"
    # no puede quedar con el código de otro lote del mismo producto
    client.post(f"/inventario/lote/{lote.id}/editar", data={"codigo": "L2", "caducidad": "2030-01-31"})
    db.session.refresh(lote)
    assert lote.codigo == "L1-BIEN"


def test_corregir_y_borrar_entrada(app, client):
    login(client, "admin"); _entrada(client, 10)
    mov = _mov()
    client.post(f"/inventario/movimiento/{mov.id}/editar", data={"cantidad": 12, "nota": "albarán 55"})
    assert db.session.get(Producto, 1).stock == 12 and _mov().nota == "albarán 55"
    client.post(f"/inventario/movimiento/{mov.id}/editar", data={"cantidad": -3})   # entrada negativa: no
    assert db.session.get(Producto, 1).stock == 12
    client.post(f"/inventario/movimiento/{mov.id}/borrar")
    assert db.session.get(Producto, 1).stock == 0


def test_no_deja_el_lote_en_negativo_ni_toca_envios(app, client):
    login(client, "admin"); _entrada(client, 5); client.post("/auth/logout")
    p = _pedido_confirmado(client, cantidad=4)
    llevar_a_validado(client, p.id)
    login(client, "admin"); _estado(client, p, "enviado")
    entrada = _mov()
    client.post(f"/inventario/movimiento/{entrada.id}/editar", data={"cantidad": 2})   # ya salieron 4
    assert db.session.get(Producto, 1).stock == 1
    client.post(f"/inventario/movimiento/{entrada.id}/borrar")
    assert db.session.get(Producto, 1).stock == 1
    salida = _mov("salida_pedido")
    assert client.post(f"/inventario/movimiento/{salida.id}/editar", data={"cantidad": -1}).status_code == 403
    assert client.post(f"/inventario/movimiento/{salida.id}/borrar").status_code == 403


def test_corregir_solo_admin(app, client):
    login(client, "admin"); _entrada(client, 5); client.post("/auth/logout")
    mov = _mov()
    for usuario in ("loga", "cliA"):
        login(client, usuario)
        assert client.get("/inventario/producto/1/corregir").status_code == 403
        assert client.post(f"/inventario/movimiento/{mov.id}/borrar").status_code == 403
        client.post("/auth/logout")
    assert db.session.get(Producto, 1).stock == 5


def test_anadir_caducidad_a_un_lote_que_no_la_tenia(app, client):
    from app.models import Lote
    login(client, "admin"); _entrada(client, 5, lote="VIEJO")
    lote = db.session.scalar(db.select(Lote).filter_by(codigo="VIEJO"))
    lote.caducidad = None; db.session.commit()            # como los lotes antiguos "SIN LOTE"
    client.post(f"/inventario/lote/{lote.id}/editar", data={"codigo": "VIEJO", "caducidad": ""})
    db.session.refresh(lote)
    assert lote.caducidad is None                         # vacía: sigue sin fecha, sin error
    client.post(f"/inventario/lote/{lote.id}/editar", data={"codigo": "VIEJO", "caducidad": "2027-06-30"})
    db.session.refresh(lote)
    assert str(lote.caducidad) == "2027-06-30"
    # una vez puesta ya no se puede quitar, solo cambiar
    client.post(f"/inventario/lote/{lote.id}/editar", data={"codigo": "VIEJO", "caducidad": ""})
    db.session.refresh(lote)
    assert str(lote.caducidad) == "2027-06-30"
