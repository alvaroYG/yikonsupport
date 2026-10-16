"""16/10/2026 · Borrar de verdad desde la terminal (app/limpieza.py): flask borrar-pedido, borrar-cliente y
limpiar-pruebas. Escenario de conftest: cliA (Clínica A, prefijo CLA) · cliB (Clínica B) · producto P1."""
import os

from app.extensions import db
from app.models import Cliente, Factura, FotoPedido, Lote, Mensaje, Pedido, Producto, User
from tests.conftest import llevar_a_validado, login, pedido_cliente, subir_foto


def _salir(client):
    client.post("/auth/logout")


def _cli(app, *args, entrada=None):
    return app.test_cli_runner().invoke(args=list(args), input=entrada).output


def _stock_p1():
    return db.session.scalar(db.select(Producto).filter_by(referencia="P1")).stock


def _pedido_enviado(client, cliente="cliA"):
    """Con stock, una foto, un mensaje y enviado (sale stock)."""
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 10,
                                                "lote": "L-LIMP", "caducidad": "2031-01-01"})
    _salir(client)
    login(client, cliente); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "ofi"); client.post(f"/pedidos/{p.id}/preparacion"); _salir(client)
    llevar_a_validado(client, p.id, "loga" if cliente == "cliA" else "logb")
    login(client, "ofi")
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "confirmar_stock": "1",
                                                 "transportista": "SEUR", "numero_seguimiento": "T1"})
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "hola"})
    _salir(client)
    db.session.expire_all()
    return db.session.get(Pedido, p.id)


def test_borrar_un_pedido_deja_el_stock_como_antes_y_borra_sus_archivos(app, client):
    p = _pedido_enviado(client)
    assert p.estado == "enviado" and _stock_p1() == 9
    foto = db.session.scalar(db.select(FotoPedido).filter_by(pedido_id=p.id))
    ruta = os.path.join(app.config["UPLOAD_FOLDER"], foto.archivo)
    assert os.path.isfile(ruta)
    ref, pid = p.referencia_interna, p.id
    salida = _cli(app, "borrar-pedido", ref, entrada="no\n")             # sin escribir la referencia: nada
    assert "Cancelado" in salida and db.session.get(Pedido, pid) is not None
    salida = _cli(app, "borrar-pedido", ref, entrada=ref + "\n")
    assert "Hecho" in salida and "fotos_pedido" in salida and "el siguiente volverá a ser" in salida
    db.session.expire_all()
    assert db.session.get(Pedido, pid) is None and not os.path.exists(ruta)
    assert _stock_p1() == 10                                              # la salida se ha ido con él
    assert db.session.scalar(db.select(Lote).filter_by(codigo="L-LIMP")) is not None
    assert db.session.get(Cliente, 1).contador_pedidos == 0               # el número se reutiliza
    login(client, "cliA"); pedido_cliente(client)
    assert db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc())).referencia_interna == ref


def test_con_factura_no_se_borra_salvo_que_se_pida(app, client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    db.session.add(Factura(numero="F-1", cliente_id=1, pedido_id=p.id))
    db.session.commit()
    assert "no lo borro" in _cli(app, "borrar-pedido", p.referencia_interna, "--si")
    assert db.session.get(Pedido, p.id) is not None
    pid = p.id
    assert "Hecho" in _cli(app, "borrar-pedido", p.referencia_interna, "--si", "--con-facturas")
    db.session.expire_all()
    assert db.session.get(Pedido, pid) is None and not db.session.scalar(db.select(Factura))


def test_borrar_un_cliente_con_todo_lo_suyo(app, client):
    p = _pedido_enviado(client, "cliB")
    pid = p.id
    salida = _cli(app, "borrar-cliente", "2", entrada="Clínica B\n")
    assert "Hecho" in salida and "usuarios" in salida
    db.session.expire_all()
    assert db.session.get(Cliente, 2) is None and db.session.get(Pedido, pid) is None
    assert db.session.scalar(db.select(User).filter_by(email="clib@ejemplo.com")) is None
    assert db.session.scalar(db.select(User).filter_by(email="logb@ejemplo.com")) is not None   # su Soporte, no
    assert db.session.get(Cliente, 1) is not None
    login(client, "admin")
    assert client.get("/clientes/").status_code == 200 and client.get("/pedidos/").status_code == 200


def test_limpiar_pruebas_deja_clientes_productos_y_usuarios_y_la_numeracion_a_1(app, client):
    _pedido_enviado(client)
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    assert db.session.get(Cliente, 1).contador_pedidos == 2
    assert "Cancelado" in _cli(app, "limpiar-pruebas", entrada="no\n")
    salida = _cli(app, "limpiar-pruebas", entrada="BORRAR\n")
    assert "Hecho" in salida
    db.session.expire_all()
    assert not db.session.scalars(db.select(Pedido)).all() and not db.session.scalars(db.select(Mensaje)).all()
    assert db.session.get(Cliente, 1).contador_pedidos == 0
    assert db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")) is not None
    assert _stock_p1() == 10                                              # entradas de stock: se quedan
    login(client, "cliA"); pedido_cliente(client)
    assert db.session.scalar(db.select(Pedido)).referencia_interna.endswith("-CLA-001")
    _salir(client)
    assert "Hecho" in _cli(app, "limpiar-pruebas", "--con-inventario", "--si")
    db.session.expire_all()
    assert _stock_p1() == 0 and not db.session.scalars(db.select(Lote)).all()
