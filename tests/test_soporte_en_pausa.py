"""
Soporte ChromGo EN PAUSA (config SOPORTE_CHROMGO = False, que es como va en producción de momento).
El código, las tablas y los datos siguen ahí; lo que se comprueba es que no se ve ni se puede entrar.
(El resto de tests lo llevan activado: ver TestConfig en config.py.)
"""
import pytest

from app.admin.forms import UsuarioForm
from app.extensions import db
from app.models import Ticket, User
from app.navegacion import menu_lateral
from app.permisos import PERMISOS, ROLES, tiene_permiso
from tests.conftest import login


@pytest.fixture
def en_pausa(app):
    app.config["SOPORTE_CHROMGO"] = False
    return app


def _usuario(nombre):
    return db.session.scalar(db.select(User).filter_by(email=f"{nombre.lower()}@ejemplo.com"))


def test_nadie_tiene_permisos_de_soporte(en_pausa):
    permisos = [p for p in PERMISOS if p.startswith("soporte.")]
    assert permisos                                   # si se renombran, este test tiene que enterarse
    for permiso in permisos:
        for rol in ROLES:
            assert tiene_permiso(rol, permiso) is False, (rol, permiso)
    cliente = _usuario("cliA")
    cliente.acceso_chromgo = True                     # ni el cliente al que se le había dado acceso
    for nombre in ("admin", "sop", "chrA", "cliA"):
        assert _usuario(nombre).puede("soporte.ver") is False, nombre


def test_los_demas_permisos_no_cambian(en_pausa):
    assert _usuario("admin").puede("pedidos.ver") is True
    assert _usuario("cliA").puede("pedidos.crear") is True


def test_las_paginas_de_soporte_no_existen(en_pausa, client):
    login(client, "admin")
    assert client.get("/soporte/").status_code == 404
    assert client.get("/soporte/nuevo").status_code == 404
    assert client.post("/soporte/nuevo", data={"asunto": "x", "texto": "y"}).status_code == 404
    assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 0


def test_no_sale_en_el_menu_ni_en_la_pagina(en_pausa, client):
    claves = [s["clave"] for s in menu_lateral(_usuario("admin"), "main.inicio", "main", None)]
    assert claves == ["pedidos", "catalogo", "clientes", "equipo", "admin"]
    login(client, "admin")
    html = client.get("/").get_data(as_text=True)
    assert "/soporte/" not in html and "ChromGo" not in html


def test_quien_solo_es_de_soporte_ve_el_aviso(en_pausa, client):
    for nombre in ("sop", "chrA"):
        login(client, nombre)
        r = client.get("/")
        assert r.status_code == 200, nombre
        assert "Soporte ChromGo no está disponible todavía" in r.get_data(as_text=True), nombre
        assert client.get("/pedidos/").status_code == 403, nombre
        client.post("/auth/logout")


def test_el_formulario_de_usuario_no_ofrece_los_roles_de_soporte(en_pausa, client):
    with en_pausa.test_request_context():
        assert [c for c, _n in UsuarioForm().rol.choices] == ["admin", "facturacion", "logistica", "fas", "cliente"]
        # ...pero quien ya lo tenía lo conserva al editarlo (si no, el formulario le cambiaría el rol)
        assert "soporte" in [c for c, _n in UsuarioForm(usuario=_usuario("sop")).rol.choices]
    login(client, "admin")
    html = client.get("/admin/usuarios/nuevo").get_data(as_text=True)
    assert 'name="acceso_chromgo"' not in html and "ChromGo" not in html


def test_editar_a_un_cliente_no_le_quita_el_acceso_guardado(en_pausa, client):
    cliente = _usuario("cliA")
    cliente.acceso_chromgo = True
    db.session.commit()
    login(client, "admin")
    r = client.post(f"/admin/usuarios/{cliente.id}", data={
        "nombre": "Cliente A", "email": cliente.email, "rol": "cliente", "activo": "y",
        "cliente_id": cliente.cliente_id, "idioma": ""})
    assert r.status_code == 302
    db.session.refresh(cliente)
    assert cliente.nombre == "Cliente A" and cliente.acceso_chromgo is True


def test_al_activarlo_vuelve_todo(en_pausa, client):
    en_pausa.config["SOPORTE_CHROMGO"] = True
    login(client, "sop")
    assert client.get("/soporte/").status_code == 200
