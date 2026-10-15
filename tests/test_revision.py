"""Fallos encontrados en la revisión del 26/09: cada test reproduce uno ya corregido."""
from datetime import date, datetime
from io import BytesIO

from sqlalchemy.orm.attributes import set_committed_value

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import Cliente, Factura, Lote, MovimientoInventario, Pedido, Producto, ReservaLote
from tests.conftest import contenido, llevar_a_validado, login, pedido_cliente, reservar_lotes
from tests.test_inventario import _entrada, _estado, _pedido_confirmado


def _pedido_enviado(client, cantidad=3, stock=10):
    p = _pedido_confirmado(client, cantidad)
    # el stock entra después del pedido: hay que asignarle el lote
    login(client, "admin"); _entrada(client, stock); reservar_lotes(client, p.id); client.post("/auth/logout")
    llevar_a_validado(client, p.id)
    login(client, "admin"); _estado(client, p, "enviado")
    return p


def test_pdf_admite_cualquier_caracter(app, client):
    """Antes: un producto 'Kit β-hCG' hacía fallar la exportación (fuente sin Unicode)."""
    db.session.get(Producto, 1).nombre = "Kit β-hCG"
    db.session.get(Cliente, 1).nombre = "Łódź Klinika"
    db.session.commit()
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    login(client, "admin")
    r = client.get("/pedidos/exportar.pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


def test_documento_vacio_no_da_error(app, client):
    login(client, "cliA")
    datos = {"contenido": contenido([(1, 1, {1: 1})]), "fecha": "2026-09-25",
             "referencia": "OC-VACIO", "documento": (BytesIO(b""), "oc.pdf"), "uso": "ruo"}
    r = client.post("/pedidos/nuevo", data=datos, content_type="multipart/form-data")
    assert r.status_code == 200 and "El archivo está vacío." in r.get_data(as_text=True)
    pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    r = client.post(f"/pedidos/{p.id}/documentos", data={"documento": (BytesIO(b""), "x.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200 and "El archivo está vacío." in r.get_data(as_text=True)


def test_boton_de_una_pestana_antigua_no_fuerza_el_estado(app, client):
    """Antes: 'Rechazar' sobre un pedido ya enviado lo devolvía a 'revisar' y reponía stock."""
    p = _pedido_enviado(client)
    assert db.session.get(Producto, 1).stock == 7
    r = client.post(f"/pedidos/{p.id}/validar", data={"rechazar": "1", "comentario": "x"},
                    follow_redirects=True)
    assert "ha cambiado de estado mientras tanto" in r.get_data(as_text=True)
    assert db.session.get(Pedido, p.id).estado == "enviado"
    assert db.session.get(Producto, 1).stock == 7
    client.post(f"/pedidos/{p.id}/preparacion")
    assert db.session.get(Pedido, p.id).estado == "enviado"


def test_doble_envio_no_resta_el_stock_dos_veces(app, client):
    """Dos peticiones casi a la vez: la segunda ve el pedido todavía 'validado'
    (dato antiguo en memoria), pero en la base de datos ya está 'enviado'."""
    p = _pedido_enviado(client)
    movimientos = db.session.scalar(db.select(db.func.count(MovimientoInventario.id)))
    # La segunda petición leyó el pedido ANTES de que la primera terminara: lo ve "validado"
    # y con su lote todavía reservado (al enviar, la reserva se convierte en la salida)
    lote = db.session.scalar(db.select(Lote))
    db.session.add(ReservaLote(pedido_id=p.id, lote_id=lote.id, cantidad=3)); db.session.commit()
    assert p.estado == "enviado"
    set_committed_value(p, "estado", "validado")       # simula el dato desactualizado
    r = _estado(client, p, "enviado")
    assert "ha cambiado de estado mientras tanto" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(MovimientoInventario.id))) == movimientos
    assert db.session.get(Producto, 1).stock == 7


def test_el_cliente_no_ve_las_notas_internas(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    p.notas = "NOTA INTERNA secreta"
    db.session.commit()
    login(client, "cliA")
    assert "NOTA INTERNA" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post("/auth/logout"); login(client, "loga")
    assert "NOTA INTERNA" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_no_se_reutiliza_el_prefijo_de_pedidos_antiguos(app, client):
    """Antes: A (CLA_001) cambia a CLX; un cliente nuevo con 'CLA' → error 500 en su primer pedido."""
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    db.session.get(Cliente, 1).prefijo = "CLX"
    db.session.commit()
    login(client, "admin")
    r = client.post("/clientes/nuevo", data={"nombre": "Nueva", "prefijo": "cla", "activo": "y"})
    assert "Ese prefijo ya se usó en pedidos de otra empresa" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(Cliente).filter_by(nombre="Nueva")) is None
    # la propia empresa sí puede volver a su prefijo de antes (su contador sigue)
    r = client.post("/clientes/1/editar", data={"nombre": "Clínica A", "cif": "B11111111",
                                                "prefijo": "CLA", "activo": "y"})
    assert db.session.get(Cliente, 1).prefijo == "CLA"


def test_se_puede_editar_la_factura_de_un_pedido_cancelado(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    p.estado = "cancelado"
    f = Factura(enviada_el=ahora(), numero="F-1", cliente_id=1, pedido=p, fecha_emision=date(2026, 9, 1),
                base_imponible=100, iva=21, total=121)
    db.session.add(f); db.session.commit()
    login(client, "admin")
    r = client.post(f"/facturas/{f.id}/editar", data={
        "numero": "F-1", "cliente_id": 1, "pedido_id": p.id, "fecha_emision": "2026-09-01",
        "base_imponible": "100", "iva": "21", "total": "121", "estado": "pagada",
        "fecha_pago": "2026-09-20"})
    assert r.status_code == 302
    assert db.session.get(Factura, f.id).estado == "pagada"


def test_anular_devuelve_lo_que_salio_aunque_cambie_controlar_stock(app, client):
    p = _pedido_enviado(client, cantidad=3, stock=10)
    assert db.session.get(Producto, 1).stock == 7
    db.session.get(Producto, 1).controlar_stock = False
    db.session.commit()
    _estado(client, p, "cancelado")
    assert db.session.get(Producto, 1).stock == 10


def test_parametros_raros_en_la_url_no_dan_error(app, client):
    login(client, "admin")
    for q in ["endpoint=x", "_method=POST", "_scheme=https", "_external=1"]:
        assert client.get(f"/pedidos/?{q}").status_code == 200


def test_producto_con_precio_cero(app, client):
    login(client, "admin")
    client.post("/productos/nuevo", data={"referencia": "GRATIS", "nombre": "Muestra",
                                          "precio": "0", "iva_pct": "21", "stock_minimo": 0,
                                          "activo": "y"})
    assert db.session.scalar(db.select(Producto).filter_by(referencia="GRATIS")) is not None


def test_las_horas_se_muestran_en_hora_de_madrid(app):
    filtro = app.jinja_env.filters["fecha_hora"]
    assert filtro(datetime(2026, 7, 1, 10, 0)) == "01/07/2026 12:00"     # verano: UTC+2
    assert filtro(datetime(2026, 1, 15, 10, 0)) == "15/01/2026 11:00"    # invierno: UTC+1
    assert filtro(None) == "—"


def test_editar_producto_guarda_la_marca(app, client):
    """Antes: CAMPOS decía "marca" (el campo se llama "categoria") y editar daba error 500."""
    login(client, "admin")
    r = client.post("/productos/1/editar", data={"referencia": "P1", "nombre": "x", "categoria": "Illumina",
                                                  "precio": "100", "iva_pct": "21.00", "stock_minimo": 0,
                                                  "activo": "y", "controlar_stock": "y"})
    assert r.status_code == 302
    assert db.session.get(Producto, 1).categoria == "Illumina"


def test_tampoco_se_reutiliza_un_prefijo_del_formato_nuevo(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")       # YK-<año>-CLA-1
    db.session.get(Cliente, 1).prefijo = "CLX"
    db.session.commit()
    login(client, "admin")
    r = client.post("/clientes/nuevo", data={"nombre": "Nueva", "prefijo": "cla", "activo": "y"})
    assert "Ese prefijo ya se usó en pedidos de otra empresa" in r.get_data(as_text=True)
    r = client.post("/clientes/nuevo", data={"nombre": "Otra", "prefijo": "LA", "activo": "y"})   # "LA" no es "CLA"
    assert db.session.scalar(db.select(Cliente).filter_by(nombre="Otra")) is not None
