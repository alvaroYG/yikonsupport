"""15/10/2026 · Recordatorio automático «¿Ha recibido su pedido?»: el día después de la fecha estimada de
entrega, si el pedido sigue «Enviado», una vez (`flask recordar-recepcion`, cron diario).
Escenario de conftest: cliA (Clínica A) · admin · ofi = Almacén."""
from datetime import date, timedelta

from app import correos_cliente as cc
from app.extensions import db
from app.models import Pedido, RegistroAuditoria
from tests.conftest import login, pedido_cliente


def _enviado(client, dias_desde_la_entrega=1):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    p.estado = "enviado"
    p.fecha_entrega_estimada = date.today() - timedelta(days=dias_desde_la_entrega)
    p.transportista, p.numero_seguimiento = "SEUR", "TRK-1"
    db.session.commit()
    return p


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _lanzar(app):
    return app.test_cli_runner().invoke(args=["recordar-recepcion"])


def test_sale_el_dia_despues_una_vez_con_el_enlace(app, client):
    app.config["URL_PLATAFORMA"] = "https://yikonsupport.com"
    p = _enviado(client, dias_desde_la_entrega=1)
    correos = _correos(app)
    r = _lanzar(app)
    assert "Recordatorios de recepción: 1" in r.output
    aviso = [c for c in correos if "¿Ha recibido su pedido" in c["Subject"]]
    assert len(aviso) == 1 and aviso[0]["To"].lower() == "clia@ejemplo.com"
    texto = aviso[0].get_content()
    assert f"https://yikonsupport.com/pedidos/{p.id}" in texto and "Marcar como recibido" in texto
    assert (date.today() - timedelta(days=1)).strftime("%d/%m/%Y") in texto
    assert db.session.get(Pedido, p.id).recordatorio_recibido_el is not None
    assert db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.detalle.like("recordatorio automático%")))
    correos.clear()
    assert "Recordatorios de recepción: 0" in _lanzar(app).output and not correos      # solo una vez
    # Yikon lo ve en la ficha
    login(client, "admin")
    assert "Recordatorio de recepción enviado al cliente" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)


def test_no_sale_antes_ni_si_ya_esta_recibido(app, client):
    hoy = _enviado(client, dias_desde_la_entrega=0)                     # hoy es la fecha estimada: aún no
    recibido = _enviado(client, dias_desde_la_entrega=3)
    recibido.estado = "entregado"
    db.session.commit()
    correos = _correos(app)
    assert "Recordatorios de recepción: 0" in _lanzar(app).output and not correos
    assert db.session.get(Pedido, hoy.id).recordatorio_recibido_el is None


def test_desactivado_en_ajustes_no_sale_ni_se_marca(app, client):
    p = _enviado(client)
    cc.configurar_avisos([c for c in cc.CASOS if c not in cc.CASOS_ACCESO and c != "recordatorio_recibido"])
    db.session.commit()
    correos = _correos(app)
    _lanzar(app)
    assert not correos and db.session.get(Pedido, p.id).recordatorio_recibido_el is None


def test_si_cambia_la_fecha_estimada_vuelve_a_salir(app, client):
    p = _enviado(client)
    _lanzar(app)
    assert db.session.get(Pedido, p.id).recordatorio_recibido_el is not None
    login(client, "ofi")
    nueva = date.today() + timedelta(days=2)
    client.post(f"/pedidos/{p.id}/datos-envio", data={"envio-fecha_entrega_estimada": nueva.isoformat(),
                                                "envio-transportista": "SEUR", "envio-numero_seguimiento": "TRK-1"})
    p = db.session.get(Pedido, p.id)
    assert p.fecha_entrega_estimada == nueva and p.recordatorio_recibido_el is None


def test_el_cliente_que_no_quiere_avisos_de_envio_no_lo_recibe(app, client):
    from app.models import User
    cli = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    cli.avisos_desactivados = "envio"
    db.session.commit()
    p = _enviado(client)
    correos = _correos(app)
    _lanzar(app)
    assert not correos and db.session.get(Pedido, p.id).recordatorio_recibido_el is not None   # no se repite


def test_sale_en_ajustes_de_correos(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/correos").get_data(as_text=True)
    assert "¿Ha recibido el pedido? (recordatorio)" in html and 'name="avisos" value="recordatorio_recibido"' in html
