"""15/10/2026 · Al hacer el pedido, el cliente elige el uso (RUO / IVD / indiferente, obligatorio) y puede
poner observaciones. Se ven en la ficha y en Preparar, que además enseña la caducidad más próxima de
los lotes reservados. Escenario de conftest: cliA (Clínica A, Soporte loga) · fac = Facturación ·
ofi = Almacén · kit K1 = 1 × P1."""
import re

from app.extensions import db
from app.models import Pedido
from tests.conftest import contenido, doc_pedido, login, pedido_cliente, proforma_aceptada


def _salir(client):
    client.post("/auth/logout")


def _pedir(client, **extra):
    datos = {"contenido": contenido([(1, 1, {1: 1})]), "fecha": "2026-10-15", "referencia": "OC-USO",
             "documento": doc_pedido(), **extra}
    return client.post("/pedidos/nuevo", data=datos)


def _ultimo():
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def test_el_uso_es_obligatorio_para_el_cliente(app, client):
    login(client, "cliA")
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    for valor in ("ruo", "ivd", "indiferente"):
        assert f'value="{valor}"' in html
    assert "data-uso-obligatorio" in html and 'name="observaciones"' in html
    r = _pedir(client)
    assert r.status_code == 200 and "Elija el uso del pedido." in r.get_data(as_text=True)
    assert _ultimo() is None
    r = _pedir(client, uso="otro")                       # lo que no es una de las tres opciones, tampoco
    assert r.status_code == 200 and _ultimo() is None


def test_se_guarda_se_ve_y_va_en_el_aviso(app, client):
    correos = app.extensions.setdefault("correos_enviados", [])
    correos.clear()
    login(client, "cliA")
    assert _pedir(client, uso="ivd", observaciones="Entregar antes del jueves, por favor").status_code == 302
    p = _ultimo()
    assert p.uso == "ivd" and p.observaciones == "Entregar antes del jueves, por favor"
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Uso: IVD (diagnóstico in vitro)" in html and "Entregar antes del jueves" in html
    aviso = [c for c in correos if "Proforma pedida" in c["Subject"]][0].get_content()
    assert "Uso: IVD (diagnóstico in vitro)" in aviso and "Entregar antes del jueves" in aviso


def test_yikon_puede_crearlo_sin_uso(app, client):
    login(client, "fac")
    r = client.post("/pedidos/nuevo", data={"cliente_id": 1, "fecha": "2026-10-15", "documento": doc_pedido(),
                                            "contenido": contenido([(1, 1, {1: 1})])})
    assert r.status_code == 302 and _ultimo().uso is None
    assert 'data-uso-obligatorio' not in client.get("/pedidos/nuevo").get_data(as_text=True)


def test_preparar_ensena_uso_observaciones_y_caducidad(app, client):
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 5,
                                                "lote": "L-CAD", "caducidad": "2031-03-15"})
    _salir(client)
    login(client, "cliA")
    _pedir(client, uso="ruo", observaciones="Con hielo seco")
    proforma_aceptada()                                   # reserva el lote (FEFO)
    _salir(client)
    p = _ultimo()
    login(client, "ofi")
    html = client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert "Uso: RUO (solo investigación)" in html and "Con hielo seco" in html
    assert "Caducidad más próxima de sus lotes:" in html and "15/03/2031" in html
    lista = client.get("/pedidos/preparar").get_data(as_text=True)
    assert "RUO (solo investigación)" in lista and "cad. 15/03/2031" in lista


def test_el_cliente_lo_cambia_al_modificar(app, client):
    login(client, "cliA")
    pedido_cliente(client, referencia="OC-M", con_proforma=True, uso="indiferente")
    p = _ultimo()
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert re.search(r'<input checked[^>]*value="indiferente"', html.split('id="modal-modificar"')[1])
    r = client.post(f"/pedidos/{p.id}/modificar", data={"contenido": contenido([(1, 1, {1: 1})]),
                                                         "fecha": p.fecha.isoformat(), "referencia": "OC-M",
                                                         "uso": "ivd", "observaciones": "Mejor IVD"},
                    follow_redirects=True)
    assert "No ha cambiado nada" not in r.get_data(as_text=True)          # cambiar solo el uso cuenta
    p = db.session.get(Pedido, p.id)
    assert p.uso == "ivd" and p.observaciones == "Mejor IVD"
