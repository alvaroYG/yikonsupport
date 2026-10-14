"""Invitaciones: el usuario nuevo recibe un enlace y elige su propia contraseña."""
import re

from app.extensions import db
from app.models import User
from tests.conftest import confirmar_correos, login


def _enlace(correo):
    return re.search(r"http://[^\s]+/auth/invitacion/[^\s]+", correo.get_content()).group(0)


def test_invitar_usuario_nuevo(app, client):
    correos = app.extensions.setdefault("correos_enviados", []); correos.clear()
    login(client, "admin")
    r = client.post("/admin/usuarios/nuevo", data={"nombre": "Ana Nueva", "email": "ana@ejemplo.com",
                                                   "rol": "cliente", "cliente_id": 1, "activo": "y",
                                                   "invitar": "y", "idioma": "en"})
    assert r.status_code == 302
    assert not correos and confirmar_correos() == 1     # la invitación sale cuando admin la revisa
    assert len(correos) == 1 and correos[0]["To"] == "ana@ejemplo.com"
    assert "Your access" in correos[0]["Subject"]                 # en su idioma
    enlace = _enlace(correos[0]).replace("http://localhost", "")
    assert "Invitación pendiente" in client.get("/admin/usuarios").get_data(as_text=True)
    client.post("/auth/logout")
    # abre el enlace, elige contraseña y entra directamente
    assert client.get(enlace).status_code == 200
    r = client.post(enlace, data={"nueva": "contraseña-segura-1", "confirmar": "contraseña-segura-1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    ana = db.session.scalar(db.select(User).filter_by(email="ana@ejemplo.com"))
    assert ana.check_password("contraseña-segura-1") and ana.ultimo_acceso is not None
    # el enlace ya no sirve una segunda vez
    client.post("/auth/logout")
    r = client.get(enlace, follow_redirects=True)
    assert "no es válida o ha caducado" in r.get_data(as_text=True)


def test_sin_invitacion_hace_falta_contrasena(app, client):
    login(client, "admin")
    r = client.post("/admin/usuarios/nuevo", data={"nombre": "X", "email": "x@ejemplo.com",
                                                   "rol": "admin", "cliente_id": 0, "activo": "y"})
    assert "Pon una contraseña" in r.get_data(as_text=True)


def test_reenviar_invitacion_y_el_token_de_invitacion_no_sirve_para_restablecer(app, client):
    correos = app.extensions.setdefault("correos_enviados", [])
    login(client, "admin")
    client.post("/admin/usuarios/nuevo", data={"nombre": "Bea", "email": "bea@ejemplo.com",
                                               "rol": "admin", "cliente_id": 0, "activo": "y", "invitar": "y"})
    assert confirmar_correos() == 1
    bea = db.session.scalar(db.select(User).filter_by(email="bea@ejemplo.com"))
    correos.clear()
    client.post(f"/admin/usuarios/{bea.id}/invitar")
    assert confirmar_correos() == 1
    assert len(correos) == 1
    token = _enlace(correos[0]).rsplit("/", 1)[1]
    client.post("/auth/logout")
    r = client.get(f"/auth/restablecer/{token}", follow_redirects=True)
    assert "no es válido o ha caducado" in r.get_data(as_text=True)
    # al editar un usuario no aparece la casilla de invitar
    login(client, "admin")
    assert 'name="invitar"' not in client.get(f"/admin/usuarios/{bea.id}").get_data(as_text=True)
