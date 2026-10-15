"""Proforma antes del pedido: el cliente la pide, Yikon la envía, el cliente la acepta o pide cambios."""
from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import Mensaje, Pedido, Proforma
from tests.conftest import doc_pedido, confirmar_correos, login, pedido_cliente, pdf_proforma
from tests.test_inventario import _entrada


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _salir(client):
    client.post("/auth/logout")


def _pedir(client):
    login(client, "cliA"); pedido_cliente(client, con_proforma=True); _salir(client)
    return db.session.scalar(db.select(Pedido))


def _enviar(client, p, **extra):
    datos = {"valida_hasta": (date.today() + timedelta(days=30)).isoformat(),
             "plazo_entrega": "5-7 días laborables", "notas": "Transporte refrigerado", "pdf": pdf_proforma()}
    datos.update(extra)
    return client.post(f"/pedidos/{p.id}/proforma/enviar", data={k: v for k, v in datos.items() if v is not None})


def test_flujo_completo_hasta_el_pedido(app, client):
    login(client, "admin"); _entrada(client, 10); _salir(client)     # lote con caducidad para P1
    p = _pedir(client)
    assert p.estado == "proforma_solicitada"
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Enviar proforma al cliente" in html and "Empezar preparación" not in html
    correos = _correos(app)
    _enviar(client, p)
    assert confirmar_correos() == 1
    db.session.refresh(p)
    pf = p.proforma_actual
    assert p.estado == "proforma_enviada" and pf.numero == f"PF-{p.referencia_interna}"
    assert [(l.referencia, l.cantidad) for l in pf.lineas] == [("P1", 1)] and pf.lineas[0].caducidad is not None
    assert correos and correos[0]["To"] == "clia@ejemplo.com" and "proforma" in correos[0].get_content().lower()
    _salir(client)

    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Aceptar y hacer el pedido" in html and pf.numero in html
    assert "100" not in html.split('id="proforma"')[1].split("</section>")[0]      # sin precios
    r = client.get(f"/pedidos/{p.id}/proforma/{pf.id}.pdf")
    assert r.data == b"%PDF-1.4 proforma de Yikon"                     # el PDF que adjuntó Yikon
    assert client.get(f"/pedidos/{p.id}/proforma/modelo.pdf").status_code == 403   # el modelo, solo Yikon
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"})
    db.session.refresh(p); db.session.refresh(pf)
    assert p.estado == "aceptado" and pf.estado == "aceptada" and pf.respondida_por.email == "clia@ejemplo.com"
    _salir(client)
    # y sigue el flujo: admin lo empieza a preparar (con el botón de la ficha)
    login(client, "admin")
    assert "Empezar preparación" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post(f"/pedidos/{p.id}/preparacion")
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"


def test_pedir_cambios_y_segunda_version(app, client):
    p = _pedir(client)
    login(client, "loga"); _enviar(client, p); _salir(client)
    correos = _correos(app)
    login(client, "cliA")
    r = client.post(f"/pedidos/{p.id}/proforma/responder", data={"cambios": "1", "comentario": ""})
    assert db.session.get(Pedido, p.id).estado == "proforma_enviada"      # sin explicar qué, no vale
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"cambios": "1", "comentario": "Quitad los tubos"})
    db.session.refresh(p)
    assert p.estado == "cambios_solicitados" and p.proformas[0].estado == "cambios"
    m = db.session.scalar(db.select(Mensaje))
    assert "Quitad los tubos" in m.texto and m.pedido_id == p.id        # queda en los mensajes del pedido
    assert [c["To"] for c in correos] == ["fac@ejemplo.com, loga@ejemplo.com"]   # a Facturación y su Soporte, no al cliente
    _salir(client)
    login(client, "loga")
    seccion = client.get(f"/pedidos/{p.id}").get_data(as_text=True).split('id="proforma"')[1].split("</section>")[0]
    assert "Quitad los tubos" in seccion and 'data-abre-chat="mensajes"' in seccion   # a la vista, y el chat a mano
    _enviar(client, p)
    db.session.refresh(p)
    assert p.estado == "proforma_enviada" and p.proforma_actual.version == 2
    assert p.proforma_actual.numero == f"PF-{p.referencia_interna}-v2"


def test_sin_pdf_no_se_envia(app, client):
    p = _pedir(client)
    login(client, "loga")
    assert client.get(f"/pedidos/{p.id}/proforma/modelo.pdf").data.startswith(b"%PDF")   # el modelo para hacerla
    _enviar(client, p, pdf=None)
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"
    _enviar(client, p, pdf=(BytesIO(b"no soy un pdf"), "proforma.pdf"))
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"
    _enviar(client, p)
    assert db.session.get(Pedido, p.id).estado == "proforma_enviada"


def test_quien_puede_hacer_que(app, client):
    p = _pedir(client)
    login(client, "cliA")
    assert client.post(f"/pedidos/{p.id}/proforma/enviar", data={}).status_code == 403     # el cliente no la envía
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 403
    _salir(client)
    login(client, "logb")                                                   # logistics de otro cliente
    assert _enviar(client, p).status_code == 404
    _salir(client)
    login(client, "loga")
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 403   # no se salta la proforma
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"
    _enviar(client, p)
    assert client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}).status_code == 403
    pf = db.session.scalar(db.select(Proforma))
    _salir(client)
    login(client, "cliB")
    assert client.get(f"/pedidos/{p.id}/proforma/{pf.id}.pdf").status_code == 404
    assert client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}).status_code == 404


def test_retirar_y_proforma_caducada(app, client):
    p = _pedir(client)
    login(client, "loga")
    r = _enviar(client, p, valida_hasta=(date.today() - timedelta(days=1)).isoformat())
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"       # fecha pasada: no se envía
    _enviar(client, p)
    client.post(f"/pedidos/{p.id}/proforma/retirar")
    db.session.refresh(p)
    assert p.estado == "proforma_solicitada" and p.proformas[0].estado == "retirada"
    _enviar(client, p)
    pf = db.session.get(Pedido, p.id).proforma_actual
    pf.valida_hasta = date.today() - timedelta(days=1)                     # ha pasado la fecha
    db.session.commit()
    _salir(client)
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "caducó" in html and "Aceptar y hacer el pedido" not in html
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"})
    assert db.session.get(Pedido, p.id).estado == "proforma_enviada"


def test_la_proforma_es_una_foto_fija(app, client):
    """Si después cambia el pedido, la proforma enviada no cambia."""
    p = _pedir(client)
    login(client, "loga"); _enviar(client, p)
    pf = db.session.get(Pedido, p.id).proforma_actual
    client.post(f"/pedidos/{p.id}/proforma/retirar")
    linea = db.session.get(Pedido, p.id).lineas[0]
    client.post(f"/pedidos/{p.id}/guardar", data={f"cantidad_linea_{linea.id}": "4"})
    db.session.refresh(pf)
    assert db.session.get(Pedido, p.id).lineas[0].cantidad == 4 and pf.lineas[0].cantidad == 1
    assert pf.lineas[0].sin_stock                                           # sin lotes: "a confirmar"


def test_los_pedidos_internos_no_pasan_por_proforma(app, client):
    from tests.conftest import contenido
    login(client, "loga")
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25",
                                        "contenido": contenido([(1, 1, {1: 1})])})
    assert db.session.scalar(db.select(Pedido)).estado == "aceptado"


def test_avisos_de_proformas(app, client):
    import re
    p = _pedir(client)
    login(client, "loga")
    html = client.get("/").get_data(as_text=True)
    assert "1 proforma por preparar" in html
    _enviar(client, p); _salir(client)
    login(client, "cliA")
    assert "1 proforma por responder" in client.get("/").get_data(as_text=True)


# ---------------------------------------------------------------- revisión
def test_cancelar_y_reabrir_vuelve_a_la_proforma(app, client):
    """Reabrir un pedido de cliente vuelve a la proforma (no a "aceptado", saltándosela)."""
    p = _pedir(client)
    login(client, "loga"); _enviar(client, p)
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "cancelado"})
    db.session.refresh(p)
    assert p.estado == "cancelado" and p.proformas[0].estado == "retirada"
    assert client.post(f"/pedidos/{p.id}/estado", data={"estado": "aceptado"}).status_code == 403
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "proforma_solicitada"})
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"


def test_tras_aceptar_no_se_cambia_sin_nueva_proforma(app, client):
    p = _pedir(client)
    login(client, "loga"); _enviar(client, p); _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    login(client, "loga")
    linea = db.session.get(Pedido, p.id).lineas[0]
    client.post(f"/pedidos/{p.id}/guardar", data={f"cantidad_linea_{linea.id}": "7"})
    assert db.session.get(Pedido, p.id).lineas[0].cantidad == 1          # ya no se edita
    # para cambiarlo: volver a "proforma solicitada" y enviar otra
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "proforma_solicitada"})
    assert db.session.get(Pedido, p.id).estado == "proforma_solicitada"


def test_admin_no_puede_forzar_proforma_enviada_sin_proforma(app, client):
    from tests.conftest import contenido
    login(client, "admin")
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25", "contenido": contenido([(1, 1, {1: 1})])})
    p = db.session.scalar(db.select(Pedido))
    assert 'value="proforma_enviada"' not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert client.post(f"/pedidos/{p.id}/estado", data={"estado": "proforma_enviada"}).status_code == 403
    assert db.session.get(Pedido, p.id).estado == "aceptado"


def test_reabrir_un_pedido_normal_no_dice_que_acepto_una_proforma(app, client):
    from tests.conftest import contenido
    login(client, "loga")
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25", "contenido": contenido([(1, 1, {1: 1})])})
    p = db.session.scalar(db.select(Pedido))
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "cancelado"})
    correos = _correos(app)
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "aceptado"})
    assert confirmar_correos() >= 1
    assert correos and "aceptación de la proforma" not in correos[0].get_content()


def test_responder_sin_boton_no_da_error(app, client):
    p = _pedir(client)
    login(client, "loga"); _enviar(client, p); _salir(client)
    login(client, "cliA")
    assert client.post(f"/pedidos/{p.id}/proforma/responder", data={}).status_code == 302
    assert client.post(f"/pedidos/{p.id}/proforma/responder", data={"comentario": "x"}).status_code == 302
    assert db.session.get(Pedido, p.id).estado == "proforma_enviada"


def test_numeracion_sin_choques(app, client, monkeypatch):
    """Dos envíos a la vez del mismo pedido calculan la misma versión: el segundo coge la siguiente."""
    from app.proformas import servicio
    p = _pedir(client)
    login(client, "loga")
    _enviar(client, p)
    client.post(f"/pedidos/{p.id}/proforma/retirar")
    monkeypatch.setattr(servicio, "numero_para", lambda pedido, version:
                        f"PF-{pedido.referencia_interna}" if version == 2 else f"PF-{pedido.referencia_interna}-v{version}")
    assert _enviar(client, p).status_code == 302                    # la v2 "choca" con la primera
    pf = db.session.get(Pedido, p.id).proforma_actual
    assert pf.numero == f"PF-{p.referencia_interna}-v3" and pf.version == 3


def test_el_cliente_cancela_mientras_es_proforma(app, client):
    p = _pedir(client)
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert 'value="cancelado"' not in html and 'data-bs-target="#modal-cancelar"' in html   # 15/10: su propio botón
    client.post(f"/pedidos/{p.id}/cancelar")
    assert db.session.get(Pedido, p.id).estado == "cancelado"
    # pero una vez aceptado, ya no (lo cancela Yikon)
    pedido_cliente(client, con_proforma=True)
    q = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    _salir(client); login(client, "loga"); _enviar(client, q); _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{q.id}/proforma/responder", data={"aceptar": "1"})
    assert db.session.get(Pedido, q.id).estado == "aceptado"
    assert client.post(f"/pedidos/{q.id}/estado", data={"estado": "cancelado"}).status_code == 403
    client.post(f"/pedidos/{q.id}/cancelar")
    assert db.session.get(Pedido, q.id).estado == "aceptado"
