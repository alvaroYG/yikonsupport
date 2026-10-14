"""La conversación general del cliente es privada con su Soporte de cliente (admin también la ve,
pero el cliente nunca lo sabe). Logística solo ve lo que el Soporte le comparte."""
from app.extensions import db
from app.models import Mensaje
from tests.conftest import confirmar_correos, login, pedido_cliente


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _salir(client):
    client.post("/auth/logout")


def _escribe_el_cliente(client, texto="¿Podemos ver la validación el martes?"):
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": texto})
    _salir(client)
    return db.session.scalar(db.select(Mensaje).filter_by(texto=texto))


def test_el_cliente_escribe_a_su_soporte_y_logistica_no_lo_ve(app, client):
    login(client, "cliA")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert "Conversación con loga" in html and "tu Soporte de cliente" in html and "admin" not in html.lower().split("<main")[1]
    _salir(client)
    correos = _correos(app)
    m = _escribe_el_cliente(client)
    assert [c["To"] for c in correos] == ["loga@ejemplo.com"]                # su Soporte, no Logística
    login(client, "ofi")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert m.texto not in html and "Solo ves los mensajes que te han compartido" in html
    assert 'name="texto"' not in html                                         # no puede escribir ahí
    client.post("/mensajes/cliente/1", data={"texto": "Hola desde Logística"})
    assert db.session.scalar(db.select(Mensaje).filter_by(texto="Hola desde Logística")) is None
    assert m.texto not in client.get("/mensajes/").get_data(as_text=True)
    _salir(client)
    for quien in ("loga", "admin"):                                           # su Soporte y admin, sí
        login(client, quien)
        assert m.texto in client.get("/mensajes/cliente/1").get_data(as_text=True)
        _salir(client)


def test_en_el_chat_del_pedido_el_cliente_ve_quien_lo_lee(app, client):
    login(client, "cliA"); pedido_cliente(client)
    html = client.get("/pedidos/1").get_data(as_text=True)
    assert "lo ven el equipo de Yikon y loga" in html


def test_compartir_con_almacen_y_despues_con_facturacion(app, client):
    m = _escribe_el_cliente(client)
    login(client, "ofi")
    assert client.post(f"/mensajes/{m.id}/compartir").status_code == 403    # Almacén no comparte
    _salir(client)
    login(client, "fac")
    assert m.texto not in client.get("/mensajes/cliente/1").get_data(as_text=True)   # Facturación tampoco lo ve aún
    assert client.post(f"/mensajes/{m.id}/compartir").status_code == 403
    _salir(client)
    correos = _correos(app)
    login(client, "loga")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert 'name="destino" value="logistica"' in html and 'name="destino" value="facturacion"' in html
    client.post(f"/mensajes/{m.id}/compartir", data={"destino": "logistica", "nota": "¿Hay stock para el martes?"})
    assert confirmar_correos() == 0                     # aviso entre compañeros: sale solo
    assert [c["To"] for c in correos] == ["ofi@ejemplo.com"]                # solo a Almacén
    assert m.texto in correos[0].get_content() and "¿Hay stock para el martes?" in correos[0].get_content()
    assert "compartido con Almacén" in correos[0].get_content()
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert "Compartido con Almacén" in html and 'name="destino" value="logistica"' not in html   # ya está
    assert client.post(f"/mensajes/{m.id}/compartir", data={"destino": "otro"}).status_code == 400
    _salir(client)
    login(client, "ofi")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert m.texto in html and "Compartido con Almacén" in html
    _salir(client)
    login(client, "fac")
    assert m.texto not in client.get("/mensajes/cliente/1").get_data(as_text=True)   # a Facturación, no
    _salir(client)
    # Después, también con Facturación: le llega solo a ella y ya lo ve; Almacén lo sigue viendo
    correos.clear()
    login(client, "loga")
    client.post(f"/mensajes/{m.id}/compartir", data={"destino": "facturacion", "nota": "Y el precio"})
    assert [c["To"] for c in correos] == ["fac@ejemplo.com"]
    db.session.refresh(m)
    assert m.compartido_roles == ["logistica", "facturacion"] and m.compartido_nota == "¿Hay stock para el martes? · Y el precio"
    _salir(client)
    for quien in ("fac", "ofi"):
        login(client, quien)
        html = client.get("/mensajes/cliente/1").get_data(as_text=True)
        assert m.texto in html and "Compartido con Almacén · Facturación" in html
        _salir(client)
    login(client, "cliA")
    assert "Compartido con" not in client.get("/mensajes/cliente/1").get_data(as_text=True)
