"""Mensajes de Yikon al cliente: unos segundos para deshacerlos antes de que el cliente los vea
y le llegue el email (por si era una nota interna escrita en el chat equivocado)."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.mensajes import servicio
from app.models import Mensaje, Pedido, ahora
from tests.conftest import confirmar_correos, login, pedido_cliente


@pytest.fixture
def con_deshacer(app, monkeypatch):
    """Activa los 10 s de deshacer y, en vez de esperar de verdad, apunta los avisos programados."""
    app.config["MENSAJES_DESHACER_SEGUNDOS"] = 10
    programados = []
    monkeypatch.setattr(servicio, "programar_aviso", lambda mensaje_id, segundos: programados.append(mensaje_id))
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return programados, correos


def _pedido(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    app.extensions.setdefault("correos_enviados", []).clear()      # (el aviso a Yikon de la proforma pedida)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _el_cliente_lo_ve(client, p, texto):
    client.post("/auth/logout"); login(client, "cliA")
    ve = texto in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post("/auth/logout")
    return ve


def test_deshacer_antes_de_que_lo_vea(app, client, con_deshacer):
    programados, correos = con_deshacer
    p = _pedido(app, client)
    login(client, "loga")
    r = client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Aina, ¿llegamos el lunes?"})
    m = db.session.scalar(db.select(Mensaje))
    assert r.headers["Location"].endswith("#mensajes") and m.visible_desde is not None
    assert programados == [m.id] and correos == []                      # el email espera a que pase el plazo
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Deshacer" in html and f"/mensajes/{m.id}/deshacer" in html  # el aviso con la cuenta atrás
    assert not _el_cliente_lo_ve(client, p, "Aina, ¿llegamos el lunes?")
    login(client, "loga")
    client.post(f"/mensajes/{m.id}/deshacer")
    assert db.session.scalar(db.select(Mensaje)) is None
    servicio.avisar_si_sigue(m.id)                                       # cuando llega la hora: no hay email
    assert correos == []


def test_pasado_el_plazo_lo_ve_y_le_llega_el_email(app, client, con_deshacer):
    programados, correos = con_deshacer
    p = _pedido(app, client)
    login(client, "loga")
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Os lo enviamos hoy"})
    m = db.session.scalar(db.select(Mensaje))
    m.visible_desde = ahora() - timedelta(seconds=1); db.session.commit()      # pasan los 10 s
    assert client.post(f"/mensajes/{m.id}/deshacer").status_code == 302
    assert db.session.get(Mensaje, m.id) is not None                     # ya no se puede deshacer
    with app.test_request_context():
        servicio.avisar_si_sigue(m.id)
    assert not correos                                   # el aviso aplazado espera a que loga lo revise
    assert confirmar_correos() == 1
    assert [c["To"].lower() for c in correos] == ["clia@ejemplo.com"]
    assert _el_cliente_lo_ve(client, p, "Os lo enviamos hoy")


def test_solo_lo_que_va_al_cliente_y_solo_quien_lo_escribio(app, client, con_deshacer):
    programados, _correos = con_deshacer
    p = _pedido(app, client)
    login(client, "cliA"); client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Del cliente"}); client.post("/auth/logout")
    login(client, "loga"); client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "Nota interna"})
    assert all(m.visible_desde is None for m in db.session.scalars(db.select(Mensaje)))   # sin espera
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Al cliente"})
    m = db.session.scalar(db.select(Mensaje).filter_by(texto="Al cliente"))
    client.post("/auth/logout"); login(client, "admin")                  # otro de Yikon no lo puede deshacer
    client.post(f"/mensajes/{m.id}/deshacer")
    assert db.session.get(Mensaje, m.id) is not None
