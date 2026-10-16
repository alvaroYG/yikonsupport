"""Paso 92 · Aviso para clientes (Ajustes → General) y Ajustes → Seguridad."""
from datetime import date, timedelta

from app.extensions import db
from app.models import User
from conftest import login


def _guardar_aviso(client, es="", en="", desde="", hasta=""):
    return client.post("/admin/ajustes/aviso-clientes", data={"aviso_es": es, "aviso_en": en, "desde": desde,
                                                              "hasta": hasta, "accion": "guardar"})


# --------------------------------------------------------------------------- #
# Aviso para clientes
# --------------------------------------------------------------------------- #
def test_el_aviso_sale_al_cliente_en_su_idioma_y_lo_puede_cerrar(app, client):
    login(client, "admin")
    _guardar_aviso(client, es="Cerramos del 24 al 26.", en="We are closed from 24th to 26th.")
    assert "Se está viendo" in client.get("/admin/ajustes/panel/comunicaciones").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "cliA")
    html = client.get("/").get_data(as_text=True)
    assert "Cerramos del 24 al 26." in html
    # en inglés, el suyo
    client.post("/idioma", data={"idioma": "en"})
    assert "We are closed from 24th to 26th." in client.get("/").get_data(as_text=True)
    client.post("/idioma", data={"idioma": "es"})
    # lo cierra: ya no sale...
    import re
    huella = re.search(r'name="huella" value="([0-9a-f]+)"', client.get("/").get_data(as_text=True)).group(1)
    client.post("/aviso-clientes/cerrar", data={"huella": huella})
    assert "Cerramos del 24 al 26." not in client.get("/").get_data(as_text=True)
    client.post("/auth/logout")
    # ...hasta que admin cambia el texto
    login(client, "admin")
    _guardar_aviso(client, es="Cerramos del 24 al 27.")
    client.post("/auth/logout")
    login(client, "cliA")
    assert "Cerramos del 24 al 27." in client.get("/").get_data(as_text=True)


def test_el_aviso_respeta_las_fechas_y_no_sale_a_yikon(app, client):
    login(client, "admin")
    manana = date.today() + timedelta(days=1)
    _guardar_aviso(client, es="Aviso futuro", desde=manana.isoformat())
    assert "Programado" in client.get("/admin/ajustes/panel/comunicaciones").get_data(as_text=True)
    assert 'class="aviso-clientes' not in client.get("/").get_data(as_text=True)     # (a Yikon no le sale)
    _guardar_aviso(client, es="Mal", desde=manana.isoformat(), hasta=date.today().isoformat())
    assert "no puede ser anterior" in client.get("/admin/ajustes/panel/comunicaciones").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "cliA")
    assert "Aviso futuro" not in client.get("/").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "admin")
    client.post("/admin/ajustes/aviso-clientes", data={"accion": "quitar"})
    assert "Sin aviso" in client.get("/admin/ajustes/panel/comunicaciones").get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Seguridad
# --------------------------------------------------------------------------- #
def _seguridad(client, **valores):
    datos = {"invitacion_dias": 7, "reset_horas": 2, "fallos": 5, "ventana_minutos": 15, "inactividad_horas": 8}
    datos.update(valores)
    return client.post("/admin/ajustes/seguridad", data=datos, follow_redirects=True)


def test_la_pagina_de_seguridad_guarda_y_valida(app, client):
    login(client, "admin")
    assert "Bloquear tras intentos fallidos" in client.get("/admin/ajustes/seguridad").get_data(as_text=True)
    assert "Escribe un número entre 3 y 50" in _seguridad(client, fallos=1).get_data(as_text=True)
    assert "Guardado" in _seguridad(client, fallos=3).get_data(as_text=True)
    from app import seguridad
    assert seguridad.valor("fallos") == 3
    assert client.get("/admin/ajustes/seguridad").status_code == 200
    client.post("/auth/logout")
    login(client, "ofi")
    assert client.get("/admin/ajustes/seguridad").status_code == 403


def test_el_bloqueo_usa_los_intentos_de_ajustes(app, client):
    login(client, "admin")
    _seguridad(client, fallos=3)
    client.post("/auth/logout")
    for _ in range(3):
        client.post("/auth/login", data={"email": "cliA@ejemplo.com", "password": "mal"})
    r = client.post("/auth/login", data={"email": "cliA@ejemplo.com", "password": "password123"})
    assert r.status_code == 429


def test_la_sesion_se_cierra_tras_las_horas_de_inactividad(app, client):
    login(client, "admin")
    _seguridad(client, inactividad_horas=1)
    assert client.get("/").status_code == 200
    with client.session_transaction() as s:              # la última actividad, hace dos horas
        s["ultima_actividad"] -= 2 * 3600
    r = client.get("/pedidos/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    # Con 0 no se cierra nunca
    login(client, "admin")
    _seguridad(client, inactividad_horas=0)
    with client.session_transaction() as s:
        s["ultima_actividad"] -= 200 * 3600
    assert client.get("/pedidos/").status_code == 200


def test_las_consultas_automaticas_no_cuentan_como_actividad(app, client):
    login(client, "admin")
    client.get("/")
    with client.session_transaction() as s:
        antes = s["ultima_actividad"] - 3600
        s["ultima_actividad"] = antes
    client.get("/mensajes/flotante/cuenta")
    with client.session_transaction() as s:
        assert s["ultima_actividad"] == antes


def test_la_invitacion_caduca_segun_ajustes(app, client):
    from app.auth.routes import crear_token_invitacion
    login(client, "admin")
    _seguridad(client, invitacion_dias=1)
    client.post("/auth/logout")
    nuevo = User(nombre="Nuevo", email="nuevo@ejemplo.com", rol="cliente", cliente_id=1)
    nuevo.set_password("x" * 20)
    db.session.add(nuevo)
    db.session.commit()
    with app.test_request_context():
        token = crear_token_invitacion(nuevo)
    import time
    from unittest import mock
    ahora_real = time.time()
    with mock.patch("itsdangerous.timed.time.time", return_value=ahora_real + 2 * 86400):
        r = client.get(f"/auth/invitacion/{token}", follow_redirects=True)
    assert "no es válida o ha caducado" in r.get_data(as_text=True)
