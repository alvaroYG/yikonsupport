"""Conversación INTERNA de cada pedido: solo admin y logistics. El cliente no la ve nunca."""
from io import BytesIO

from app.extensions import db
from app.models import AdjuntoMensaje, Mensaje, Pedido
from tests.conftest import confirmar_correos, login, pedido_cliente

SECRETO = "Ojo: el lote PA2409 está justo de caducidad"


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _salir(client):
    client.post("/auth/logout")


def _pedido_de_a(client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    return db.session.scalar(db.select(Pedido))



def _flotante(client, internas=False):
    """Las pestañas del botón flotante de mensajes (donde Yikon ve sus no leídos: ya no van en la campana)."""
    html = client.get("/mensajes/flotante" + ("?internas=1" if internas else "")).get_data(as_text=True)
    return " ".join(html.split())


def test_admin_escribe_y_logistics_lo_recibe_pero_el_cliente_no(app, client):
    p = _pedido_de_a(client)
    correos = _correos(app)
    login(client, "admin")
    r = client.post(f"/mensajes/pedido/{p.id}/interno", content_type="multipart/form-data",
                    data={"texto": SECRETO, "adjuntos": (BytesIO(b"%PDF-1.4 x"), "nota.pdf")})
    assert r.status_code == 302 and r.headers["Location"].endswith("#interno")
    m = db.session.scalar(db.select(Mensaje))
    assert m.interno and m.hilo == f"interno-{p.id}"
    assert confirmar_correos() == 0                     # aviso entre compañeros: sale solo
    # email a su logistics (loga), no al cliente ni a logb
    destinatarios = {d.strip() for c in correos for d in c["To"].split(",")}
    assert destinatarios == {"loga@ejemplo.com"}
    assert "conversación interna" in correos[0]["Subject"]
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert SECRETO in html and "Chat interno" in html
    # Va en su propio botón y su propia ventana, que dice que el cliente no lo ve y "Guardar nota"
    assert 'data-abre-chat="interno"' in html and "el cliente no ve esto" in html and "Guardar nota" in html
    panel = html.split('id="interno"')[1].split("</section>")[0]
    assert SECRETO in panel and "Enviar al cliente" not in panel
    _salir(client)

    login(client, "loga")
    assert 'Internas <span class="cuenta">1</span>' in _flotante(client)            # en el botón flotante
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)                  # el botón "Interno" con su contador
    boton = html.split('data-abre-chat="interno"')[1].split("</button>")[0]
    assert "data-contador-chat>1" in boton
    assert "Interna · pedido" in client.get("/mensajes/?internas=1").get_data(as_text=True)
    client.get(f"/mensajes/pedido/{p.id}/interno/nuevos?despues=999999&abierto=1")  # abre el chat interno
    assert 'Internas <span class="cuenta">0</span>' in _flotante(client)            # leída
    boton = client.get(f"/pedidos/{p.id}").get_data(as_text=True).split('data-abre-chat="interno"')[1].split("</button>")[0]
    assert "data-contador-chat" not in boton
    _salir(client)

    login(client, "cliA")                                            # el cliente: nada de nada
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert SECRETO not in html and "Chat interno" not in html and "chat-interno" not in html
    assert SECRETO not in client.get("/mensajes/").get_data(as_text=True)
    assert "nota interna" not in client.get("/").get_data(as_text=True)
    assert client.get(f"/mensajes/pedido/{p.id}/interno/nuevos").status_code == 403
    assert client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "hola"}).status_code == 403
    adjunto = db.session.scalar(db.select(AdjuntoMensaje))
    assert client.get(f"/mensajes/adjunto/{adjunto.id}").status_code == 404
    assert SECRETO not in client.get(f"/mensajes/pedido/{p.id}/nuevos").get_data(as_text=True)


def test_logistics_escribe_y_admin_lo_ve_en_el_boton_flotante(app, client):
    p = _pedido_de_a(client)
    login(client, "loga"); client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "¿Lo preparas hoy?"})
    _salir(client)
    login(client, "admin")
    html = _flotante(client)
    assert 'Internas <span class="cuenta">1</span>' in html
    assert 'Clientes <span class="cuenta">0</span>' in html     # no se mezcla con los mensajes del cliente
    # al responder, lo suyo no le cuenta como pendiente (y lo anterior queda leído)
    client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "Sí, esta tarde"})
    assert 'Internas <span class="cuenta">0</span>' in _flotante(client)
    _salir(client)
    login(client, "logb")                            # logistics de otro cliente: ni la ve ni escribe
    assert client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "x"}).status_code == 404
    assert client.get(f"/mensajes/pedido/{p.id}/interno/nuevos").status_code == 404


def test_los_mensajes_con_el_cliente_siguen_igual(app, client):
    p = _pedido_de_a(client)
    login(client, "cliA"); client.post(f"/mensajes/pedido/{p.id}", data={"texto": "¿Cuándo llega?"}); _salir(client)
    login(client, "loga")
    html = _flotante(client)
    assert 'Clientes <span class="cuenta">1</span>' in html and 'Internas <span class="cuenta">0</span>' in html
    m = db.session.scalar(db.select(Mensaje))
    assert not m.interno and m.hilo == f"pedido-{p.id}"
