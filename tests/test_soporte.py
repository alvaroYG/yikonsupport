"""
Soporte ChromGo: tickets. Lo importante: cada empresa ve SOLO sus tickets, el cliente nunca
ve las notas internas, y los tickets no se mezclan con los Mensajes de pedidos.
"""
from io import BytesIO

from app.extensions import db
from app.models import Cliente, Mensaje, Ticket, TicketMensaje, User
from tests.conftest import confirmar_correos, login


def _correos(app):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    return correos


def _destinatarios(correos):
    return {d.strip() for c in correos for d in c["To"].split(",")}


def _nuevo(client, asunto="El informe CNV no se genera", **extra):
    datos = {"asunto": asunto, "categoria": "cnv", "prioridad": "alta", "referencia": "S-2026-0042",
             "texto": "Al pulsar «Generar informe» sale un error 500.", **extra}
    return client.post("/soporte/nuevo", data=datos, content_type="multipart/form-data")


def _ticket():
    return db.session.scalar(db.select(Ticket).order_by(Ticket.id.desc()))


def test_quien_ve_soporte(app, client):
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    for usuario, esperado in [("admin", 200), ("sop", 200), ("chrA", 200), ("loga", 200), ("cliA", 403)]:
        login(client, usuario)
        assert client.get("/soporte/").status_code == esperado, usuario
        client.post("/auth/logout")
    # un cliente "normal" entra si su empresa usa ChromGo
    cli = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    cli.acceso_chromgo = True; db.session.commit()
    login(client, "cliA")
    assert client.get("/soporte/").status_code == 200
    assert "Tickets ChromGo" in client.get("/pedidos/").get_data(as_text=True)      # en el menú


def test_roles_nuevos_solo_ven_soporte(app, client):
    login(client, "chrA")
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/soporte/")    # su inicio
    for url in ("/pedidos/", "/mensajes/", "/productos/catalogo", "/facturas/mias", "/documentos/"):
        assert client.get(url).status_code == 403, url
    client.post("/auth/logout")
    login(client, "sop")
    for url in ("/pedidos/", "/mensajes/", "/clientes/", "/inventario/", "/facturas/"):
        assert client.get(url).status_code == 403, url
    assert client.get("/documentos/").status_code == 200                          # es del equipo


def test_cliente_abre_ticket_y_avisa_al_equipo(app, client):
    correos = _correos(app)
    login(client, "chrA")
    r = _nuevo(client, adjuntos=(BytesIO(b"error log"), "chromgo.log"))
    assert r.status_code == 302
    t = _ticket()
    assert t.numero.startswith("TK-") and t.numero.endswith("-0001")
    assert t.cliente.nombre == "Clínica A" and t.estado == "abierto" and t.prioridad == "alta"
    assert t.mensajes[0].adjuntos[0].nombre_original == "chromgo.log"
    assert _destinatarios(correos) == {"sop@ejemplo.com"}                        # soporte (no admin, no logistics)
    assert "Nuevo ticket" in correos[0]["Subject"] and t.numero in correos[0]["Subject"]
    # nada de esto aparece en Mensajes
    assert db.session.scalar(db.select(db.func.count(Mensaje.id))) == 0


def test_aislamiento_entre_empresas(app, client):
    login(client, "chrA"); _nuevo(client); client.post("/auth/logout")
    t = _ticket()
    adjunto_url = None
    login(client, "chrB")
    assert client.get(f"/soporte/{t.id}").status_code == 404
    assert client.get(f"/soporte/{t.id}/nuevos").status_code == 404
    assert client.post(f"/soporte/{t.id}/responder", data={"texto": "hola"}).status_code == 404
    assert client.post(f"/soporte/{t.id}/cerrar").status_code == 404
    assert t.asunto not in client.get("/soporte/?estado=todos").get_data(as_text=True)
    client.post("/auth/logout")
    # los compañeros de la misma empresa sí lo ven
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    cli = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    cli.acceso_chromgo = True; db.session.commit()
    login(client, "cliA")
    assert client.get(f"/soporte/{t.id}").status_code == 200


def test_notas_internas_no_las_ve_el_cliente(app, client):
    login(client, "chrA"); _nuevo(client); client.post("/auth/logout")
    t = _ticket()
    login(client, "sop")
    client.post(f"/soporte/{t.id}/nota", content_type="multipart/form-data",
                data={"nota-texto": "Parece el bug del pipeline v2.3; lo miro con bioinfo",
                      "nota-adjuntos": (BytesIO(b"traza"), "traza.txt")})
    nota = db.session.scalar(db.select(TicketMensaje).filter_by(interno=True))
    assert nota is not None
    client.post("/auth/logout")
    login(client, "chrA")
    html = client.get(f"/soporte/{t.id}").get_data(as_text=True)
    assert "bug del pipeline" not in html and "Notas internas" not in html
    assert "bug del pipeline" not in client.get(f"/soporte/{t.id}/nuevos").get_json()["html"]
    assert client.get(f"/soporte/{t.id}/nuevos-internos").status_code == 403
    assert client.get(f"/soporte/adjunto/{nota.adjuntos[0].id}").status_code == 404
    assert client.post(f"/soporte/{t.id}/nota", data={"nota-texto": "x"}).status_code == 403


def test_respuestas_y_estados_automaticos(app, client):
    correos = _correos(app)
    login(client, "chrA"); _nuevo(client); client.post("/auth/logout")
    t = _ticket()
    correos.clear()
    login(client, "sop")
    client.post(f"/soporte/{t.id}/responder", data={"texto": "¿Qué navegador usa?", "dejar_en": "esperando_cliente"})
    assert confirmar_correos() == 1
    db.session.refresh(t)
    assert t.estado == "esperando_cliente" and t.asignado_a.email == "sop@ejemplo.com"   # se lo queda quien responde
    assert _destinatarios(correos) == {"chra@ejemplo.com"}
    client.post("/auth/logout")
    correos.clear()
    login(client, "chrA")
    assert "1 ticket de ChromGo con novedades" in client.get("/soporte/").get_data(as_text=True)
    client.post(f"/soporte/{t.id}/responder", data={"texto": "Chrome 128"})
    db.session.refresh(t)
    assert t.estado == "en_curso"                                  # responde el cliente → vuelve a en curso
    assert _destinatarios(correos) == {"sop@ejemplo.com"}          # a quien lo lleva
    # el cliente lo cierra
    client.post(f"/soporte/{t.id}/cerrar")
    db.session.refresh(t)
    assert t.estado == "cerrado" and t.resuelto is not None
    r = client.post(f"/soporte/{t.id}/responder", data={"texto": "otra cosa"}, follow_redirects=True)
    assert "está cerrado" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(TicketMensaje.id)).filter_by(texto="otra cosa")) == 0


def test_panel_del_equipo(app, client):
    login(client, "chrA"); _nuevo(client); client.post("/auth/logout")
    t = _ticket()
    sop = db.session.scalar(db.select(User).filter_by(email="sop@ejemplo.com"))
    login(client, "admin")
    client.post(f"/soporte/{t.id}/gestion", data={"estado": "resuelto", "prioridad": "urgente",
                                                  "categoria": "informes", "asignado_a_id": sop.id})
    db.session.refresh(t)
    assert (t.estado, t.prioridad, t.categoria, t.asignado_a_id) == ("resuelto", "urgente", "informes", sop.id)
    # el cambio de estado queda en la conversación; lo demás, en las notas internas
    publicos = [m.texto for m in t.mensajes if not m.interno]
    internos = [m.texto for m in t.mensajes if m.interno]
    assert any("Resuelto" in x for x in publicos)
    assert any("Urgente" in x and "sop" in x for x in internos)
    # no se puede asignar a alguien que no es del equipo
    loga = db.session.scalar(db.select(User).filter_by(email="loga@ejemplo.com"))
    assert client.post(f"/soporte/{t.id}/gestion", data={"estado": "resuelto", "prioridad": "urgente",
                                                         "categoria": "informes", "asignado_a_id": loga.id}).status_code == 400
    client.post("/auth/logout")
    login(client, "chrA")                                   # el cliente no gestiona
    assert client.post(f"/soporte/{t.id}/gestion", data={"estado": "cerrado"}).status_code == 403


def test_equipo_abre_ticket_en_nombre_de_un_cliente(app, client):
    correos = _correos(app)
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    login(client, "sop")
    r = _nuevo(client, asunto="Llamada: no pueden entrar", cliente_id=b.id)
    assert r.status_code == 302
    t = _ticket()
    assert t.cliente_id == b.id and t.creado_por.email == "sop@ejemplo.com"
    assert confirmar_correos() == 1
    assert _destinatarios(correos) == {"chrb@ejemplo.com"}      # los de la empresa con acceso a soporte
    client.post("/auth/logout")
    login(client, "chrB")
    assert "Llamada: no pueden entrar" in client.get("/soporte/").get_data(as_text=True)


def test_cliente_no_puede_elegir_otra_empresa(app, client):
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    login(client, "chrA")
    _nuevo(client, cliente_id=b.id)                            # el campo no existe para él: se ignora
    assert _ticket().cliente.nombre == "Clínica A"


def test_admin_puede_crear_usuarios_de_los_roles_nuevos(app, client):
    login(client, "admin")
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    r = client.post("/admin/usuarios/nuevo", data={"nombre": "Ana", "email": "ana@ejemplo.com", "rol": "cliente_chromgo",
                                                   "cliente_id": 0, "password": "password1234", "idioma": ""})
    assert "debe pertenecer a una empresa" in r.get_data(as_text=True)
    client.post("/admin/usuarios/nuevo", data={"nombre": "Ana", "email": "ana@ejemplo.com", "rol": "cliente_chromgo",
                                               "cliente_id": a.id, "password": "password1234", "idioma": "", "activo": "y"})
    client.post("/admin/usuarios/nuevo", data={"nombre": "Sergio", "email": "sergio@ejemplo.com", "rol": "soporte",
                                               "cliente_id": a.id, "password": "password1234", "idioma": "", "activo": "y"})
    ana = db.session.scalar(db.select(User).filter_by(email="ana@ejemplo.com"))
    sergio = db.session.scalar(db.select(User).filter_by(email="sergio@ejemplo.com"))
    assert ana.cliente_id == a.id and sergio.cliente_id is None       # soporte no es de ninguna empresa


def test_leer_una_conversacion_no_marca_la_otra(app, client):
    """Revisión: al ver (o recibir por sondeo) la conversación del cliente, las notas internas
    siguen contando como nuevas hasta abrirlas, y al revés."""
    from app.soporte.servicio import internos_sin_leer
    login(client, "chrA"); _nuevo(client); client.post("/auth/logout")
    t = _ticket()
    login(client, "sop")
    client.post(f"/soporte/{t.id}/nota", data={"nota-texto": "nota para admin"})
    client.post("/auth/logout")
    login(client, "chrA"); client.post(f"/soporte/{t.id}/responder", data={"texto": "más datos"}); client.post("/auth/logout")
    admin = db.session.scalar(db.select(User).filter_by(email="admin@ejemplo.com"))
    login(client, "admin")
    client.get(f"/soporte/{t.id}/nuevos?despues=0")                  # sondeo de la conversación del cliente
    assert internos_sin_leer(admin, t) == 1
    client.get(f"/soporte/{t.id}/nuevos-internos?despues=0")
    assert internos_sin_leer(admin, t) == 0


def test_numeracion_pasado_el_9999(app, client):
    from datetime import date
    login(client, "chrA"); _nuevo(client)
    t = _ticket(); t.numero = f"TK-{date.today().year}-9999"; db.session.commit()
    _nuevo(client, asunto="dos"); _nuevo(client, asunto="tres")
    anio = date.today().year
    assert set(db.session.scalars(db.select(Ticket.numero))) == {f"TK-{anio}-9999", f"TK-{anio}-10000", f"TK-{anio}-10001"}


def test_fas_en_los_tickets_de_sus_clientes(app, client):
    """FAS: los tickets de SUS clientes, con las notas internas. Responde al cliente, pero el
    estado no cambia (eso lo decide Soporte); no gestiona, no cierra ni abre tickets.
    Logística no ve Soporte."""
    correos = _correos(app)
    login(client, "chrA"); _nuevo(client, asunto="Ticket de A"); client.post("/auth/logout")
    login(client, "chrB"); _nuevo(client, asunto="Ticket de B"); client.post("/auth/logout")
    ta = db.session.scalar(db.select(Ticket).filter_by(asunto="Ticket de A"))
    tb = db.session.scalar(db.select(Ticket).filter_by(asunto="Ticket de B"))
    login(client, "sop"); client.post(f"/soporte/{ta.id}/nota", data={"nota-texto": "Laura, ¿les enviamos el kit nuevo?"})
    client.post("/auth/logout")
    login(client, "loga")                                          # FAS de la Clínica A
    html = client.get("/soporte/?estado=todos").get_data(as_text=True)
    assert "Ticket de A" in html and "Ticket de B" not in html
    assert client.get(f"/soporte/{tb.id}").status_code == 404
    html = client.get(f"/soporte/{ta.id}").get_data(as_text=True)
    assert "¿les enviamos el kit nuevo?" in html and "Guardar cambios" not in html
    assert "El estado del ticket lo cambia el equipo de soporte" in html
    # notas internas: le llegan al equipo; el cliente no la ve
    correos.clear()
    assert client.post(f"/soporte/{ta.id}/nota", data={"nota-texto": "Sí, sale mañana"}).status_code == 302
    assert confirmar_correos() == 1
    assert "sop@ejemplo.com" in _destinatarios(correos) and "chra@ejemplo.com" not in _destinatarios(correos)
    # responde al cliente: el mensaje llega, el estado sigue igual y no se le asigna
    correos.clear()
    assert client.post(f"/soporte/{ta.id}/responder", data={"texto": "Os llamo esta tarde",
                                                            "dejar_en": "resuelto"}).status_code == 302
    db.session.refresh(ta)
    assert ta.estado == "abierto" and ta.asignado_a_id is None
    assert confirmar_correos() == 1
    assert any(m.texto == "Os llamo esta tarde" and not m.interno for m in ta.mensajes)
    assert "chra@ejemplo.com" in _destinatarios(correos)
    # lo que no puede hacer
    assert client.post(f"/soporte/{ta.id}/gestion", data={"estado": "cerrado"}).status_code == 403
    assert client.post(f"/soporte/{ta.id}/cerrar").status_code == 403
    assert client.get("/soporte/nuevo").status_code == 403
    assert client.post(f"/soporte/{tb.id}/responder", data={"texto": "hola"}).status_code == 404
    client.post("/auth/logout")
    login(client, "chrA")
    html = client.get(f"/soporte/{ta.id}").get_data(as_text=True)
    assert "Sí, sale mañana" not in html and "Os llamo esta tarde" in html
    client.post("/auth/logout")
    login(client, "ofi")                                           # Logística: Soporte no
    assert client.get(f"/soporte/{ta.id}").status_code == 403


def test_empresa_desactivada_no_abre_tickets(app, client):
    """Revisión: un cliente de una empresa desactivada no puede abrir un ticket (luego no lo vería)."""
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    a.activo = False; db.session.commit()
    login(client, "chrA")
    assert _nuevo(client).status_code == 403
    assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 0
