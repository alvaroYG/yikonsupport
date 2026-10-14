"""Administración → Ajustes: los plazos de aviso los fija admin (app/ajustes.py)."""
from app import ajustes
from app.extensions import db
from app.models import Ajuste, RegistroAuditoria
from tests.conftest import login


def _datos(**cambios):
    datos = {f"plazo_{estado}": dias for estado, (dias, _texto) in ajustes.PLAZOS.items()}
    datos.update({f"plazo_{estado}": valor for estado, valor in cambios.items()})
    return datos


def test_solo_admin_entra_en_ajustes(app, client):
    for usuario, esperado in [("admin", 200), ("ofi", 403), ("loga", 403), ("cliA", 403)]:
        login(client, usuario)
        assert client.get("/admin/ajustes").status_code == esperado, usuario
        assert client.post("/admin/ajustes", data=_datos(aceptado=9)).status_code == (302 if esperado == 200 else 403)
        client.post("/auth/logout")
    assert ajustes.plazos()["aceptado"] == 9                      # solo lo cambió admin


def test_sin_tocar_nada_valen_los_de_fabrica_y_al_guardar_se_apunta(app, client):
    assert ajustes.plazos() == {estado: dias for estado, (dias, _texto) in ajustes.PLAZOS.items()}
    login(client, "admin")
    html = client.get("/admin/ajustes").get_data(as_text=True)
    assert 'name="plazo_proforma_enviada" value="7"' in html
    client.post("/admin/ajustes", data=_datos(proforma_enviada=10, enviado=0))
    assert ajustes.plazos()["proforma_enviada"] == 10 and ajustes.plazos()["enviado"] == 0
    assert db.session.scalar(db.select(db.func.count(Ajuste.clave))) == 2          # solo se guarda lo cambiado
    registro = db.session.scalar(db.select(RegistroAuditoria).filter_by(entidad="Ajuste"))
    assert "proforma_enviada 7→10" in registro.detalle and "enviado 7→0" in registro.detalle


def test_un_valor_que_no_vale_no_guarda_nada(app, client):
    login(client, "admin")
    for malo in ("-1", "9999", "abc", ""):
        r = client.post("/admin/ajustes", data=_datos(aceptado=malo, enviado=20))
        assert r.status_code == 200 and "Escribe un número de días entre 0 y 365." in r.get_data(as_text=True), malo
    assert ajustes.plazos()["enviado"] == 7 and db.session.scalar(db.select(db.func.count(Ajuste.clave))) == 0


def test_con_cero_no_se_avisa_nunca(app, client):
    from datetime import timedelta
    from app.models import Pedido, ahora
    from tests.conftest import pedido_cliente
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    for r in db.session.scalars(db.select(RegistroAuditoria).filter_by(entidad="Pedido", entidad_id=p.id)):
        r.fecha = ahora() - timedelta(days=40)
    db.session.commit()
    login(client, "admin")
    assert "espera-lenta" in client.get("/").get_data(as_text=True)
    client.post("/admin/ajustes", data=_datos(aceptado=0))
    html = client.get("/").get_data(as_text=True)
    assert "espera-lenta" not in html and "hace 40 días" in html
