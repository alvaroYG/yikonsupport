"""15/10/2026 · Datos de facturación y de envío en la ficha del cliente, «Mi empresa» para sus usuarios
(solo ver) y el albarán en PDF que va dentro del paquete (admin y Almacén; nº = referencia interna;
al enviarlo se copian los datos para que su albarán no cambie). Escenario de conftest: cliA (Clínica A,
id 1, Soporte loga) · fac = Facturación · ofi = Almacén · kit K1 = 1 × P1."""
from app.extensions import db
from app.models import Cliente, Pedido
from app.pedidos import albaran
from tests.conftest import llevar_a_validado, login, pedido_cliente

DIRECCION = {"nombre": "Clínica A", "prefijo": "CLA", "cif": "B11111111", "razon_social": "Clínica A S.L.",
             "direccion": "Calle Mayor 1", "codigo_postal": "28001", "ciudad": "Madrid", "provincia": "Madrid",
             "pais": "España", "activo": "y"}


def _salir(client):
    client.post("/auth/logout")


def _ultimo():
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _guardar_cliente(client, **extra):
    login(client, "fac")
    r = client.post("/clientes/1/editar", data={**DIRECCION, **extra})
    _salir(client)
    return r


def _pedido(client):
    login(client, "cliA"); pedido_cliente(client, referencia="OC-ALB"); _salir(client)
    return _ultimo()


def test_facturacion_guarda_los_datos_de_facturacion_y_envio(app, client):
    login(client, "fac")
    html = client.get("/clientes/nuevo").get_data(as_text=True)
    assert 'name="envio_igual"' in html and 'value="España"' in html and 'id="envio-direccion"' in html
    assert 'name="envio_instrucciones"' in client.get("/clientes/1/editar").get_data(as_text=True)
    _salir(client)
    assert _guardar_cliente(client, envio_igual="y", envio_contacto="Ana", envio_telefono="600111222",
                            envio_instrucciones="Muelle 3, de 9 a 14").status_code == 302
    c = db.session.get(Cliente, 1)
    assert c.codigo_postal == "28001" and c.provincia == "Madrid" and c.envio_igual
    env = c.datos_envio()
    assert env["direccion"] == "Calle Mayor 1" and env["destinatario"] == "Clínica A S.L." and env["contacto"] == "Ana"
    assert c.envio_completo
    # Otra dirección de envío
    _guardar_cliente(client, envio_direccion="Polígono Sur, nave 7", envio_codigo_postal="41001",
                     envio_ciudad="Sevilla", envio_destinatario="Laboratorio Sur")
    env = db.session.get(Cliente, 1).datos_envio()
    assert env["direccion"] == "Polígono Sur, nave 7" and env["ciudad"] == "Sevilla"
    assert env["destinatario"] == "Laboratorio Sur"
    login(client, "fac")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert 'id="pestana-envio"' in html and "Polígono Sur, nave 7" in html and "Falta la dirección" not in html


def test_si_no_es_la_misma_y_no_la_escriben_falta(app, client):
    assert _guardar_cliente(client).status_code == 302     # se guarda, pero sin dirección de envío
    assert not db.session.get(Cliente, 1).envio_completo


def test_sin_direccion_lo_avisa(app, client):
    login(client, "fac")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert "falta el envío" in html and "sin ella no se puede hacer el albarán" in html


def test_el_cliente_ve_su_empresa_pero_no_la_cambia(app, client):
    _guardar_cliente(client, envio_igual="y")
    login(client, "cliA")
    assert 'href="/clientes/mi-empresa"' in client.get("/").get_data(as_text=True)
    html = client.get("/clientes/mi-empresa").get_data(as_text=True)
    assert "Clínica A S.L." in html and "Calle Mayor 1" in html and "B11111111" in html
    assert "/clientes/1/editar" not in html and "albarán" not in html
    assert client.get("/clientes/1/editar").status_code == 403
    assert client.post("/clientes/1/editar", data={**DIRECCION, "ciudad": "Otra"}).status_code == 403
    assert client.get("/clientes/1").status_code == 403
    assert db.session.get(Cliente, 1).ciudad == "Madrid"
    _salir(client)
    login(client, "fac")                               # Yikon no tiene «Mi empresa»
    assert client.get("/clientes/mi-empresa").status_code == 403


def test_almacen_saca_el_albaran(app, client):
    p = _pedido(client)
    login(client, "ofi")
    # Sin dirección de envío: no se genera, se avisa
    r = client.get(f"/pedidos/{p.id}/albaran.pdf?volver=preparar")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/pedidos/{p.id}/preparar")
    assert "no tiene dirección de envío" in client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    _salir(client)
    _guardar_cliente(client, envio_igual="y")
    login(client, "ofi")
    r = client.get(f"/pedidos/{p.id}/albaran.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert f'filename="Albaran_{p.referencia_interna}.pdf"' in r.headers["Content-Disposition"]
    assert f'/pedidos/{p.id}/albaran.pdf' in client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert f'/pedidos/{p.id}/albaran.pdf' in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    # Lo que lleva: el kit con su producto debajo (sin precios)
    filas = albaran.contenido(p)
    assert filas[0][0] == 1 and filas[0][3] is False and filas[1][3] is True


def test_solo_admin_y_almacen(app, client):
    p = _pedido(client)
    _guardar_cliente(client, envio_igual="y")
    for quien, codigo in (("cliA", 403), ("fac", 403), ("loga", 403), ("admin", 200)):
        login(client, quien)
        assert client.get(f"/pedidos/{p.id}/albaran.pdf").status_code == codigo, quien
        if codigo == 403 and quien != "cliA":
            assert "albaran.pdf" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
        _salir(client)


def test_al_enviarlo_se_queda_con_la_direccion_de_entonces(app, client):
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5,
                                                "lote": "L-ALB", "caducidad": "2031-03-15"})
    _salir(client)
    _guardar_cliente(client, envio_igual="y")
    p = _pedido(client)
    assert [l.codigo for _a, l, _n in albaran.lotes(p)] == ["L-ALB"]          # reservado
    login(client, "ofi"); client.post(f"/pedidos/{p.id}/preparacion"); _salir(client)
    llevar_a_validado(client, p.id)
    login(client, "ofi")
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "confirmar_stock": "1",
                                                 "transportista": "SEUR", "numero_seguimiento": "T1"})
    _salir(client)
    p = db.session.get(Pedido, p.id)
    assert p.estado == "enviado" and p.datos_albaran["envio"]["direccion"] == "Calle Mayor 1"
    assert _guardar_cliente(client, envio_igual="y", direccion="Calle Nueva 9").status_code == 302   # se muda
    db.session.expire_all()
    p = db.session.get(Pedido, p.id)
    assert p.datos_para_albaran["envio"]["direccion"] == "Calle Mayor 1"       # el albarán de lo enviado, no
    assert db.session.get(Cliente, 1).datos_envio()["direccion"] == "Calle Nueva 9"
    assert [(l.codigo, n) for _a, l, n in albaran.lotes(p)] == [("L-ALB", 1)]  # los que salieron
    login(client, "ofi")
    assert client.get(f"/pedidos/{p.id}/albaran.pdf").status_code == 200
