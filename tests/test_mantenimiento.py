"""Modo mantenimiento: solo entra admin; los demás ven el aviso (también en la página de entrar)."""
from tests.conftest import login


def test_solo_entra_admin_y_se_desactiva(app, client):
    login(client, "admin")
    client.post("/admin/ajustes/mantenimiento", data={"activado": "1", "mensaje": "Volvemos a las 12:00"})
    assert "Modo mantenimiento activado" in client.get("/pedidos/").get_data(as_text=True)   # admin trabaja
    client.post("/auth/logout")
    assert "Volvemos a las 12:00" in client.get("/auth/login").get_data(as_text=True)
    login(client, "ofi")
    r = client.get("/pedidos/")
    assert r.status_code == 503 and "Volvemos a las 12:00" in r.get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "admin")
    client.post("/admin/ajustes/mantenimiento", data={})
    client.post("/auth/logout")
    login(client, "ofi")
    assert client.get("/pedidos/").status_code == 200


def test_solo_admin_lo_cambia(app, client):
    login(client, "ofi")
    assert client.post("/admin/ajustes/mantenimiento", data={"activado": "1"}).status_code == 403
