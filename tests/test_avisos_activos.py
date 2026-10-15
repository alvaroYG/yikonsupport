"""15/10/2026 (cambio de Álvaro): Ajustes → Correos al cliente → «Qué correos recibe el cliente».
Admin desactiva un aviso y deja de salir para todos los clientes; los de acceso siguen siempre."""
from app import correos_cliente as cc
from app.extensions import db
from app.models import Pedido
from tests.conftest import confirmar_correos, login, pedido_cliente


def test_desactivar_un_aviso_al_cliente(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/correos").get_data(as_text=True)
    assert 'name="avisos" value="preparacion"' in html and 'value="invitacion"' not in html.split("Guardar avisos activos")[0].split("Qué correos recibe el cliente")[1]
    activos = [c for c in cc.CASOS if c not in cc.CASOS_ACCESO and c != "preparacion"]
    r = client.post("/admin/ajustes/correos/avisos-activos", data={"avisos": activos})
    assert r.status_code == 302 and not cc.aviso_activado("preparacion") and cc.aviso_activado("enviado")
    assert cc.aviso_activado("invitacion")                      # los de acceso, siempre
    assert client.post("/admin/ajustes/correos/avisos-activos", data={"avisos": ["invitacion"]}).status_code == 400
    client.post("/auth/logout")
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    login(client, "ofi")
    client.post(f"/pedidos/{p.id}/preparacion")
    assert confirmar_correos() == 0 and not correos             # «En preparación» ya no se prepara
