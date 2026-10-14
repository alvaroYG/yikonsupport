"""Auditoría: cada objeto con su nombre (no "Pedido #23"), enlazado, y su historial con un clic."""
from app.extensions import db
from app.models import Pedido, Producto, RegistroAuditoria
from tests.conftest import login, pedido_cliente


def _pedido(client, ref="PO-9"):
    login(client, "cliA"); pedido_cliente(client, referencia=ref); client.post("/auth/logout")
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def test_el_objeto_sale_con_su_nombre_y_enlace(app, client):
    p = _pedido(client)
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/preparacion")
    html = client.get("/admin/auditoria").get_data(as_text=True)
    assert f'<a href="/pedidos/{p.id}">{p.referencia_interna} · Clínica A</a>' in html
    assert f"Pedido #{p.id}" not in html
    r = db.session.scalar(db.select(RegistroAuditoria).filter_by(entidad="Pedido", entidad_id=p.id))
    assert r.objeto == f"{p.referencia_interna} · Clínica A"                        # guardado con el registro


def test_historial_de_un_objeto_y_filtros(app, client):
    p = _pedido(client)
    otro = _pedido(client, "PO-10")
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/preparacion")
    client.post(f"/pedidos/{otro.id}/preparacion")
    html = client.get(f"/admin/auditoria?tipo=Pedido&id={p.id}").get_data(as_text=True)
    assert "Historial de" in html and p.referencia_interna in html and otro.referencia_interna not in html
    html = client.get(f"/admin/auditoria?q={otro.referencia_interna}").get_data(as_text=True)
    assert otro.referencia_interna in html and f">{p.referencia_interna} ·" not in html
    html = client.get("/admin/auditoria?accion=login").get_data(as_text=True)
    assert p.referencia_interna not in html


def test_lo_borrado_se_sigue_leyendo(app, client):
    prod = Producto(referencia="TMP-1", nombre="Producto temporal", precio=1)
    db.session.add(prod); db.session.commit()
    login(client, "admin")
    client.post(f"/productos/{prod.id}/borrar")
    assert db.session.get(Producto, prod.id) is None
    html = client.get("/admin/auditoria?tipo=Producto").get_data(as_text=True)
    assert "TMP-1 · Producto temporal" in html and "ya no existe" in html


def test_los_estados_salen_con_su_nombre(app, client):
    p = _pedido(client)
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/preparacion")
    html = client.get(f"/admin/auditoria?tipo=Pedido&id={p.id}").get_data(as_text=True)
    assert "Aceptado → En preparación" in html and "aceptado → en_preparacion" not in html
