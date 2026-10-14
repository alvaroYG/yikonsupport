"""Paso 92 · Incidencias: «Hay un problema con este pedido» (app/incidencias.py)."""
from io import BytesIO

from app.extensions import db
from app.models import Incidencia, Mensaje, Pedido
from conftest import FOTO_JPG, login, pedido_cliente


def _pedido_enviado(client):
    login(client, "cliA")
    pedido_cliente(client)
    client.post("/auth/logout")
    pedido = db.session.scalar(db.select(Pedido))
    pedido.estado = "enviado"
    db.session.commit()
    return pedido


def _avisar(client, pedido_id, motivo="danado", texto="La caja llegó abollada", fotos=()):
    datos = {"motivo": motivo, "texto": texto,
             "fotos": [(BytesIO(contenido), nombre) for nombre, contenido in fotos]}
    return client.post(f"/pedidos/{pedido_id}/incidencias", data=datos, content_type="multipart/form-data")


def test_el_cliente_avisa_de_un_problema_con_fotos_y_va_al_chat_y_a_yikon(app, client):
    pedido = _pedido_enviado(client)
    app.extensions["correos_enviados"] = []
    login(client, "cliA")
    html = client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    assert "Hay un problema con este pedido" in html and 'id="modal-incidencia"' in html
    r = _avisar(client, pedido.id, fotos=[("caja.jpg", FOTO_JPG)])
    assert r.status_code == 302
    inc = db.session.scalar(db.select(Incidencia))
    assert inc.abierta and inc.motivo == "danado" and len(inc.fotos) == 1
    # El texto y la foto van al chat del pedido, como mensaje del cliente
    mensaje = db.session.get(Mensaje, inc.mensaje_id)
    assert mensaje.pedido_id == pedido.id and mensaje.de_cliente and "La caja llegó abollada" in mensaje.texto
    # Email: al Soporte de cliente (loga) y a Logística (ofi), con el aviso de incidencia (no el de "mensaje nuevo")
    correos = app.extensions["correos_enviados"]
    assert len(correos) == 1 and "Problema con el pedido" in correos[0]["Subject"]
    assert "loga@ejemplo.com" in correos[0]["To"] and "ofi@ejemplo.com" in correos[0]["To"]
    assert "admin@ejemplo.com" not in correos[0]["To"]
    client.post("/auth/logout")

    # Yikon: aviso en la ficha, en la campana y en Pendientes
    login(client, "loga")
    ficha = client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    assert "Problema abierto: Llegó dañado" in ficha and "Ver y resolver" in ficha
    inicio = client.get("/").get_data(as_text=True)
    assert "Incidencias abiertas" in inicio and "Problema en" in inicio
    # ...el FAS de otro cliente no la ve
    client.post("/auth/logout")
    login(client, "logb")
    assert "Problema en" not in client.get("/").get_data(as_text=True)


def test_yikon_la_resuelve_con_una_nota_que_le_llega_al_cliente(app, client):
    pedido = _pedido_enviado(client)
    login(client, "cliA")
    _avisar(client, pedido.id, motivo="falta", texto="Faltan los tubos")
    client.post("/auth/logout")
    inc = db.session.scalar(db.select(Incidencia))
    login(client, "ofi")
    # Sin nota no se cierra
    client.post(f"/pedidos/{pedido.id}/incidencias/{inc.id}/resolver", data={"nota": " "})
    assert db.session.get(Incidencia, inc.id).abierta
    client.post(f"/pedidos/{pedido.id}/incidencias/{inc.id}/resolver", data={"nota": "Os mandamos los tubos hoy"})
    inc = db.session.get(Incidencia, inc.id)
    assert not inc.abierta and inc.nota_resolucion == "Os mandamos los tubos hoy"
    ultimo = db.session.scalar(db.select(Mensaje).order_by(Mensaje.id.desc()))
    assert not ultimo.de_cliente and "Os mandamos los tubos hoy" in ultimo.texto
    client.post("/auth/logout")
    login(client, "cliA")
    html = client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    assert "Resuelta" in html and "Os mandamos los tubos hoy" in html


def test_solo_en_pedidos_enviados_o_recibidos_y_solo_el_cliente_de_ese_pedido(app, client):
    login(client, "cliA")
    pedido_cliente(client)
    pedido = db.session.scalar(db.select(Pedido))       # "aceptado": aún no ha salido
    assert "Hay un problema con este pedido" not in client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    _avisar(client, pedido.id)
    assert db.session.scalar(db.select(db.func.count(Incidencia.id))) == 0
    pedido.estado = "entregado"
    db.session.commit()
    client.post("/auth/logout")
    login(client, "cliB")                                # otro cliente: ni lo ve
    assert _avisar(client, pedido.id).status_code == 404
    client.post("/auth/logout")
    login(client, "loga")                                # Yikon no abre incidencias
    assert _avisar(client, pedido.id).status_code == 403


def test_las_fotos_tienen_que_ser_fotos(app, client):
    pedido = _pedido_enviado(client)
    login(client, "cliA")
    r = _avisar(client, pedido.id, fotos=[("virus.jpg", b"MZ esto no es una foto")], )
    assert r.status_code == 302
    assert db.session.scalar(db.select(db.func.count(Incidencia.id))) == 0
    r = client.get(f"/pedidos/{pedido.id}")
    assert "no parece una foto" in r.get_data(as_text=True)
