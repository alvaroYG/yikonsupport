from io import BytesIO

from app.extensions import db
from app.models import DocumentoPedido, Pedido, RegistroAuditoria
from tests.conftest import doc_pedido, login, pedido_cliente
from tests.conftest import contenido as contenido_pedido

PDF = b"%PDF-1.4 orden de compra interna"


def _pedido_con_documento(client, usuario="cliA", nombre="OC-2026-15.pdf", contenido=PDF, ref="OC-15"):
    login(client, usuario)
    r = client.post("/pedidos/nuevo", data={"documento": doc_pedido(), 
        "contenido": contenido_pedido([(1, 1, {1: 1})]), "fecha": "2026-09-25", "referencia": ref,
        "documento": (BytesIO(contenido), nombre)}, content_type="multipart/form-data")
    return r, db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def test_cliente_adjunta_documento_al_hacer_el_pedido(app, client):
    r, p = _pedido_con_documento(client)
    assert r.status_code == 302
    assert [d.nombre_original for d in p.documentos] == ["OC-2026-15.pdf"]
    # lo puede descargar y se descarga como adjunto (no se abre dentro de la web)
    d = p.documentos[0]
    r = client.get(f"/pedidos/{p.id}/documentos/{d.id}")
    assert r.status_code == 200 and r.data == PDF
    assert "attachment" in r.headers["Content-Disposition"]


def test_tipo_no_permitido_no_crea_el_pedido(app, client):
    r, p = _pedido_con_documento(client, nombre="virus.exe", contenido=b"MZ...")
    assert "no admitido" in r.get_data(as_text=True)
    assert p is None                                   # el pedido NO se ha creado a medias


def test_adjuntar_despues_desde_la_ficha(app, client):
    login(client, "cliA"); pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    for nombre in ["registro.xlsx", "pedido.docx"]:
        client.post(f"/pedidos/{p.id}/documentos", data={"documento": (BytesIO(b"datos"), nombre)},
                    content_type="multipart/form-data")
    assert sorted(d.nombre_original for d in p.documentos) == ["pedido.docx", "pedido.pdf", "registro.xlsx"]  # (+ la orden de compra)
    assert db.session.scalar(db.select(db.func.count(RegistroAuditoria.id)).where(
        RegistroAuditoria.detalle.like("documento adjuntado%"))) == 2


def test_logistics_y_admin_lo_ven_otra_empresa_no(app, client):
    _, p = _pedido_con_documento(client)
    d = p.documentos[0]
    client.post("/auth/logout")
    for usuario, esperado in [("loga", 200), ("admin", 200), ("logb", 404), ("cliB", 404)]:
        login(client, usuario)
        assert client.get(f"/pedidos/{p.id}/documentos/{d.id}").status_code == esperado, usuario
        client.post("/auth/logout")


def test_otra_empresa_no_puede_adjuntar_en_pedido_ajeno(app, client):
    _, p = _pedido_con_documento(client)
    client.post("/auth/logout")
    login(client, "cliB")
    r = client.post(f"/pedidos/{p.id}/documentos", data={"documento": (BytesIO(b"x"), "x.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 404 and len(p.documentos) == 1


def test_quien_lo_subio_puede_quitarlo_mientras_no_se_envie(app, client):
    _, p = _pedido_con_documento(client)
    d = p.documentos[0]
    client.post(f"/pedidos/{p.id}/documentos/{d.id}/borrar")
    assert db.session.scalar(db.select(db.func.count(DocumentoPedido.id))) == 0
    # ya enviado, el cliente no puede quitar lo que subió
    _, p2 = _pedido_con_documento(client, ref="OC-16")
    p2.estado = "enviado"; db.session.commit()
    assert client.post(f"/pedidos/{p2.id}/documentos/{p2.documentos[0].id}/borrar").status_code == 403


def test_soporte_de_cliente_quita_cualquier_documento_de_sus_clientes(app, client):
    """Aunque lo subiera el cliente y el pedido ya haya salido; en pedidos de otros clientes, no."""
    _, p = _pedido_con_documento(client)
    p.estado = "entregado"; db.session.commit()
    client.post("/auth/logout"); login(client, "logb")                   # Soporte de otro cliente
    assert client.post(f"/pedidos/{p.id}/documentos/{p.documentos[0].id}/borrar").status_code == 404
    client.post("/auth/logout"); login(client, "loga")                   # el de Clínica A
    assert "documentos/%d/borrar" % p.documentos[0].id in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post(f"/pedidos/{p.id}/documentos/{p.documentos[0].id}/borrar")
    assert db.session.scalar(db.select(db.func.count(DocumentoPedido.id))) == 0


def test_admin_sube_el_coa_de_un_pedido_enviado_y_el_cliente_lo_descarga(app, client):
    """Los COA (dependen del lote) se adjuntan en los documentos del pedido, ya enviado."""
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    p.estado = "entregado"; db.session.commit()
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "COA de los lotes enviados" in html                      # recordatorio para Yikon
    client.post(f"/pedidos/{p.id}/documentos", content_type="multipart/form-data",
                data={"documento": (BytesIO(b"%PDF-1.4 COA lote PA2409"), "COA_PA2409.pdf")})
    doc = db.session.scalar(db.select(DocumentoPedido).filter_by(nombre_original="COA_PA2409.pdf"))
    assert doc is not None
    client.post("/auth/logout"); login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "COA_PA2409.pdf" in html and "COA de los lotes enviados" not in html
    r = client.get(f"/pedidos/{p.id}/documentos/{doc.id}")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


def test_modelo_de_pedido_de_compra(app, client):
    """El cliente descarga el modelo de pedido (Word) desde la ventana de nuevo pedido."""
    login(client, "cliA")
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    assert "/pedidos/modelo-pedido-compra" in html
    r = client.get("/pedidos/modelo-pedido-compra")
    assert r.status_code == 200 and r.data[:2] == b"PK"                  # un .docx es un zip
    assert "attachment" in r.headers["Content-Disposition"] and "Pedido_de_compra_Yikon.docx" in r.headers["Content-Disposition"]
    client.post("/auth/logout")
    login(client, "chrA")                                                # quien no hace pedidos, no
    assert client.get("/pedidos/modelo-pedido-compra").status_code == 403
