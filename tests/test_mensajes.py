"""Mensajes entre clientes y Yikon: conversación general por cliente y conversación de cada pedido."""
import re

from app.extensions import db
from app.models import Cliente, LecturaHilo, Mensaje, Pedido, User
from tests.conftest import confirmar_correos, login, pedido_cliente


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _sin_leer(client):
    """El número del menú "Mensajes" (0 si no aparece)."""
    html = client.get("/mensajes/").get_data(as_text=True)
    m = re.search(r'title="Mensajes sin leer">(\d+)<', html)
    return int(m.group(1)) if m else 0


def _salir(client):
    client.post("/auth/logout")


def _pedido_de_a(client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    return db.session.scalar(db.select(Pedido))


# ---------------------------------------------------------------- conversación general
def test_el_cliente_escribe_y_su_logistics_lo_recibe(app, client):
    correos = _correos(app)
    login(client, "cliA")
    r = client.post("/mensajes/cliente/1", data={"texto": "¿Tenéis stock de tubos?"})
    assert r.status_code == 302
    m = db.session.scalar(db.select(Mensaje))
    assert m.hilo == "cliente-1" and m.de_cliente and m.pedido_id is None
    # aviso por email solo a su logistics (no a admin ni a logb)
    assert len(correos) == 1 and correos[0]["To"] == "loga@ejemplo.com"
    assert "¿Tenéis stock de tubos?" in correos[0].get_content()
    assert "/mensajes/cliente/1" in correos[0].get_content()
    assert _sin_leer(client) == 0                     # lo que escribes tú no es "sin leer"
    _salir(client)

    login(client, "loga")
    assert _sin_leer(client) == 1
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert "¿Tenéis stock de tubos?" in html
    assert _sin_leer(client) == 0                     # al abrirla, queda leída
    client.post("/mensajes/cliente/1", data={"texto": "Sí, os mandamos 2 cajas."})
    _salir(client)

    login(client, "cliA")
    assert _sin_leer(client) == 1
    assert "Sí, os mandamos 2 cajas." in client.get("/mensajes/cliente/1").get_data(as_text=True)


def test_sin_logistics_asignado_avisa_a_los_admin(app, client):
    db.session.get(Cliente, 1).logisticos = []
    db.session.commit()
    correos = _correos(app)
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "Hola"})
    assert [c["To"] for c in correos] == ["admin@ejemplo.com"]


def test_un_solo_aviso_hasta_que_lo_lee(app, client):
    """Tres mensajes seguidos → un email. Cuando lo lee, el siguiente vuelve a avisar."""
    correos = _correos(app)
    login(client, "cliA")
    for texto in ["uno", "dos", "tres"]:
        client.post("/mensajes/cliente/1", data={"texto": texto})
    assert len(correos) == 1
    _salir(client); login(client, "loga")
    client.get("/mensajes/cliente/1")
    _salir(client); login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "cuatro"})
    assert len(correos) == 2


def test_cada_cliente_solo_ve_lo_suyo(app, client):
    p = _pedido_de_a(client)
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "secreto de A"})
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "pedido de A"})
    _salir(client)
    for usuario in ["cliB", "logb"]:
        login(client, usuario)
        assert client.get("/mensajes/cliente/1").status_code == 404
        assert client.get("/mensajes/cliente/1/nuevos").status_code == 404
        assert client.get(f"/mensajes/pedido/{p.id}/nuevos").status_code == 404
        assert client.post("/mensajes/cliente/1", data={"texto": "intruso"}).status_code == 404
        assert client.post(f"/mensajes/pedido/{p.id}", data={"texto": "intruso"}).status_code == 404
        html = client.get("/mensajes/").get_data(as_text=True)
        assert "secreto de A" not in html and "pedido de A" not in html
        assert _sin_leer(client) == 0
        _salir(client)
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 2
    # el cliente no puede "colarse" en la conversación de otra empresa aunque la pida por filtro
    login(client, "cliB")
    assert "secreto de A" not in client.get("/mensajes/?cliente_id=1").get_data(as_text=True)


def test_mensaje_vacio_largo_o_con_html(app, client):
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "   \n  "})
    client.post("/mensajes/cliente/1", data={"texto": "x" * 5001})
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 0
    client.post("/mensajes/cliente/1", data={"texto": "<script>alert(1)</script>\nsegunda línea"})
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ---------------------------------------------------------------- conversación del pedido
def test_conversacion_dentro_del_pedido(app, client):
    p = _pedido_de_a(client)
    correos = _correos(app)
    login(client, "cliA")
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "¿Podéis añadir 2 tubos?"})
    assert db.session.scalar(db.select(Mensaje)).hilo == f"pedido-{p.id}"
    assert f"/pedidos/{p.id}#mensajes" in correos[0].get_content()
    assert p.referencia_interna in correos[0]["Subject"]
    _salir(client)

    login(client, "loga")
    # en la lista de pedidos, el pedido lleva su contador de mensajes sin leer
    assert f'href="/pedidos/{p.id}#mensajes"' in client.get("/pedidos/").get_data(as_text=True)
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "¿Podéis añadir 2 tubos?" in html and 'id="mensajes"' in html
    assert "Enviar al cliente" in html and "lo verá en la plataforma" in html     # dice a quién va
    # Abrir la ficha no lo da por leído: hay que abrir el chat (el botón "Cliente" lleva el contador)
    assert _sin_leer(client) == 1 and "data-contador-chat" in html
    client.get(f"/mensajes/pedido/{p.id}/nuevos?despues=999999&abierto=1")       # abre el chat
    assert _sin_leer(client) == 0
    assert f'href="/pedidos/{p.id}#mensajes"' not in client.get("/pedidos/").get_data(as_text=True)
    # aparece en la lista de conversaciones
    assert "¿Podéis añadir 2 tubos?" in client.get("/mensajes/").get_data(as_text=True)


def test_los_mensajes_de_un_companero_no_son_pendientes(app, client):
    """Admin escribe al cliente: para loga (mismo lado, Yikon) no es un mensaje sin leer."""
    login(client, "admin")
    client.post("/mensajes/cliente/1", data={"texto": "Os escribe admin"})
    _salir(client)
    login(client, "loga")
    assert _sin_leer(client) == 0
    _salir(client)
    login(client, "cliA")
    assert _sin_leer(client) == 1


def test_mensajes_nuevos_sin_recargar(app, client):
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "primero"})
    primero = db.session.scalar(db.select(Mensaje)).id
    _salir(client)
    login(client, "loga")
    r = client.get(f"/mensajes/cliente/1/nuevos?despues={primero}").get_json()
    assert r["html"].strip() == "" and r["ultimo"] == primero
    assert _sin_leer(client) == 1                  # no ha llegado nada nuevo: no marca nada
    r = client.get("/mensajes/cliente/1/nuevos?despues=0").get_json()
    assert "primero" in r["html"] and r["ultimo"] == primero
    assert _sin_leer(client) == 0                  # lo ha visto en pantalla


def test_un_usuario_nuevo_no_hereda_pendientes_antiguos(app, client):
    from datetime import timedelta
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "antiguo"})
    _salir(client)
    m = db.session.scalar(db.select(Mensaje))
    m.fecha = m.fecha - timedelta(days=30)
    nuevo = User(nombre="Nueva", email="nueva@ejemplo.com", rol="fas",
                 clientes_asignados=[db.session.get(Cliente, 1)])
    nuevo.set_password("password123")
    db.session.add(nuevo); db.session.commit()
    login(client, "nueva")
    assert _sin_leer(client) == 0
    assert "antiguo" in client.get("/mensajes/cliente/1").get_data(as_text=True)   # pero la ve


def test_aviso_en_el_idioma_de_cada_uno(app, client):
    db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma = "en"
    db.session.commit()
    correos = _correos(app)
    login(client, "loga")
    client.post("/mensajes/cliente/1", data={"texto": "Hola"})
    assert confirmar_correos() == 1
    assert correos[0]["To"] == "clia@ejemplo.com" and "New message" in correos[0]["Subject"]


def test_quien_escribe_lo_tiene_leido(app, client):
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "hola"})
    lectura = db.session.scalar(db.select(LecturaHilo).filter_by(hilo="cliente-1"))
    assert lectura.ultimo_mensaje_id == db.session.scalar(db.select(Mensaje)).id


# ---------------------------------------------------------------- revisión
def test_usuario_nuevo_y_logistics_reasignado_si_reciben_aviso(app, client):
    """Antes: si había mensajes antiguos sin leer "por él", nunca le llegaba el email."""
    correos = _correos(app)
    login(client, "cliA")
    client.post("/mensajes/cliente/1", data={"texto": "primero"})        # avisa a loga
    db.session.get(Cliente, 1).logisticos = [db.session.scalar(db.select(User).filter_by(email="logb@ejemplo.com"))]
    db.session.commit()
    correos.clear()
    client.post("/mensajes/cliente/1", data={"texto": "segundo"})
    assert [c["To"] for c in correos] == ["logb@ejemplo.com"]
    _salir(client)
    # usuario cliente creado después de una respuesta de Yikon: el siguiente mensaje sí le avisa
    login(client, "logb"); client.post("/mensajes/cliente/1", data={"texto": "respuesta"}); _salir(client)
    confirmar_correos()
    nuevo = User(nombre="cliA2", email="clia2@ejemplo.com", rol="cliente", empresa=db.session.get(Cliente, 1))
    nuevo.set_password("password123"); db.session.add(nuevo); db.session.commit()
    correos.clear()
    login(client, "logb"); client.post("/mensajes/cliente/1", data={"texto": "otra"})
    assert confirmar_correos() == 1
    assert "clia2@ejemplo.com" in correos[0]["To"]


def test_parametro_despues_absurdo_no_da_error(app, client):
    login(client, "cliA")
    for valor in ["99999999999999999999", "-5", "abc"]:
        r = client.get(f"/mensajes/cliente/1/nuevos?despues={valor}")
        assert r.status_code == 200 and "html" in r.get_json()


# ---------------------------------------------------------------- archivos adjuntos
def _con_archivos(client, url, texto="", archivos=()):
    from io import BytesIO
    datos = {"texto": texto, "adjuntos": [(BytesIO(contenido), nombre) for nombre, contenido in archivos]}
    return client.post(url, data=datos, content_type="multipart/form-data")


def test_adjuntos_en_un_mensaje(app, client):
    from app.models import AdjuntoMensaje
    p = _pedido_de_a(client)
    correos = _correos(app)
    login(client, "cliA")
    _con_archivos(client, f"/mensajes/pedido/{p.id}", "Os mando la orden",
                  [("orden.pdf", b"%PDF-1.4 x"), ("foto.jpg", b"\xff\xd8\xff" + b"0" * 50)])
    adjuntos = db.session.scalars(db.select(AdjuntoMensaje)).all()
    assert [a.nombre_original for a in adjuntos] == ["orden.pdf", "foto.jpg"]
    assert "orden.pdf" in correos[0].get_content()
    # solo archivo, sin texto: también vale
    _con_archivos(client, "/mensajes/cliente/1", "", [("albaran.pdf", b"%PDF x")])
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 2
    _salir(client)
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "orden.pdf" in html
    r = client.get(f"/mensajes/adjunto/{adjuntos[0].id}")
    assert r.status_code == 200 and r.data == b"%PDF-1.4 x" and "attachment" in r.headers["Content-Disposition"]
    assert "📎 albaran.pdf" in client.get("/mensajes/").get_data(as_text=True)
    _salir(client)
    for usuario in ["cliB", "logb"]:
        login(client, usuario)
        assert client.get(f"/mensajes/adjunto/{adjuntos[0].id}").status_code == 404
        _salir(client)


def test_adjuntos_no_validos_no_guardan_nada(app, client):
    from app.models import AdjuntoMensaje
    login(client, "cliA")
    # un archivo peligroso junto a uno bueno: no se guarda ninguno (ni el mensaje)
    r = _con_archivos(client, "/mensajes/cliente/1", "hola", [("ok.pdf", b"%PDF"), ("virus.exe", b"MZ")])
    assert "tipo no admitido" in r.get_data(as_text=True)
    assert 'hola</textarea>' in r.get_data(as_text=True)       # conserva lo escrito
    r = _con_archivos(client, "/mensajes/cliente/1", "hola", [(f"{i}.pdf", b"%PDF") for i in range(6)])
    assert "Como máximo 5 archivos" in r.get_data(as_text=True)
    _con_archivos(client, "/mensajes/cliente/1", "", [])          # ni texto ni archivo
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 0
    assert db.session.scalar(db.select(db.func.count(AdjuntoMensaje.id))) == 0


# ---------------------------------------------------------------- mensaje nuevo (admin/logistics)
def test_mensaje_nuevo_desde_la_pagina_de_mensajes(app, client):
    login(client, "loga")
    html = client.get("/mensajes/").get_data(as_text=True)
    assert "Mensaje nuevo" in html and 'id="modal-mensaje-nuevo"' in html
    assert "Clínica A" in html and "Clínica B" not in html            # solo sus clientes en la lista
    r = client.post("/mensajes/", data={"cliente_id": 1, "texto": "Hola, os escribimos por la renovación"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/mensajes/cliente/1")
    m = db.session.scalar(db.select(Mensaje))
    assert m.hilo == "cliente-1" and not m.de_cliente
    # sin cliente o sin texto: se reabre la ventana con el error y lo escrito
    r = client.post("/mensajes/", data={"cliente_id": 0, "texto": "sin cliente"})
    assert "data-abrir-al-cargar" in r.get_data(as_text=True) and "Elige el cliente." in r.get_data(as_text=True)
    # un cliente que no es suyo: no
    assert client.post("/mensajes/", data={"cliente_id": 2, "texto": "x"}).status_code in (200, 404)
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 1
    _salir(client)
    login(client, "cliA")                                              # el cliente no tiene esta ventana
    assert "modal-mensaje-nuevo" not in client.get("/mensajes/").get_data(as_text=True)
    assert client.post("/mensajes/", data={"cliente_id": 1, "texto": "x"}).status_code == 403
