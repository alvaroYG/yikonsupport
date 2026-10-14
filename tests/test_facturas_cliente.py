"""El cliente ve sus facturas y descarga el PDF oficial que sube admin."""
from datetime import date
from io import BytesIO

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import Factura
from tests.conftest import login, pedido_cliente

PDF = b"%PDF-1.4\n" + b"0" * 300


def _datos(**extra):
    datos = {"numero": "F-2026-1", "cliente_id": 1, "pedido_id": 0, "fecha_emision": "2026-09-01",
             "base_imponible": "100", "iva": "21", "total": "121", "estado": "pendiente", "notas": "NOTA INTERNA"}
    datos.update(extra)
    return datos


def _registrar(client, pdf=PDF, nombre="F-2026-1.pdf", **extra):
    datos = _datos(**extra)
    if pdf is not None:
        datos["pdf"] = (BytesIO(pdf), nombre)
    return client.post("/facturas/nueva", data=datos, content_type="multipart/form-data")


def test_admin_sube_el_pdf_y_el_cliente_lo_descarga(app, client):
    login(client, "admin")
    assert _registrar(client).status_code == 302
    f = db.session.scalar(db.select(Factura))
    assert f.pdf_nombre == "F-2026-1.pdf" and f.pdf_tamano == len(PDF)
    client.post("/auth/logout")
    # Registrada pero sin enviar: el cliente todavía no la ve
    login(client, "cliA")
    assert "F-2026-1" not in client.get("/facturas/mias").get_data(as_text=True)
    assert client.get(f"/facturas/{f.id}/pdf").status_code == 404
    client.post("/auth/logout")
    login(client, "admin"); client.post(f"/facturas/{f.id}/enviada"); client.post("/auth/logout")

    login(client, "cliA")
    html = client.get("/facturas/mias").get_data(as_text=True)
    assert "F-2026-1" in html and "Descargar PDF" in html
    assert "NOTA INTERNA" not in html and "121" not in html      # sin notas internas ni importes
    r = client.get(f"/facturas/{f.id}/pdf")
    assert r.status_code == 200 and r.data == PDF
    assert "attachment" in r.headers["Content-Disposition"] and r.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/facturas/").status_code == 403           # la lista de admin sigue cerrada


def test_otra_empresa_y_otro_fas_no_la_ven(app, client):
    login(client, "admin"); _registrar(client); client.post("/auth/logout")
    f = db.session.scalar(db.select(Factura))
    login(client, "cliB")
    assert client.get(f"/facturas/{f.id}/pdf").status_code == 404
    assert "F-2026-1" not in client.get("/facturas/mias").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "logb")                                      # FAS de otra clínica
    assert client.get(f"/facturas/{f.id}/pdf").status_code == 404
    assert "F-2026-1" not in client.get("/facturas/").get_data(as_text=True)
    assert client.get("/facturas/mias").status_code == 403
    client.post("/auth/logout")
    login(client, "loga")                                      # su FAS: la consulta, pero no la edita
    assert client.get(f"/facturas/{f.id}/pdf").status_code == 200
    assert "F-2026-1" in client.get("/facturas/").get_data(as_text=True)
    assert client.get(f"/facturas/{f.id}/editar").status_code == 403


def test_solo_pdf_de_verdad(app, client):
    login(client, "admin")
    r = _registrar(client, pdf=b"<html>no soy un pdf</html>", nombre="factura.pdf")
    assert "no es un PDF" in r.get_data(as_text=True)
    r = _registrar(client, pdf=b"%PDF-1.4 hola", nombre="factura.exe")
    assert "no es un PDF" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Factura.id))) == 0
    # sin PDF también se puede registrar (se sube después)
    assert _registrar(client, pdf=None).status_code == 302
    f = db.session.scalar(db.select(Factura))
    assert f.pdf_archivo is None and client.get(f"/facturas/{f.id}/pdf").status_code == 404


def test_sustituir_el_pdf_borra_el_anterior(app, client):
    import os
    login(client, "admin"); _registrar(client)
    f = db.session.scalar(db.select(Factura))
    anterior = os.path.join(app.config["DOCUMENTOS_FOLDER"], f.pdf_archivo)
    assert os.path.exists(anterior)
    datos = _datos(pdf=(BytesIO(PDF + b"v2"), "F-2026-1-v2.pdf"))
    assert client.post(f"/facturas/{f.id}/editar", data=datos, content_type="multipart/form-data").status_code == 302
    db.session.refresh(f)
    assert f.pdf_nombre == "F-2026-1-v2.pdf" and not os.path.exists(anterior)


def test_el_cliente_la_ve_en_la_ficha_de_su_pedido(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    from app.models import Pedido
    p = db.session.scalar(db.select(Pedido))
    db.session.add(Factura(enviada_el=ahora(), numero="F-9", cliente_id=1, pedido=p, fecha_emision=date(2026, 9, 1),
                           base_imponible=100, iva=21, total=121)); db.session.commit()
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "F-9" in html and "PDF pendiente" in html and "121" not in html
