"""15/10/2026 · El cliente modifica o cancela su pedido mientras no ha aceptado la proforma
(«Modificar pedido» / «Cancelar pedido» en la ficha). Si ya tenía la proforma, al modificar se
retira y Facturación recibe un aviso. Escenario de conftest: cliA (Clínica A, su Soporte = loga) ·
fac = Facturación · kit K1 = 1 × P1 (100 €)."""
from app.extensions import db
from app.models import Mensaje, Pedido
from tests.conftest import contenido, login, pdf_proforma, pedido_cliente


def _salir(client):
    client.post("/auth/logout")


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _proforma(client):
    login(client, "cliA"); pedido_cliente(client, referencia="OC-1", con_proforma=True); _salir(client)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _enviar_proforma(client, p):
    from datetime import date, timedelta
    login(client, "fac")
    client.post(f"/pedidos/{p.id}/proforma/enviar", data={
        "valida_hasta": (date.today() + timedelta(days=30)).isoformat(), "pdf": pdf_proforma()})
    _salir(client)


def _modificar(client, p, kits=2, referencia="OC-1"):
    return client.post(f"/pedidos/{p.id}/modificar", data={
        "contenido": contenido([(1, kits, {1: kits})]), "fecha": "2026-10-20", "referencia": referencia,
        "uso": "ruo"})


def _destinatarios(correos, asunto):
    return {d.strip() for c in correos if asunto in c["Subject"] for d in c["To"].split(",")}


def test_modifica_antes_de_la_proforma(app, client):
    p = _proforma(client)
    correos = _correos(app)
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert 'data-bs-target="#modal-modificar"' in html and 'id="modal-cancelar"' in html
    assert _modificar(client, p, kits=3, referencia="OC-1b").status_code == 302      # sin documento: vale
    p = db.session.get(Pedido, p.id)
    assert p.estado == "proforma_solicitada" and p.kits[0].cantidad == 3 and p.referencia == "OC-1b"
    assert str(p.fecha) == "2026-10-20"
    assert _destinatarios(correos, "Pedido modificado por el cliente") == {"fac@ejemplo.com", "loga@ejemplo.com"}
    assert db.session.scalar(db.select(Mensaje).where(Mensaje.pedido_id == p.id, Mensaje.texto.like("He modificado%")))


def test_con_la_proforma_enviada_se_retira_y_se_avisa(app, client):
    login(client, "admin")                     # stock, para que la proforma reserve un lote
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 10,
                                                "lote": "L1", "caducidad": "2099-12-31"})
    _salir(client)
    p = _proforma(client)
    _enviar_proforma(client, p)
    p = db.session.get(Pedido, p.id)
    assert p.estado == "proforma_enviada" and p.reservas
    correos = _correos(app)
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Al guardar se retira la proforma" in html
    _modificar(client, p, kits=2)
    db.session.expire_all()
    p = db.session.get(Pedido, p.id)
    assert p.estado == "cambios_solicitados" and p.kits[0].cantidad == 2
    assert p.proforma_actual.estado == "cambios" and "proforma nueva" in p.proforma_actual.comentario_cambios
    assert not p.reservas                      # los lotes se vuelven a proponer con la nueva
    aviso = [c for c in correos if "Pedido modificado por el cliente" in c["Subject"]]
    assert aviso and "se ha retirado" in aviso[0].get_content() and "Antes llevaba: 1 × Kit uno" in aviso[0].get_content()
    # Puede seguir modificando mientras tanto (sigue sin aceptar)
    assert _modificar(client, p, kits=4).status_code == 302
    assert db.session.get(Pedido, p.id).kits[0].cantidad == 4


def test_se_conservan_los_precios_que_puso_yikon(app, client):
    p = _proforma(client)
    login(client, "fac")
    kp = p.kits[0]
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "80", f"cantidad_kit_{kp.id}": "1",
                                                  f"cantidad_linea_{kp.lineas[0].id}": "1"})
    _salir(client)
    assert float(db.session.get(Pedido, p.id).kits[0].precio_unitario) == 80
    login(client, "cliA")
    _modificar(client, p, kits=2)
    p = db.session.get(Pedido, p.id)
    assert float(p.kits[0].precio_unitario) == 80 and float(p.base_imponible) == 160


def test_cancela_con_motivo_y_se_avisa(app, client):
    p = _proforma(client)
    _enviar_proforma(client, p)
    correos = _correos(app)
    login(client, "cliA")
    assert client.post(f"/pedidos/{p.id}/cancelar", data={"motivo": "Ya no lo necesitamos"}).status_code == 302
    p = db.session.get(Pedido, p.id)
    assert p.estado == "cancelado" and p.proformas[0].estado == "retirada"
    assert db.session.scalar(db.select(Mensaje).where(Mensaje.pedido_id == p.id, Mensaje.texto.like("%Ya no lo necesitamos%")))
    aviso = [c for c in correos if "Pedido cancelado por el cliente" in c["Subject"]]
    assert _destinatarios(correos, "Pedido cancelado por el cliente") == {"fac@ejemplo.com", "loga@ejemplo.com"}
    assert "Ya no lo necesitamos" in aviso[0].get_content()
    assert "modal-modificar" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_sin_motivo_tambien(app, client):
    p = _proforma(client)
    login(client, "cliA")
    client.post(f"/pedidos/{p.id}/cancelar")
    assert db.session.get(Pedido, p.id).estado == "cancelado"


def test_aceptado_ya_no_y_solo_el_suyo(app, client):
    p = _proforma(client)
    login(client, "cliB")                                  # otro cliente: ni lo ve
    assert _modificar(client, p).status_code == 404
    assert client.post(f"/pedidos/{p.id}/cancelar").status_code == 404
    _salir(client)
    login(client, "fac")                                   # Yikon no usa estas rutas (tiene las suyas)
    assert _modificar(client, p).status_code == 403
    _salir(client)
    _enviar_proforma(client, p)
    login(client, "cliA")
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"})
    assert db.session.get(Pedido, p.id).estado == "aceptado"
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "modal-modificar" not in html and "modal-cancelar" not in html and "¿Necesita cambiar algo?" in html
    _modificar(client, p, kits=5)
    client.post(f"/pedidos/{p.id}/cancelar")
    p = db.session.get(Pedido, p.id)
    assert p.estado == "aceptado" and p.kits[0].cantidad == 1


def test_la_referencia_no_puede_ser_la_de_otro_pedido(app, client):
    p = _proforma(client)
    login(client, "cliA")
    pedido_cliente(client, referencia="OC-2", con_proforma=True)
    r = _modificar(client, p, referencia="OC-2")
    assert r.status_code == 200 and "Ya hay un pedido con esa referencia" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).referencia == "OC-1"


def test_los_avisos_salen_en_ajustes(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/avisos-internos").get_data(as_text=True)
    assert 'value="pedido_modificado:facturacion"' in html and 'value="pedido_cancelado:fas"' in html


def test_guardar_sin_cambiar_nada_no_retira_la_proforma(app, client):
    p = _proforma(client)
    _enviar_proforma(client, p)
    correos = _correos(app)
    login(client, "cliA")
    r = client.post(f"/pedidos/{p.id}/modificar", data={"contenido": contenido([(1, 1, {1: 1})]),
                                                       "fecha": p.fecha.isoformat(), "referencia": "OC-1",
                                                       "uso": "ruo"},
                    follow_redirects=True)
    assert "No ha cambiado nada" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "proforma_enviada" and not correos
