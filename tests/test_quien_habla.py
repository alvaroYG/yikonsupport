"""Ajustes → Qué ve cada rol → «Quién habla con los clientes»: admin decide qué roles escriben al
cliente en la conversación general y en la de cada pedido (app/apartados.py: hablar_general y
hablar_pedidos). Escenario de conftest: ofi = Almacén · fac = Facturación · loga = FAS de Clínica A."""
import re

from app.extensions import db
from app.models import Mensaje, Pedido
from tests.conftest import login, pedido_cliente
from tests.test_apartados import _como_venia, _guardar


def _salir(client):
    client.post("/auth/logout")


def _mensaje(texto):
    return db.session.scalar(db.select(Mensaje).filter_by(texto=texto))


def _escribe_el_cliente(client, texto="¿Cuándo llega el pedido?"):
    login(client, "cliA"); client.post("/mensajes/cliente/1", data={"texto": texto}); _salir(client)
    return _mensaje(texto)


def _marcada(html, valor):
    casilla = re.search(rf'<input[^>]*value="{valor}"[^>]*>', html)
    assert casilla, valor
    return " checked" in casilla.group(0)


def test_la_tabla_tiene_el_bloque_y_viene_como_hasta_ahora(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/apartados").get_data(as_text=True)
    assert "Quién habla con los clientes" in html
    assert _marcada(html, "hablar_general:fas") and not _marcada(html, "hablar_general:facturacion")
    assert not _marcada(html, "hablar_general:logistica")
    assert all(_marcada(html, f"hablar_pedidos:{rol}") for rol in ("facturacion", "logistica", "fas"))
    assert 'value="hablar_general:cliente"' not in html            # el cliente, siempre


def test_dar_la_conversacion_general_a_facturacion(app, client):
    m = _escribe_el_cliente(client)
    _guardar(client, _como_venia(app) + ["hablar_general:facturacion"])
    login(client, "fac")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert m.texto in html and 'name="texto"' in html
    client.post("/mensajes/cliente/1", data={"texto": "Os escribe Facturación"})
    assert _mensaje("Os escribe Facturación") is not None
    _salir(client)
    # ...y ya no se le ofrece «Compartir con Facturación» (ya lo ve todo); con Almacén, sí
    login(client, "loga")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert 'name="destino" value="facturacion"' not in html and 'name="destino" value="logistica"' in html


def test_almacen_con_la_general_sigue_sin_ver_los_mensajes_de_las_proformas(app, client):
    login(client, "cliA"); pedido_cliente(client, con_proforma=True)
    p = db.session.scalar(db.select(Pedido))
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Sobre la proforma"})
    _salir(client)
    m = _escribe_el_cliente(client)
    _guardar(client, _como_venia(app) + ["hablar_general:logistica"])
    login(client, "ofi")
    html = client.get("/mensajes/").get_data(as_text=True)
    assert "Sobre la proforma" not in html
    assert m.texto in client.get("/mensajes/cliente/1").get_data(as_text=True)


def test_quitar_la_general_al_soporte_de_cliente_la_deja_en_solo_lectura(app, client):
    m = _escribe_el_cliente(client)
    _guardar(client, [c for c in _como_venia(app) if c != "hablar_general:fas"])
    login(client, "loga")
    html = client.get("/mensajes/cliente/1").get_data(as_text=True)
    assert m.texto in html and 'name="texto"' not in html
    client.post("/mensajes/cliente/1", data={"texto": "No debería salir"})
    assert _mensaje("No debería salir") is None
    assert client.post("/mensajes/flotante/hilo/cliente-1", data={"texto": "Tampoco"}).status_code == 403
    _salir(client)
    login(client, "cliA")                                         # el cliente sigue escribiendo
    client.post("/mensajes/cliente/1", data={"texto": "Sigo aquí"})
    assert _mensaje("Sigo aquí") is not None


def test_quitar_los_mensajes_de_los_pedidos_a_almacen(app, client):
    login(client, "cliA"); pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "¿Sale hoy?"})
    _salir(client)
    _guardar(client, [c for c in _como_venia(app) if c != "hablar_pedidos:logistica"])
    login(client, "ofi")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "¿Sale hoy?" in html                                   # lo sigue leyendo
    assert f'action="/mensajes/pedido/{p.id}"' not in html        # pero sin formulario
    assert client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Sí"}).status_code == 403
    assert client.post(f"/mensajes/flotante/hilo/pedido-{p.id}", data={"texto": "Sí"}).status_code == 403
    # El chat interno del pedido no cambia
    client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "Nota para el equipo"})
    assert _mensaje("Nota para el equipo") is not None
    _salir(client)
    login(client, "fac")                                          # Facturación sigue pudiendo
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Os escribe Facturación"})
    assert _mensaje("Os escribe Facturación") is not None
