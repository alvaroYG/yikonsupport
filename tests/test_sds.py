"""Catálogo de productos para el cliente, con la ficha de seguridad (SDS) de cada uno."""
from io import BytesIO

from app.extensions import db
from app.models import Producto
from tests.conftest import login

PDF = b"%PDF-1.4 ficha de seguridad"


def _subir_sds(client, producto_id=1, contenido=PDF, nombre="SDS_P1.pdf", **extra):
    datos = {"referencia": "P1", "nombre": "Kit 1", "categoria": "Illumina", "precio": "100",
             "iva_pct": "21.00", "stock_minimo": 0, "activo": "y", "controlar_stock": "y",
             "sds_pdf": (BytesIO(contenido), nombre)}
    datos.update(extra)
    return client.post(f"/productos/{producto_id}/editar", data=datos, content_type="multipart/form-data")


def test_admin_sube_la_sds_y_el_cliente_la_descarga(app, client):
    db.session.add(Producto(referencia="P2", nombre="Tubos", precio=10, categoria="MGI"))
    db.session.add(Producto(referencia="VIEJO", nombre="Producto de baja", precio=10, activo=False))
    db.session.commit()
    login(client, "admin")
    assert _subir_sds(client).status_code == 302
    p = db.session.get(Producto, 1)
    assert p.sds_nombre == "SDS_P1.pdf" and p.sds_fecha is not None
    client.post("/auth/logout")

    login(client, "cliA")
    html = client.get("/productos/catalogo").get_data(as_text=True)
    assert "Kit 1" in html and "Tubos" in html and "Illumina" in html and "MGI" in html
    assert "Producto de baja" not in html                 # solo el catálogo activo
    assert "€" not in html and "Precio sin IVA" not in html   # sin precios (su empresa no los ve)
    assert "Kit uno" in html                               # también los kits
    assert "Sin SDS" in html                               # Tubos no tiene SDS todavía
    r = client.get(f"/productos/{p.id}/sds")
    assert r.status_code == 200 and r.data == PDF and "attachment" in r.headers["Content-Disposition"]
    # la lista interna de productos (con precios) sigue cerrada para el cliente
    assert client.get("/productos/").status_code == 403


def test_solo_pdf_y_sustituir_borra_la_anterior(app, client):
    import os
    login(client, "admin")
    r = _subir_sds(client, contenido=b"no soy pdf", nombre="sds.pdf")
    assert "no es un PDF" in r.get_data(as_text=True) and db.session.get(Producto, 1).sds_archivo is None
    _subir_sds(client)
    anterior = os.path.join(app.config["DOCUMENTOS_FOLDER"], db.session.get(Producto, 1).sds_archivo)
    _subir_sds(client, contenido=PDF + b" v2", nombre="SDS_P1_v2.pdf")
    p = db.session.get(Producto, 1)
    assert p.sds_nombre == "SDS_P1_v2.pdf" and not os.path.exists(anterior)
    # editar sin subir otra la conserva
    datos = {"referencia": "P1", "nombre": "Kit 1 nuevo", "precio": "100", "iva_pct": "21.00",
             "stock_minimo": 0, "activo": "y", "controlar_stock": "y"}
    client.post("/productos/1/editar", data=datos)
    assert db.session.get(Producto, 1).sds_nombre == "SDS_P1_v2.pdf"


def test_sds_de_un_producto_de_baja(app, client):
    login(client, "admin"); _subir_sds(client)
    db.session.get(Producto, 1).activo = False; db.session.commit()
    assert client.get("/productos/1/sds").status_code == 200    # admin sí
    client.post("/auth/logout"); login(client, "cliA")
    assert client.get("/productos/1/sds").status_code == 404    # el cliente ya no
    assert client.get("/productos/99/sds").status_code == 404


def test_catalogo_con_precios_si_su_empresa_los_ve(app, client):
    from app.models import Cliente, PrecioCliente
    c = db.session.get(Cliente, 1)
    c.ver_precios = True
    db.session.add(PrecioCliente(cliente=c, kit_id=1, precio=80))     # tarifa especial del kit
    db.session.commit()
    login(client, "cliA")
    html = client.get("/productos/catalogo").get_data(as_text=True)
    assert "Precio sin IVA" in html and "80,00 €" in html and "100,00 €" in html   # kit con su tarifa, producto
    client.post("/auth/logout"); login(client, "cliB")                 # otra empresa, sin la opción
    assert "Precio sin IVA" not in client.get("/productos/catalogo").get_data(as_text=True)
