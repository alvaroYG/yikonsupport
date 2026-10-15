"""15/10/2026 · Soporte de cliente lleva sus clientes de punta a punta: los da de alta (quedan asignados
a él), cambia sus datos y crea/edita los usuarios de esas empresas (rol Cliente, con invitación).
Admin solo vigila: le llega el aviso «Alta de un cliente o de un usuario» y nada espera su aprobación.
Escenario de conftest: loga = Soporte de Clínica A (id 1) · logb = Soporte de Clínica B (id 2) · cliA."""
from app.extensions import db
from app.models import Cliente, CorreoBorrador, User
from tests.conftest import confirmar_correos, login


def _salir(client):
    client.post("/auth/logout")


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def test_soporte_da_de_alta_un_cliente_y_queda_suyo(app, client):
    correos = _correos(app)
    login(client, "loga")
    assert 'href="/clientes/nuevo"' in client.get("/clientes/").get_data(as_text=True)
    html = client.get("/clientes/nuevo").get_data(as_text=True)
    assert 'name="logisticos"' not in html                 # quién lo lleva no lo elige: es suyo
    r = client.post("/clientes/nuevo", data={"nombre": "Clínica Nueva", "cif": "B33333333", "activo": "y",
                                             "envio_igual": "y"})
    c = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica Nueva"))
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/clientes/{c.id}#usuarios")
    assert [u.nombre for u in c.logisticos] == ["loga"]
    assert client.get(f"/clientes/{c.id}").status_code == 200
    # A admin le llega el aviso (sin revisión: es entre compañeros); a él no
    aviso = [m for m in correos if "Cliente nuevo: Clínica Nueva" in m["Subject"]]
    assert aviso and aviso[0]["To"] == "admin@ejemplo.com" and "loga" in aviso[0].get_content()
    _salir(client)
    login(client, "logb")                                  # otro Soporte no lo ve
    assert client.get(f"/clientes/{c.id}").status_code == 404


def test_soporte_cambia_los_datos_de_los_suyos_y_no_los_de_otros(app, client):
    login(client, "loga")
    datos = {"nombre": "Clínica A", "prefijo": "CLA", "cif": "B11111111", "ciudad": "Bilbao", "activo": "y",
             "envio_igual": "y"}
    assert client.post("/clientes/1/editar", data=datos).status_code == 302
    assert db.session.get(Cliente, 1).ciudad == "Bilbao"
    assert [u.nombre for u in db.session.get(Cliente, 1).logisticos] == ["loga"]   # sigue siendo suyo
    assert client.get("/clientes/2/editar").status_code == 404
    # No ve el nombre del cliente que ya tiene ese CIF (no es suyo)
    r = client.post("/clientes/1/editar", data={**datos, "cif": "B22222222"})
    assert "Ese CIF ya está registrado en otro cliente." in r.get_data(as_text=True)
    assert "Clínica B" not in r.get_data(as_text=True)
    # Los precios especiales siguen siendo de Facturación y admin
    assert client.post("/clientes/1/precios", data={"kit_id": 1, "precio": "50"}).status_code == 403


def test_soporte_crea_usuarios_de_su_cliente_con_invitacion(app, client):
    correos = _correos(app)
    login(client, "loga")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert 'id="usuarios"' in html and "Usuarios y avisos" in html and "/clientes/1/usuarios/nuevo" in html
    r = client.post("/clientes/1/usuarios/nuevo", data={"nombre": "Marta", "email": "Marta@ClinicaA.com",
                                                       "activo": "y", "idioma": "es"})
    assert r.status_code == 302
    u = db.session.scalar(db.select(User).filter_by(email="marta@clinicaa.com"))
    assert u.rol == "cliente" and u.cliente_id == 1 and u.activo
    # La invitación la revisa y la envía él (como todas)
    borrador = db.session.scalar(db.select(CorreoBorrador).filter_by(estado="pendiente"))
    assert borrador and borrador.autor_id == db.session.scalar(db.select(User.id).filter_by(email="loga@ejemplo.com"))
    assert confirmar_correos() >= 1
    assert any("marta@clinicaa.com" in m["To"] for m in correos)
    assert any("Usuario nuevo en Clínica A" in m["Subject"] and m["To"] == "admin@ejemplo.com" for m in correos)
    # Editar, desactivar y no repetir email
    assert client.post(f"/clientes/1/usuarios/{u.id}", data={"nombre": "Marta R.", "email": "marta@clinicaa.com",
                                                            "idioma": ""}).status_code == 302
    u = db.session.get(User, u.id)
    assert u.nombre == "Marta R." and not u.activo and u.rol == "cliente"
    r = client.post("/clientes/1/usuarios/nuevo", data={"nombre": "Otra", "email": "cliA@ejemplo.com", "activo": "y"})
    assert "Ya existe un usuario con ese email." in r.get_data(as_text=True)


def test_reenviar_la_invitacion(app, client):
    login(client, "loga")
    cli = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    client.post(f"/clientes/1/usuarios/{cli.id}/invitar")
    assert db.session.scalar(db.select(CorreoBorrador).filter_by(estado="pendiente"))


def test_solo_usuarios_de_sus_clientes(app, client):
    cliB = db.session.scalar(db.select(User).filter_by(email="clib@ejemplo.com"))
    loga = db.session.scalar(db.select(User).filter_by(email="loga@ejemplo.com"))
    login(client, "loga")
    assert client.get("/clientes/2/usuarios/nuevo").status_code == 404
    assert client.get(f"/clientes/2/usuarios/{cliB.id}").status_code == 404
    assert client.get(f"/clientes/1/usuarios/{cliB.id}").status_code == 404          # de otra empresa
    assert client.get(f"/clientes/1/usuarios/{loga.id}").status_code == 404          # no es de un cliente
    assert client.get("/admin/usuarios").status_code == 403                          # la gestión general, no
    _salir(client)
    for quien in ("fac", "ofi", "cliA"):                   # Facturación: ni clientes ni usuarios (sí sus datos)
        login(client, quien)
        assert client.get("/clientes/1/usuarios/nuevo").status_code == 403, quien
        assert client.get("/clientes/nuevo").status_code == 403, quien
        _salir(client)
    login(client, "fac")
    assert 'href="/clientes/nuevo"' not in client.get("/clientes/").get_data(as_text=True)
    assert client.get("/clientes/1/editar").status_code == 200


def test_admin_tambien_y_no_tiene_que_aprobar_nada(app, client):
    correos = _correos(app)
    login(client, "admin")
    assert client.post("/clientes/1/usuarios/nuevo", data={"nombre": "Luis", "email": "luis@a.com",
                                                          "activo": "y"}).status_code == 302
    assert db.session.scalar(db.select(User).filter_by(email="luis@a.com")).activo
    assert not [m for m in correos if "Usuario nuevo" in m["Subject"]]     # no se avisa a sí mismo


def test_sin_el_apartado_clientes_no_puede(app, client):
    from app import apartados
    apartados.guardar({(c, r) for c, ap in apartados.APARTADOS.items() for r in ap.cambiables
                       if not (c == "clientes" and r == "fas") and apartados.visible(c, r)})
    db.session.commit()
    login(client, "loga")
    assert client.get("/clientes/nuevo").status_code == 403
    assert client.get("/clientes/1/usuarios/nuevo").status_code == 403
