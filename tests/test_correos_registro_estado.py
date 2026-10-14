"""Registro de correos enviados (con reenviar) y página de Estado de la plataforma."""
from app.extensions import db
from app.models import CorreoEnviado, ErrorWeb, Pedido
from tests.conftest import confirmar_correos, login, pedido_cliente


def _salir(client):
    client.post("/auth/logout")


def _pedido_en_preparacion(client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); _salir(client)
    assert confirmar_correos() == 1                      # admin confirma el aviso al cliente
    return p


def test_cada_correo_queda_registrado_con_su_pedido(app, client):
    p = _pedido_en_preparacion(client)
    al_cliente = db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="cliente.preparacion"))
    assert al_cliente.para == "clia@ejemplo.com" and al_cliente.estado == "enviado"
    assert al_cliente.pedido_id == p.id and p.referencia_interna in al_cliente.texto and "cid:" in al_cliente.html
    assert db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="interno.proforma_pedida")) is not None
    login(client, "admin")
    html = client.get(f"/admin/correos?q={p.referencia_interna}").get_data(as_text=True)
    assert al_cliente.asunto in html and "Al cliente · En preparación" in html


def test_el_que_falla_se_ve_y_se_reenvia(app, client, monkeypatch):
    import smtplib
    app.config.update(MAIL_BACKEND="smtp", MAIL_SERVER="smtp.ejemplo.invalid", MAIL_PORT=25)

    def no_hay_servidor(*a, **k):
        raise smtplib.SMTPConnectError(421, "no responde")
    monkeypatch.setattr(smtplib, "SMTP", no_hay_servidor)
    _pedido_en_preparacion(client)
    fallido = db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="cliente.preparacion"))
    assert fallido.estado == "fallido" and "no responde" in fallido.error
    app.config["MAIL_BACKEND"] = "memoria"                 # vuelve el servidor
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    login(client, "admin")
    assert "No se pudo enviar" in client.get(f"/admin/correos/{fallido.id}").get_data(as_text=True)
    client.post(f"/admin/correos/{fallido.id}/reenviar")
    assert not correos                                   # el reenvío también pasa por la revisión
    assert confirmar_correos() == 1
    assert [c["To"] for c in correos] == ["clia@ejemplo.com"]
    assert any(p.get("Content-ID") == "<logo-yikon>" for p in correos[0].walk())     # con el logo otra vez
    reenvio = db.session.scalar(db.select(CorreoEnviado).filter_by(reenvio_de_id=fallido.id))
    assert reenvio.estado == "enviado"


def test_soporte_ve_solo_los_de_sus_clientes_y_no_reenvia(app, client):
    _pedido_en_preparacion(client)
    del_cliente = db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="cliente.preparacion"))
    interno = db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="interno.proforma_pedida"))
    login(client, "loga")
    html = client.get("/admin/correos").get_data(as_text=True)
    assert del_cliente.asunto in html and interno.asunto not in html
    assert client.post(f"/admin/correos/{del_cliente.id}/reenviar").status_code == 403
    assert "Reenviar" not in client.get(f"/admin/correos/{del_cliente.id}").get_data(as_text=True)
    _salir(client)
    login(client, "logb")                                        # Soporte de otro cliente
    assert client.get(f"/admin/correos/{del_cliente.id}").status_code == 404
    _salir(client)
    login(client, "ofi")
    assert client.get("/admin/correos").status_code == 403


def test_el_enlace_de_restablecer_no_se_guarda(app, client):
    client.post("/auth/olvide", data={"email": "clia@ejemplo.com"})
    r = db.session.scalar(db.select(CorreoEnviado).filter_by(tipo="restablecer"))
    assert r is not None and "http" not in (r.texto or "")


def test_estado_de_la_plataforma(app, client, tmp_path):
    marca = tmp_path / "ultima_copia.txt"
    marca.write_text("2020-01-01T03:00")
    app.config["COPIA_SEGURIDAD_MARCA"] = str(marca)
    db.session.add(ErrorWeb(ruta="GET /pedidos/9", usuario="ofi@ejemplo.com", error="KeyError: 'x'"))
    db.session.commit()
    login(client, "admin")
    html = client.get("/admin/estado").get_data(as_text=True)
    assert "Hace más de 2 días" in html and "GET /pedidos/9" in html and "Invitaciones sin usar" in html
    _salir(client)
    login(client, "loga")
    assert client.get("/admin/estado").status_code == 403
