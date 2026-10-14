"""14/10/2026 · Logística pasa a ser ALMACÉN (rol "logistica": los pedidos desde que el cliente acepta,
fotos, envío e inventario) y nace FACTURACIÓN (rol "facturacion": proformas, facturas, clientes,
precios y catálogo). Escenario de conftest: ofi = Almacén · fac = Facturación."""
from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import Cliente, Factura, Mensaje, Pedido, Producto, User
from tests.conftest import login, pdf_proforma, pedido_cliente, subir_foto


def _salir(client):
    client.post("/auth/logout")


def _proforma(client):
    """Un pedido de cliA que todavía es proforma (solicitada)."""
    login(client, "cliA"); pedido_cliente(client, con_proforma=True); _salir(client)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _enviar_proforma(client, p, quien="fac"):
    login(client, quien)
    r = client.post(f"/pedidos/{p.id}/proforma/enviar", data={
        "valida_hasta": (date.today() + timedelta(days=30)).isoformat(), "pdf": pdf_proforma()})
    _salir(client)
    return r


def test_almacen_no_ve_las_proformas_y_si_lo_aceptado(app, client):
    p = _proforma(client)
    login(client, "ofi")
    assert client.get(f"/pedidos/{p.id}").status_code == 404
    assert p.referencia_interna not in client.get("/pedidos/").get_data(as_text=True)
    _salir(client)
    assert _enviar_proforma(client, p).status_code == 302                        # Facturación la envía
    login(client, "ofi")
    assert client.get(f"/pedidos/{p.id}").status_code == 404                     # aún sin aceptar
    _salir(client)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    login(client, "ofi")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "aceptado" and "Empezar preparación" in html
    assert "100,00 €" not in html and "Total" not in html                         # sin precios
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 302
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"


def test_cancelado_lo_ve_almacen_solo_si_llego_a_aceptarse(app, client):
    p = _proforma(client)
    login(client, "fac"); client.post(f"/pedidos/{p.id}/estado", data={"estado": "cancelado"}); _salir(client)
    assert db.session.get(Pedido, p.id).estado == "cancelado"
    login(client, "cliA"); pedido_cliente(client); _salir(client)                 # este, aceptado
    q = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "fac"); client.post(f"/pedidos/{q.id}/estado", data={"estado": "cancelado"}); _salir(client)
    assert db.session.get(Pedido, q.id).estado == "cancelado"
    login(client, "ofi")
    assert client.get(f"/pedidos/{p.id}").status_code == 404 and client.get(f"/pedidos/{q.id}").status_code == 200


def test_almacen_no_hace_lo_de_facturacion(app, client):
    p = _proforma(client)
    login(client, "ofi")
    assert client.post(f"/pedidos/{p.id}/proforma/enviar", data={"pdf": pdf_proforma()}).status_code == 403
    assert client.get("/facturas/").status_code == 403 and client.get("/facturas/nueva").status_code == 403
    assert client.get("/clientes/").status_code == 403 and client.get("/productos/nuevo").status_code == 403
    assert client.get("/pedidos/nuevo").status_code == 403
    assert "Hacer un pedido" not in client.get("/").get_data(as_text=True)


def test_facturacion_no_hace_lo_de_almacen(app, client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "fac")
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 403
    assert client.get("/pedidos/preparar").status_code == 403
    assert subir_foto(client, p.id).status_code == 403
    # Inventario: solo consulta (ni movimientos ni el mínimo)
    assert client.get("/inventario/").status_code == 200
    assert client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 5,
                                                       "lote": "L1", "caducidad": "2099-12-31"}).status_code == 403
    assert client.post("/inventario/producto/1/minimo", data={"stock_minimo": "3"}).status_code == 403
    assert 'name="stock_minimo"' not in client.get("/inventario/").get_data(as_text=True)


def test_facturacion_registra_y_envia_facturas_y_cobra(app, client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "fac")
    client.post(f"/facturas/pedido/{p.id}", data={"numero": "F-1", "fecha_emision": date.today().isoformat(),
                                                  "pdf": (BytesIO(b"%PDF-1.4 f"), "f.pdf")})
    f = db.session.scalar(db.select(Factura))
    assert f is not None and f.fase == "por_enviar"
    client.post(f"/facturas/{f.id}/enviada"); client.post(f"/facturas/{f.id}/pagada")
    db.session.refresh(f)
    assert f.enviada and f.estado == "pagada"


def test_facturacion_edita_clientes_pero_no_asigna_el_soporte(app, client):
    login(client, "fac")
    html = client.get("/clientes/1/editar").get_data(as_text=True)
    assert 'name="nombre"' in html and 'name="logisticos"' not in html
    r = client.post("/clientes/1/editar", data={"nombre": "Clínica A nueva", "prefijo": "CLA", "activo": "y",
                                                "logisticos": [db.session.scalar(db.select(User.id).filter_by(email="logb@ejemplo.com"))]})
    assert r.status_code == 302
    cliente = db.session.get(Cliente, 1)
    assert cliente.nombre == "Clínica A nueva" and [u.email for u in cliente.logisticos] == ["loga@ejemplo.com"]
    # precios especiales y catálogo, también
    client.post("/clientes/1/precios", data={"kit_id": 1, "precio": "80"})
    from app.models import PrecioCliente
    assert db.session.scalar(db.select(PrecioCliente.precio).filter_by(cliente_id=1)) == 80
    assert client.get("/productos/1/editar").status_code == 200
    _salir(client)
    login(client, "admin")
    assert 'name="logisticos"' in client.get("/clientes/1/editar").get_data(as_text=True)


def test_almacen_cambia_el_minimo_desde_inventario(app, client):
    login(client, "ofi")
    html = client.get("/inventario/").get_data(as_text=True)
    assert 'name="stock_minimo"' in html
    r = client.post("/inventario/producto/1/minimo?q=kit", data={"stock_minimo": "4"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/inventario/?q=kit#productos")
    assert db.session.get(Producto, 1).stock_minimo == 4
    client.post("/inventario/producto/1/minimo", data={"stock_minimo": "-2"})
    assert db.session.get(Producto, 1).stock_minimo == 4                          # no vale
    from app.models import RegistroAuditoria
    assert db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.detalle.like("%stock mínimo: 0 → 4")))


def test_almacen_solo_ve_los_mensajes_de_sus_pedidos(app, client):
    p = _proforma(client)
    login(client, "cliA"); client.post(f"/mensajes/pedido/{p.id}", data={"texto": "¿Tenéis la proforma?"}); _salir(client)
    assert db.session.scalar(db.select(Mensaje).filter_by(texto="¿Tenéis la proforma?")) is not None
    login(client, "ofi")
    assert "¿Tenéis la proforma?" not in client.get("/mensajes/").get_data(as_text=True)
    assert client.get(f"/mensajes/pedido/{p.id}/nuevos").status_code == 404
    _salir(client)
    login(client, "fac")
    assert "¿Tenéis la proforma?" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_la_proforma_aceptada_le_llega_a_almacen(app, client):
    p = _proforma(client)
    _enviar_proforma(client, p)
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"})
    destinatarios = {d.strip() for c in correos for d in c["To"].split(",") if "Proforma aceptada" in c["Subject"]}
    assert destinatarios == {"ofi@ejemplo.com"}


def test_ajustes_tienen_la_columna_facturacion(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/avisos-internos").get_data(as_text=True)
    assert 'value="factura_devuelta:facturacion"' in html and 'value="factura_devuelta:logistica"' not in html
    assert 'value="mensaje_compartido:facturacion"' in html
    html = client.get("/admin/ajustes/apartados").get_data(as_text=True)
    assert "Facturación" in html and "Almacén" in html
    html = client.get("/admin/usuarios/nuevo").get_data(as_text=True)
    assert 'value="facturacion"' in html and ">Almacén<" in html
