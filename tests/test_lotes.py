"""Lotes y caducidad: entradas con lote obligatorio, salida FEFO, sin caducados."""
from datetime import date, timedelta

from app.extensions import db
from app.inventario.stock import avisos_caducidad
from app.models import Lote, MovimientoInventario, Producto
from tests.conftest import llevar_a_validado, login
from tests.test_inventario import _entrada, _estado, _pedido_confirmado

HOY = date.today()
def _dia(n): return (HOY + timedelta(days=n)).isoformat()


def _stock_lote(codigo):
    lote = db.session.scalar(db.select(Lote).filter_by(codigo=codigo))
    return lote.stock if lote else None


def _enviar(client, cantidad):
    p = _pedido_confirmado(client, cantidad)
    llevar_a_validado(client, p.id)
    login(client, "admin")
    return p, _estado(client, p, "enviado")


def test_la_entrada_exige_lote_y_caducidad(app, client):
    login(client, "admin")
    r = client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5},
                    follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Indica el lote." in html and "Indica la fecha de caducidad del lote." in html
    assert db.session.get(Producto, 1).stock == 0


def test_mismo_lote_suma_pero_no_con_otra_caducidad(app, client):
    login(client, "admin")
    _entrada(client, 5, lote="A1", caducidad=_dia(100))
    _entrada(client, 2, lote="A1", caducidad=_dia(100))
    assert _stock_lote("A1") == 7
    r = _entrada(client, 1, lote="A1", caducidad=_dia(200))
    assert _stock_lote("A1") == 7                      # rechazado: esa caducidad no cuadra
    assert db.session.scalar(db.select(db.func.count(Lote.id))) == 1


def test_sale_primero_el_lote_que_caduca_antes(app, client):
    login(client, "admin")
    _entrada(client, 5, lote="TARDE", caducidad=_dia(300))
    _entrada(client, 3, lote="PRONTO", caducidad=_dia(30))
    client.post("/auth/logout")
    _enviar(client, 4)
    assert _stock_lote("PRONTO") == 0 and _stock_lote("TARDE") == 4


def test_los_lotes_caducados_no_se_envian(app, client):
    login(client, "admin")
    _entrada(client, 10, lote="VIEJO", caducidad=_dia(20))
    db.session.scalar(db.select(Lote).filter_by(codigo="VIEJO")).caducidad = HOY - timedelta(days=1)
    db.session.commit()
    client.post("/auth/logout")
    p, r = _enviar(client, 2)
    # un lote caducado no se reserva nunca: el pedido se queda sin lote y no se puede enviar
    assert p.reservas == []
    assert "No se puede enviar: Kit 1: faltan 2 por asignar a un lote" in r.get_data(as_text=True)
    assert db.session.get(type(p), p.id).estado == "validado"
    assert _stock_lote("VIEJO") == 10


def test_anular_devuelve_cada_unidad_a_su_lote(app, client):
    login(client, "admin")
    _entrada(client, 2, lote="L-A", caducidad=_dia(10))
    _entrada(client, 5, lote="L-B", caducidad=_dia(90))
    client.post("/auth/logout")
    p, _r = _enviar(client, 4)                         # 2 de L-A y 2 de L-B
    assert (_stock_lote("L-A"), _stock_lote("L-B")) == (0, 3)
    _estado(client, p, "cancelado")
    assert (_stock_lote("L-A"), _stock_lote("L-B")) == (2, 5)


def test_ajustes_solo_sobre_lotes_existentes_y_sin_dejarlos_en_negativo(app, client):
    login(client, "admin")
    _entrada(client, 3, lote="R1", caducidad=_dia(50))
    r = _entrada(client, -1, tipo="ajuste", lote="NOEXISTE")
    assert db.session.get(Producto, 1).stock == 3
    _entrada(client, -5, tipo="ajuste", lote="R1")
    assert _stock_lote("R1") == 3                       # no puede quedar en −2
    _entrada(client, -1, tipo="ajuste", lote="R1")
    assert _stock_lote("R1") == 2


def test_el_lote_enviado_lo_ve_logistics_pero_no_el_cliente(app, client):
    login(client, "admin")
    _entrada(client, 5, lote="TRAZA-77", caducidad=_dia(90))
    client.post("/auth/logout")
    p, _r = _enviar(client, 1)
    assert "TRAZA-77" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)      # admin
    client.post("/auth/logout"); login(client, "loga")
    assert "TRAZA-77" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post("/auth/logout"); login(client, "cliA")
    assert "TRAZA-77" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_aviso_de_caducidad_a_una_semana(app, client):
    login(client, "admin")
    _entrada(client, 1, lote="SEMANA", caducidad=_dia(6))
    _entrada(client, 1, lote="MES", caducidad=_dia(30))
    with app.test_request_context():
        codigos = [a["lote"].codigo for a in avisos_caducidad()]
    assert codigos == ["SEMANA"]
    html = client.get("/").get_data(as_text=True)
    assert "SEMANA" in html and "Caduca en 6 días" in html
    assert "SEMANA" in client.get("/inventario/caducidades").get_data(as_text=True)
