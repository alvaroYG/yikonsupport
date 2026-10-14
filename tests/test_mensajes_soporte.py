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
    assert "lo ven Logística y loga" in html


def test_compartir_con_logistica(app, client):
    m = _escribe_el_cliente(client)
    login(client, "ofi")
    assert client.post(f"/mensajes/{m.id}/compartir").status_code == 403    # Logística no comparte
    _salir(client)
    correos = _correos(app)
    login(client, "loga")
    client.post(f"/mensajes/{m.id}/compartir", data={"nota": "¿Hay stock para el martes?"})
    assert confirmar_correos() == 1
    assert [c["To"] for c in correos] == ["ofi@ejemplo.com"]
    assert m.texto in correos[0].get_content() and "¿Hay stock para el martes?" in correos[0].get_content()
    _salir(client)
    login(client, "ofi")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert m.texto in html and "Compartido con Logística" in html
    _salir(client)
    login(client, "cliA")
    assert "Compartido con Logística" not in client.get("/mensajes/cliente/1").get_data(as_text=True)
