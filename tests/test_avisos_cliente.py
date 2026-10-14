"""Paso 92 · Qué avisos recibe cada usuario del cliente (ficha del cliente) y emails en copia.
También: la invitación y el cambio de contraseña salen con el logo y la firma de «Correos al cliente»."""
from app.extensions import db
from app.models import CopiaAviso, Pedido, PlantillaCorreo, RegistroAuditoria, User
from conftest import confirmar_correos, login, pedido_cliente


def _usuario(nombre):
    return db.session.scalar(db.select(User).filter_by(email=f"{nombre.lower()}@ejemplo.com"))


def _segundo_usuario_de_a():
    u = User(nombre="Marta", email="marta@ejemplo.com", rol="cliente", cliente_id=1)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    return u


def _pedido_en_preparacion(client):
    login(client, "cliA")
    pedido_cliente(client)
    client.post("/auth/logout")
    return db.session.scalar(db.select(Pedido))


def test_cada_usuario_recibe_solo_los_avisos_marcados_y_las_copias_tambien(app, client):
    marta = _segundo_usuario_de_a()
    pedido = _pedido_en_preparacion(client)
    login(client, "loga")                                # su Soporte de cliente
    html = client.get("/clientes/1").get_data(as_text=True)
    assert "Avisos por email" in html and "Emails en copia" in html
    cli = _usuario("cliA")
    # cliA: todo menos "Estado del pedido" · Marta: todo · almacén (sin usuario): solo "Estado del pedido"
    datos = {f"u{cli.id}": ["proformas", "envio", "mensajes"], f"u{marta.id}": ["proformas", "estado", "envio", "mensajes"],
             "copia_email_0": "Almacen@Clinica-A.com", "copia_tipos_0": ["estado"]}
    r = client.post("/clientes/1/avisos", data=datos)
    assert r.status_code == 302
    assert db.session.get(User, cli.id).avisos_desactivados == "estado"
    copia = db.session.scalar(db.select(CopiaAviso))
    assert copia.email == "almacen@clinica-a.com" and copia.tipos == "estado"
    assert db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.detalle.like("avisos por email:%")))

    # Logística empieza a prepararlo: es un aviso de "Estado del pedido"
    app.extensions["correos_enviados"] = []
    client.post("/auth/logout")
    login(client, "ofi")
    client.post(f"/pedidos/{pedido.id}/preparacion")
    assert confirmar_correos() == 1
    para = " ".join(c["To"] for c in app.extensions["correos_enviados"])
    assert "marta@ejemplo.com" in para and "almacen@clinica-a.com" in para
    assert "clia@ejemplo.com" not in para


def test_mensajes_solo_a_quien_los_tiene_marcados(app, client):
    marta = _segundo_usuario_de_a()
    pedido = _pedido_en_preparacion(client)
    marta.avisos_desactivados = "mensajes"
    db.session.add(CopiaAviso(cliente_id=1, email="jefa@clinica-a.com", tipos="mensajes"))
    db.session.commit()
    app.extensions["correos_enviados"] = []
    login(client, "loga")
    client.post(f"/mensajes/pedido/{pedido.id}", data={"texto": "¿Os va bien el jueves?"})
    assert confirmar_correos() >= 1
    para = " ".join(c["To"] for c in app.extensions["correos_enviados"])
    assert "clia@ejemplo.com" in para and "jefa@clinica-a.com" in para and "marta@ejemplo.com" not in para


def test_solo_admin_y_su_soporte_lo_cambian_y_no_vale_el_email_de_un_usuario(app, client):
    login(client, "logb")                                # Soporte de OTRO cliente
    assert client.post("/clientes/1/avisos", data={}).status_code == 404
    client.post("/auth/logout")
    login(client, "ofi")                                 # Logística: no
    assert client.post("/clientes/1/avisos", data={}).status_code == 403
    client.post("/auth/logout")
    login(client, "admin")
    r = client.post("/clientes/1/avisos", data={"copia_email_0": "clia@ejemplo.com", "copia_tipos_0": ["envio"]},
                    follow_redirects=True)
    assert "ya es un usuario de este cliente" in r.get_data(as_text=True)
    r = client.post("/clientes/1/avisos", data={"copia_email_0": "esto no es un email"}, follow_redirects=True)
    assert "no es un email válido" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(CopiaAviso.id))) == 0
    # Quitar una copia
    db.session.add(CopiaAviso(cliente_id=1, email="x@clinica-a.com", tipos="envio"))
    db.session.commit()
    client.post("/clientes/1/avisos", data={"copia_email_0": "x@clinica-a.com", "copia_quitar_0": "1"})
    assert db.session.scalar(db.select(db.func.count(CopiaAviso.id))) == 0


def test_la_invitacion_lleva_logo_y_firma_y_su_texto_se_puede_cambiar(app, client):
    login(client, "admin")
    html = client.get("/admin/ajustes/correos").get_data(as_text=True)
    assert "Invitación" in html and "Cambiar la contraseña" in html
    # Admin cambia el texto de la invitación (sin quitar el enlace: obligatorio)
    r = client.post("/admin/ajustes/correos/invitacion?idioma=es",
                    data={"idioma": "es", "accion": "guardar", "asunto": "Bienvenida a Yikon",
                          "cuerpo": "Hola {nombre}:\n\nTu enlace: {enlace_acceso} (vale {caducidad})"})
    assert r.status_code == 302 and db.session.scalar(db.select(PlantillaCorreo).filter_by(clave="invitacion"))
    r = client.post("/admin/ajustes/correos/invitacion?idioma=es",
                    data={"idioma": "es", "accion": "guardar", "asunto": "Sin enlace", "cuerpo": "Hola {nombre}"})
    assert "tiene que llevar {enlace_acceso}" in r.get_data(as_text=True)
    app.extensions["correos_enviados"] = []
    client.post("/admin/usuarios/nuevo", data={"nombre": "Ana", "email": "ana@ejemplo.com", "rol": "logistica",
                                               "cliente_id": 0, "activo": "y", "invitar": "y", "idioma": "es"})
    assert not app.extensions["correos_enviados"]       # la invitación espera a que admin la revise
    assert confirmar_correos() == 1
    correo = app.extensions["correos_enviados"][0]
    assert correo["Subject"] == "Bienvenida a Yikon"
    texto = correo.get_content()
    assert "Hola Ana:" in texto and "/auth/invitacion/" in texto and "7 días" in texto
    html = correo.get_body(preferencelist=("html",)).get_content()
    assert "cid:logo-yikon" in html                       # el logo, dentro del correo
    assert "aviso automático" in texto                    # la firma de fábrica


def test_el_cambio_de_contrasena_tambien_y_dice_lo_que_vale_el_enlace(app, client):
    app.extensions["correos_enviados"] = []
    client.post("/auth/olvide", data={"email": "cliA@ejemplo.com"})
    correo = app.extensions["correos_enviados"][0]
    texto = correo.get_content()
    assert "/auth/restablecer/" in texto and "2 horas" in texto
    assert "cid:logo-yikon" in correo.get_body(preferencelist=("html",)).get_content()
