"""Ajustes → Datos de Yikon, Proformas (valores por defecto) y Avisos internos."""
from datetime import date, timedelta
from io import BytesIO

from app import datos_empresa
from app.extensions import db
from app.models import Factura, Pedido, User
from tests.conftest import confirmar_correos, login, pedido_cliente, pdf_proforma


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _salir(client):
    client.post("/auth/logout")


def _a(correos):
    """Todos los destinatarios (un correo va a varios a la vez si comparten idioma)."""
    return sorted(d for m in correos for d in m["To"].split(", "))


# ---------------------------------------------------------------- Datos de Yikon
def test_sin_tocar_nada_el_excel_sale_como_antes_y_al_cambiarlo_cambia_todo(app, client):
    with app.test_request_context():
        assert datos_empresa.lineas_vendedor() == app.config["VENDEDOR_FACTURA"]
    login(client, "admin")
    datos = {"nombre": "Yikon Europe", "razon_social": "YIKON GENOMICS, S.L.", "cif": "B12345678",
             "telefono": "+34 930 000 000", "direccion": "Calle Nueva 1\nPlanta 2", "cp_ciudad": "08001 Barcelona",
             "pais": "España", "email": "hola@yikonsupport.com", "web": "yikonsupport.com"}
    client.post("/admin/ajustes/datos-yikon", data=datos)
    with app.test_request_context():
        assert datos_empresa.lineas_vendedor() == ["YIKON GENOMICS, S.L.", "Calle Nueva 1", "Planta 2",
                                                   "08001 Barcelona, España", "CIF: B12345678"]
        from app.correos_cliente import texto
        firma = texto("firma", "es")["cuerpo"]
    assert firma.startswith("Yikon Europe\nCalle Nueva 1, Planta 2, 08001 Barcelona, España\n+34 930 000 000 · hola@")
    html = client.get("/admin/ajustes/datos-yikon").get_data(as_text=True)
    assert "08001 Barcelona, España" in html and "CIF B12345678" in html     # las dos vistas previas
    _salir(client)
    login(client, "ofi")
    assert client.get("/admin/ajustes/datos-yikon").status_code == 403


# ---------------------------------------------------------------- Proformas por defecto
def test_la_proforma_sale_rellena_en_el_idioma_del_cliente(app, client):
    login(client, "admin")
    client.post("/admin/ajustes/proformas", data={
        "validez": "15", "plazo_es": "5–7 días laborables", "plazo_en": "5–7 working days",
        "notas_es": "Transporte refrigerado.", "notas_en": "Cold-chain shipping."})
    _salir(client)
    login(client, "cliA"); pedido_cliente(client, con_proforma=True); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert (date.today() + timedelta(days=15)).isoformat() in html
    assert "5–7 días laborables" in html and "Transporte refrigerado." in html
    db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma = "en"
    db.session.commit()
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "5–7 working days" in html and "Cold-chain shipping." in html
    _salir(client)
    login(client, "admin")
    r = client.post("/admin/ajustes/proformas", data={"validez": "0"})
    assert "entre 1 y 365" in r.get_data(as_text=True)


# ---------------------------------------------------------------- Avisos internos
def test_avisos_nuevos_de_la_proforma_con_los_de_fabrica(app, client):
    correos = _correos(app)
    login(client, "cliA"); pedido_cliente(client, con_proforma=True)
    assert _a(correos) == ["loga@ejemplo.com", "ofi@ejemplo.com"]          # proforma pedida: Logística y su Soporte
    assert "ha pedido una proforma" in correos[0].get_content()
    _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "loga")
    client.post(f"/pedidos/{p.id}/proforma/enviar", data={"valida_hasta": (date.today() + timedelta(days=30)).isoformat(),
                                                         "pdf": pdf_proforma()})
    _salir(client)
    correos = _correos(app)
    login(client, "cliA")
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"cambios": "1", "comentario": "Quitad los tubos"})
    assert _a(correos) == ["loga@ejemplo.com"]                              # un solo email (no también el de "mensaje")
    assert "Quitad los tubos" in correos[0].get_content() and "Cambios a la proforma" in correos[0]["Subject"]


def test_admin_decide_quien_recibe(app, client):
    login(client, "admin")
    client.post("/admin/ajustes/avisos-internos", data={"recibe": ["proforma_pedida:admin"]})   # solo admin
    _salir(client)
    correos = _correos(app)
    login(client, "cliA"); pedido_cliente(client, con_proforma=True); _salir(client)
    assert _a(correos) == ["admin@ejemplo.com"]
    login(client, "admin")
    client.post("/admin/ajustes/avisos-internos", data={"accion": "fabrica"})
    html = client.get("/admin/ajustes/avisos-internos").get_data(as_text=True)
    assert 'value="proforma_pedida:logistica"' in html and 'value="devuelto:fas"' not in html   # "—": no lo recibe
    _salir(client)
    login(client, "loga")
    assert client.get("/admin/ajustes/avisos-internos").status_code == 403


def test_facturas_revisar_y_devuelta(app, client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    correos = _correos(app)
    login(client, "ofi")
    client.post(f"/facturas/pedido/{p.id}", data={"numero": "F-1", "fecha_emision": date.today().isoformat(),
                                                  "revisar": "y", "pdf": (BytesIO(b"%PDF-1.4 f"), "f.pdf")})
    assert confirmar_correos() == 1                     # lo escribe Logística: pasa por su revisión
    assert _a(correos) == ["loga@ejemplo.com"] and "Factura para revisar" in correos[0]["Subject"]
    _salir(client)
    f = db.session.scalar(db.select(Factura))
    correos = _correos(app)
    login(client, "loga")
    client.post(f"/facturas/{f.id}/devolver", data={"comentario": "Falta el descuento"})
    assert confirmar_correos() == 1
    assert _a(correos) == ["ofi@ejemplo.com"] and "Falta el descuento" in correos[0].get_content()


def test_quien_no_ve_facturas_no_recibe_sus_avisos(app, client):
    login(client, "admin")
    from app import apartados
    with app.test_request_context():
        marcadas = [f"{c}:{r}" for c, ap in apartados.APARTADOS.items() for r in ap.cambiables
                    if apartados.de_fabrica(c, r) and (c, r) != ("facturas", "fas")]
    client.post("/admin/ajustes/apartados", data={"accion": "guardar", "ver": marcadas})
    _salir(client)
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    correos = _correos(app)
    login(client, "ofi")
    client.post(f"/facturas/pedido/{p.id}", data={"numero": "F-2", "fecha_emision": date.today().isoformat(), "revisar": "y"})
    assert correos == []
