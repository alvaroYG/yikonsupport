from app.extensions import db
from app.models import Pedido, Producto, RevisionPedido
from tests.conftest import FOTO_JPG, confirmar_correos, llevar_a_validado, login, pedido_cliente, reservar_lotes, subir_foto


def _pedido_confirmado(client, cliente="cliA", logistics="loga"):
    login(client, cliente); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    return p


def _estado(pid):
    return db.session.get(Pedido, pid).estado


def test_flujo_completo(app, client):
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    assert _estado(p.id) == "validado"
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1", "confirmar_stock": "1"})
    assert _estado(p.id) == "enviado"


def test_sin_fotos_no_se_manda_a_validar(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/enviar-validacion")
    assert _estado(p.id) == "en_preparacion"


def test_solo_imagenes_de_verdad(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin")
    r = subir_foto(client, p.id, contenido=b"esto no es una imagen", nombre="virus.jpg")
    assert len(db.session.get(Pedido, p.id).fotos) == 0
    subir_foto(client, p.id)
    assert len(db.session.get(Pedido, p.id).fotos) == 1


def test_el_cliente_nunca_ve_las_fotos(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post("/auth/logout")
    foto = db.session.get(Pedido, p.id).fotos[0]
    login(client, "cliA")
    assert client.get(f"/pedidos/{p.id}/fotos/{foto.id}").status_code == 403
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Fotos de preparación" not in html and "fotos/" not in html
    assert "En preparación" in html          # y no ve el estado interno


def test_logistics_de_otro_cliente_no_ve_las_fotos(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post("/auth/logout")
    foto = db.session.get(Pedido, p.id).fotos[0]
    login(client, "logb")
    assert client.get(f"/pedidos/{p.id}/fotos/{foto.id}").status_code == 404
    client.post("/auth/logout")
    login(client, "loga")
    r = client.get(f"/pedidos/{p.id}/fotos/{foto.id}")
    assert r.status_code == 200 and r.data == FOTO_JPG


def test_admin_puede_validar_si_logistics_no_puede(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion")
    client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"})
    assert _estado(p.id) == "validado"
    rev = db.session.scalar(db.select(RevisionPedido))
    assert "en lugar de Soporte de cliente" in rev.comentario      # queda claro quién lo hizo


def test_admin_puede_forzar_cualquier_estado(app, client):
    from app.models import RegistroAuditoria
    p = _pedido_confirmado(client)
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    r = client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1", "confirmar_stock": "1"},
                    follow_redirects=True)
    assert _estado(p.id) == "enviado"                        # en preparación → enviado sin fotos
    assert "Fuera del flujo normal" in r.get_data(as_text=True)
    ultimo = db.session.scalar(db.select(RegistroAuditoria).order_by(RegistroAuditoria.id.desc()))
    assert "CAMBIO FORZADO" in ultimo.detalle
    assert db.session.get(Producto, 1).stock == 4            # el stock se descuenta igual


def test_logistics_sigue_limitado_al_flujo(app, client):
    p = _pedido_confirmado(client)
    login(client, "loga")
    assert client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR", "numero_seguimiento": "TRK1"}).status_code == 403
    assert client.post(f"/pedidos/{p.id}/estado", data={"estado": "validado"}).status_code == 403
    assert _estado(p.id) == "en_preparacion"


def test_rechazo_exige_comentario_y_avisa_a_admin(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion")
    client.post("/auth/logout")
    login(client, "loga")
    client.post(f"/pedidos/{p.id}/validar", data={"rechazar": "1", "comentario": ""})
    assert _estado(p.id) == "en_validacion"          # sin comentario no se rechaza
    client.post(f"/pedidos/{p.id}/validar", data={"rechazar": "1", "comentario": "Falta un kit"})
    assert _estado(p.id) == "en_preparacion"             # vuelve a preparación, marcado como devuelto
    assert db.session.get(Pedido, p.id).devuelto
    rev = db.session.scalar(db.select(RevisionPedido))
    assert rev.aprobado is False and rev.comentario == "Falta un kit"
    client.post("/auth/logout")
    login(client, "admin")
    inicio = client.get("/").get_data(as_text=True)
    assert "Devueltos por Soporte de cliente" in inicio and "Falta un kit" in inicio
    # admin corrige, sube otra foto y lo reenvía
    subir_foto(client, p.id)
    client.post(f"/pedidos/{p.id}/enviar-validacion")
    assert _estado(p.id) == "en_validacion" and not db.session.get(Pedido, p.id).devuelto


def test_enviar_exige_seguimiento(app, client):
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    r = client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "confirmar_stock": "1", "transportista": "SEUR"},
                    follow_redirects=True)
    assert _estado(p.id) == "validado" and "número de seguimiento" in r.get_data(as_text=True)
    assert db.session.get(Producto, 1).stock == 5                 # no ha salido nada


def test_logistics_ve_lo_que_tiene_pendiente(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin"); subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion")
    client.post("/auth/logout")
    login(client, "loga")
    assert 'data-grupo="validar"' in client.get("/").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "logb")   # no es su cliente
    assert 'data-grupo="validar"' not in client.get("/").get_data(as_text=True)


def test_fecha_estimada_de_entrega(app, client):
    from datetime import date
    from tests.conftest import llevar_a_validado
    p = _pedido_confirmado(client)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5, "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asigna el lote
    confirmar_correos()                      # (los avisos de los pasos anteriores)
    correos = app.extensions.setdefault("correos_enviados", []); correos.clear()
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "confirmar_stock": "1",
                                                 "fecha_entrega_estimada": "2026-10-02",
                                                 "transportista": "SEUR", "numero_seguimiento": "SE123"})
    assert confirmar_correos() == 1
    assert db.session.get(Pedido, p.id).fecha_entrega_estimada == date(2026, 10, 2)
    contenido = correos[0].get_content()                        # va en el email al cliente
    assert "02/10/2026" in contenido and "SEUR" in contenido and "SE123" in contenido
    # admin la corrige → el cliente recibe otro email con la fecha nueva
    correos.clear()
    client.post(f"/pedidos/{p.id}/datos-envio", data={"envio-fecha_entrega_estimada": "2026-10-05",
                                                      "envio-transportista": "SEUR", "envio-numero_seguimiento": "SE123"})
    assert db.session.get(Pedido, p.id).fecha_entrega_estimada == date(2026, 10, 5)
    assert confirmar_correos() == 1
    assert len(correos) == 1 and "05/10/2026" in correos[0].get_content()
    assert "datos de envío actualizados" in correos[0]["Subject"]
    # guardar sin cambios no manda nada (ni deja nada para revisar)
    client.post(f"/pedidos/{p.id}/datos-envio", data={"envio-fecha_entrega_estimada": "2026-10-05",
                                                      "envio-transportista": "SEUR", "envio-numero_seguimiento": "SE123"})
    assert confirmar_correos() == 0 and len(correos) == 1
    # el enlace de seguimiento solo puede ser http(s): nada de "javascript:"
    client.post(f"/pedidos/{p.id}/datos-envio", data={"envio-fecha_entrega_estimada": "2026-10-05",
                                                      "envio-enlace_seguimiento": "javascript:alert(1)"})
    assert db.session.get(Pedido, p.id).enlace_seguimiento is None
    # no puede ser anterior a la fecha del pedido
    client.post(f"/pedidos/{p.id}/datos-envio", data={"envio-fecha_entrega_estimada": "2020-01-01"})
    assert db.session.get(Pedido, p.id).fecha_entrega_estimada == date(2026, 10, 5)
    client.post("/auth/logout")
    # el cliente la ve en la ficha y en su lista
    login(client, "cliA")
    ficha = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "05/10/2026" in ficha and "SE123" in ficha             # fecha y seguimiento
    assert "05/10/2026" in client.get("/pedidos/").get_data(as_text=True)
    # y no puede cambiarla
    assert client.post(f"/pedidos/{p.id}/datos-envio",
                       data={"envio-fecha_entrega_estimada": "2026-12-31"}).status_code == 403
