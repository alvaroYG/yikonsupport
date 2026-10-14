"""
Mensajes de Yikon en el botón flotante (app/mensajes/routes.py: flotante*). Mismas reglas de
alcance que el resto: cada uno, las conversaciones de sus clientes; el cliente no lo tiene.
Y la campana del cliente, con una línea por conversación.
"""
from app.extensions import db
from app.mensajes import servicio
from app.models import Cliente, Mensaje, Pedido, User
from tests.conftest import login, pedido_cliente


def _usuario(nombre):
    return db.session.scalar(db.select(User).filter_by(email=f"{nombre.lower()}@ejemplo.com"))


def _pedido(client, usuario="cliA"):
    login(client, usuario); pedido_cliente(client); client.post("/auth/logout")
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _escribe(usuario, pedido=None, texto="Hola", interno=False, cliente=None):
    servicio.enviar(_usuario(usuario), cliente or pedido.cliente, texto, pedido=pedido, interno=interno, avisar=False)
    db.session.commit()


def test_el_boton_sale_solo_para_yikon_con_sus_no_leidos(app, client):
    p = _pedido(client)
    _escribe("cliA", p, "¿Cuándo llega?")
    login(client, "admin")
    html = client.get("/").get_data(as_text=True)
    assert 'id="mensajes-flotante"' in html and 'data-mf-contador >1<' in html
    assert "mensaje sin leer" not in html and 'id="pestana-mensajes"' not in html     # ni campana ni pendientes
    assert client.get("/mensajes/flotante/cuenta").get_json() == {"sin_leer": 1}
    client.post("/auth/logout")
    login(client, "cliA")
    assert 'id="mensajes-flotante"' not in client.get("/").get_data(as_text=True)
    for url in ("/mensajes/flotante", "/mensajes/flotante/cuenta", f"/mensajes/flotante/hilo/pedido-{p.id}"):
        assert client.get(url).status_code == 403, url


def test_la_lista_pone_primero_las_no_leidas_y_separa_las_internas(app, client):
    leido, pendiente = _pedido(client), _pedido(client)
    _escribe("cliA", leido, "Mensaje viejo")
    _escribe("cliA", pendiente, "Mensaje sin leer")
    _escribe("ofi", pendiente, "Ojo con este pedido", interno=True)
    login(client, "admin")
    client.get(f"/mensajes/flotante/hilo/pedido-{leido.id}")                 # abrirlo lo da por leído
    lista = client.get("/mensajes/flotante").get_data(as_text=True)
    assert lista.index(pendiente.referencia_interna) < lista.index(leido.referencia_interna)
    assert lista.count('class="mf-conversacion sin-leer"') == 1 and "Ojo con este pedido" not in lista
    internas = client.get("/mensajes/flotante?internas=1").get_data(as_text=True)
    assert "Ojo con este pedido" in internas and "Mensaje sin leer" not in internas


def test_se_lee_y_se_responde_dentro_del_panel(app, client):
    p = _pedido(client)
    _escribe("cliA", p, "¿Cuándo llega?")
    login(client, "admin")
    hilo = client.get(f"/mensajes/flotante/hilo/pedido-{p.id}").get_data(as_text=True)
    assert "¿Cuándo llega?" in hilo and 'data-cuenta="0"' in hilo and f'/pedidos/{p.id}#mensajes' in hilo
    r = client.post(f"/mensajes/flotante/hilo/pedido-{p.id}", data={"texto": "  Sale mañana  "})
    assert r.status_code == 200 and "Sale mañana" in r.get_data(as_text=True)
    enviado = db.session.scalar(db.select(Mensaje).order_by(Mensaje.id.desc()))
    assert (enviado.texto, enviado.hilo, enviado.de_cliente, enviado.interno) == ("Sale mañana", f"pedido-{p.id}", False, False)
    r = client.post(f"/mensajes/flotante/hilo/pedido-{p.id}", data={"texto": "   "})
    assert "Escribe algo antes de enviar." in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 2
    # una nota interna, desde su conversación interna
    client.post(f"/mensajes/flotante/hilo/interno-{p.id}", data={"texto": "Solo para nosotros"})
    assert db.session.scalar(db.select(Mensaje).order_by(Mensaje.id.desc())).interno is True


def test_cada_uno_solo_abre_las_conversaciones_de_sus_clientes(app, client):
    pa, pb = _pedido(client, "cliA"), _pedido(client, "cliB")
    _escribe("cliA", pa); _escribe("cliB", pb)
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    login(client, "loga")                                                     # lleva la Clínica A
    lista = client.get("/mensajes/flotante").get_data(as_text=True)
    assert pa.referencia_interna in lista and pb.referencia_interna not in lista
    for hilo in (f"pedido-{pb.id}", f"interno-{pb.id}", f"cliente-{b.id}"):
        assert client.get(f"/mensajes/flotante/hilo/{hilo}").status_code == 404, hilo
        assert client.post(f"/mensajes/flotante/hilo/{hilo}", data={"texto": "x"}).status_code == 404, hilo
    assert client.get("/mensajes/flotante/hilo/otra-cosa").status_code == 404
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 2


def test_la_campana_del_cliente_dice_de_donde_es_cada_mensaje(app, client):
    p = _pedido(client)
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    _escribe("loga", p, "Sale mañana con SEUR")
    _escribe("loga", texto="Sí, hay stock", cliente=a)
    login(client, "cliA")
    html = client.get("/").get_data(as_text=True)
    assert f"Mensaje nuevo en {p.referencia_interna}" in html and f'href="/pedidos/{p.id}#mensajes"' in html
    assert "Mensaje nuevo de loga" in html and f'href="/mensajes/cliente/{a.id}"' in html
    assert "«Sale mañana con SEUR»" in html and "«Sí, hay stock»" in html
    # ...y desde la cabecera escribe directamente a su responsable
    assert f'href="/mensajes/cliente/{a.id}">Escribir a loga' in html
