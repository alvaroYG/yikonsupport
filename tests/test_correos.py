import re

from app.extensions import db
from app.models import Pedido, User
from tests.conftest import confirmar_correos, llevar_a_validado, login, pedido_cliente, reservar_lotes, subir_foto


def _correos(app):
    return app.extensions.setdefault("correos_enviados", [])


def _pedido_confirmado(client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    confirmar_correos()                                  # admin confirma el aviso al cliente
    return p


def test_cliente_recibe_email_cuando_cambia_su_estado(app, client):
    _correos(app).clear()
    p = _pedido_confirmado(client)
    al_cliente = [m for m in _correos(app) if "clia@" in m["To"]]    # (a Yikon le llega "proforma pedida")
    assert len(al_cliente) == 1
    msg = al_cliente[0]
    assert msg["To"] == "clia@ejemplo.com" and "En preparación" in msg["Subject"]
    assert p.referencia_interna in msg.get_content()


def test_los_pasos_internos_no_mandan_email_al_cliente(app, client):
    p = _pedido_confirmado(client)
    _correos(app).clear()
    llevar_a_validado(client, p.id)          # fotos, validación...: para el cliente sigue "En preparación"
    assert [m for m in _correos(app) if "clia@" in m["To"]] == []


def test_enviado_y_entregado_avisan_al_cliente(app, client):
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    confirmar_correos()                      # (los avisos de los pasos anteriores)
    _correos(app).clear()
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1", "confirmar_stock": "1"})
    client.post(f"/pedidos/{p.id}/recibido")           # admin lo marca en nombre del cliente
    assert confirmar_correos() == 2
    asuntos = [m["Subject"] for m in _correos(app)]
    assert any("Enviado" in a for a in asuntos) and any("Recibido" in a for a in asuntos)
    enviado = next(m for m in _correos(app) if "Enviado" in m["Subject"])
    assert "TRK1" in enviado.get_content() and "Recibido" in enviado.get_content()


def test_el_cliente_marca_recibido_y_avisa_a_admin_y_logistics(app, client):
    from app.models import Mensaje
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1", "confirmar_stock": "1"})
    client.post("/auth/logout")
    _correos(app).clear()
    login(client, "cliA")
    assert "Marcar como recibido" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post(f"/pedidos/{p.id}/recibido")
    assert db.session.get(Pedido, p.id).estado == "entregado"
    [msg] = _correos(app)                               # uno para admin, Facturación y su Soporte (no al cliente)
    assert set(msg["To"].replace(" ", "").split(",")) == {"admin@ejemplo.com", "fac@ejemplo.com", "loga@ejemplo.com"}
    assert "Recibido" in msg["Subject"]
    aviso = db.session.scalar(db.select(Mensaje).filter_by(pedido_id=p.id))
    assert "recibido" in aviso.texto                    # y en la conversación del pedido (campana)
    # otro cliente o logistics no pueden marcarlo
    client.post("/auth/logout"); login(client, "loga")
    assert client.post(f"/pedidos/{p.id}/recibido").status_code == 403


def test_revisar_urgente_avisa_a_los_admins(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion")
    client.post("/auth/logout")
    confirmar_correos()                      # (el aviso de "para validar")
    _correos(app).clear()
    login(client, "loga")
    client.post(f"/pedidos/{p.id}/validar", data={"rechazar": "1", "comentario": "Falta un kit"})
    assert confirmar_correos() == 0                     # aviso entre compañeros: sale solo
    [msg] = _correos(app)
    # a quien prepara: admin y Logística
    assert set(msg["To"].split(", ")) == {"admin@ejemplo.com", "ofi@ejemplo.com"} and "Devuelto por Soporte de cliente" in msg["Subject"]
    assert "Falta un kit" in msg.get_content()


def test_sin_commit_no_hay_email(app, client):
    """Si el cambio no se guarda (p. ej. falta stock), no sale ningún correo."""
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    _correos(app).clear()
    login(client, "admin")                    # sin stock: el envío se rechaza
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1", "confirmar_stock": "1"})
    assert _correos(app) == []


def test_recuperar_contrasena(app, client):
    _correos(app).clear()
    r = client.post("/auth/olvide", data={"email": "cliA@ejemplo.com"}, follow_redirects=True)
    assert "te hemos enviado un enlace" in r.get_data(as_text=True)
    enlace = re.search(r"http://\S+/auth/restablecer/\S+", _correos(app)[0].get_content()).group(0)
    ruta = enlace.split("localhost", 1)[1]
    client.post(ruta, data={"nueva": "nuevaclave123", "confirmar": "nuevaclave123"})
    r = client.post("/auth/login", data={"email": "clia@ejemplo.com", "password": "nuevaclave123"})
    assert r.status_code == 302
    client.post("/auth/logout")
    # el mismo enlace ya no sirve una segunda vez
    r = client.get(ruta, follow_redirects=True)
    assert "no es válido o ha caducado" in r.get_data(as_text=True)


def test_email_inexistente_mismo_mensaje_y_sin_correo(app, client):
    _correos(app).clear()
    r = client.post("/auth/olvide", data={"email": "nadie@ejemplo.com"}, follow_redirects=True)
    assert "te hemos enviado un enlace" in r.get_data(as_text=True)
    assert _correos(app) == []


def test_token_falsificado(client):
    r = client.get("/auth/restablecer/esto-no-es-un-token", follow_redirects=True)
    assert "no es válido" in r.get_data(as_text=True)
