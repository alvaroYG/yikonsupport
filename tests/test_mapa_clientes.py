"""15/10/2026 · Mapa de clientes (Clientes → Mapa): un punto por cliente situado (latitud/longitud), su
resumen al elegirlo. Cada uno ve los clientes que ve en la lista (Soporte de cliente: los suyos). La
posición se busca sola con la ciudad al guardar (app/geocodificar.py, aquí simulado: los tests no salen a
internet) o se pone a mano en el mapita del formulario. Escenario: loga lleva Clínica A (id 1), logb la B."""
import json
import re

from app.extensions import db
from app.models import Cliente
from tests.conftest import login, pedido_cliente

DATOS = {"nombre": "Clínica A", "prefijo": "CLA", "cif": "B11111111", "ciudad": "Bilbao", "pais": "España",
         "activo": "y", "envio_igual": "y"}


def _salir(client):
    client.post("/auth/logout")


def _situar(cid, lat, lon):
    c = db.session.get(Cliente, cid)
    c.latitud, c.longitud = lat, lon
    db.session.commit()


def _datos_del_mapa(html):
    return json.loads(re.search(r'<script type="application/json" id="mapa-datos">(.*?)</script>', html, re.S).group(1))


def _buscador(monkeypatch, app, resultado):
    """Sustituye la búsqueda en OpenStreetMap; devuelve la lista de lo que se ha buscado."""
    from app import geocodificar
    llamadas = []
    app.config["GEOCODIFICAR"] = True
    monkeypatch.setattr(geocodificar, "buscar", lambda *a, **k: (llamadas.append(a), resultado)[1])
    return llamadas


def test_el_mapa_y_quien_ve_que(app, client):
    _situar(1, 43.26, -2.93)
    _situar(2, -34.6, -58.38)
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    login(client, "admin")
    html = client.get("/clientes/mapa").get_data(as_text=True)
    datos = {d["nombre"]: d for d in _datos_del_mapa(html)}
    assert set(datos) == {"Clínica A", "Clínica B"}
    a = datos["Clínica A"]
    assert a["lat"] == 43.26 and a["estado"] == "con_pedidos" and a["pedidos_anio"] == 1 and len(a["serie"]) == 12
    assert a["soporte"] == "loga" and a["url"] == "/clientes/1"
    assert datos["Clínica B"]["estado"] == "nuevo"
    assert 'id="filtro-soporte"' in html and "vendor/mapa/d3.min.js" in html
    assert 'href="/clientes/mapa"' in client.get("/clientes/").get_data(as_text=True)
    _salir(client)
    login(client, "loga")                                          # Soporte de cliente: solo los suyos
    html = client.get("/clientes/mapa").get_data(as_text=True)
    assert [d["nombre"] for d in _datos_del_mapa(html)] == ["Clínica A"] and 'id="filtro-soporte"' not in html
    _salir(client)
    for quien in ("cliA", "ofi"):
        login(client, quien)
        assert client.get("/clientes/mapa").status_code == 403, quien
        _salir(client)


def test_los_que_no_estan_situados_salen_aparte(app, client):
    _situar(1, 43.26, -2.93)
    login(client, "admin")
    html = client.get("/clientes/mapa").get_data(as_text=True)
    assert [d["nombre"] for d in _datos_del_mapa(html)] == ["Clínica A"]
    assert "1 cliente sin situar" in html and "/clientes/2/editar" in html


def test_al_guardar_se_busca_la_ciudad_solo_si_cambia(app, client, monkeypatch):
    llamadas = _buscador(monkeypatch, app, (43.263, -2.935))
    login(client, "fac")
    assert client.post("/clientes/1/editar", data=DATOS).status_code == 302
    c = db.session.get(Cliente, 1)
    assert (c.latitud, c.longitud) == (43.263, -2.935) and len(llamadas) == 1
    client.post("/clientes/1/editar", data={**DATOS, "notas": "otra cosa", "latitud": "43.263", "longitud": "-2.935"})
    assert len(llamadas) == 1                                      # la dirección no ha cambiado: no se busca
    client.post("/clientes/1/editar", data={**DATOS, "ciudad": "Bogotá", "pais": "Colombia"})
    assert len(llamadas) == 2 and llamadas[-1][0] == "Bogotá"


def test_si_no_se_encuentra_se_avisa_y_no_sale(app, client, monkeypatch):
    _situar(1, 1.0, 1.0)
    _buscador(monkeypatch, app, None)
    login(client, "fac")
    r = client.post("/clientes/1/editar", data={**DATOS, "ciudad": "Villaninguna"}, follow_redirects=True)
    assert "No he encontrado «Villaninguna, España» en el mapa" in r.get_data(as_text=True)
    assert db.session.get(Cliente, 1).latitud is None


def test_a_mano_en_el_mapita_y_quitarlo(app, client, monkeypatch):
    llamadas = _buscador(monkeypatch, app, (0.0, 0.0))
    login(client, "loga")                                          # (Soporte de cliente edita los suyos)
    html = client.get("/clientes/1/editar").get_data(as_text=True)
    assert "data-mapa-elegir" in html and html.count('name="latitud"') == 1
    client.post("/clientes/1/editar", data={**DATOS, "latitud": "40.41650", "longitud": "-3.70380",
                                            "ubicacion_manual": "1"})
    c = db.session.get(Cliente, 1)
    assert (c.latitud, c.longitud) == (40.4165, -3.7038) and not llamadas    # lo puesto a mano manda
    client.post("/clientes/1/editar", data={**DATOS, "ubicacion_manual": "quitar"})
    assert db.session.get(Cliente, 1).latitud is None
    client.post("/clientes/1/editar", data={**DATOS, "latitud": "999", "longitud": "5", "ubicacion_manual": "1"})
    assert db.session.get(Cliente, 1).latitud == 0.0               # punto imposible: se busca la ciudad


def test_sin_internet_no_falla(app, monkeypatch):
    import urllib.request

    from app import geocodificar

    def sin_red(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr(urllib.request, "urlopen", sin_red)
    app.config["GEOCODIFICAR"] = True
    assert geocodificar.buscar("Bilbao", "España") is None
    app.config["GEOCODIFICAR"] = False
    assert geocodificar.buscar("Bilbao", "España") is None


def test_comando_situar_clientes(app, monkeypatch):
    import time

    from app import geocodificar
    monkeypatch.setattr(time, "sleep", lambda s: None)
    app.config["GEOCODIFICAR"] = True
    monkeypatch.setattr(geocodificar, "buscar", lambda ciudad, *a: (10.0, 20.0) if ciudad == "Bilbao" else None)
    db.session.get(Cliente, 1).ciudad = "Bilbao"
    db.session.commit()
    salida = app.test_cli_runner().invoke(args=["situar-clientes"]).output
    assert "Situados: 1" in salida and "Clínica B (sin ciudad)" in salida
    assert db.session.get(Cliente, 1).latitud == 10.0
