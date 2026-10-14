"""Paso 92 · "Ver como un usuario": solo admin, solo lectura, franja arriba y en la auditoría."""
from app.extensions import db
from app.models import LecturaHilo, Mensaje, Pedido, RegistroAuditoria, User, VistaPedido
from conftest import login, pedido_cliente


def _id(email):
    return db.session.scalar(db.select(User.id).filter_by(email=f"{email.lower()}@ejemplo.com"))


def test_admin_ve_como_un_cliente_con_la_franja_y_queda_en_la_auditoria(app, client):
    login(client, "admin")
    r = client.post(f"/admin/usuarios/{_id('cliA')}/ver-como", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Estás viendo la plataforma como cliA" in html and "Volver a mi usuario (admin)" in html
    assert "Tus pedidos en curso" in html                     # el inicio del cliente, no el de admin
    registro = db.session.scalar(db.select(RegistroAuditoria).filter_by(accion="ver_como"))
    assert registro is not None and registro.entidad_id == _id("cliA")
    # y vuelve a ser admin
    r = client.post("/auth/dejar-de-ver-como", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Has vuelto a tu usuario" in html and "Estás viendo" not in html
    assert client.get("/admin/usuarios").status_code == 200


def test_no_se_puede_ver_como_otro_admin_ni_lo_puede_hacer_quien_no_es_admin(app, client):
    otro = User(nombre="Otro admin", email="otro@ejemplo.com", rol="admin")
    otro.set_password("password123")
    db.session.add(otro)
    db.session.commit()
    login(client, "admin")
    assert client.post(f"/admin/usuarios/{otro.id}/ver-como").status_code == 404
    assert client.post(f"/admin/usuarios/{_id('admin')}/ver-como").status_code == 404
    client.post("/auth/logout")
    login(client, "ofi")
    assert client.post(f"/admin/usuarios/{_id('cliA')}/ver-como").status_code == 403


def test_viendo_como_no_se_guarda_nada_ni_se_envia_ningun_correo(app, client):
    login(client, "cliA")
    pedido_cliente(client)
    client.post("/auth/logout")
    pedido = db.session.scalar(db.select(Pedido))
    # Yikon le escribe: el cliente lo tiene sin leer
    login(client, "loga")
    client.post(f"/mensajes/pedido/{pedido.id}", data={"texto": "Hola"})
    client.post("/auth/logout")
    app.extensions["correos_enviados"] = []
    acceso_antes = db.session.get(User, _id("cliA")).ultimo_acceso
    login(client, "admin")
    client.post(f"/admin/usuarios/{_id('cliA')}/ver-como")
    # Enviar algo: rechazado
    r = client.post(f"/mensajes/pedido/{pedido.id}", data={"texto": "esto no debe salir"}, follow_redirects=True)
    assert "no se puede guardar ni enviar nada" in r.get_data(as_text=True)
    # Abrir páginas que "apuntan" cosas (visto, leídos): se deshace al terminar
    assert client.get(f"/pedidos/{pedido.id}").status_code == 200
    assert client.get(f"/mensajes/pedido/{pedido.id}/nuevos?abierto=1").status_code == 200
    db.session.expire_all()
    assert db.session.scalar(db.select(db.func.count(Mensaje.id)).filter_by(texto="esto no debe salir")) == 0
    assert db.session.scalar(db.select(VistaPedido).filter_by(usuario_id=_id("cliA"))) is None
    lectura = db.session.scalar(db.select(LecturaHilo).filter_by(usuario_id=_id("cliA")))
    assert lectura is None or lectura.ultimo_mensaje_id == 0
    assert app.extensions["correos_enviados"] == []
    # Ni siquiera el último acceso del cliente cambia
    assert db.session.get(User, _id("cliA")).ultimo_acceso == acceso_antes


def test_si_al_admin_le_quitan_el_rol_mientras_ve_como_se_le_saca(app, client):
    login(client, "admin")
    client.post(f"/admin/usuarios/{_id('cliA')}/ver-como")
    db.session.get(User, _id("admin")).rol = "logistica"
    db.session.commit()
    r = client.get("/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_viendo_como_no_se_deja_la_cookie_de_recordarme_del_otro_usuario(app, client):
    client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "password123", "recordar": "y"})
    client.post(f"/admin/usuarios/{_id('cliA')}/ver-como")
    r = client.get("/")
    assert "remember_token" not in " ".join(r.headers.getlist("Set-Cookie"))
    # la cookie que hay sigue siendo la del admin: al "cerrar el navegador" se vuelve a entrar como admin
    with client.session_transaction() as s:
        s.clear()
    assert "Hola, admin" in client.get("/").get_data(as_text=True)
