"""Registrar la factura y subir su PDF desde la ficha del pedido."""
from io import BytesIO

from app.extensions import db
from app.models import Factura, Pedido
from tests.conftest import login, pedido_cliente

PDF = b"%PDF-1.4\n" + b"0" * 300


def _pedido(client, confirmar=True):
    login(client, "cliA"); pedido_cliente(client, cantidad=2); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    if confirmar:
        login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    return p


def _registrar(client, pedido, pdf=PDF, numero="F-2026-7"):
    datos = {"numero": numero, "fecha_emision": "2026-09-29", "fecha_vencimiento": "2026-10-29"}
    if pdf is not None:
        datos["pdf"] = (BytesIO(pdf), "factura.pdf")
    return client.post(f"/facturas/pedido/{pedido.id}", data=datos, content_type="multipart/form-data")


def test_registrar_desde_el_pedido_sin_importes(app, client):
    p = _pedido(client)
    login(client, "admin")
    r = _registrar(client, p)
    assert r.status_code == 302 and f"/pedidos/{p.id}" in r.headers["Location"]
    f = db.session.scalar(db.select(Factura))
    assert f.pedido_id == p.id and f.cliente_id == p.cliente_id
    assert f.total is None and f.base_imponible is None      # la factura se hace fuera: aquí no hay importes
    assert f.fecha_vencimiento.isoformat() == "2026-10-29"
    assert f.pdf_tamano == len(PDF)
    # la ficha del pedido la muestra en el recuadro de facturas
    assert "F-2026-7" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_sin_pdf_tambien_vale_y_luego_se_sube(app, client):
    p = _pedido(client)
    login(client, "admin")
    _registrar(client, p, pdf=None)
    f = db.session.scalar(db.select(Factura))
    assert f.pdf_archivo is None
    r = client.post(f"/facturas/{f.id}/subir-pdf", data={"pdf": (BytesIO(PDF), "buena.pdf"), "volver": "pedido"},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and f"/pedidos/{p.id}" in r.headers["Location"]
    db.session.refresh(f)
    assert f.pdf_nombre == "buena.pdf"
    # sustituirlo: el archivo nuevo reemplaza al anterior
    anterior = f.pdf_archivo
    client.post(f"/facturas/{f.id}/subir-pdf", data={"pdf": (BytesIO(PDF + b"1"), "otra.pdf")},
                content_type="multipart/form-data")
    db.session.refresh(f)
    assert f.pdf_nombre == "otra.pdf" and f.pdf_archivo != anterior


def test_no_se_factura_una_proforma(app, client):
    login(client, "cliA"); pedido_cliente(client, con_proforma=True); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    assert p.estado == "proforma_solicitada"
    login(client, "admin")
    _registrar(client, p)
    assert db.session.scalar(db.select(db.func.count(Factura.id))) == 0


def test_numero_repetido_y_pdf_falso(app, client):
    p = _pedido(client)
    login(client, "admin")
    _registrar(client, p)
    _registrar(client, p)                                  # mismo número
    _registrar(client, p, pdf=b"no soy un pdf", numero="F-2026-8")
    assert db.session.scalar(db.select(db.func.count(Factura.id))) == 1


def test_solo_admin(app, client):
    p = _pedido(client)
    for usuario in ("loga", "cliA"):
        login(client, usuario)
        assert _registrar(client, p).status_code == 403
        client.post("/auth/logout")
