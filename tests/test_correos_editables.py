"""Correos al cliente con texto editable por admin (Ajustes → Correos al cliente), firma y logo."""
from io import BytesIO

from app import correos_cliente as cc
from app.extensions import db
from app.models import Ajuste, Pedido, PlantillaCorreo, User
from tests.conftest import confirmar_correos, login, pedido_cliente

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _a_preparacion(client):
    """Un pedido de cliA que pasa a "En preparación" (le llega un correo). Su referencia: PO-77, PO-78…"""
    n = db.session.scalar(db.select(db.func.count(Pedido.id)))
    login(client, "cliA"); pedido_cliente(client, referencia=f"PO-{77 + n}"); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    assert confirmar_correos() == 1                      # admin confirma el aviso al cliente
    return p


def _al_cliente(correos):
    """Los que le llegan a cliA (al crear el pedido, a Yikon le llega el aviso de proforma pedida)."""
    return [m for m in correos if "clia@" in m["To"]]


def _html(msg):
    return msg.get_body(preferencelist=("html",)).get_content()


def test_sin_tocar_nada_sale_el_texto_de_siempre_con_firma_y_logo(app, client):
    correos = _correos(app)
    p = _a_preparacion(client)
    msg = _al_cliente(correos)[0]
    assert msg["Subject"] == f"Su pedido {p.referencia_interna}: En preparación"
    texto = msg.get_content()
    assert "Estamos preparando su pedido." in texto and "Su referencia: PO-77" in texto
    assert "Yikon Genomics España" in texto.split("-- \n")[1]                   # la firma, al final
    assert 'src="cid:logo-yikon"' in _html(msg)
    logo = next(parte for parte in msg.walk() if parte.get("Content-ID") == "<logo-yikon>")
    assert logo.get_content_type() == "image/png"


def test_admin_cambia_el_texto_y_es_el_que_llega(app, client):
    login(client, "admin")
    r = client.post("/admin/ajustes/correos/preparacion?idioma=es", data={
        "accion": "guardar", "asunto": "Manos a la obra con {referencia}",
        "cuerpo": "Buenas,\n\nYa estamos con {referencia}.\nSu ref.: {su_referencia}\n\n{enlace}"})
    assert r.status_code == 302
    client.post("/auth/logout")
    db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma = "es"
    db.session.commit()
    correos = _correos(app)
    p = _a_preparacion(client)
    assert _al_cliente(correos)[0]["Subject"] == f"Manos a la obra con {p.referencia_interna}"
    assert f"Ya estamos con {p.referencia_interna}.\nSu ref.: PO-77" in _al_cliente(correos)[0].get_content()
    # en inglés sigue saliendo el original (cada idioma se cambia por separado)
    db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma = "en"
    db.session.commit()
    correos = _correos(app)
    _a_preparacion(client)
    assert "Your order" in _al_cliente(correos)[0]["Subject"]


def test_lineas_y_parrafos_sin_dato_no_salen():
    plantilla = "Hola,\n\nPedido {referencia}\nSu ref.: {su_referencia}\n\nAdjuntos:\n{adjuntos}\n\nAdiós"
    assert cc.rellenar(plantilla, {"referencia": "YK-1", "su_referencia": "", "adjuntos": ""}) == \
        "Hola,\n\nPedido YK-1\n\nAdiós"


def test_un_dato_que_no_existe_no_se_guarda(app, client):
    login(client, "admin")
    r = client.post("/admin/ajustes/correos/preparacion?idioma=es", data={
        "accion": "guardar", "asunto": "Pedido {referencia}", "cuerpo": "Llega el {dia_de_entrega}"})
    assert r.status_code == 200 and "{dia_de_entrega}" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(PlantillaCorreo)) is None
    # {seguimiento} existe, pero no en este correo
    client.post("/admin/ajustes/correos/preparacion?idioma=es", data={
        "accion": "guardar", "asunto": "Pedido {referencia}", "cuerpo": "Seguimiento {seguimiento}"})
    assert db.session.scalar(db.select(PlantillaCorreo)) is None


def test_volver_al_original_y_guardar_lo_mismo_no_deja_nada(app, client):
    login(client, "admin")
    url = "/admin/ajustes/correos/cancelado?idioma=es"
    client.post(url, data={"accion": "guardar", "asunto": "Cancelado {referencia}", "cuerpo": "Lo sentimos."})
    assert cc.texto("cancelado", "es")["cambiado"]
    client.post(url, data={"accion": "original"})
    assert not cc.texto("cancelado", "es")["cambiado"]
    with app.test_request_context():
        original = cc.de_fabrica("cancelado", "es")
    client.post(url, data={"accion": "guardar", **original})
    assert db.session.scalar(db.select(PlantillaCorreo)) is None


def test_solo_admin(app, client):
    for usuario in ("ofi", "loga", "cliA"):
        login(client, usuario)
        assert client.get("/admin/ajustes/correos").status_code == 403
        assert client.post("/admin/ajustes/correos/preparacion/vista-previa", data={"cuerpo": "x"}).status_code == 403
        client.post("/auth/logout")


def test_vista_previa_y_prueba(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/correos/enviado?idioma=en").get_data(as_text=True)
    assert "Your order YK-2026-Ejemplo-014" in html and "{seguimiento}" in html     # ejemplo y datos a elegir
    r = client.post("/admin/ajustes/correos/enviado/vista-previa?idioma=es",
                    data={"asunto": "Sale {referencia}", "cuerpo": "Va con {transportista}\n{nada}"}).get_json()
    assert r["asunto"] == "Sale YK-2026-Ejemplo-014" and "DHL Express" in r["html"]
    assert "data:image/png;base64," in r["html"] and any("{nada}" in e for e in r["errores"])
    correos = _correos(app)
    client.post("/admin/ajustes/correos/enviado?idioma=es",
                data={"accion": "prueba", "asunto": "Sale {referencia}", "cuerpo": "Va con {transportista}"})
    assert confirmar_correos() == 1
    assert [m["To"] for m in correos] == ["admin@ejemplo.com"] and correos[0]["Subject"] == "[Prueba] Sale YK-2026-Ejemplo-014"
    assert db.session.scalar(db.select(PlantillaCorreo)) is None                    # la prueba no guarda


def test_firma_y_logo(app, client):
    login(client, "admin")
    client.post("/admin/ajustes/correos/firma?idioma=es",
                data={"accion": "guardar", "cuerpo": "Aina López · Logística\n+34 600 000 000"})
    client.post("/admin/ajustes/correos/logo", data={"con_logo": "1", "accion": "guardar",
                                                     "logo": (BytesIO(PNG), "nuevo.png")})
    assert db.session.get(Ajuste, "correo.logo_archivo").valor.startswith("logo_correo_")
    assert client.get("/admin/ajustes/correos/logo.img").data == PNG
    client.post("/auth/logout")
    correos = _correos(app)
    _a_preparacion(client)
    assert _al_cliente(correos)[0].get_content().endswith("-- \nAina López · Logística\n+34 600 000 000\n")
    logo = next(parte for parte in _al_cliente(correos)[0].walk() if parte.get("Content-ID") == "<logo-yikon>")
    assert logo.get_content() == PNG
    # sin logo
    login(client, "admin")
    client.post("/admin/ajustes/correos/logo", data={"accion": "guardar"})
    client.post("/auth/logout")
    correos = _correos(app)
    _a_preparacion(client)
    assert "<img" not in _html(_al_cliente(correos)[0]) and not any(p.get("Content-ID") for p in _al_cliente(correos)[0].walk())


def test_mensajes_el_cliente_recibe_el_editable_y_yikon_el_de_siempre(app, client):
    login(client, "admin")
    client.post("/admin/ajustes/correos/mensaje_nuevo?idioma=es", data={
        "accion": "guardar", "asunto": "Te escribe {quien}", "cuerpo": "{texto}\n\n{enlace}"})
    client.post("/auth/logout")
    correos = _correos(app)
    login(client, "loga"); client.post("/mensajes/cliente/1", data={"texto": "¿Qué tal el kit?"}); client.post("/auth/logout")
    assert confirmar_correos() == 1
    assert correos[0]["To"] == "clia@ejemplo.com" and correos[0]["Subject"].startswith("Te escribe loga")
    assert correos[0].get_content().startswith("¿Qué tal el kit?")
    correos = _correos(app)
    login(client, "cliA"); client.post("/mensajes/cliente/1", data={"texto": "Muy bien"})
    assert correos and correos[0]["To"] == "loga@ejemplo.com" and "Nuevo mensaje" in correos[0]["Subject"]
    assert not correos[0].is_multipart()                                         # a Yikon, el de siempre
